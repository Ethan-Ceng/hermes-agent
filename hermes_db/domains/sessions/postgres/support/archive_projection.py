"""Current transcript/wire spillover names, independent of a database driver."""

from hermes_db.domains.sessions.postgres.support.search_projection import content_text


def spillover_names(row):
    from tools.tool_result_storage import spillover_names_in_text
    names = spillover_names_in_text(content_text(row), row.get("api_content"))
    return sorted(names) or None
