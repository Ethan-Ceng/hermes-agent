"""Stable multilingual recall corpus; IDs do not encode database row sequences."""

ROWS = [
    ("standup", "user", "Sarah prefers the standup meeting scheduled early on Thursday mornings"),
    ("answer", "assistant", "Noted, standup moved to Thursday."),
    ("daemon", "user", "graphiti daemon looks healthy today"),
    ("cjk", "user", "我们计划在广西桂林讨论数据库连接池，修改youer服务端。"),
    ("code", "assistant", "Edit my-app.config.ts with docker networking and TLS."),
    ("literal", "user", "完成率100%_ok，单引号'及路径 C:/work/project"),
]


def populate(store):
    store.create_session("search", "cli", model="model")
    for index, (_, role, text) in enumerate(ROWS):
        store.append_message("search", role=role, content=text, timestamp=200 + index)


def recall_contract(store):
    populate(store)
    for query, needle in [("standup Thursday", "standup"), ("when does Sarah like her standup scheduled", "standup"),
        ('"docker networking"', "docker"), ("networ*", "network"), ("桂林", "桂林"), ("库", "库"),
        ("数据库连接池", "数据库"), ("youer", "youer"), ("my-app.config.ts", "config")]:
        rows = store.search_messages(query)
        assert rows, query
        assert needle.casefold() in " ".join(row["snippet"].casefold() for row in rows), query
    assert store.search_messages("zebra xylophone quantum") == []
    assert store.search_messages("站会 周五") == []
    assert all("thursday" not in row["snippet"].lower() for row in store.search_messages("standup NOT Thursday"))


def filter_contract(store):
    populate(store)
    assert store.search_messages("standup", source_filter=["api_server"]) == []
    assert store.search_messages("standup", exclude_sources=["cli"]) == []
    started = store.get_session("search")["started_at"]
    assert store.search_messages("standup", after_ts=int(started) + 1) == []
    assert store.search_messages("standup", before_ts=int(started)) == []
    assert all(row["role"] == "assistant" for row in store.search_messages("standup", role_filter=["assistant"]))
    rows = store.search_messages("standup", fields=["id", "role"])
    assert rows and all(set(row) == {"id", "role"} for row in rows)
    assert store.search_messages("standup", sort="oldest", limit=1)[0]["timestamp"] == 200
    assert store.search_messages("standup", sort="newest", limit=1)[0]["timestamp"] == 201
    full = store.search_messages("standup", sort="oldest", limit=20)
    assert store.search_messages("standup", sort="oldest", limit=1, offset=1) == full[1:2]
    assert all(row["context"] and "content" not in row for row in full)
