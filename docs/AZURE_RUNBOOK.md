# Azure FNOL cutover runbook

Local SQLite, stdio step servers, and Bedrock remain the default. Azure turns
on only when the environment variables below are set.

## Pieces

| Role | Azure resource |
|---|---|
| Files (documents, wording, fixtures) | Blob containers `case-documents`, `policy-wording`, `fnol-fixtures` |
| Rows | Azure SQL database `fnol` schemas `enterprise`, `input`, `output`, `trace` |
| Processes | Container Apps: `enterprise`, `intake`, `policy`, `rules`, `citations`, `reviewer`; Job `analyst` |
| Model | Microsoft Foundry deployment `gemma-4-31b` (catalog `google/gemma-4-31b-it`) |
| Extra safety | Azure AI Content Safety; local `assess()` still runs |
| Secrets | Key Vault + managed identity |

Blob containers are folders of files. Container Apps are running programs. They are not the same thing.

## Environment switches

| Variable | Effect when set |
|---|---|
| `FNOL_BLOB_ACCOUNT` | Read documents and wording from Blob |
| `FNOL_SQL_SERVER` | Use Azure SQL instead of SQLite |
| `FNOL_STEP_TRANSPORT=http` | Analyst calls step HTTP URLs instead of stdio |
| `FNOL_INTAKE_URL` / `FNOL_POLICY_URL` / `FNOL_RULES_URL` / `FNOL_CITATIONS_URL` | Step base URLs |
| `FNOL_MODEL_PROVIDER=azure` | Use Foundry Gemma instead of Bedrock. Also required for the intake prompt-injection check; without it every case with leftover document lines routes `manual_review` |
| `FNOL_FOUNDRY_ENDPOINT` | Foundry / Azure OpenAI style endpoint |
| `FNOL_FOUNDRY_DEPLOYMENT` | Default `gemma-4-31b` |
| `FNOL_CONTENT_SAFETY_ENDPOINT` | Optional Content Safety scan before `assess()` |
| `FNOL_AI_ENABLED=1` | Fill `evidence_summary` (default off) |

## Deploy

1. Accept Marketplace terms and request quota for Gemma 4 31B in the target region. Create a Foundry deployment named `gemma-4-31b`.
2. Build and push the image: `docker build -f deploy/Dockerfile -t $ACR/fnol:azure .`
3. Copy `deploy/azure/parameters.example.json`, fill `containerImage`, `sqlAdminObjectId`, and `foundryEndpoint`.
4. Deploy: `az deployment group create -g $RG -f deploy/azure/main.bicep -p @parameters.json`
5. Apply SQL scripts in order from `deploy/azure/sql/` against database `fnol`.
6. Upload `data/dev/documents/*.md` to `case-documents`, `data/dev/policies/*.md` to `policy-wording`, and `data/dev/dataset.json` to `fnol-fixtures`.
7. Grant each Container App managed identity access to Blob (Storage Blob Data Reader/Contributor), SQL (db roles), and Foundry/Content Safety as needed.
8. Assign Entra app role `Claims.Reviewer` to humans who approve. Configure Easy Auth on the reviewer app so only that role reaches `/v1/*`.

## Fresh proof run

With AI off (`FNOL_AI_ENABLED=0`):

```sh
# Start job / run analyst prepare against the Azure stack
uv run --locked python -m fnol_analyst prepare --out submissions/results.json

# Human approves via reviewer HTTP (or local runtime.py for SQLite)
# POST /v1/approve/{review_id} with Claims.Reviewer

uv run --locked python -m fnol_analyst file --case-id CASE_ID

uv run --locked python tools/evaluate.py \
  --data data/dev \
  --gold feedback/dev_gold.json \
  --submission submissions/results.json \
  --report reports/azure.json
```

Cutover is green when pytest passes locally (this branch), the AI-off draft hash for a known case matches the pre-Azure hash, and `evaluate.py` reports against `feedback/dev_gold.json` after one approve-and-file pass.

## Optional state copy

```sh
export FNOL_SQL_SERVER=...
uv run --locked --group azure python tools/migrate_state.py --state-dir .state
```

## Rollback

Unset the Azure environment variables (or scale Container Apps to zero) and run the local mock + stdio path. Assessment and CI never require Azure.
