"""AnalystClient: drive the four step servers and write the deterministic draft.

Steps 1-4 are delegated to the step servers (independent calls, pipelined
across cases). Step 5 builds the draft from stored decisions only. Step 8
hashes it with the mock's canonical form, writes output.sqlite, and exports
the contract JSON. Review, records, and the Bedrock shadow path are not here.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from fnol_analyst.draft import FACT_COLUMNS, build_draft
from fnol_analyst.servers import ServerSet
from fnol_foundation.canonical import RestrictedValueError, digest
from fnol_foundation.events import record_event
from fnol_foundation.stores import DraftRecord, Stores, state_dir

ACTOR = "analyst"


class AnalystError(Exception):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


class AnalystClient:
    def __init__(
        self,
        *,
        mock_url: str | None = None,
        state_dir_path: str | Path | None = None,
        documents_dir: str | Path | None = None,
        policies_dir: str | Path | None = None,
    ):
        self.mock_url = (mock_url or os.environ.get("FNOL_MOCK_URL", "http://127.0.0.1:8767")).rstrip("/")
        self.state_dir = Path(state_dir_path) if state_dir_path is not None else state_dir()
        self.documents_dir = Path(documents_dir) if documents_dir else None
        self.policies_dir = Path(policies_dir) if policies_dir else None
        self.stores = Stores(self.state_dir)
        self._servers: ServerSet | None = None

    @property
    def servers(self) -> ServerSet:
        if self._servers is None:
            self._servers = ServerSet(
                state_dir=self.state_dir,
                mock_url=self.mock_url,
                documents_dir=self.documents_dir,
                policies_dir=self.policies_dir,
            )
        return self._servers

    def close(self) -> None:
        if self._servers is not None:
            self._servers.close()
            self._servers = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def case_ids(self) -> list[str]:
        return [row["case_id"] for row in self.stores.input.latest_loss_keys() if row.get("case_id")]

    def ingest(self) -> dict[str, Any]:
        return self.servers.ingest()

    def select_policy(self, case_id: str | None = None) -> dict[str, Any]:
        return self.servers.select_policy(case_id)

    def route(self, case_id: str | None = None) -> dict[str, Any]:
        return self.servers.route(case_id)

    def cite(self, case_id: str | None = None) -> dict[str, Any]:
        return self.servers.cite(case_id)

    def prepare(self, case_ids: list[str] | None = None, *, workers: int = 3) -> dict[str, Any]:
        """Steps 1-4. Intake once, then policy -> rules -> citations per case, pipelined.

        If any case fails after intake, PrepareError lists every failure. Decisions
        already written for successful cases remain on disk.
        """
        ingest = self.ingest()
        ids = case_ids or [row["case_id"] for row in ingest.get("revisions", [])]
        cases = self.servers.prepare_all(ids, workers=workers)
        return {"ingest": ingest, "cases": cases}

    def build(self, case_id: str) -> DraftRecord:
        """Steps 5 and 8 for one case. Reuses an identical latest draft."""
        revision = self.stores.input.get_revision(case_id)
        if revision is None:
            raise AnalystError("revision_missing", f"no input revision for {case_id}")
        decisions = {}
        for kind in ("policy", "route", "citations"):
            row = self.stores.input.get_decision(case_id, revision.revision, kind)
            if row is None:
                raise AnalystError(
                    f"{kind}_decision_missing",
                    f"no {kind} decision for {case_id}",
                )
            decisions[kind] = row["body"]
        trace_id = revision.trace_id or uuid.uuid4().hex
        started = time.perf_counter()
        try:
            draft = build_draft(
                case_id=case_id,
                input_revision=revision.revision,
                facts_row={key: revision.payload.get(key) for key in FACT_COLUMNS},
                policy=decisions["policy"],
                route=decisions["route"],
                citations=decisions["citations"],
            )
        except RestrictedValueError:
            self._event(
                trace_id, "5", "draft_built", case_id, revision.revision, None,
                status="error", error_code="restricted_value", started=started,
            )
            raise AnalystError("restricted_value", "draft refused: restricted value") from None
        draft_hash = digest(draft)
        existing = self.stores.output.latest_draft(case_id)
        if existing is not None and existing.draft_hash == draft_hash:
            return existing
        self._event(
            trace_id, "5", "draft_built", case_id, revision.revision, None,
            status="ok", output_sha256=draft_hash, started=started,
        )
        started = time.perf_counter()
        record = self.stores.output.record_draft(case_id, draft, input_revision=revision.revision)
        self._event(
            trace_id, "8", "draft_recorded", case_id, revision.revision, record.draft_id,
            status="ok", output_sha256=record.draft_hash, started=started,
        )
        return record

    def build_all(self, case_ids: list[str] | None = None) -> list[DraftRecord]:
        return [self.build(case_id) for case_id in (case_ids or self.case_ids())]

    def export(self, path: str | Path, case_ids: list[str] | None = None) -> Path:
        """Write the contract JSON array from drafts already on disk.

        Does not build. Run ``build`` or ``prepare`` first.
        """
        rows = []
        for case_id in case_ids or self.case_ids():
            record = self.stores.output.latest_draft(case_id)
            if record is None:
                raise AnalystError("draft_missing", f"no draft for {case_id}; run build first")
            rows.append(record.draft)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
        return target

    def _event(
        self,
        trace_id,
        step,
        event,
        case_id,
        input_revision,
        draft_id,
        *,
        status,
        error_code=None,
        duration_ms=None,
        output_sha256=None,
        started=None,
    ):
        if duration_ms is None and started is not None:
            duration_ms = int((time.perf_counter() - started) * 1000)
        record_event(
            self.stores,
            trace_id=trace_id,
            step=step,
            event=event,
            actor=ACTOR,
            status=status,
            case_id=case_id,
            input_revision=input_revision,
            draft_id=draft_id,
            error_code=error_code,
            duration_ms=duration_ms,
            output_sha256=output_sha256,
        )
