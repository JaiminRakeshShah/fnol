"""Desk accounts and server-side sessions.

Identity lives in ``.state/desk.sqlite``, or in the Postgres ``desk`` schema
when a database URL is set. Sessions are opaque tokens; only the hash is stored.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fnol_foundation.db import open_db, using_postgres
from fnol_foundation.stores import state_dir

TEAMS = frozenset({"handlers", "analysts", "security"})
SESSION_HOURS = 12
COOKIE_NAME = "fnol_desk_session"
PBKDF2_ROUNDS = 200_000

# Fictional training accounts. Documented passwords only for local demo.
SEED_USERS = (
    {
        "username": "achen",
        "display_name": "Avery Chen",
        "team": "handlers",
        "password": "handler-desk",
    },
    {
        "username": "jellis",
        "display_name": "Jordan Ellis",
        "team": "analysts",
        "password": "analyst-desk",
    },
    {
        "username": "rokonkwo",
        "display_name": "Riley Okonkwo",
        "team": "security",
        "password": "security-desk",
    },
)

AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  team TEXT NOT NULL,
  password_salt TEXT NOT NULL,
  password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  FOREIGN KEY (username) REFERENCES users(username)
);
"""


@dataclass(frozen=True)
class User:
    username: str
    display_name: str
    team: str


class AuthError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _hash_password(password: str, salt: bytes) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS
    )
    return digest.hex()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def desk_db_path(directory: Path | None = None) -> Path:
    base = Path(directory) if directory is not None else state_dir()
    if not using_postgres():
        base.mkdir(parents=True, exist_ok=True)
    return base / "desk.sqlite"


def connect_auth(path: Path | None = None):
    db_path = Path(path) if path is not None else desk_db_path()
    db = open_db(db_path, kind="desk")
    if not using_postgres():
        db.executescript(AUTH_SCHEMA)
    return db


def seed_users(db) -> None:
    """Insert the three fictional accounts if the users table is empty."""
    count = db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    if count:
        return
    for row in SEED_USERS:
        if row["team"] not in TEAMS:
            raise AuthError("bad_seed", f"unknown team {row['team']}")
        salt = secrets.token_bytes(16)
        db.execute(
            """INSERT INTO users
               (username, display_name, team, password_salt, password_hash)
               VALUES (?, ?, ?, ?, ?)""",
            (
                row["username"],
                row["display_name"],
                row["team"],
                salt.hex(),
                _hash_password(row["password"], salt),
            ),
        )
    db.commit()


def ensure_seeded(path: Path | None = None) -> Path:
    db_path = Path(path) if path is not None else desk_db_path()
    with connect_auth(db_path) as db:
        seed_users(db)
    return db_path


def login(username: str, password: str, *, path: Path | None = None) -> tuple[User, str]:
    """Verify credentials and return (user, raw_session_token)."""
    if not isinstance(username, str) or not isinstance(password, str):
        raise AuthError("invalid_credentials", "username and password are required")
    username = username.strip()
    db_path = ensure_seeded(path)
    with connect_auth(db_path) as db:
        row = db.execute(
            "SELECT username, display_name, team, password_salt, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            raise AuthError("invalid_credentials", "username or password is wrong")
        salt = bytes.fromhex(row["password_salt"])
        expected = row["password_hash"]
        actual = _hash_password(password, salt)
        if not hmac.compare_digest(expected, actual):
            raise AuthError("invalid_credentials", "username or password is wrong")
        token = secrets.token_urlsafe(32)
        now = _utc_now()
        expires = now + timedelta(hours=SESSION_HOURS)
        db.execute(
            """INSERT INTO sessions (token_hash, username, created_at, expires_at)
               VALUES (?, ?, ?, ?)""",
            (_hash_token(token), row["username"], _iso(now), _iso(expires)),
        )
        db.commit()
        user = User(
            username=row["username"],
            display_name=row["display_name"],
            team=row["team"],
        )
        return user, token


def logout(token: str | None, *, path: Path | None = None) -> None:
    if not token:
        return
    db_path = ensure_seeded(path)
    with connect_auth(db_path) as db:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))
        db.commit()


def user_from_session(token: str | None, *, path: Path | None = None) -> User | None:
    if not token:
        return None
    db_path = ensure_seeded(path)
    with connect_auth(db_path) as db:
        row = db.execute(
            """SELECT u.username, u.display_name, u.team, s.expires_at
               FROM sessions s
               JOIN users u ON u.username = s.username
               WHERE s.token_hash = ?""",
            (_hash_token(token),),
        ).fetchone()
        if row is None:
            return None
        expires = _parse_iso(row["expires_at"])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= _utc_now():
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))
            db.commit()
            return None
        return User(
            username=row["username"],
            display_name=row["display_name"],
            team=row["team"],
        )


def require_team(user: User | None, *allowed: str) -> User:
    if user is None:
        raise AuthError("unauthenticated", "sign in required")
    if allowed and user.team not in allowed:
        raise AuthError("forbidden", f"team {user.team} cannot perform this action")
    return user


def user_public(user: User) -> dict:
    return {
        "username": user.username,
        "display_name": user.display_name,
        "team": user.team,
    }
