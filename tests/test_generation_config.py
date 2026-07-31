from pathlib import Path

import pytest
import yaml

from toolcall_tr.generation.config import (
    DEFAULT_GENERATOR_MODEL,
    DEFAULT_JUDGE_MODEL,
    GenerationConfig,
    GenerationConfigError,
    LLMConfig,
    ModelRoleConfig,
    RetryConfig,
    load_generation_config,
)


def _minimal_config(**llm_overrides: object) -> dict[str, object]:
    llm: dict[str, object] = {"provider": "template", **llm_overrides}
    return {
        "llm": llm,
        "prompts": {"user_query": "test-v1", "path": "prompts"},
        "styles": ["resmi"],
        "constraints": {},
        "normalization": {},
    }


def test_checked_in_generation_config_is_valid_and_offline_by_default() -> None:
    config = load_generation_config(Path("configs/generation.yaml"))

    assert config.llm.provider == "template"
    assert config.llm.api == "responses"
    assert config.llm.models.generator.model == DEFAULT_GENERATOR_MODEL
    assert config.llm.models.judge.model == DEFAULT_JUDGE_MODEL
    assert config.llm.models.generator.model == "gpt-4.1-mini"
    assert config.llm.models.judge.model == "gpt-5-mini"
    assert config.llm.models.generator.max_output_tokens == 512
    assert config.llm.models.judge.max_output_tokens == 2048
    assert config.llm.cache.enabled is True
    assert config.llm.concurrency.max_in_flight == 8
    assert config.llm.retry.max_attempts == 4
    assert config.llm.budget.max_requests == 1_200
    assert config.llm.fallback.on_generation_error == "fail"
    assert config.llm.fallback.on_judge_error == "fail"
    assert config.prompts.user_query == "toolcall-tr-user-v6"
    assert config.prompts.file == Path("user_query_v6.md")
    assert config.prompts.mode == "synthesize"


def test_pilot_200_config_has_narrow_paid_run_budget() -> None:
    config = load_generation_config(Path("configs/generation-pilot-200.yaml"))

    assert config.llm.models.generator.model == "gpt-4.1-mini"
    assert config.llm.models.judge.model == "gpt-5-mini"
    assert config.llm.budget.max_requests == 450
    assert config.llm.budget.max_input_tokens == 400_000
    assert config.llm.budget.max_output_tokens == 120_000
    assert config.llm.models.judge.reasoning_effort == "low"
    assert config.llm.models.judge.max_output_tokens == 4096
    assert config.llm.fallback.on_judge_error == "reject"
    assert config.llm.fallback.on_budget_exceeded == "stop"
    assert config.prompts.mode == "synthesize"


def test_openai_provider_uses_responses_api_and_configurable_roles() -> None:
    config = GenerationConfig.model_validate(
        _minimal_config(
            provider="openai",
            api="responses",
            models={
                "generator": {
                    "model": "custom-generator",
                    "reasoning_effort": "low",
                    "temperature": 0.7,
                    "max_output_tokens": 700,
                    "verbosity": "medium",
                },
                "judge": {
                    "model": "custom-judge",
                    "reasoning_effort": "high",
                    "temperature": None,
                    "max_output_tokens": 2500,
                    "verbosity": "high",
                },
            },
        )
    )

    assert config.llm.provider == "openai"
    assert config.llm.models.generator.reasoning_effort == "low"
    assert config.llm.models.generator.verbosity == "medium"
    assert config.llm.models.judge.reasoning_effort == "high"


def test_legacy_model_keys_are_accepted() -> None:
    role = ModelRoleConfig.model_validate(
        {
            "provider": "openai",
            "model": "legacy-model",
            "reasoning": "low",
            "max_tokens": 321,
        }
    )

    assert role.reasoning_effort == "low"
    assert role.max_output_tokens == 321


@pytest.mark.parametrize("legacy_name", ["max_tokens", "max_completion_tokens"])
def test_legacy_and_responses_token_keys_cannot_be_mixed(legacy_name: str) -> None:
    with pytest.raises(ValueError, match="birlikte kullanılamaz"):
        ModelRoleConfig.model_validate(
            {
                "model": "test-model",
                legacy_name: 100,
                "max_output_tokens": 200,
            }
        )


def test_chat_completions_api_is_rejected_with_clear_path() -> None:
    with pytest.raises(ValueError, match="responses"):
        LLMConfig.model_validate({"api": "chat_completions"})


def test_generator_and_judge_must_be_different_models() -> None:
    with pytest.raises(ValueError, match="farklı modeller"):
        LLMConfig.model_validate(
            {
                "models": {
                    "generator": {"model": "same-model"},
                    "judge": {"model": "same-model"},
                }
            }
        )


def test_secret_fields_are_rejected_and_environment_variable_is_named() -> None:
    raw = _minimal_config()
    assert isinstance(raw["llm"], dict)
    raw["llm"]["api_key"] = "must-not-be-here"

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        GenerationConfig.model_validate(raw)


def test_run_budget_and_concurrency_are_strictly_positive() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        LLMConfig.model_validate({"budget": {"max_requests": 0}})
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        LLMConfig.model_validate({"concurrency": {"max_in_flight": 0}})


def test_retry_max_delay_cannot_precede_initial_delay() -> None:
    with pytest.raises(ValueError, match="küçük olamaz"):
        RetryConfig(initial_delay_seconds=10.0, max_delay_seconds=2.0)


def test_retired_candidates_key_has_actionable_error() -> None:
    with pytest.raises(ValueError, match="ayrı benchmark"):
        LLMConfig.model_validate({"candidates": []})


def test_loader_wraps_validation_error_with_file_name(tmp_path: Path) -> None:
    path = tmp_path / "generation.yaml"
    path.write_text(
        yaml.safe_dump(_minimal_config(api="chat_completions")),
        encoding="utf-8",
    )

    with pytest.raises(GenerationConfigError, match=r"generation\.yaml"):
        load_generation_config(path)
