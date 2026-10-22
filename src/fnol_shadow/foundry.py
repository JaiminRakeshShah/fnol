"""Gemma 4 31B on Microsoft Foundry (Azure).

Same sampling as Bedrock Mantle: temperature 1.0, top_p 0.95, max_tokens 1200.
Uses the OpenAI-compatible chat completions route on the Foundry project endpoint.
Deployment name defaults to gemma-4-31b (catalog model google/gemma-4-31b-it).
"""

from __future__ import annotations

import os
from typing import Callable

import json
import time
import urllib.error
import urllib.request

from fnol_shadow.bedrock import ChatReply, _message_text, _tokens
from fnol_shadow.errors import ShadowError
from fnol_shadow.http import Sleeper

DEFAULT_DEPLOYMENT = "gemma-4-31b"
DEFAULT_API_VERSION = "2024-05-01-preview"


def _post_json(
    url: str,
    *,
    headers: dict[str, str],
    body: dict,
    timeout: float,
    sleeper: Sleeper | None,
    max_attempts: int = 3,
) -> tuple[int, dict[str, str], dict]:
    pause = sleeper or (lambda attempt: time.sleep(0.25 * attempt))
    last: tuple[int, dict[str, str], dict] = (0, {}, {})
    data = json.dumps(body).encode("utf-8")
    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                status = response.status
                hdrs = {k.lower(): v for k, v in response.headers.items()}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
            hdrs = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
        except (urllib.error.URLError, TimeoutError, OSError):
            last = (0, {}, {})
            if attempt == max_attempts:
                return last
            pause(attempt)
            continue
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        last = (status, hdrs, payload)
        if status == 200 or status == 429 or status >= 500:
            if status != 200 and attempt < max_attempts:
                pause(attempt)
                continue
        return last
    return last


class FoundryClient:
    """Chat client with the same ``chat(system, user) -> ChatReply`` surface as MantleClient."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str | None = None,
        deployment: str = DEFAULT_DEPLOYMENT,
        api_version: str = DEFAULT_API_VERSION,
        content_safety: Callable[[str], str | None] | None = None,
        sleeper: Sleeper | None = None,
        timeout: float = 60,
    ):
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ShadowError("foundry_config", "FNOL_FOUNDRY_ENDPOINT is required")
        self.endpoint = endpoint.rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model_id = deployment or DEFAULT_DEPLOYMENT
        self.api_version = api_version or DEFAULT_API_VERSION
        self.content_safety = content_safety
        self.sleeper = sleeper
        self.timeout = timeout
        self.chat_url = (
            f"{self.endpoint}/openai/deployments/{self.model_id}/chat/completions"
            f"?api-version={self.api_version}"
        )

    def chat(self, system: str, user: str) -> ChatReply:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        else:
            token = _managed_identity_token()
            if not token:
                raise ShadowError(
                    "api_key_missing",
                    "Foundry API key or managed identity is required",
                )
            headers["Authorization"] = f"Bearer {token}"
        status, _hdrs, payload = _post_json(
            self.chat_url,
            headers=headers,
            body={
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 1.0,
                "top_p": 0.95,
                "max_tokens": 1200,
            },
            timeout=self.timeout,
            sleeper=self.sleeper,
        )
        if status != 200:
            raise ShadowError("foundry_http", f"foundry returned {status}")
        text, finish = _message_text(payload)
        guardrail = None
        if isinstance(finish, str) and finish.lower() in {"content_filter", "content_filtered"}:
            guardrail = "INTERVENED"
        if self.content_safety is not None and guardrail is None:
            try:
                action = self.content_safety(text)
            except Exception:
                action = None
            if action == "INTERVENED":
                guardrail = "INTERVENED"
        return ChatReply(
            text=text,
            input_tokens=_tokens(payload, "prompt_tokens", "input_tokens"),
            output_tokens=_tokens(payload, "completion_tokens", "output_tokens"),
            guardrail_action=guardrail,
        )


def load_foundry_client() -> FoundryClient:
    from fnol_shadow.content_safety import content_safety_check

    endpoint = os.environ.get("FNOL_FOUNDRY_ENDPOINT", "").strip()
    deployment = os.environ.get("FNOL_FOUNDRY_DEPLOYMENT", DEFAULT_DEPLOYMENT).strip()
    api_key = os.environ.get("FNOL_FOUNDRY_API_KEY", "").strip() or None
    api_version = os.environ.get("FNOL_FOUNDRY_API_VERSION", DEFAULT_API_VERSION).strip()
    return FoundryClient(
        endpoint=endpoint,
        api_key=api_key,
        deployment=deployment or DEFAULT_DEPLOYMENT,
        api_version=api_version or DEFAULT_API_VERSION,
        content_safety=content_safety_check,
    )


def _managed_identity_token() -> str:
    """Bearer token for Foundry when no API key is configured."""
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError:
        return ""
    try:
        credential = DefaultAzureCredential()
        token = credential.get_token("https://cognitiveservices.azure.com/.default")
        return token.token
    except Exception:
        return ""
