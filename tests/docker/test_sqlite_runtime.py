"""Runtime qualification for SQLite in the published Docker image."""

from __future__ import annotations

import json
import subprocess


_SQLITE_PROBE = '\nimport json\nimport sqlite3\n\nfrom hermes_db.infra.sqlite.runtime import is_sqlite_wal_reset_vulnerable\n\ndb = sqlite3.connect(":memory:")\ntry:\n    db.execute("CREATE VIRTUAL TABLE docs USING fts5(content, tokenize=\'trigram\')")\n    db.execute("INSERT INTO docs VALUES (\'hermes\')")\n    matches = db.execute(\n        "SELECT count(*) FROM docs WHERE docs MATCH \'erm\'"\n    ).fetchone()[0]\nfinally:\n    db.close()\n\nprint(json.dumps({\n    "sqlite_version": sqlite3.sqlite_version,\n    "wal_reset_vulnerable": is_sqlite_wal_reset_vulnerable(\n        sqlite3.sqlite_version_info\n    ),\n    "trigram_matches": matches,\n}))\n'


def test_image_links_fixed_sqlite_with_fts5_trigram(built_image: str) -> None:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "hermes",
            "--entrypoint",
            "/opt/hermes/.venv/bin/python",
            built_image,
            "-c",
            _SQLITE_PROBE,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, (
        f"SQLite runtime probe failed: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    payload = json.loads(result.stdout)
    assert payload["wal_reset_vulnerable"] is False, payload
    assert payload["trigram_matches"] == 1, payload
