"""Register explicit database administration without importing optional drivers."""


def _dispatch(args):
    from hermes_cli.db_cmd import run_db_command

    return run_db_command(args)


def build_db_parser(subparsers):
    parser = subparsers.add_parser("db", help="Inspect or explicitly upgrade session storage schema")
    commands = parser.add_subparsers(dest="db_action", required=True)
    descriptions = {
        "status": "Check whether the selected profile's session database is ready",
        "upgrade": "Explicitly create or upgrade the selected profile's session database",
    }
    for name, description in descriptions.items():
        command = commands.add_parser(name, help=description)
        command.set_defaults(func=_dispatch)
