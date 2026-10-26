"""A human decision webhook copies that one case forward."""

from types import SimpleNamespace
from unittest import TestCase

from fnol_analyst.follow import advance_case


class _Output:
    def __init__(self, record):
        self.record = record

    def latest_draft(self, case_id):
        if self.record is not None and self.record.case_id == case_id:
            return self.record
        return None


class _Client:
    def __init__(self, record, decision):
        self.stores = SimpleNamespace(output=_Output(record))
        self.calls = []
        self._decision = decision

    def review_status(self, case_id):
        self.calls.append(("review", case_id))
        return {"status": self._decision, "case_id": case_id}

    def file(self, case_id):
        self.calls.append(("file", case_id))
        return {"status": "created", "case_id": case_id}


class FollowTests(TestCase):
    def test_approval_is_copied_and_filed(self):
        client = _Client(
            SimpleNamespace(case_id="AUTO-D01", review_id="rev_1", status="in_review", outcome=None),
            "approved",
        )
        done = advance_case(client, "AUTO-D01")
        self.assertEqual(client.calls, [("review", "AUTO-D01"), ("file", "AUTO-D01")])
        self.assertEqual(done, {"case_id": "AUTO-D01", "status": "created", "filed": True})

    def test_rejection_updates_the_draft_and_does_not_file(self):
        client = _Client(
            SimpleNamespace(case_id="AUTO-D02", review_id="rev_2", status="in_review", outcome=None),
            "not_submitted",
        )
        done = advance_case(client, "AUTO-D02")
        self.assertEqual(client.calls, [("review", "AUTO-D02")])
        self.assertFalse(done["filed"])

    def test_pending_stays_put(self):
        client = _Client(
            SimpleNamespace(case_id="AUTO-D03", review_id="rev_3", status="in_review", outcome=None),
            "in_review",
        )
        advance_case(client, "AUTO-D03")
        self.assertEqual(client.calls, [("review", "AUTO-D03")])
