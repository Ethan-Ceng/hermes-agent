"""Checkout cache maintenance preserves PM-managed test/runtime generations."""


def test_checkout_sweep_removes_source_bytecode_and_preserves_build_runtime(tmp_path):
    from hermes_cli.main import _clear_bytecode_cache
    source = tmp_path / "agent" / "__pycache__" / "source.pyc"
    runtime = tmp_path / ".build" / "pm-generation" / "__pycache__" / "sdk.pyc"
    for path in (source, runtime):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"cached bytecode")
    _clear_bytecode_cache(tmp_path)
    assert not source.exists()
    assert runtime.read_bytes() == b"cached bytecode"
