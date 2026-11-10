---
title: Database Backends
description: Profile-scoped SQLite and PostgreSQL domains, transactions, migrations and verification
---

# Database backends

The profile's `storage.backend` selects SQLite or PostgreSQL for all system-owned
databases. Configuration, Markdown, existing JSON formats, workspace files and
attachment content retain their file formats. See the
[configuration and administration guide](../user-guide/postgresql-session-storage.md).

## Boundaries and ownership

`hermes_cli/db_setup.py` resolves configuration and secrets in the owning profile.
`hermes_cli/db_sessions.py` and `hermes_cli/db_domains.py` acquire business resources.
`hermes_db/factory.py` selects a technical `BackendResource` from the resolved settings,
explicit native path and business schema token. It does not resolve a Profile or construct stores.
`hermes_db/core/catalog.py` declares each implemented capability, its minimum
revision and its current table modules. These imports do not require a PG driver
in SQLite mode.

| Layer | Responsibility |
| --- | --- |
| Existing facade and selected domain adapter | Preserve public business inputs, records and errors |
| `hermes_db/domains/` | Business resources, captured scope and named persistence operations |
| `hermes_db/core/` | Driver-free values and the business capability catalog |
| `hermes_db/integration/` | Store composition, profile binding and cross-domain coordination |
| `hermes_db/domains/<domain>/postgres/queries/` | Core statements, scoped predicates and lossless row conversion |
| `hermes_db/domains/<domain>/postgres/operations/` | Locks, quotas, state transitions, receipts and multi-step transactions |
| `hermes_db/tables/` | Shared current Core metadata, composite keys and scope-preserving foreign keys |
| `hermes_db/infra/backends/postgresql/transactions.py` | Bounded connections, transaction outcomes and sanitized failures |
| `hermes_db/migrations/` | Explicit forward Alembic revisions and frozen historical schema definitions |

PostgreSQL pools and technical transaction outcomes live under `hermes_db/infra/backends/postgresql/`.
Transactions receive the business schema translation token explicitly. Lossless query value
helpers live in `hermes_db/domains/sql/postgresql.py`; worker change observation belongs to
`hermes_db/domains/runtime/postgres/change_tracking.py`.

Small domains keep scoped statements and their operations together: Projects and
verification use a single `postgres.py`; Cron separates execution history, durable
delivery and notepad quotas; metrics separates counter records from its persistent
outbox. Projects shares slug and path rules with the native implementation in
`hermes_db/domains/projects/rules.py`. Larger domains retain separate query and
workflow modules where they have distinct responsibilities.

PG sessions use explicit catalog, messages, history, lifecycle and usage components,
plus profile transfer coordination. `hermes_db/integration/session_composition.py`
binds them to one captured context; transactions, deferred accounting, close state
and transcript snapshot pins retain the same resource identity. Native and PG
share pure transcript, search and validation rules.

Runtime admissions, local history, policy, workers and media borrow that session
context through `hermes_db/integration/runtime_composition.py`. Writes retain the
profile binding; runtime reads reuse session snapshot pins and close state. The
delegation ledger keeps its additional store fence on the same Connection.

Kanban persistence lives in named workflows directly under
`hermes_db/domains/kanban/postgres/`: catalog/DAG retraction, claims, review,
completion, dispatch, runs, files, workspaces, notifications, owners and
maintenance. Profile/Board transfer and application callbacks are composed under
`hermes_db/integration/`. Shared scoped statements and run evidence stay separate to preserve
a one-way import graph; receipts, effects and swarm retain their own lifecycle.

Rooms use lifecycle, ownership, grants, tasks, work, policy and replication
workflows with shared scoped statements. Attachment metadata shares its SQL
owner; file gates, authorization snapshots and content I/O retain separate
composition so no database connection spans byte I/O.

Cron process identity, active-send tracking, profile-bound clocks and post-commit
observers are supplied by `hermes_db/integration/cron_application.py`; its SQL
workflows keep their existing connection and lock ownership. RetainDB's HTTP
client/thread coordination lives in `hermes_db/integration/retain_transport.py`,
while durable queue transitions remain in its domain. Hosted media decoding,
retirement collection and API image compaction are composed at the owning profile.

`scripts/hermes_db_boundary_lint.py`, included in `scripts/check`, enforces the
infrastructure/domain/composition direction. Its review registry grants specific
symbols to named consumers: shared values and pure policy, Agent transcript
semantics, API dispatch and Native SQLite bridges have separate reasons. A new
helper needs review; approving one symbol does not approve the rest of its module.
Native facades cannot be imported by lower PG workflows. Historical migrations
remain frozen and do not receive runtime dependency permissions.

SQLite technical connections, transactions, WAL, lock guards and runtime inspection live under
`hermes_db/infra/backends/sqlite/`. They accept resolved options and never initialize business
Schema during ordinary `open_db`. `hermes_cli/db_sqlite_policy.py` captures Profile WAL settings
and composes explicit `initialize_profile_sqlite` calls with the existing business algorithms.

SQLite retains its native implementations. Domain adapters select PG before a
SQLite file-existence check or connection. There is no general SQLite SQL
translator or PG object pretending to be a SQLite connection. A migrated
consumer uses a named operation rather than `_conn`, raw cursors or arbitrary
SQL callbacks.

