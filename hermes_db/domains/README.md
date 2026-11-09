# Domain resources

`acquire_profile_domain(name, profile_home=owner, sqlite_path=legacy_path)` resolves
the owning Profile once. A Cron, Board or attachment directory is a domain location,
never a way to infer the Profile. Deferred consumers keep the resulting immutable
`DatabaseScope`; workers continue to use owner RPC rather than acquiring resources.

SQLite domain adapters use `sqlite_path` and their existing native implementation.
The catalog and resource imports do not require PostgreSQL dependencies. PG adapters
use `resource.read()` and `resource.write()` for short Core operations and pass
`resource.scope` to every repository. These units of work are internal boundaries,
not an arbitrary SQL interface for business callers. Every business query, constraint,
lock, count and deletion includes `store_id` and any domain keys.

Resources hold no checked-out connection between operations. Closing one resource
does not dispose the process pool or affect peers. Threads can use the captured
scope without consulting the ambient Profile; a forked child must acquire again.
Network, model and file waits stay outside transactions. Existing transaction error
classification, including unknown commit outcomes, is reused without write retries.

Register PG support only when the actual adapter and explicit migration exist.
`DomainSpec` names its first revision and Core table modules. `hermes db status`
reports supported modules, missing tables and `full_system_ready` separately from
readiness of currently implemented modules. An unsupported or uninitialized domain
fails explicitly. Opening a resource never creates tables. New tables use
`scoped_table`/`scoped_fk` and the shared schema translation; revisions 0001–0004
remain frozen. Domain migrations are added alongside their actual implementation,
not as placeholder tables or empty revisions.

Reuse `hermes_db.core.values.encode_text`/`decode_text` for exact text that may contain
NUL, with binary columns. Serialize arbitrary JSON with its types intact (including
booleans, numeric zero, empty containers and null); never use truthiness to drop a
valid value. PostgreSQL Text/JSONB query projections must be separately defined and
must not enter identity or digest inputs. UTF-8 byte quotas count the exact encoded
payload, not a projection. Timestamp columns keep each domain's existing instant
and timezone contract; do not normalize opaque user timestamp strings. Domain
contracts must prove these choices through real writes and reads.

Kanban uses `(store_id, board_id)` handles resolved by the owner's Board registry.
The human slug points to its current immutable generation; archive retires that
generation, and explicit same-slug creation allocates another. A held handle cannot
write a retired generation. Tasks, links, comments and events include both keys,
and every graph mutation holds the Board row lock. PG never interprets a SQLite
path override as a Board or Profile. Its local files live under the owner's Profile;
worker-owner routing, runs and workspace/subscription lifecycles have separate
capability records. PG content follows `kanban/data/<board_id>` so reusing a slug
cannot reuse another generation's files. Archive/delete/import file jobs commit
their intent before filesystem work, retain shared references, and can resume an
interrupted publication without recreating the Board. PG export/import uses the
v2 logical archive and verifies registered attachment hashes; SQLite archives
remain on the SQLite path, without cross-backend migration.

An adopted ordinary worker resolves only a slug in its owner's Profile; a Kanban
worker remains bound to its frozen Board reference. Reserved children carry their
own authenticated read claim and cannot mutate Boards. Large attachment bytes use
bounded authenticated chunks and an owner-selected private stage. The final
attachment metadata and command receipt commit together; an unknown commit keeps
the same command and stage. File-job, upload-stage and cleanup-token maintenance
must reconcile durable ownership before removing recovery material.
`board.json` remains file configuration; the PG registry only holds identity and
lifecycle. File writes happen after the registry transaction and can fail visibly;
retrying Board creation preserves the committed active generation.

Kanban run/claim transitions, dispatch ownership and worker commands use scoped
Core transactions. The dispatch lease releases connections while workers or files
are being prepared. Adopted workers call closed owner RPC verbs; they cannot
acquire an owner resource or choose another Board reference. Command results are
recorded with the primary Board effect, independently of session persistence
sequence numbers. A private worker outbox retries the original command identity.

Workspace paths are resolved outside transactions and registered as store-scoped
file references. Cleanup commits a per-path token before removing files, so a
concurrent task reference or live parent dependency cannot race the removal.
Interrupted tokens remain fenced until explicit reconciliation. File content,
workspace paths and Board configuration stay local. The `kanban_workspace`
capability also reports subscriptions, transfer and the remaining Kanban consumers.

Hosted rooms capture a `RoomStoreRef` containing the owning Profile, stable
store_id and a nonsecret database-target fingerprint. SQLite locations never
identify a PG Profile. Core room/event/replica operations hold short scoped locks;
read snapshots keep the authority and replay cursor consistent. Room limits,
event byte accounting, idempotency and permanent retired identities remain
durable. PG never imports the legacy SQLite room dataset or creates a separate
`hosted-pg-*.db` coordination ledger. Trusted transaction callbacks use `CoreEffect`.
Driver leases/tasks and passive work snapshots join the same scoped room
transactions; canonical FIFO authorization uses its own writer's connection.
Evidence capacity failures roll back a savepoint, while invalid retained bytes
remain classified and immutable. Authority changes freeze old producer scopes.
Policy cursors, bounded transcripts, terminal publication references and router
claims also persist on Core. Opaque projection identities use bytes; indexed
event query keys do not enter event identity. Model waits hold no connection and
prepared answers retain their captured authority/log fences. Attachment
publication remains a separate integration task; these contracts alone do not
establish full rooms or system readiness.
