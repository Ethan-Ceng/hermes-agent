---
title: "SQLite and PostgreSQL Storage"
description: "Select one database backend for a profile, initialize PostgreSQL, and preserve local files"
---

# SQLite and PostgreSQL storage

Each profile selects one backend for all Hermes-owned databases. SQLite is the
default and runs independently without a PostgreSQL instance or the PostgreSQL
extra. Setting `storage.backend: postgresql` selects PostgreSQL for:

- Sessions, messages, prompts, usage, canonical admissions, workers, routing,
  delivery obligations, API responses, continuation and idempotency records.
- Projects, folders, discovery caches and verification evidence.
- Cron executions, incidents, delivery queues and job notepads.
- Kanban boards, tasks, runs, subscriptions, workspace references and attachment metadata.
- Hosted rooms, events, coordination, work records, policy, routing and attachment metadata.
- Local metrics, consent, aggregate packages and the sending outbox.
- Portable plugin storage, Discord recovery, the RetainDB pending queue and Matrix encryption.

The gateway retains ownership of canonical session writes; managed workers use
authenticated RPC. Different profiles may select different backends. A component
cannot override its profile's selection.

The integration preflight requires PostgreSQL 15 or newer. Actual acceptance has
used PostgreSQL 17.11 and `pg_trgm` 1.6; this does not certify every server version.
The [implementation plan](https://github.com/NousResearch/hermes-agent/blob/main/docs/plans/unified-database-backends-plan.md)
records release gates and evidence, including independent installation and final
review. Session-only acceptance results do not establish whole-system support.

## Prepare the profile

Install the optional dependencies through Hermes PM:

```bash
hermes pm install --extra postgresql
```

Hermes uses SQLAlchemy Core, synchronous psycopg and Alembic. It does not install,
start or manage a PostgreSQL service. The administrator prepares the database,
roles, backups and `pg_trgm`. Schema upgrades refuse a missing extension rather
than installing it.

In the owning profile's `config.yaml`, configure a fresh logical dataset:

```yaml
storage:
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

The selection lives at `storage.backend` and `storage.postgresql`. Older
development configurations under `storage.session` are rejected with instructions
to move these keys. There are no separate Cron, Kanban, room or plugin backend
settings. To choose SQLite, use `storage: {backend: sqlite}`.

Set the connection secret in that profile's `.env` or its existing secret source:

```dotenv
HERMES_POSTGRES_DSN=postgresql+psycopg://user:password@host:5432/hermes
```

Use a libpq-compatible TLS policy where required. Keep the DSN out of
`config.yaml`; `dsn_env` names the secret. Profile selection uses Hermes's ordinary
`--profile` option and profile secret scope.

`schema` must be an explicit lowercase SQL identifier. `store_id` is a stable,
application-owned identity within it. Give independent profiles different IDs.
Two installations using the same database, schema and ID address the same dataset
across all domains. Renaming a profile preserves its ID and reanchors its local
content references. An interrupted PG rename keeps the destination unpublished;
resolve the reported error and retry the same rename. Cloning allocates a new ID.
Changing an ID, database or schema selects another dataset without moving data.
Captured background owners reject a changed target. Database namespaces do not
replace application authorization.

## Initialize the fresh schema

Run the explicit administration commands under the owning profile:

```bash
hermes db status
hermes db upgrade
hermes db status
```

The upgrade role needs permission to create the selected schema and its objects,
or ownership of an administrator-prepared schema. Runtime roles need access to
the schema, tables and identity sequences. Routine startup checks the declared
Alembic revision and required capabilities; it performs no DDL. Repeated upgrades
to the current revision are safe. A nonempty schema without a recognized version
is refused. Stop application writers before upgrading and arrange a database
backup with the administrator.

Initialization and readiness also check `pg_trgm`, even when the schema revision
is current. If it is missing, `hermes db status` reports `ready: false` and the
repair SQL; `hermes db upgrade` stops before schema DDL. The administrator runs
`CREATE EXTENSION IF NOT EXISTS pg_trgm;` in the configured database, then retries.

PostgreSQL starts with new data. Selecting it does not import old SQLite
databases, queue formats, JSONL history, session mirrors or Matrix keys. There is
no dual-write or migration back to SQLite. Selecting SQLite again opens its
independently retained local data.

## Connections and failures

The pool limit for one process and connection configuration is
`pool_size + max_overflow`; it must not exceed `connection_budget`. Include every
gateway, helper process and distinct connection configuration in the deployment's
total. Profiles using the same pool borrow short-lived connections. Model calls,
tools, file operations and delivery waits run outside database transactions.
Pool limits are process-local, not a cluster-wide reservation.

Outages, missing drivers, incompatible schemas and pool timeouts produce explicit
failures. Hermes does not switch to SQLite, JSONL or an in-memory queue to report
success. After a lost COMMIT acknowledgement, the outcome is unknown: reconcile
using the original request identity. Do not create a new idempotency key to guess
that the action failed. HTTP unknown-commit failures disable SDK automatic retries
with `x-should-retry: false`.

Absent local system `.db` files are normal in PG mode. `hermes db status` checks
the configured backend and complete schema. SQLite WAL repair, journal mode,
physical optimization and pre-gateway history adoption apply to SQLite. Use
administrator-managed PostgreSQL tools for its physical maintenance and backups.

## Files, backups and updates

Configuration and secrets, Cron job definitions, Markdown memory, existing JSON
files, workspaces, attachment content and tool spill files remain files. Their
database metadata uses the selected backend. Retain the owning node's required
files; PostgreSQL does not turn them into shared storage.

Hermes file backups record each profile's backend. For PG profiles they exclude
known system SQLite databases and sidecars. Restoring such a backup restores
files, not PostgreSQL rows. Arrange database backup and restoration with the
administrator. Automatic code downgrades are refused while a profile selects PG:
older code may ignore this configuration or require an older schema. SQLite
snapshot recovery is not a PostgreSQL rollback procedure.

This backend does not implement distributed file storage, account management,
Kubernetes or active-active gateway ownership. External delivery remains
best-effort. RetainDB ingestion and post-commit observers may retry after an
interrupted acknowledgement; remote effects are not exactly-once.

## Plugins and Matrix

Maintained local stores listed above follow the profile backend. External plugins
must use portable `plugin_store` operations or a supported domain adapter. The
legacy `plugin_db()` arbitrary SQLite SQL API is SQLite-only. Under PG it fails
with the plugin name and the required portable capability; it cannot silently
create another database.

Matrix encryption uses the pinned mautrix 0.21.1 SDK and native Olm dependency.
Install its supported feature group through PM:

```bash
hermes pm install --extra matrix --extra postgresql
```

The Matrix extra is supported on Linux; its existing restriction also applies to
SQLite. PG encryption uses the unified Core/psycopg store, without an SDK SQLite
connection or a separate asyncpg pool. The upstream SQLite store imports an
asyncpg exception type as part of the Matrix group; this does not require a
PostgreSQL service.

PG starts without old encryption keys. Use a fresh, verified Matrix device and
access token when the new dataset cannot match an existing device. Hermes does
not import SQLite/pickle keys, reset remote devices or promise decryption of
untransferred history. Storage failures abort encrypted startup; they do not
become a successful plaintext connection.

## Developer verification

Use an independent, administrator-managed test database with `pg_trgm` already
available. A private YAML configuration declares its purpose:

```yaml
purpose: hermes-postgresql-tests
database: hermes_disposable_tests
dsn: postgresql+psycopg://test-role:secret@host/hermes_disposable_tests
```

The test role needs CREATE permission for disposable schemas. Tests verify the
actual database name, use a unique ownership-marked schema and refuse to reuse or
clean up another schema. Keep this file outside version control. Pass only its
path to the standard runner:

```bash
scripts/run_tests.sh tests/hermes_db/postgresql -- -m integration --postgres-test-config /private/postgresql.yaml
```

The [developer guide](../developer-guide/database-backends.md) describes domain
boundaries and installation probes. Single-backend acceptance performs actual
business writes and fresh-process recovery while rejecting every SQLite
connection, including memory databases, URI connections, aliases and constructors.
User SQLite documents run in a separate file-input process. SQL compilation
contracts alone do not validate PostgreSQL locking, migrations or recovery.
