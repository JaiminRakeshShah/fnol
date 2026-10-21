# Metrics and the page threshold

Both metrics are computed in `src/fnol_hardening/metrics.py` from the same samples `start_routing` records.

## route_within_slo_ratio

Successes divided by samples. A success is a route returned in 15,000 ms or less, including `manual_review`. This is the SLO ratio.

## time_to_route_p95_ms

The 95th percentile of those durations, nearest-rank (`ceil(0.95 * n) - 1`).

## Alert: fnol_slo_breach

Page a human when both of these are true:

- at least 20 samples have been observed, and
- `route_within_slo_ratio` is below 0.95, or `time_to_route_p95_ms` is above 15,000.

The page is the signal to open `docs/week10/RUNBOOK.md` if the failing cases are ambiguous or show an injection, and to apply the error-budget action in `docs/week10/SLO.md`. Below 20 samples the alert stays quiet so a single dev run does not page. The scenario run in this repo (12 cases) stays inside the SLO and does not page. A probe with 22 samples and two misses does page; that probe is in `docs/week10/evidence/09_metrics.txt`.

Structured logs are JSON lines with `trace_id`, `span_id`, and `parent_span_id`. `record_event` writes one line per pipeline step. Tool HTTP attempts and the rules reasoning step write their own spans. Set `FNOL_LOG_PATH` to keep a file, and `FNOL_LOG_STDERR=0` to silence stderr. Restricted markers are redacted before the line is written.
