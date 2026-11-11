"""Fresh maintenance process: every SQLite constructor is forbidden before app imports."""

import sys


def audit(event, _args):
    if event == "sqlite3.connect":
        raise AssertionError("PG maintenance attempted SQLite")


sys.addaudithook(audit)

if __name__ == "__main__":
    from hermes_cli.db_maintenance import maintain_profile
    assert maintain_profile(sys.argv[1])["backend"] == "postgresql"
