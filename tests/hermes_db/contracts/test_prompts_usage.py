"""Exact prompt/tool pins and model/task attribution survive storage boundaries."""

import json


def test_prompt_and_tool_pin_are_exact_and_independent_of_route_updates(store):
    prompt = "spaces  \n中文\x00original"
    pin = [{"name": "tool", "parameters": {"enum": ["a", "b"]}}]
    store.create_session("s", source="cli", model="first", system_prompt=prompt)
    store.update_session_tool_names("s", pin)
    store.update_session_billing_route("s", provider="other", base_url="https://other.invalid")
    assert store.get_session("s")["system_prompt"] == prompt
    assert store.get_session("s")["tool_names"] == json.dumps(pin)
    store.update_system_prompt("s", "new exact")
    assert store.get_session("s")["system_prompt"] == "new exact"
    assert store.get_session("s")["tool_names"] == json.dumps(pin)


def test_usage_delta_absolute_and_first_accounted_route(store):
    store.create_session("s", source="cli", model="requested")
    store.update_token_counts("s", input_tokens=4, output_tokens=2, api_call_count=1,
                              model="fallback", billing_provider="provider", estimated_cost_usd=.2)
    row = store.get_session("s")
    assert row["model"] == "fallback"
    assert row["input_tokens"] == 4
    store.update_token_counts("s", input_tokens=3, api_call_count=1, model="second", billing_provider="other")
    assert store.get_session("s")["input_tokens"] == 7
    store.update_token_counts("s", input_tokens=10, output_tokens=9, api_call_count=8, absolute=True)
    row = store.get_session("s")
    assert (row["input_tokens"], row["output_tokens"], row["api_call_count"]) == (10, 9, 8)
    assert store.get_recent_session_model_route("s")["model"] == "second"


def test_auxiliary_usage_does_not_inherit_main_route_or_overwrite_summary(store):
    store.create_session("s", source="cli", model="main")
    store.update_token_counts("s", input_tokens=5, api_call_count=1, model="main", billing_provider="main-provider")
    store.record_auxiliary_usage("s", "vision", input_tokens=7, api_call_count=2)
    assert store.get_session("s")["input_tokens"] == 5
    assert store.auxiliary_usage_by_task("s")["vision"]["input_tokens"] == 7
    store.record_auxiliary_usage("missing", "title", input_tokens=1)
    store.create_session("missing", source="cli")
    assert store.get_session("missing")["source"] == "cli"


def test_queued_usage_is_flushed_before_authoritative_reads(store):
    store.create_session("s", source="cli", model="m")
    for count in (1, 2, 3):
        store.queue_token_counts("s", input_tokens=count, api_call_count=1, model="m", billing_provider="p")
    assert store.flush_token_counts()
    row = store.get_session("s")
    assert row["input_tokens"] == 6
    assert row["api_call_count"] == 3


def test_unknown_nullable_totals_are_not_replaced_with_invented_zeroes(store):
    store.create_session("s", source="cli")
    store.update_token_counts("s", input_tokens=None, absolute=True)
    assert store.get_session("s")["input_tokens"] is None
    store.update_token_counts("s", input_tokens=2)
    assert store.get_session("s")["input_tokens"] is None
