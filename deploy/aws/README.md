# AWS deploy

Two stacks, in this order. Both stay in us-east-1.

1. `foundation.yaml` — evidence bucket, KMS key, ECR repository, log groups, task roles, permissions boundary.
2. `data.yaml` — VPC with two private subnets, security groups, RDS PostgreSQL, the managed master secret, and IAM connect policies for the task roles that already exist.

The database is not public. Storage and the master secret use the foundation KMS key. Automated backups default to 7 days. Multi-AZ defaults to off (`MultiAZ=true` turns it on). Deletion protection defaults to on. IAM database authentication is on. Task roles can `rds-db:connect` only as their own database user. They cannot read the master secret. `fnol-migrate` can read that secret and nothing else.

Evidence objects stay in S3 (`case-documents/`, `policy-wording/`). Do not load old SQLite files. Run intake again so revisions are written into Postgres.

## Deploy

```sh
aws cloudformation deploy \
  --region us-east-1 \
  --stack-name fnol-foundation \
  --template-file deploy/aws/foundation.yaml \
  --capabilities CAPABILITY_NAMED_IAM

KEY_ARN=$(aws cloudformation describe-stacks --region us-east-1 \
  --stack-name fnol-foundation \
  --query "Stacks[0].Outputs[?OutputKey=='KeyArn'].OutputValue" --output text)
BOUNDARY=$(aws cloudformation describe-stacks --region us-east-1 \
  --stack-name fnol-foundation \
  --query "Stacks[0].Outputs[?OutputKey=='TaskBoundaryArn'].OutputValue" --output text)
```

Pass `PermissionsBoundaryArn` so the migrate role sits under the same ceiling as the task roles. Omit it and the migrate role is limited to the secret policy in the template.

```sh
aws cloudformation deploy \
  --region us-east-1 \
  --stack-name fnol-data \
  --template-file deploy/aws/data.yaml \
  --parameter-overrides EvidenceKeyArn="$KEY_ARN" PermissionsBoundaryArn="$BOUNDARY" MultiAZ=false \
  --capabilities CAPABILITY_NAMED_IAM
```

Confirm `EngineVersion` (default `16.8`) is still offered in RDS before the first deploy. `db.t4g.micro` is the default class.

`CreateVpcEndpoints` defaults to true. Those endpoints let a task in the private subnets pull from ECR, write logs, and read Secrets Manager without a NAT gateway. Interface endpoints have an hourly charge. Set `CreateVpcEndpoints=false` only if another path reaches those APIs.

## Migrate

From a task in the service security group (the database is not reachable from the public internet):

```sh
export FNOL_DB_SECRET_ARN="$(aws cloudformation describe-stacks --region us-east-1 \
  --stack-name fnol-data --query "Stacks[0].Outputs[?OutputKey=='MasterSecretArn'].OutputValue" --output text)"
export FNOL_PG_NAMESPACE=shared
uv run --group postgres python tools/migrate.py
```

The command applies `deploy/aws/sql/postgres/*.sql` once per namespace and records versions in `public.fnol_schema_migrations`. Run it again after adding a new SQL file. Do not edit a file that has already been applied.

That creates the schemas and the login roles `fnol_intake`, `fnol_policy`, `fnol_rules`, `fnol_citations`, `fnol_analyst`, `fnol_enterprise`, `fnol_reviewer`, and `fnol_desk`. On RDS they are granted `rds_iam`.

## Task environment

Each service sets its own database user. Example for intake:

```sh
FNOL_RDS_IAM_AUTH=1
FNOL_RDS_HOST=<DatabaseEndpoint output>
FNOL_RDS_PORT=5432
FNOL_RDS_DB=fnol
FNOL_RDS_USER=fnol_intake
FNOL_PG_NAMESPACE=shared
AWS_REGION=us-east-1
```

Leave `FNOL_DATABASE_URL` unset on tasks. The process builds a short-lived IAM auth token and connects with TLS (`sslmode=require`). Use `fnol_policy`, `fnol_rules`, `fnol_citations`, `fnol_analyst`, `fnol_enterprise`, or `fnol_reviewer` for the other services. The desk uses `fnol_desk`. The reviewer task role may connect as `fnol_reviewer` or `fnol_desk`.

`FNOL_STATE_DIR` is only the SQLite directory. On Postgres with `FNOL_PG_NAMESPACE=shared`, every task uses the same schemas regardless of that path.

## Local Postgres

```sh
docker compose up -d postgres
export FNOL_DATABASE_URL=postgresql://fnol:fnol@127.0.0.1:5432/fnol
export FNOL_PG_NAMESPACE=shared
uv run --group postgres python tools/migrate.py
```

`docker compose up mock` runs that migration and then the mock. Host commands without `FNOL_DATABASE_URL` keep using SQLite files under `.state/`.

CI sets `FNOL_PG_NAMESPACE=isolate` so each test directory gets its own schemas on one server. Do not use `isolate` for a real deployment.
