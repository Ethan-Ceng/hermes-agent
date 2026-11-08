"""Enumerate durable Board snapshot files without descending into content workspaces."""


def directory_files(directory, home, database_policy):
    for path in directory.rglob("*"):
        if not path.is_file() or not database_policy.include(path):
            continue
        relative = path.relative_to(home).as_posix()
        if "/workspaces/" in f"/{relative}/" or "/attachments/" in f"/{relative}/":
            continue
        yield path, relative
