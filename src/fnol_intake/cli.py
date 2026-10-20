"""Command line for the intake server."""

import argparse

from fnol_foundation.stores import Stores, database_url

from fnol_intake.run import DocumentMissing, IntakeError, run_intake


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ingest FNOL cases from the mock API into Postgres.")
    parser.add_argument("--mock-url", required=True)
    parser.add_argument("--documents-dir", required=True)
    parser.add_argument("--policies-dir", required=True)
    parser.add_argument("--dsn", default=None, help="Postgres DSN. Defaults to FNOL_DATABASE_URL.")
    args = parser.parse_args(argv)
    stores = Stores(args.dsn or database_url())
    try:
        result = run_intake(stores, args.mock_url, args.documents_dir, args.policies_dir)
    except DocumentMissing as exc:
        print(exc)
        return 1
    except IntakeError as exc:
        print(f"{exc.error_code}: {exc}")
        return 1
    finally:
        stores.close()
    for revision in result["revisions"]:
        print(f"{revision.case_id} revision {revision.revision}")
    return 0
