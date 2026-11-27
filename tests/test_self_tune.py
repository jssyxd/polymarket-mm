

def test_disable_quoting_writes_false_and_keeps_other_params(tmp_path):
    from pmm.engine.self_tune import disable_quoting, load_params

    path = tmp_path / "params.json"
    path.write_text('{"quoting_enabled": true, "half_spread_cents": 3.0}', encoding="utf-8")

    disabled = disable_quoting(path, reason="single_leg_flow")

    assert disabled["quoting_enabled"] is False
    assert disabled["quoting_disabled_reason"] == "single_leg_flow"
    assert load_params(path)["quoting_enabled"] is False
    assert load_params(path)["half_spread_cents"] == 3.0
