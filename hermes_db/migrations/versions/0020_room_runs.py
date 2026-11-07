"""Frozen driver leases and attempt generations; schema creation is explicit only."""

from alembic import op

revision = "0020_room_runs"
down_revision = "0019_room_events"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema = conn.dialect.identifier_preparer.quote(op.get_context().config.attributes["schema"])
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_driver_leases (store_id TEXT NOT NULL, room_id TEXT NOT NULL, "
        "gateway_id TEXT NOT NULL, authority_epoch BIGINT NOT NULL CHECK(authority_epoch >= 1), process_generation TEXT NOT NULL, "
        "lease_generation BIGINT NOT NULL CHECK(lease_generation >= 1), expires_at DOUBLE PRECISION NOT NULL, "
        "acquired_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL, released_at DOUBLE PRECISION, "
        f"PRIMARY KEY(store_id,room_id), FOREIGN KEY(store_id,room_id) REFERENCES {schema}.hosted_rooms(store_id,room_id) ON DELETE CASCADE)")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_driver_tasks (store_id TEXT NOT NULL, room_id TEXT NOT NULL, "
        "task_id TEXT NOT NULL, thread_id TEXT NOT NULL, turn_id TEXT NOT NULL, source_event_seq BIGINT NOT NULL CHECK(source_event_seq >= 1), "
        "payload_json BYTEA NOT NULL, payload_digest TEXT NOT NULL, status TEXT NOT NULL "
        "CHECK(status IN ('queued','running','settled','failed','cancelled','indeterminate','deferred','stopping')), "
        "execution_generation BIGINT NOT NULL DEFAULT 0 CHECK(execution_generation >= 0), "
        "cancel_generation BIGINT NOT NULL DEFAULT 0 CHECK(cancel_generation >= 0), run_gateway_id TEXT, run_process_generation TEXT, "
        "run_lease_generation BIGINT, cancel_id TEXT, settlement_id TEXT, settlement_status TEXT, result_json BYTEA, "
        "created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL, started_at DOUBLE PRECISION, "
        "terminal_at DOUBLE PRECISION, indeterminate_at DOUBLE PRECISION, PRIMARY KEY(store_id,room_id,task_id), "
        f"UNIQUE(store_id,room_id,thread_id,turn_id), FOREIGN KEY(store_id,room_id) REFERENCES {schema}.hosted_rooms(store_id,room_id) ON DELETE CASCADE)")
    conn.exec_driver_sql(f"CREATE INDEX idx_hosted_room_driver_tasks_status ON {schema}.hosted_room_driver_tasks "
                         "(store_id,room_id,status,source_event_seq,created_at,task_id)")
    conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_policy_publications (store_id TEXT NOT NULL, "
        "room_id TEXT NOT NULL, task_id TEXT NOT NULL, kind TEXT NOT NULL, execution_generation BIGINT NOT NULL DEFAULT 0, "
        "seq BIGINT NOT NULL, PRIMARY KEY(store_id,room_id,task_id,kind,execution_generation), "
        f"FOREIGN KEY(store_id,room_id) REFERENCES {schema}.hosted_rooms(store_id,room_id) ON DELETE CASCADE)")
    for suffix in ("source", "pending"):
        extra = "target_install_id TEXT NOT NULL, route_generation TEXT NOT NULL, status TEXT NOT NULL," if suffix == "pending" else ""
        key = ",target_install_id" if suffix == "pending" else ""
        conn.exec_driver_sql(f"CREATE TABLE {schema}.hosted_room_work_records_{suffix} (store_id TEXT NOT NULL, "
            "room_id TEXT NOT NULL, producer_gateway_id TEXT NOT NULL, producer_epoch BIGINT NOT NULL, "
            "revision BIGINT NOT NULL, digest TEXT NOT NULL, record_json BYTEA NOT NULL, disposition TEXT NOT NULL "
            "CHECK(disposition IN ('current','superseded_authority','historical','invalid')), "
            f"{extra} PRIMARY KEY(store_id,room_id,producer_gateway_id,producer_epoch{key}), "
            f"FOREIGN KEY(store_id,room_id) REFERENCES {schema}.hosted_rooms(store_id,room_id) ON DELETE CASCADE)")
    _work_guards(conn, schema)


def _work_guards(conn, schema):
    # Older writers must not relabel or replace historical/invalid retained bytes.
    conn.exec_driver_sql(f"""CREATE FUNCTION {schema}.hermes_room_work_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $guard$
        BEGIN
          IF TG_OP='DELETE' THEN
            IF OLD.disposition!='current' AND EXISTS (SELECT 1 FROM {schema}.hosted_rooms
                WHERE store_id=OLD.store_id AND room_id=OLD.room_id AND disbanded_at IS NULL) THEN
              RAISE EXCEPTION 'historical work record is immutable' USING ERRCODE='23514';
            END IF;
            RETURN OLD;
          END IF;
          IF (NEW.store_id,NEW.room_id,NEW.producer_gateway_id,NEW.producer_epoch)
                IS DISTINCT FROM (OLD.store_id,OLD.room_id,OLD.producer_gateway_id,OLD.producer_epoch)
             OR (OLD.disposition!='current' AND (NEW.record_json,NEW.revision,NEW.digest,NEW.disposition)
                IS DISTINCT FROM (OLD.record_json,OLD.revision,OLD.digest,OLD.disposition)) THEN
            RAISE EXCEPTION 'historical work record is immutable' USING ERRCODE='23514';
          END IF;
          IF TG_TABLE_NAME='hosted_room_work_records_pending' AND OLD.disposition!='current' THEN
            IF (NEW.status,NEW.route_generation,NEW.target_install_id)
                IS DISTINCT FROM (OLD.status,OLD.route_generation,OLD.target_install_id) THEN
              RAISE EXCEPTION 'historical delivery outcome is immutable' USING ERRCODE='23514';
            END IF;
          END IF;
          RETURN NEW;
        END $guard$""")
    for suffix in ("source", "pending"):
        conn.exec_driver_sql(f"CREATE TRIGGER trg_work_{suffix}_immutable BEFORE UPDATE OR DELETE "
            f"ON {schema}.hosted_room_work_records_{suffix} FOR EACH ROW EXECUTE FUNCTION {schema}.hermes_room_work_immutable()")
    conn.exec_driver_sql(f"""CREATE FUNCTION {schema}.hermes_room_work_freeze() RETURNS trigger
        LANGUAGE plpgsql AS $freeze$
        BEGIN
          UPDATE {schema}.hosted_room_work_records_source SET disposition='historical'
            WHERE store_id=NEW.store_id AND room_id=NEW.room_id AND disposition='current'
              AND (producer_gateway_id!=NEW.authority_gateway_id OR producer_epoch!=NEW.authority_epoch);
          UPDATE {schema}.hosted_room_work_records_pending
            SET disposition=CASE WHEN status='acked' THEN 'historical' ELSE 'superseded_authority' END
            WHERE store_id=NEW.store_id AND room_id=NEW.room_id AND disposition='current'
              AND (producer_gateway_id!=NEW.authority_gateway_id OR producer_epoch!=NEW.authority_epoch);
          RETURN NEW;
        END $freeze$""")
    conn.exec_driver_sql(f"CREATE TRIGGER trg_work_authority_freeze AFTER UPDATE OF authority_gateway_id,authority_epoch "
        f"ON {schema}.hosted_rooms FOR EACH ROW EXECUTE FUNCTION {schema}.hermes_room_work_freeze()")


def downgrade():
    raise RuntimeError("Storage downgrade is unsupported; use an administrator-managed database backup")
