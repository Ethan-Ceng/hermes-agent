---
title: "PostgreSQL Session Storage"
description: "Configure a fresh PostgreSQL session store, initialize its schema, and budget its connections"
---

# PostgreSQL session storage

SQLite remains the default session backend. PostgreSQL is an explicit option for
session history, prompts, usage, the canonical run queue and receipts, routing,
delivery obligations, and API response/run continuation and idempotency records.
The gateway remains the owner of canonical session writes; managed workers use
its authenticated RPC interface.

The implementation has offline contract coverage. **Real PostgreSQL acceptance
has not been run for this implementation.** The test preflight requires PostgreSQL
15 or newer; no particular server version is yet certified by execution evidence.
See the repository's PostgreSQL implementation plan for the current verification
status before deploying it.

## Prepare the profile

Install the optional dependencies through Hermes PM:

```bash
hermes pm install --extra postgresql
```

Hermes uses SQLAlchemy Core, synchronous psycopg, and Alembic. It does not install,
start, or manage a PostgreSQL service. The database administrator prepares the
database, roles, backups, and the `pg_trgm` extension. Schema upgrades refuse to
proceed if that extension is missing; they do not install extensions.

In the owning profile's `config.yaml`, configure a fresh logical store:

```yaml
storage:
  session:
    backend: postgresql
    postgresql:
      dsn_env: HERMES_POSTGRES_DSN
      schema: hermes
      store_id: personal-main
      pool_size: 5
      max_overflow: 5
      connection_budget: 10
      pool_timeout_seconds: 30
      connect_timeout_seconds: 10
      write_lock_timeout_seconds: 10
      statement_timeout_seconds: 60
```

Set the connection secret in that profile's `.env` or its existing secret source:

```dotenv
HERMES_POSTGRES_DSN=postgresql+psycopg://user:password@host:5432/hermes
```

Use a libpq-compatible TLS policy in the DSN where required by your deployment.
Keep the DSN out of `config.yaml`; `dsn_env` names the secret. Profile selection
uses Hermes's ordinary `--profile` option and profile secret scope.

`schema` must be an explicit lowercase SQL identifier. `store_id` is a stable,
server-managed logical identity within that schema. Give independent profiles
different IDs. Two installations deliberately using the same database, schema,
and ID address the same logical session store. Renaming a profile preserves its
ID; cloning a profile allocates a new one. Changing an ID selects a different
store and does not move data. Database namespaces do not replace application
authorization.

## Initialize the fresh schema

Run the explicit administration commands under the owning profile:

```bash
hermes db status
hermes db upgrade
hermes db status
```

The upgrade role needs permission to create the selected schema and its objects,
or ownership of an administrator-prepared schema. Runtime roles need access to
the schema, its tables and identity sequences. Routine application startup only
checks the declared Alembic revision; it does not perform DDL. Repeated upgrades
to the current revision are safe. A nonempty schema without a recognized version
is refused. Stop application writers before upgrading and prepare an appropriate
database backup with the administrator.

Initialization checks required extensions before creating tables. Ordinary
startup and readiness checks also verify `pg_trgm`, including when the schema
revision is already current. If it is missing, `hermes db status` reports
`ready: false`, names the missing extension, and provides the repair SQL;
`hermes db upgrade` stops before schema DDL. The administrator connects to the
configured database and runs `CREATE EXTENSION IF NOT EXISTS pg_trgm;`, then
retries the upgrade. Hermes does not install extensions during application boot.

PostgreSQL starts with new data. Selecting this backend does not import an old
SQLite `state.db`, old queue formats, JSONL history, or session mirrors. It does
not dual-write or provide a migration back to SQLite. Selecting SQLite again
opens its independently retained local data.

## Connections and failure handling

The pool limit for one process and connection configuration is
`pool_size + max_overflow`; it must not exceed `connection_budget`. Include every
gateway, helper process, and distinct connection configuration when calculating
the deployment's total. Stores using the same pool borrow short-lived
connections; model calls, tools, and delivery waits do not retain transactions.
Pool limits are process-local, not a cluster-wide reservation.

Database outages, missing drivers, wrong schema revisions, and pool timeouts
produce explicit failures. Hermes does not report success by switching to SQLite,
JSONL, or an in-memory queue. When commit acknowledgement is lost, the result is
unknown: reconcile using the original request identity rather than submitting
the action with a new idempotency key. HTTP unknown-commit failures disable SDK
automatic retries with `x-should-retry: false`.

An absent local `state.db` is normal in PG mode. `hermes db status` checks the
configured backend. SQLite WAL repair, journal mode, physical optimization, and
pre-gateway history adoption apply to SQLite. Use database administration tools
for PostgreSQL maintenance and backups.

## Files and deployment boundaries

Configuration, workspaces, attachments, tool spill files, Markdown memory,
and the independent Cron/Kanban/plugin databases remain local. Hermes file
backups do not back up PostgreSQL. Hosted-room coordination also remains local;
its main sessions and canonical admissions use the configured PostgreSQL store.
Retain the owning node's required files. This backend does not implement
distributed file storage, account management, or active-active gateway ownership.
External message delivery remains best-effort and cannot promise exactly-once
effects in a remote platform.

## Developer verification

Use an independent, administrator-managed test database with `pg_trgm` already
available. A private local YAML test configuration must declare its purpose:

```yaml
purpose: hermes-postgresql-tests
database: hermes_disposable_tests
dsn: postgresql+psycopg://test-role:secret@host/hermes_disposable_tests
```

The test role needs CREATE permission for disposable schemas. Tests verify the
actual database name, use a unique ownership-marked schema, and refuse to reuse
or clean up another schema. Keep this secret file outside version control. Pass
only its path to the standard runner:

```bash
scripts/run_tests.sh tests/hermes_db/postgresql -- -m integration --postgres-test-config /private/postgresql.yaml
```

Offline SQLAlchemy contracts using SQLite validate business behavior; they do
not validate PostgreSQL locking, SQL syntax, migrations, concurrency, or recovery
under actual connection failures.
