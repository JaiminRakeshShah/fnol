-- Desk accounts and server-side sessions. Only the session token hash is stored.

CREATE TABLE IF NOT EXISTS {{desk}}.users (
  username text PRIMARY KEY,
  display_name text NOT NULL,
  team text NOT NULL,
  password_salt text NOT NULL,
  password_hash text NOT NULL
);

CREATE TABLE IF NOT EXISTS {{desk}}.sessions (
  token_hash text PRIMARY KEY,
  username text NOT NULL REFERENCES {{desk}}.users (username),
  created_at text NOT NULL,
  expires_at text NOT NULL
);
