"""Owner identity for the SQLite store doubles used by managed execution unit contracts."""


class SQLiteWorkerStoreIdentity:
    def __init__(self, rpc, scope, *args):
        self.profile_home = scope['profile_id']

    def owner_read(self, name, **arguments):
        assert name == 'storage.identity' and not arguments
        return {'version': 1, 'backend': 'sqlite', 'profile_home': self.profile_home,
                'store_id': None, 'target': None}
