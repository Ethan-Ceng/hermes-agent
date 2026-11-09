"""Bind standalone room calls to their selected Profile, including owner-absent reads."""


def invoke(params, call):
    from gateway.run import _profile_runtime_scope
    from hermes_constants import get_hermes_home
    from tui_gateway.methods_groups_forward import _home
    from tui_gateway import methods_groups
    server = methods_groups._bound_server
    home = get_hermes_home() if server is None else _home(server, params)
    with _profile_runtime_scope(home):
        return call()


def service_matches(service):
    from gateway.hosted_rooms import default_db_path
    from hermes_db.domains.rooms.api import normalize_location, RoomStoreRef
    current, selected = normalize_location(service.db_path), normalize_location(default_db_path())
    if isinstance(current, RoomStoreRef) or isinstance(selected, RoomStoreRef):
        return current == selected
    return current.parent.resolve() == selected.parent.resolve()
