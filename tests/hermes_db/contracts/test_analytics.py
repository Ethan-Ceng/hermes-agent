"""Terminal insights and dashboard analytics share exact scoped counters."""


def _populate(store, sid="s"):
    store.create_session(sid, "cli", model="main")
    store.append_message(sid, "user", "question")
    store.append_message(sid, "assistant", "answer", tool_calls=[
        {"type": "function", "function": {"name": "skill_view", "arguments": '{"name": "test-skill"}'}}])
    store.append_message(sid, "tool", "output", tool_name="skill_view")
    store.update_token_counts(sid, input_tokens=10, output_tokens=3, api_call_count=1, model="main", billing_provider="provider")
    store.flush_token_counts()


def test_insights_engine_reports_sessions_tools_and_skills_on_both_backends(store):
    from agent.insights import InsightsEngine
    _populate(store)
    engine = InsightsEngine(store)
    report = engine.generate()
    assert report["overview"]["total_sessions"] == 1
    assert report["overview"]["total_input_tokens"] == 10
    assert report["overview"]["user_messages"] == 1
    assert report["tools"][0]["tool"] == "skill_view" and report["tools"][0]["count"] == 1
    assert engine.generate(source="discord")["empty"]
    assert engine.get_usage_breakdown()["skills"]["summary"]["total_skill_loads"] == 1


def test_core_dashboard_usage_aggregates_and_source_filter_never_cross_store(core_pair):
    from agent.insights import InsightsEngine
    store = core_pair[0]
    for db in core_pair:
        _populate(db)
    assert store.analytics_rows("totals", 0)[0]["total_sessions"] == 1
    assert store.analytics_rows("daily", 0)[0]["input_tokens"] == 10
    assert store.analytics_rows("by_model", 0)[0]["sessions"] == 1
    main = store.analytics_rows("models_main", 0)
    assert len(main) == 1 and main[0]["input_tokens"] == 10 and main[0]["api_calls"] == 1
    assert store.analytics_rows("auxiliary", 0) == []
    assert InsightsEngine(store).generate(source="cli")["overview"]["total_sessions"] == 1
    assert store.analytics_rows("model_totals", 0)[0]["total_sessions"] == 1
    assert store.analytics_rows("models_fallback", 0)[0]["tool_calls"] == 1


def test_core_dashboard_consumer_queries_do_not_require_a_sqlite_connection(core_pair, monkeypatch):
    from hermes_cli.web_routers import analytics
    store = core_pair[0]
    _populate(store)
    monkeypatch.setattr(analytics, "_open_session_db_for_profile", lambda *args, **kwargs: store)
    monkeypatch.setattr(store, "close", lambda: None)
    report = analytics._get_usage_analytics()
    assert report["totals"]["total_sessions"] == 1 and report["by_model"][0]["input_tokens"] == 10
    report = analytics._get_models_analytics()
    assert report["totals"]["total_sessions"] == 1 and len(report["models"]) == 1
