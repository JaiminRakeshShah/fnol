"""Read case documents and policy wording from disk or Azure Blob Storage.

Disk is the default. Set FNOL_BLOB_ACCOUNT to read from Blob instead.
Containers default to case-documents and policy-wording; override with
FNOL_DOCUMENTS_CONTAINER and FNOL_POLICIES_CONTAINER.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class BlobError(RuntimeError):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


def blob_enabled() -> bool:
    return bool(os.environ.get("FNOL_BLOB_ACCOUNT", "").strip())


def documents_container() -> str:
    return os.environ.get("FNOL_DOCUMENTS_CONTAINER", "case-documents").strip() or "case-documents"


def policies_container() -> str:
    return os.environ.get("FNOL_POLICIES_CONTAINER", "policy-wording").strip() or "policy-wording"


def fixtures_container() -> str:
    return os.environ.get("FNOL_FIXTURES_CONTAINER", "fnol-fixtures").strip() or "fnol-fixtures"


def container_for(directory: str | Path) -> str:
    """Map a local directory path to the Blob container used in Azure mode."""
    name = Path(directory).name.lower()
    if name in {"documents", "case-documents"}:
        return documents_container()
    if name in {"policies", "policy-wording"}:
        return policies_container()
    if name in {"dev", "fixtures", "fnol-fixtures"}:
        return fixtures_container()
    return name


def read_source(directory: str | Path, source_id: str):
    """Return (path_or_uri, bytes, text) for ``{source_id}.md``, or None.

    Same contract as ``fnol_intake.parse.read_source``. Refuses path traversal.
    """
    if not isinstance(source_id, str) or not source_id:
        return None
    if any(part in source_id for part in ("/", "\\", "..")):
        return None
    blob_name = f"{source_id}.md"
    if blob_enabled():
        return _read_blob(container_for(directory), blob_name)
    root = Path(directory).resolve()
    path = (root / blob_name).resolve()
    if path.parent != root or not path.is_file():
        return None
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return path, data, text


def list_markdown_sources(directory: str | Path) -> list[dict[str, str]]:
    """Return ``[{source_id, sha256}, ...]`` for every ``*.md`` in the store."""
    from fnol_intake.parse import file_sha256

    if blob_enabled():
        return _list_blob_markdown(container_for(directory))
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"policies directory does not exist: {directory}")
    sources = []
    for path in sorted(root.glob("*.md")):
        sources.append({
            "source_id": path.stem,
            "sha256": file_sha256(path.read_bytes()),
        })
    return sources


def _client():
    account = os.environ.get("FNOL_BLOB_ACCOUNT", "").strip()
    if not account:
        raise BlobError("blob_config", "FNOL_BLOB_ACCOUNT is required")
    try:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient
    except ImportError as exc:
        raise BlobError(
            "blob_deps",
            "azure-storage-blob and azure-identity are required for Blob mode",
        ) from exc
    url = f"https://{account}.blob.core.windows.net"
    credential = DefaultAzureCredential()
    return BlobServiceClient(account_url=url, credential=credential)


def _read_blob(container: str, blob_name: str):
    try:
        client = _client()
        blob = client.get_blob_client(container=container, blob=blob_name)
        if not blob.exists():
            return None
        data = blob.download_blob().readall()
    except BlobError:
        raise
    except Exception as exc:
        raise BlobError("blob_read", f"failed to read {container}/{blob_name}: {exc}") from exc
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    uri = f"azure-blob://{container}/{blob_name}"
    return uri, data, text


def _list_blob_markdown(container: str) -> list[dict[str, str]]:
    from fnol_intake.parse import file_sha256

    try:
        client = _client()
        container_client = client.get_container_client(container)
        items: list[dict[str, str]] = []
        for blob in sorted(container_client.list_blobs(), key=lambda b: b.name):
            name = blob.name
            if not name.endswith(".md") or "/" in name.rstrip("/"):
                continue
            data = container_client.download_blob(name).readall()
            items.append({
                "source_id": Path(name).stem,
                "sha256": file_sha256(data),
            })
        return items
    except BlobError:
        raise
    except Exception as exc:
        raise BlobError("blob_list", f"failed to list {container}: {exc}") from exc


def download_text(container: str, blob_name: str) -> str | None:
    """Fetch one blob as UTF-8 text, or None when missing."""
    found = _read_blob(container, blob_name) if blob_enabled() else None
    if found is None:
        return None
    return found[2]
