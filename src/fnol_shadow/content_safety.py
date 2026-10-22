"""Azure AI Content Safety check for the optional handler summary.

Returns ``INTERVENED`` when the text is blocked, otherwise None.
When Content Safety is not configured or unreachable, returns None so the
local ``assess()`` check remains the gate (same pattern as a missing Bedrock
guardrail).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def content_safety_enabled() -> bool:
    return bool(os.environ.get("FNOL_CONTENT_SAFETY_ENDPOINT", "").strip())


def content_safety_check(text: str) -> str | None:
    """Scan model output. ``INTERVENED`` means refuse; None means continue to assess()."""
    endpoint = os.environ.get("FNOL_CONTENT_SAFETY_ENDPOINT", "").strip().rstrip("/")
    if not endpoint:
        return None
    if not isinstance(text, str) or not text.strip():
        return "INTERVENED"
    key = os.environ.get("FNOL_CONTENT_SAFETY_KEY", "").strip()
    url = f"{endpoint}/contentsafety/text:analyze?api-version=2024-09-01"
    body = json.dumps({
        "text": text[:10_000],
        "categories": ["Hate", "SelfHarm", "Sexual", "Violence"],
        "haltOnBlocklistHit": True,
        "outputType": "FourSeverityLevels",
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if key:
        headers["Ocp-Apim-Subscription-Key"] = key
    else:
        token = _aad_token()
        if not token:
            return None
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    categories = payload.get("categoriesAnalysis")
    if isinstance(categories, list):
        for item in categories:
            if not isinstance(item, dict):
                continue
            severity = item.get("severity")
            if isinstance(severity, int) and severity >= 4:
                return "INTERVENED"
    blocklist = payload.get("blocklistsMatch")
    if isinstance(blocklist, list) and blocklist:
        return "INTERVENED"
    return None


def _aad_token() -> str:
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
