"""Post-update verification follows the selected storage capability."""


def print_postgresql_completion(message):
    from hermes_constants import get_hermes_home
    from hermes_cli.db_diagnostics import configured_probe
    from hermes_cli.update_cmd import _print_update_completion
    report = configured_probe(get_hermes_home())
    if report["status"] != "ok":
        print("Code updated; PostgreSQL system storage is not ready. Inspect `hermes db status` before restarting business work.")
        return False
    _print_update_completion(message)
    return True
