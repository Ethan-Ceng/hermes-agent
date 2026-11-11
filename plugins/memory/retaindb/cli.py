"""Active-provider CLI for explicit RetainDB local queue Schema lifecycle."""
from pathlib import Path


def register_cli(parser):
    commands = parser.add_subparsers(dest='retaindb_command', required=True)
    db = commands.add_parser('db', help='Inspect or explicitly upgrade RetainDB queue storage')
    actions = db.add_subparsers(dest='retaindb_db_action', required=True)
    actions.add_parser('status', help='Check the existing queue Schema')
    actions.add_parser('upgrade', help='Create or upgrade the local queue Schema')
    parser.set_defaults(func=dispatch)


def dispatch(args):
    from hermes_constants import get_hermes_home
    from plugins.plugin_storage import selected_storage_backend, open_plugin_database, StorageSchemaError
    from .storage_schema import initialize_queue_schema, schema_ready
    home = get_hermes_home()
    if selected_storage_backend(home) != 'sqlite':
        print('RetainDB uses PostgreSQL business Schema; use `hermes db status` or `hermes db upgrade`.')
        return 0
    if args.retaindb_db_action == 'upgrade':
        initialize_queue_schema(profile_home=home)
    try:
        open_plugin_database(Path(home) / 'retaindb_queue.db', db_label='RetainDB queue',
            ready=schema_ready, profile_home=home, wal=False).close()
    except StorageSchemaError:
        print('RetainDB queue Schema is not ready. Run `hermes retaindb db upgrade`.')
        return 1
    print('RetainDB queue Schema ready.')
    return 0
