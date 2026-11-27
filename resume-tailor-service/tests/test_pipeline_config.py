import pytest
from pydantic import ValidationError

from app import doc_store
from app.pipeline import config
from app.pipeline.config import AdapterSpec, PipelineConfig


@pytest.fixture(params=["json", "sql"], autouse=True)
def backend(request, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "_JSON_BACKENDS", {})
    if request.param == "sql":
        monkeypatch.setattr(
            config, "_BACKEND_OVERRIDE", doc_store.SqlBackend(f"sqlite:///{tmp_path / 'c.db'}")
        )
    return request.param


def _cli(**extra) -> dict:
    return {"type": "cli", "command": ["tool", "{prompt}"], "capabilities": ["reason"], **extra}


def _config(adapters: dict, steps: dict | None = None) -> PipelineConfig:
    return PipelineConfig.model_validate({"adapters": adapters, "steps": steps or {}})


def test_cli_adapter_needs_prompt_placeholder():
    with pytest.raises(ValidationError, match="prompt"):
        AdapterSpec.model_validate({"type": "cli", "command": ["tool", "-p"], "capabilities": ["cheap"]})


def test_api_and_sdk_adapters_need_a_model():
    with pytest.raises(ValidationError, match="model"):
        AdapterSpec.model_validate({"type": "api", "provider": "gemini", "capabilities": ["cheap"]})
    with pytest.raises(ValidationError, match="model"):
        AdapterSpec.model_validate({"type": "sdk", "capabilities": ["cheap"]})
    with pytest.raises(ValidationError, match="key_env"):
        AdapterSpec.model_validate({"type": "api", "provider": "gemini", "model": "m", "capabilities": ["cheap"]})
    with pytest.raises(ValidationError, match="provider"):
        AdapterSpec.model_validate({"type": "api", "provider": "nope", "model": "m", "capabilities": ["cheap"]})


def test_unknown_capability_is_rejected():
    with pytest.raises(ValidationError):
        AdapterSpec.model_validate(_cli(capabilities=["telepathy"]))


def test_env_block_refuses_secret_looking_variables():
    with pytest.raises(ValidationError, match="key_env"):
        AdapterSpec.model_validate(_cli(env={"OPENAI_API_KEY": "sk-123"}))
    for value in ("sk-or-v1-abcdef0123456789", "AIzaSyA1234567890abcdefghij", "ghp_abcdefghijklmnop1234"):
        with pytest.raises(ValidationError, match="key_env"):
            AdapterSpec.model_validate(_cli(env={"AUTH": value}))
    AdapterSpec.model_validate(_cli(env={"GEMINI_CLI_HOME": "~/.gem"}))


def test_adapter_names_come_from_the_dict_keys():
    cfg = _config({"one": _cli()})
    assert cfg.adapters["one"].name == "one"


def test_step_preference_naming_an_unknown_adapter_is_rejected():
    with pytest.raises(ValidationError, match="ghost"):
        _config({"one": _cli()}, {"fit_score": {"prefer": ["ghost"]}})
    with pytest.raises(ValidationError, match="ghost"):
        _config({"one": _cli()}, {"fit_score": {"canary": {"adapter": "ghost", "share": 0.2}}})
    with pytest.raises(ValidationError):
        _config({"one": _cli()}, {"fit_score": {"canary": {"adapter": "one", "share": 1.5}}})


def test_check_step_prefs_flags_adapters_lacking_the_step_capability():
    cfg = _config(
        {"cheap": _cli(capabilities=["cheap"]), "smart": _cli()},
        {"fit_score": {"prefer": ["cheap", "smart"], "canary": {"adapter": "cheap", "share": 0.1}},
         "mystery": {"prefer": ["smart"]}},
    )

    errors = config.check_step_prefs(cfg, {"fit_score": "reason"})

    assert any("cheap" in e and "fit_score" in e for e in errors)
    assert any("canary" in e for e in errors)
    assert any("mystery" in e for e in errors)
    assert not any("smart" in e and "fit_score" in e for e in errors)


def test_key_set_reads_the_environment_never_the_value(monkeypatch):
    spec = AdapterSpec.model_validate(
        {"type": "api", "provider": "gemini", "model": "m", "key_env": "TEST_PIPE_KEY", "capabilities": ["cheap"]}
    )
    monkeypatch.delenv("TEST_PIPE_KEY", raising=False)
    assert config.key_set(spec) is False
    monkeypatch.setenv("TEST_PIPE_KEY", "secret-value")
    assert config.key_set(spec) is True
    assert "secret-value" not in spec.model_dump_json()
    # A cli adapter with no key env has nothing to set.
    assert config.key_set(AdapterSpec.model_validate(_cli())) is True


def test_committed_defaults_parse_and_hold_no_secrets():
    cfg = config.load_defaults()

    assert {"gemini_lite", "claude_haiku", "codex", "cursor", "opencode_free", "antigravity", "openrouter_haiku",
            "gemini_flash"} <= set(cfg.adapters)
    assert cfg.adapters["claude_haiku"].isolation == "claude_hermetic"
    assert cfg.adapters["openrouter_haiku"].type == "sdk"
    assert cfg.adapters["openrouter_haiku"].key_env == "OPENROUTER_API_KEY"
    assert cfg.adapters["openrouter_haiku"].tools == ["web_fetch", "dossier_read"]
    assert cfg.adapters["gemini_flash"].enabled is False
    assert cfg.capability_caps["browser_read"] == 2
    text = config.DEFAULTS_PATH.read_text()
    assert "AIza" not in text and "sk-" not in text


def test_first_load_seeds_version_one_from_defaults():
    cfg = config.load_config()

    assert cfg.version == 1
    assert cfg.updated_at
    assert set(cfg.adapters) == set(config.load_defaults().adapters)
    assert [v["version"] for v in config.list_versions()] == [1]


def test_save_keeps_history_and_rollback_copies_forward():
    first = config.load_config()
    changed = first.model_copy(deep=True)
    changed.workers = 9

    saved = config.save_config(changed)
    assert saved.version == 2
    assert config.load_config().workers == 9

    rolled = config.rollback(1)
    assert rolled.version == 3
    assert rolled.workers == first.workers
    assert config.load_config().version == 3
    assert [v["version"] for v in config.list_versions()] == [3, 2, 1]
    with pytest.raises(config.VersionNotFound):
        config.rollback(42)


def test_reset_to_defaults_is_a_new_version():
    cfg = config.load_config()
    cfg.workers = 1
    config.save_config(cfg)

    reset = config.reset_to_defaults()

    assert reset.version == 3
    assert reset.workers == config.load_defaults().workers
