"""Register explicit database administration without importing optional drivers."""


def _dispatch(args):
    from hermes_cli.db_cmd import run_db_command

    return run_db_command(args)


def build_db_parser(subparsers):
    parser = subparsers.add_parser("db", help="Inspect or explicitly upgrade session storage schema")
    commands = parser.add_subparsers(dest="db_action", required=True)
    for name in ("status", "upgrade"):
        command = commands.add_parser(name, help=f"{name.capitalize()} the selected profile's session database schema")
        command.set_defaults(func=_dispatch)
