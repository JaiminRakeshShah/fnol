# AWS reviewer CLI (accept / reject)

Use this when you want human decisions to hit **AWS Postgres** (and Grafana), not local SQLite.

Do **not** use bare `tools/runtime.py approve` for AWS unless `FNOL_DATABASE_URL` is pointed at the RDS tunnel. Default runtime state is local.

## Prerequisites

- AWS CLI + Session Manager plugin
- SSO profile (examples use `atharv`)
- uv with the `postgres` group

```sh
aws sso login --profile atharv
```

Ignore `aws login` errors on profile `default` if that profile has access keys. Use `AWS_PROFILE=atharv`.

## 1. Start the AWS-backed reviewer

Leave this terminal running:

```sh
AWS_PROFILE=atharv uv run --locked --group postgres python tools/reviewer_aws.py
```

Success looks like:

```text
reviewer_aws: tunnel already on 127.0.0.1:15432   # or "starting SSM tunnel…" then "tunnel ready"
reviewer_aws: serving AWS Postgres via tunnel on http://127.0.0.1:8090/
reviewer HTTP on http://127.0.0.1:8090 (postgres)
```

UI: http://127.0.0.1:8090/

## 2. If port 8090 is already in use

Error: `OSError: [Errno 48] Address already in use`

Find and stop the old listener:

```sh
lsof -nP -iTCP:8090 -sTCP:LISTEN
kill <PID>
```

Or check whether the existing process is already usable:

```sh
curl -s -H "X-Fnol-Roles: Claims.Reviewer" \
  http://127.0.0.1:8090/v1/pending | python3 -m json.tool
```

If that returns JSON, you can skip restarting.

Optional: run on another port instead of killing:

```sh
FNOL_HTTP_PORT=8091 AWS_PROFILE=atharv \
  uv run --locked --group postgres python tools/reviewer_aws.py
```

Then use `8091` in the curl commands below.

## 3. List pending reviews (new terminal)

```sh
curl -s -H "X-Fnol-Roles: Claims.Reviewer" \
  http://127.0.0.1:8090/v1/pending | python3 -m json.tool
```

Note each item’s `id` (e.g. `rev_…`) and `case_id`.

Empty `[]` means nothing is waiting. Submit drafts from the **analyst ECS task** first (see below).

## 4. Accept or reject

```sh
# accept
curl -s -X POST \
  -H "X-Fnol-Roles: Claims.Reviewer" \
  -H "X-Fnol-Reviewer: atharv" \
  http://127.0.0.1:8090/v1/approve/REVIEW_ID

# reject
curl -s -X POST \
  -H "X-Fnol-Roles: Claims.Reviewer" \
  -H "X-Fnol-Reviewer: atharv" \
  http://127.0.0.1:8090/v1/reject/REVIEW_ID
```

Replace `REVIEW_ID` with a real `rev_…` value. Expected body includes `"status":"approved"` or `"status":"rejected"`.

Re-list pending; that review should be gone. Grafana refreshes about every minute.

## 5. Create pending reviews on AWS (if queue is empty)

Laptop `python -m fnol_analyst` without AWS env does **not** write the AWS DB.

Exec into the analyst task, then prepare/submit there:

```sh
aws ecs list-tasks --cluster fnol --service-name fnol-analyst \
  --region us-east-1 --profile atharv

aws ecs execute-command --cluster fnol --task TASK_ID \
  --container analyst --interactive --command "/bin/sh" \
  --region us-east-1 --profile atharv
```

Inside the task:

```sh
python -m fnol_analyst prepare
python -m fnol_analyst submit --case-id AUTO-D02
```

Then go back to steps 3–4 on your laptop against `8090`.

## Quick demo picks

| Case | What it shows |
|------|----------------|
| AUTO-D02 | urgent / injury |
| AUTO-D04 | missing required information |
| AUTO-D05 | ambiguous / no unique policy |
| AUTO-D08 | prompt-injection blocked → manual_review |
| AUTO-D07 | claims history unavailable (after submit) |
| AUTO-D10 | duplicate delivery (hard block on file after approve) |
| AUTO-D11 | repair-amount conflict → specialist (Grafana “Conflicting evidence” stays 0; that panel counts `conflicts[]` only) |

## 6. Clear / blank the AWS DB

Wipes **shared** FNOL data tables only (input, output, trace, mock). Does **not** delete the RDS instance, schemas, roles, or migration ledger. **This clears Grafana numbers for everyone** — only do it when the team agrees.

Uses `fnol_migrate` (has truncate rights). `fnol_reviewer` cannot blank all tables.

### A. Tunnel must be up first

In a dedicated terminal (leave it running):

```sh
# free stale reviewer if needed
lsof -nP -iTCP:8090 -sTCP:LISTEN
kill <PID>   # only if something is on 8090

AWS_PROFILE=atharv uv run --locked --group postgres python tools/reviewer_aws.py
```

Confirm the tunnel:

```sh
lsof -nP -iTCP:15432 -sTCP:LISTEN
```

If you see `Connection refused` / timeout on blank, the tunnel died — kill whatever was on `8090`, re-run `reviewer_aws.py`, then continue.

### B. Fresh IAM token + blank (other terminal)

IAM tokens expire in ~15 minutes. Generate the token and blank in the **same** shell, right before running:

```sh
aws sso login --profile atharv

RDS_HOST=fnol-postgres.cc92c6i402lj.us-east-1.rds.amazonaws.com
TOKEN=$(aws rds generate-db-auth-token \
  --hostname "$RDS_HOST" --port 5432 --region us-east-1 \
  --username fnol_migrate --profile atharv)
ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$TOKEN")

unset FNOL_RDS_HOST FNOL_RDS_IAM_AUTH
export FNOL_DATABASE_URL="postgresql://fnol_migrate:${ENC}@127.0.0.1:15432/fnol?sslmode=require"
export FNOL_PG_NAMESPACE=shared

# must print: 127.0.0.1:15432/fnol?sslmode=require
python3 -c "import os; print(os.environ['FNOL_DATABASE_URL'].split('@')[-1])"

uv run --locked --group postgres python tools/blank_state.py
```

Success:

```text
blanked input.input_revisions, input.procedure_sources, input.tool_payloads, input.decisions, output.drafts, trace.trace_events, mock.reviews, mock.records, mock.keys, mock.calls, mock.audit
```

Then:

```sh
curl -s -H "X-Fnol-Roles: Claims.Reviewer" \
  http://127.0.0.1:8090/v1/pending | python3 -m json.tool
```

Expect `[]`. Re-`prepare` / `submit` from the analyst ECS task to refill.

### Local mock only (does **not** clear AWS)

```sh
uv run --locked python tools/runtime.py reset --confirm
```

## Stop

Ctrl-C the `reviewer_aws.py` terminal. Optional: kill the SSM tunnel on `15432` if nothing else needs it (`lsof -nP -iTCP:15432 -sTCP:LISTEN`).
