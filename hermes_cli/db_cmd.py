"""Profile-bound schema commands; PostgreSQL instances remain administrator-owned."""

import json
import sys


def run_db_command(args):
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_db.errors import StorageError

    try:
        settings, scope = resolve_db_configuration()
        if settings.backend == "sqlite":
            from hermes_cli.db_session_schema import sqlite_session_schema_status, upgrade_sqlite_session_schema

            operation = {"status": sqlite_session_schema_status, "upgrade": upgrade_sqlite_session_schema}[args.db_action]
            result = operation(scope)
        else:
            from hermes_db.schema import schema_status, upgrade_schema

            operation = {"status": schema_status, "upgrade": upgrade_schema}[args.db_action]
            result = operation(settings.postgresql)
            result["store_id"] = scope.store_id
    except StorageError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ready", True) else 1
