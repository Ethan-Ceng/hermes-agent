# hermes_db ownership

Read the root guide and [two-layer design](../docs/designs/hermes-db-two-layer-boundary.md).

- Concrete database implementations live directly in `infra/sqlite/` and `infra/postgresql/`.

- `infra/` and technical root `factory`, `settings`, `scope`, `errors` accept resolved facts;they own drivers,pools,transactions,technical failures,release,version checks and explicit migration execution. They cannot import business tables/catalog/stores or application composition.
- `domains/`, business root contracts/resources, `core/catalog.py`, `tables/` and `migrations/` own named business SQL,scope predicates,receipts,constraints and Schema content. Supply actual connections/resources and explicit callbacks;do not resolve Profiles/secrets,spawn Worker/RPC,perform file/network effects or construct engines here. `api.py` has no composition exemption.
- Application owners live in `hermes_cli/`, `agent/`, `gateway/`, `cron/` and the existing public `plugins/plugin_storage.py`. Move actual definitions and fix consumers,closed dynamic tables,test patch sites,skills and active docs together;no internal re-export shims or unused registration layers.
- Ordinary startup/acquisition checks existing Schema and executes no DDL. Explicit Profile create/upgrade,plugin enable/setup or plugin `db upgrade` own provisioning. Backend selection chooses independent datasets and never copies,dual-writes,falls back or hot-swaps live sessions.
- Preserve 65 fixed resources,0031/31 revisions/29 table modules,DB Python <=359 and root11. Do not edit historical SQL or flatten revisions. Application moves are not net code deletion.
- Preserve original same-connection fences,lock order,authorized reads/pins,safe retirement,COMMIT outcomes and close/drain. Use `scripts/run_tests.sh` with an isolated HOME/RUNTIME bound before PM/import;PG tests only use fixture-owned random schemas.
- Run `scripts/hermes_db_boundary_lint.py --check` and applicable root checks. Symbol-specific pure-policy reuse needs an ownership reason;reviews never waive direction or side-effect rules.
