import pytest
from pathlib import Path
from agentos_pilot.config import GotthardConfig, TierConfig
from agentos_pilot.bouncer import ArgosBouncer, BouncerIntervention


def test_gotthard_default_config():
    config = GotthardConfig.default()
    assert config.runtime.default_tier == "flash"
    assert config.runtime.per_run_budget_usd == 0.50
    assert "flash" in config.tiers
    assert "ifm" in config.tiers
    assert "frontier" in config.tiers
    assert config.tiers["ifm"].model == "IFM/K2-Horizon-375B-A23B"
    assert config.tiers["ifm"].api_base == "https://api.ifm.ai/v1"


def test_routing_rules_resolution():
    config = GotthardConfig.default()
    # Task matching 'test'
    tier_test = config.resolve_tier_for_task("Run unit tests and linting")
    assert tier_test.name == "flash"

    # Task matching 'architecture'
    tier_arch = config.resolve_tier_for_task("Draft architecture specification for payment service")
    assert tier_arch.name == "ifm"

    # Fallback to default
    tier_generic = config.resolve_tier_for_task("Do something completely random")
    assert tier_generic.name == "flash"


def test_toml_loader(tmp_path: Path):
    toml_content = """
    [runtime]
    default_tier = "ifm"
    per_run_budget_usd = 0.75

    [tiers.ifm]
    model = "custom-ifm"
    api_key_env = "MY_IFM_KEY"
    """
    toml_file = tmp_path / "custom.toml"
    toml_file.write_text(toml_content)

    config = GotthardConfig.from_toml_file(toml_file)
    assert config.runtime.default_tier == "ifm"
    assert config.runtime.per_run_budget_usd == 0.75
    assert config.tiers["ifm"].model == "custom-ifm"
    assert config.tiers["ifm"].api_key_env == "MY_IFM_KEY"


def test_argos_bouncer_cycle_detection():
    bouncer = ArgosBouncer(max_identical_tool_calls=3)

    # First two identical failures - should not trip
    bouncer.inspect_tool_dispatch("pytest", {"args": "-v"}, exit_code=1, output="AssertionError")
    bouncer.inspect_tool_dispatch("pytest", {"args": "-v"}, exit_code=1, output="AssertionError")

    # Third identical failure - trips Bouncer cycle-breaker
    with pytest.raises(BouncerIntervention, match="Cycle detected"):
        bouncer.inspect_tool_dispatch("pytest", {"args": "-v"}, exit_code=1, output="AssertionError")


def test_argos_dynamic_context_injection():
    bouncer = ArgosBouncer()
    bouncer.context.system_invariants.append("Never delete git root")
    bouncer.context.pinned_specs.append("GIVEN a user WHEN token expires THEN return 401")
    
    # Mid-flight injection by operator
    bouncer.context.inject_hint("Use Argon2id instead of bcrypt")

    payload = bouncer.context.compile_prompt_payload()
    assert "Never delete git root" in payload
    assert "GIVEN a user" in payload
    assert "Use Argon2id instead of bcrypt" in payload
