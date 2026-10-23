-- The migrate task connects as fnol_migrate with IAM. It does not read the
-- master password secret. Service roles may read the migration ledger and
-- nothing else in public. They do not create it.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fnol_migrate') THEN
    CREATE ROLE fnol_migrate LOGIN;
  END IF;
END
$$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rds_iam') THEN
    GRANT rds_iam TO fnol_migrate;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rds_superuser') THEN
    GRANT rds_superuser TO fnol_migrate;
  END IF;
END
$$;

DO $$
DECLARE
  dbname text := current_database();
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO fnol_migrate', dbname);
END
$$;

GRANT SELECT ON public.fnol_schema_migrations TO
  fnol_migrate,
  fnol_intake,
  fnol_policy,
  fnol_rules,
  fnol_citations,
  fnol_analyst,
  fnol_enterprise,
  fnol_reviewer,
  fnol_desk;