Every PG key, lookup, mutation, unique constraint and foreign key preserves
`store_id`. Board, room, plugin, account and device keys add domain scope. They do
not replace it. Composite foreign keys prevent cross-store or cross-Board links.
Keep arbitrary JSON and text lossless, including NUL; domain codecs use byte
columns where PostgreSQL text/JSON cannot represent the original value.

Background callbacks bind the captured home and secret scope. Do not read the
launch profile's environment or infer a PG owner from `state.db` or another
SQLite path. Deferred references freeze the store and a credential-free target
fingerprint, including the database and schema; a changed target is refused.
Profile rename preserves the store and reanchors typed local paths with a
resumable local operation journal before publishing the destination.

## Transactions and files

Use short resource `read()`/`write()` contexts. Keep filesystem work, model/API
calls, waits and plugin observers outside borrowed connections. Preserve each
domain's lock order, conditional transitions and terminal-state rules. The pool
is per process and connection configuration; distinct processes and pool settings
consume separate budgets.

Confirmed serialization/deadlock rollbacks differ from unknown COMMIT outcomes.
Do not retry an unknown action under a new identity or silently choose SQLite.
Persist immutable receipts with the primary effect and reconcile the original
request. Canonical session writes remain owned by the gateway and its adopted
worker protocol.

Files are not part of an SQL transaction. Attachment generations, import stages,
workspace cleanup and Board retirement use durable preparation/cleanup intents
and explicit local ownership markers. Retain a pending intent after interruption
or an unknown commit. Do not reclaim a running worker upload or release a
workspace deletion fence based on age. The owning profile's maintenance replays
these intents under the existing file gate and database fences.

Post-commit Kanban work uses a staged outbox committed with the primary action.
An external hook may be attempted again after a crash; it is not exactly-once.
RetainDB also has an at-least-once remote boundary. Metrics preserve consent,
aggregation windows and immutable sending packages; selecting PG does not enable
telemetry or widen its payload.

## Migrations and optional features

Ordinary startup checks readiness and performs no DDL. `hermes db upgrade`
explicitly upgrades the selected schema. Append a revision rather than editing
an already shipped historical revision. Current domain tables and capabilities
must match the migration head. The administrator supplies `pg_trgm`; neither
startup nor an upgrade installs services or extensions.

New PG datasets do not consume legacy SQLite databases, old encryption keys or
JSONL mirrors. There is no SQLite import, dual-write or reverse migration.
Profile file backups and restores cannot stand in for a PG database backup.

Plugin authors use portable `plugin_store` operations for JSON KV/CAS/TTL or a
real domain protocol. The SQLite `plugin_db()` SQL API is explicitly incompatible
with PG. Report the plugin and missing capability instead of disabling it or
reporting a successful in-memory write.

Matrix uses the actual pinned mautrix CryptoStore protocol and SDK encryption
objects. Its Linux-only PM extra is an existing platform boundary. The PG
adapter uses synchronous Core/psycopg behind the async SDK boundary and never
opens the SDK SQLite store or an asyncpg pool. SDK handler failures must reach
the caller before advancing the persisted sync cursor. The SQLite SDK's import
of an asyncpg exception type does not imply a PostgreSQL connection.

## Verification

Run Python tests through `scripts/run_tests.sh` using a PM-managed test
environment. PostgreSQL tests take a private `--postgres-test-config` path and
verify the database name and the ownership marker on a fresh random schema.
They never reuse business tables. The PG directory automatically rejects all
SQLite connections, including memory/URI forms and direct constructors.

```bash
scripts/run_tests.sh tests/hermes_db/contracts/test_single_backend.py
scripts/run_tests.sh tests/hermes_db/postgresql/test_single_backend.py -- -m integration --postgres-test-config /private/postgresql.yaml
scripts/run_tests.sh tests/hermes_db/postgresql/scenarios/kanban_full_gateway.py -- -m integration --postgres-test-config /private/postgresql.yaml
```

The combined PG process writes all domains, including actual Matrix SDK crypto
and the RetainDB pending queue, then a fresh interpreter reads two stores in
reverse profile order. Ordinary daemon tests separately exercise actual adopted
workers, local model tools and restart receipts. Neither an absent `.db` file
nor a compiled SQL statement is sufficient evidence.

SQLite acceptance refuses PG core imports and proves fresh-process recovery.
Its Linux SDK case retains the real upstream exception-type dependency while
rejecting PG connection functions. A separate file-input process verifies user
SQLite documents without weakening the PG business guard.

Installation verification requires explicit PM-built interpreters and an exported
source-bundle. The probes use `-I`, run outside the checkout, verify the installed
package's location, initialize an ownership-checked PG schema, repeat the upgrade
and recover all domains after process exit. Pass these arguments to the runner:

```bash
scripts/run_tests.sh tests/hermes_db/test_distribution.py -- --hermes-distribution-source /independent/source --hermes-sqlite-python /independent/sqlite-env/bin/python --hermes-postgresql-python /independent/pg-env/bin/python
scripts/run_tests.sh tests/hermes_db/postgresql/test_distribution_initialization.py -- -m integration --postgres-test-config /private/postgresql.yaml --hermes-distribution-source /independent/source --hermes-postgresql-python /independent/pg-env/bin/python
```

The full SDK cases run on Linux with the Matrix extra. Windows independently
checks its supported installation, migration and business surfaces. Skips due
to absent explicit installation arguments are not evidence of a passing release
artifact. Record failures, platform coverage, exact commands and recovery points
in the implementation plan, followed by final verification and independent review.
