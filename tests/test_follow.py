"""A human decision webhook copies that one case forward.

A poll copies the same decision when the webhook never arrived.
"""

import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from fnol_analyst.follow import advance_case, poll_interval_seconds, poll_open_reviews


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


class _Queue:
    def __init__(self, records):
        self.records = list(records)

    def latest_draft(self, case_id):
        for record in self.records:
            if record.case_id == case_id:
                return record
        return None

    def in_review(self):
        return [record for record in self.records if record.status == "in_review"]

    def approved_unfiled(self):
        return [
            record
            for record in self.records
            if record.status == "approved" and record.outcome == "approved"
        ]


class _PollingClient:
    def __init__(self, records, decisions):
        self.stores = SimpleNamespace(output=_Queue(records))
        self.calls = []
        self._decisions = decisions

    def peek_review(self, review_id):
        self.calls.append(("peek", review_id))
        return self._decisions.get(review_id)

    def review_status(self, case_id):
        self.calls.append(("review", case_id))
        record = self.stores.output.latest_draft(case_id)
        return {"status": self._decisions.get(record.review_id), "case_id": case_id}

    def file(self, case_id):
        self.calls.append(("file", case_id))
        return {"status": "created", "case_id": case_id}


class PollTests(TestCase):
    def test_interval_defaults_to_five_minutes(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FNOL_REVIEW_POLL_SECONDS", None)
            self.assertEqual(poll_interval_seconds(), 300)

    def test_pending_review_is_left_alone(self):
        waiting = SimpleNamespace(
            case_id="AUTO-D12", review_id="rev_wait", status="in_review", outcome=None
        )
        client = _PollingClient([waiting], {"rev_wait": "pending"})
        self.assertEqual(poll_open_reviews(client), [])
        self.assertEqual(client.calls, [("peek", "rev_wait")])

    def test_missed_approval_is_copied_and_filed(self):
        waiting = SimpleNamespace(
            case_id="AUTO-D12", review_id="rev_done", status="in_review", outcome=None
        )
        client = _PollingClient([waiting], {"rev_done": "approved"})
        done = poll_open_reviews(client)
        self.assertEqual(
            client.calls,
            [("peek", "rev_done"), ("review", "AUTO-D12"), ("file", "AUTO-D12")],
        )
        self.assertEqual(done, [{"case_id": "AUTO-D12", "status": "created", "filed": True}])

    def test_approved_draft_that_was_not_filed_is_retried(self):
        ready = SimpleNamespace(
            case_id="AUTO-D08", review_id="rev_8", status="approved", outcome="approved"
        )
        client = _PollingClient([ready], {})
        done = poll_open_reviews(client)
        self.assertEqual(client.calls, [("file", "AUTO-D08")])
        self.assertTrue(done[0]["filed"])
