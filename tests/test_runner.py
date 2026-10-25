import pytest

from agentos_pilot.config import TierConfig
from agentos_pilot.runner import (
    AgyCliRunner,
    OpenAiCompatibleRunner,
    RunnerError,
    build_runner_for_tier,
    runner_requirements_met,
)


def _agy_tier(**overrides):
    base = dict(
        name="flash",
        type="cli_or_api",
        engine="agy",
        model="gemini-3.8-flash",
        api_key_env="GEMINI_API_KEY",
    )
    base.update(overrides)
    return TierConfig(**base)


def _ifm_tier(**overrides):
    base = dict(
        name="ifm",
        type="openai_compatible",
        model="IFM/K2-Horizon-375B-A23B",
        api_base="https://api.ifm.ai/v1",
        api_key_env="IFM_API_KEY",
    )
    base.update(overrides)
    return TierConfig(**base)


def _frontier_tier(**overrides):
    base = dict(
        name="frontier",
        type="anthropic_or_tensorx",
        model="claude-3-7-sonnet",
        api_base="https://api.tensorx.ai/v1",
        api_key_env="TENSORX_API_KEY",
    )
    base.update(overrides)
    return TierConfig(**base)


# --- runner selection -------------------------------------------------


def test_build_runner_for_tier_agy_selects_agy_cli_runner():
    runner, runner_type = build_runner_for_tier(_agy_tier())
    assert isinstance(runner, AgyCliRunner)
    assert runner_type == "agy_cli"


def test_build_runner_for_tier_openai_compatible_selects_openai_runner():
    runner, runner_type = build_runner_for_tier(_ifm_tier())
    assert isinstance(runner, OpenAiCompatibleRunner)
    assert runner_type == "openai_compatible"
    assert runner.api_base == "https://api.ifm.ai/v1"
    assert runner.api_key_env == "IFM_API_KEY"


def test_build_runner_for_tier_unknown_type_has_no_runner():
    runner, runner_type = build_runner_for_tier(_frontier_tier())
    assert runner is None
    assert runner_type == "anthropic_or_tensorx"


def test_build_runner_for_tier_openai_compatible_without_api_key_env_has_no_runner():
    runner, runner_type = build_runner_for_tier(_ifm_tier(api_key_env=None))
    assert runner is None
    assert runner_type == "openai_compatible"


# --- agy runner: missing-binary fallback -------------------------------


def test_agy_runner_not_available_when_binary_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("pathlib.Path.exists", lambda self: False)
    runner = AgyCliRunner()
    assert runner.is_available() is False


def test_agy_runner_available_when_binary_on_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/agy")
    runner = AgyCliRunner()
    assert runner.is_available() is True


def test_agy_runner_run_raises_runner_error_when_binary_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("pathlib.Path.exists", lambda self: False)
    runner = AgyCliRunner()
    with pytest.raises(RunnerError, match="agy binary not found"):
        runner.run("gemini-3.8-flash", "do the thing")


def test_runner_requirements_met_false_for_missing_agy_binary(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("pathlib.Path.exists", lambda self: False)
    runner = AgyCliRunner()
    tier = _agy_tier()
    ok, reason = runner_requirements_met(tier, runner)
    assert ok is False
    assert "agy" in reason
    assert "flash" in reason


def test_runner_requirements_met_true_for_present_agy_binary():
    runner = AgyCliRunner(binary="/usr/bin/agy")
    tier = _agy_tier()
    ok, reason = runner_requirements_met(tier, runner)
    assert ok is True


def test_runner_requirements_met_false_when_no_runner_dispatchable():
    tier = _frontier_tier()
    runner, _ = build_runner_for_tier(tier)
    ok, reason = runner_requirements_met(tier, runner)
    assert ok is False
    assert "no dispatchable runner" in reason


# --- openai-compatible runner: auth-error path with IFM_API_KEY unset --


def test_openai_runner_not_available_when_api_key_env_unset(monkeypatch):
    monkeypatch.delenv("IFM_API_KEY", raising=False)
    runner = OpenAiCompatibleRunner(api_base="https://api.ifm.ai/v1", api_key_env="IFM_API_KEY")
    assert runner.is_available() is False


def test_openai_runner_run_raises_runner_error_when_api_key_env_unset(monkeypatch):
    monkeypatch.delenv("IFM_API_KEY", raising=False)
    runner = OpenAiCompatibleRunner(api_base="https://api.ifm.ai/v1", api_key_env="IFM_API_KEY")
    with pytest.raises(RunnerError, match="IFM_API_KEY is not set"):
        runner.run("IFM/K2-Horizon-375B-A23B", "do the thing")


def test_runner_requirements_met_false_for_ifm_tier_without_api_key(monkeypatch):
    monkeypatch.delenv("IFM_API_KEY", raising=False)
    tier = _ifm_tier()
    runner, _ = build_runner_for_tier(tier)
    ok, reason = runner_requirements_met(tier, runner)
    assert ok is False
    assert "IFM_API_KEY" in reason


def test_runner_requirements_met_true_for_ifm_tier_with_api_key(monkeypatch):
    monkeypatch.setenv("IFM_API_KEY", "secret")
    tier = _ifm_tier()
    runner, _ = build_runner_for_tier(tier)
    ok, reason = runner_requirements_met(tier, runner)
    assert ok is True


def test_openai_runner_raises_on_non_2xx_response(monkeypatch):
    import io
    import urllib.error

    monkeypatch.setenv("IFM_API_KEY", "secret")
    runner = OpenAiCompatibleRunner(api_base="https://api.ifm.ai/v1", api_key_env="IFM_API_KEY")

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"error":"unauthorized"}')
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(RunnerError, match="HTTP 401"):
        runner.run("IFM/K2-Horizon-375B-A23B", "do the thing")
