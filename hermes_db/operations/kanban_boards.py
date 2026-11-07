"""Board names resolve to persistent, non-path-derived generations."""

from uuid import uuid4
from sqlalchemy import and_, delete, select, update
from sqlalchemy.dialects.postgresql import insert

from hermes_db.tables.kanban import kanban_boards as boards, kanban_board_names as names, kanban_board_locks as locks


def _scope(table, store):
    return table.c.store_id == store.scope.require_store_id()


def _registry_lock(conn, store):
    conn.execute(insert(locks).values(store_id=store.scope.require_store_id()).on_conflict_do_nothing())
    conn.execute(select(locks).where(_scope(locks, store)).with_for_update()).one()


def _lookup(conn, store, slug):
    return conn.execute(select(boards).join(names, and_(boards.c.store_id == names.c.store_id,
        boards.c.board_id == names.c.board_id)).where(_scope(boards, store), names.c.slug == slug)).mappings().one_or_none()


def _metadata(row, slug):
    from hermes_cli.kanban_db_boards import _read_metadata_file
    meta = _read_metadata_file(slug)
    if row is not None:
        meta["archived"] = bool(row["archived"])
    return meta


def _save(conn, store, slug, row, archived):
    if row is None:
        board_id = uuid4().hex
        conn.execute(boards.insert().values(store_id=store.scope.require_store_id(), board_id=board_id, slug=slug, archived=int(archived)))
        conn.execute(insert(names).values(store_id=store.scope.require_store_id(), slug=slug, board_id=board_id)
            .on_conflict_do_update(index_elements=[names.c.store_id, names.c.slug], set_={"board_id": board_id}))
    else:
        board_id = row["board_id"]
        conn.execute(update(boards).where(_scope(boards, store), boards.c.board_id == board_id).values(archived=int(archived)))
    return board_id


def resolve_board(store, slug):
    with store.read() as conn:
        row = _lookup(conn, store, slug)
    if row is None and slug == "default":
        create_board(store, slug)
        with store.read() as conn:
            row = _lookup(conn, store, slug)
    if row is None:
        raise ValueError(f"kanban board {slug!r} does not exist; create it with `hermes kanban boards create {slug}`")
    if row["archived"]:
        raise ValueError(f"kanban board {slug!r} is archived; refusing to recreate its database")
    return row["board_id"]


def read_board_metadata(store, board=None):
    from hermes_cli import kanban_db as kb
    slug = kb._slug_or_default(board)
    with store.read() as conn:
        row = _lookup(conn, store, slug)
    return _metadata(row, slug)


def board_exists(store, board=None):
    from hermes_cli import kanban_db as kb
    slug = kb._slug_or_default(board)
    with store.read() as conn:
        return slug == kb.DEFAULT_BOARD or _lookup(conn, store, slug) is not None


def write_board_metadata(store, board, *, name=None, description=None, icon=None, color=None, archived=None,
                         default_workdir=None, project_id=None):
    from hermes_cli import kanban_db as kb
    from hermes_cli.kanban_db_boards import _write_metadata_file
    kb._assert_not_delegated_child_mutation()
    slug = kb._slug_or_default(board)
    values = dict(name=name, description=description, icon=icon, color=color, archived=archived,
                  default_workdir=default_workdir, project_id=project_id)
    with store.write() as conn:
        _registry_lock(conn, store)
        row = _lookup(conn, store, slug)
        if row is not None and row["archived"] and archived is False:
            raise ValueError("Recreate an archived Board with create_board; its old generation is immutable")
        if row is not None:
            conn.execute(select(boards).where(_scope(boards, store), boards.c.board_id == row["board_id"]).with_for_update()).one()
        state = bool(row["archived"]) if row is not None and archived is None else bool(archived)
        _save(conn, store, slug, row, state)
    return _write_metadata_file(slug, **values)


def create_board(store, slug, *, name=None, description=None, icon=None, color=None, default_workdir=None, project_id=None):
    from hermes_cli import kanban_db as kb
    from hermes_cli.kanban_db_boards import _write_metadata_file
    kb._assert_not_delegated_child_mutation()
    slug = kb._require_slug(slug)
    with store.write() as conn:
        _registry_lock(conn, store)
        row = _lookup(conn, store, slug)
        if row is not None and row["archived"]:
            row = None
        _save(conn, store, slug, row, False)
    return _write_metadata_file(slug, name=name, description=description, icon=icon, color=color,
                                default_workdir=default_workdir, project_id=project_id, archived=False)


def list_boards(store, *, include_archived=True):
    with store.read() as conn:
        slugs = list(conn.scalars(select(names.c.slug).where(_scope(names, store)).order_by(names.c.slug)))
        rows = [("default", _lookup(conn, store, "default"))]
        for slug in slugs:
            if slug == "default":
                continue
            row = _lookup(conn, store, slug)
            if include_archived or not row["archived"]:
                rows.append((slug, row))
    return [_metadata(row, slug) for slug, row in rows]


def remove_board(store, slug, *, archive=True):
    from hermes_cli import kanban_db as kb
    kb._assert_not_delegated_child_mutation()
    slug = kb._require_slug(slug)
    if slug == "default":
        raise ValueError("the 'default' board cannot be removed")
    with store.write() as conn:
        _registry_lock(conn, store)
        row = _lookup(conn, store, slug)
        if row is None:
            raise ValueError(f"board {slug!r} does not exist")
        condition = and_(_scope(boards, store), boards.c.board_id == row["board_id"])
        conn.execute(select(boards).where(condition).with_for_update()).one()
        conn.execute(update(boards).where(condition).values(archived=1) if archive else delete(boards).where(condition))
    if kb.get_current_board() == slug:
        kb.clear_current_board()
    return {"slug": slug, "action": "archived" if archive else "deleted", "new_path": ""}
