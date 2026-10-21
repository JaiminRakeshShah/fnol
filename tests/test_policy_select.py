"""Interval selection: inclusive start, exclusive end, no guessed version."""

from fnol_policy.select import select_policy

V1 = {
    "version": "1",
    "effective_from": "2026-01-01T00:00:00Z",
    "effective_to": "2026-09-01T00:00:00Z",
    "wording_source": "AUTO-WORDING-V1",
    "endorsements": [],
}
V2 = {
    "version": "2",
    "effective_from": "2026-09-01T00:00:00Z",
    "effective_to": "2027-01-01T00:00:00Z",
    "wording_source": "AUTO-WORDING-V2",
    "endorsements": ["AUTO-END-GLASS-01"],
}
REISSUE = {
    "version": "2-reissue",
    "effective_from": "2026-09-01T00:00:00Z",
    "effective_to": "2027-01-01T00:00:00Z",
    "wording_source": "AUTO-WORDING-V1",
    "endorsements": [],
}


def test_october_incident_selects_version_two():
    body = select_policy("2026-10-01T12:00:00Z", {"source_id": "AUTO-D01-POLICY", "policies": [V1, V2]})
    assert body["reason"] == "matched"
    assert body["policy_available"] is True
    assert body["selected_policy_version"] == "2"
    assert body["wording_source"] == "AUTO-WORDING-V2"
    assert body["endorsements"] == ["AUTO-END-GLASS-01"]


def test_overlap_is_ambiguous_and_still_available():
    body = select_policy(
        "2026-10-01T12:00:00Z",
        {"source_id": "AUTO-D05-POLICY", "policies": [V1, V2, REISSUE]},
    )
    assert body["reason"] == "ambiguous"
    assert body["policy_available"] is True
    assert body["selected_policy_version"] is None
    assert body["wording_source"] is None
    assert body["endorsements"] == []


def test_exclusive_end_matches_nothing():
    body = select_policy("2027-01-01T00:00:00Z", {"source_id": "AUTO-D06-POLICY", "policies": [V1, V2]})
    assert body["reason"] == "zero"
    assert body["policy_available"] is True
    assert body["selected_policy_version"] is None


def test_instant_before_version_two_selects_version_one():
    body = select_policy("2026-08-31T23:59:59Z", {"source_id": "AUTO-D12-POLICY", "policies": [V1, V2]})
    assert body["reason"] == "matched"
    assert body["selected_policy_version"] == "1"
    assert body["wording_source"] == "AUTO-WORDING-V1"
