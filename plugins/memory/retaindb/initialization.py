"""Initialize configuration, credentials and queue inside the provider's owning Profile."""

import os
import re
from pathlib import Path


def initialize(provider, session_id, **kwargs):
    from hermes_cli.db_setup import _owning_profile
    from hermes_constants import get_hermes_home
    from . import _Client, _WriteQueue, _DEFAULT_BASE_URL, _load_retaindb_config, _quiet, get_secret, spawn_context_thread
    home = Path(kwargs["hermes_home"]) if kwargs.get("hermes_home") else get_hermes_home()
    home = home.resolve()
    if provider._queue is not None:
        provider._queue.shutdown()
    with _owning_profile(home):
        config = {key: value.strip() for key, value in _load_retaindb_config().items() if isinstance(value, str)}
        base_url = re.sub(r"/+$", "", get_secret("RETAINDB_BASE_URL", "") or config.get("base_url") or _DEFAULT_BASE_URL)
        project = get_secret("RETAINDB_PROJECT", "") or config.get("project")
        if not project:
            profile_name = os.path.basename(str(kwargs.get("hermes_home", "")))
            project = f"hermes-{profile_name}" if profile_name not in {"", ".hermes"} else "default"
        client = provider._client = _Client(get_secret("RETAINDB_API_KEY", "") or "", base_url, project)
        provider._session_id, provider._user_id = session_id, kwargs.get("user_id", "default") or "default"
        provider._agent_id = kwargs.get("agent_id", "hermes") or "hermes"
        provider._queue = _WriteQueue(client, home / "retaindb_queue.db", profile_home=home)
        soul = (home / "SOUL.md").read_text(encoding="utf-8-sig", errors="replace").strip() if (home / "SOUL.md").exists() else ""
        if soul:
            agent_id = provider._agent_id
            seed = lambda: client.seed_agent_identity(agent_id, soul, source="soul_md")
            spawn_context_thread(_quiet, args=("soul seed", seed), name="retaindb-soul-seed").start()
