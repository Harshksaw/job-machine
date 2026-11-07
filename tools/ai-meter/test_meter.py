import meter

POLICY = {
    "currency": "CAD",
    "budgets": {"claude": {"day": 20, "week": 100}, "codex": {"day": 10, "week": 50}},
    "throttle_at": 0.8,
    "routes": {
        "direction": ["claude", "codex"],
        "heavy": ["cursor", "opencode", "codex"],
        "bulk": ["opencode", "cursor"],
    },
}


def _state(**spend):
    return {
        "providers": {
            name: {"day": day, "week": week} for name, (day, week) in spend.items()
        }
    }


def test_direction_stays_on_claude_under_budget():
    assert meter.pick("direction", _state(claude=(5, 30)), POLICY)["tool"] == "claude"


def test_direction_moves_to_codex_when_claude_day_budget_is_nearly_spent():
    choice = meter.pick("direction", _state(claude=(17, 30)), POLICY)
    assert choice["tool"] == "codex"
    assert "claude" in choice["reason"]


def test_week_budget_also_throttles():
    assert meter.pick("direction", _state(claude=(1, 95)), POLICY)["tool"] == "codex"


def test_heavy_work_goes_to_cursor_first():
    assert meter.pick("heavy", _state(claude=(1, 1)), POLICY)["tool"] == "cursor"


def test_bulk_work_goes_to_free_opencode():
    assert meter.pick("bulk", _state(), POLICY)["tool"] == "opencode"


def test_last_choice_is_used_when_every_budgeted_tool_is_spent():
    choice = meter.pick("direction", _state(claude=(30, 30), codex=(30, 30)), POLICY)
    assert choice["tool"] == "codex"
    assert "over budget" in choice["reason"]


def test_unknown_kind_is_rejected():
    try:
        meter.pick("poetry", _state(), POLICY)
    except ValueError as error:
        assert "direction" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_summarize_reads_codeburn_provider_details():
    today = {"current": {"providerDetails": [
        {"id": "claude", "cost": 12.5, "calls": 175},
        {"id": "cursor-agent", "cost": 0.02, "calls": 3},
        {"id": "cursor", "cost": 0.5, "calls": 9},
    ]}}
    week = {"current": {"providerDetails": [{"id": "claude", "cost": 40.0, "calls": 900}]}}
    providers = meter.summarize(today, week)
    assert providers["claude"] == {"day": 12.5, "week": 40.0, "calls_day": 175}
    # CodeBurn calls the CLI "cursor-agent"; the router calls it "cursor".
    assert providers["cursor"]["day"] == 0.02
    assert providers["cursor-ide"]["day"] == 0.5
