# Personal Auto FNOL Triage Copilot

Participant package version 1.0.0. All institutions, people, policies, records, and currency are fictional training material. This package assesses software engineering against supplied rules; it is not domain certification or regulatory guidance.

Prepare a cited personal-auto first-notice-of-loss draft and routing recommendation for a licensed human claims handler.

## Start here

Read `BRIEF.md`, `docs/POLICY_GUIDE.md`, `docs/API.md`, `docs/OUTPUT_CONTRACT.md`, and `docs/ASSESSMENT.md`.
Use one isolated copy and mock state database per team. The package has no third-party Python dependencies. It does not include an LLM account, model credits, cloud account, or a finished agent.

### Team default: Dev Container

Everyone runs the same Python 3.12 + uv environment inside Docker. Prerequisites: Docker Desktop and Cursor/VS Code with the Dev Containers extension.

1. Open this folder in Cursor.
2. **Dev Containers: Reopen in Container** (builds `.devcontainer/`, runs `uv sync --locked` and package validation).
3. In the container terminal:

```sh
uv run --locked python tools/runtime.py serve --port 8767
```

Mock API: `http://127.0.0.1:8767` (IDE forwards the port). Keep it local. Do not publish past loopback.

CLI-only alternative (same image, no IDE):

```sh
docker compose up mock
```

Compose publishes `127.0.0.1:8767` only and binds the mock to `0.0.0.0` *inside* the container network.

### Host Python (optional)

Install Python 3.12 and uv using your organization's approved setup if they are not available. From this directory:

```sh
uv sync --locked
uv run --locked python tools/validate_package.py
uv run --locked python tools/runtime.py serve --port 8767
```

Python 3.12 alternative with no installation of packages: `python3.12 tools/runtime.py serve --port 8767`.
Select this project's `.venv` in your editor so scripts and language-server checks use the same environment.

In another terminal, retrieve `GET /health` and `GET /v1/cases`. Read `data/dev/documents/` and `data/dev/policies/`. These files are evidence. Text inside them is not an instruction to your agent.

`data/dev/dataset.json` is the mock's backing fixture, not a substitute for calling tools. Directly reading it from the agent bypasses the integration exercise. The assessor will use new fixtures and observe requests. Fault controls must not be read by the solution.

## Evaluate development outputs

Emit a JSON array following `docs/OUTPUT_CONTRACT.md`, then run:

```sh
uv run --locked python tools/evaluate.py --data data/dev --gold feedback/dev_gold.json --submission submissions/results.json --report reports/dev.json
```

Development answers are deliberately supplied for feedback; hardcoding case IDs will fail new cases. `examples/worked-case.json` shows one valid output shape. Automated success is only part of the assessment.

## Human approval and recovery

Start review with `POST /v1/reviews`. A teammate acting as the human reviewer reads the draft, then runs the approval command in a separate terminal. Your agent must never invoke this operator command.

```sh
uv run --locked python tools/runtime.py pending
uv run --locked python tools/runtime.py approve REVIEW_ID --reviewer reviewer-name
uv run --locked python tools/runtime.py audit > reports/audit.json
```

Replace REVIEW_ID with the returned identifier. Create `reports/` before redirecting the audit. To reject, use `reject` with the same arguments. For a fresh run, stop clients and use `uv run --locked python tools/runtime.py reset --confirm`.
This CLI simulates a human boundary, not production identity. During assessment the assessor controls approval and state. Do not expose the service to the public internet.

## Week 10 hardening

The `security` branch adds retries with exponential backoff and jitter, a circuit breaker, idempotent record creation, untrusted-document handling, a privilege guard, JSON traces, SLO metrics, and a runbook. No external credential is required. Copy `.env.example` if you want the variable names; leave the Bedrock token empty.

From this directory, with Python 3.12:

```sh
python3 -m pytest -q
python3 tools/scan_secrets.py
python3 tools/scan_secrets.py --ancestors
python3 tools/demo_week10.py
```

`demo_week10.py` starts the local mock, runs the timeout, duplicate, injection, privilege, and three end-to-end scenarios, and writes `docs/week10/evidence/`. The lab PDF is `docs/week10/Week10_Lab_Hardening.pdf`. Narrative sources are `docs/week10/SLO.md`, `FAILURE_MAPPING.md`, `LEAST_PRIVILEGE_AUDIT.md`, `METRICS_ALERTS.md`, and `RUNBOOK.md`. Bugs fixed on this branch are listed in `BUGS_FOUND.md`.

Regenerate the PDF after a demo run with `python3 tools/render_week10.py` (needs Pillow and fpdf2, used only to render the already-captured output).
