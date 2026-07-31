from __future__ import annotations

from typing import Any

import pytest

from toolcall_tr.generation import LLMQueryGenerator, TemplateQueryGenerator
from toolcall_tr.generation.config import load_generation_config
from toolcall_tr.generation.runtime import PaidAPINotAllowedError, build_generation_runtime


def test_varsayilan_runtime_tamamen_cevrimdisidir() -> None:
    config = load_generation_config()

    runtime = build_generation_runtime(config)

    assert isinstance(runtime.generator, TemplateQueryGenerator)
    assert runtime.judge is None
    assert runtime.budget is None
    assert runtime.provider == "template"
    assert runtime.fallback == config.llm.fallback


@pytest.mark.parametrize(
    ("provider", "judge_enabled"),
    [("openai", False), ("template", True)],
)
def test_ucretli_api_acik_izin_olmadan_kurulmaz(
    provider: str,
    judge_enabled: bool,
) -> None:
    config = load_generation_config()

    with pytest.raises(PaidAPINotAllowedError, match="allow-paid-api"):
        build_generation_runtime(
            config,
            provider=provider,  # type: ignore[arg-type]
            judge_enabled=judge_enabled,
        )


def test_openai_runtime_model_rollerini_ayri_kurar(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[dict[str, Any]] = []

    class _FakeOpenAIClient:
        provider = "openai"

        def __init__(self, model: str, **kwargs: Any) -> None:
            self.model = model
            created.append({"model": model, **kwargs})

    monkeypatch.setattr(
        "toolcall_tr.generation.runtime.OpenAIClient",
        _FakeOpenAIClient,
    )
    config = load_generation_config()

    runtime = build_generation_runtime(
        config,
        provider="openai",
        judge_enabled=True,
        allow_paid_api=True,
    )

    assert isinstance(runtime.generator, LLMQueryGenerator)
    assert runtime.judge is not None
    assert runtime.budget is not None
    assert runtime.fallback == config.llm.fallback
    assert [item["model"] for item in created] == ["gpt-4.1-mini", "gpt-5-mini"]
    assert created[0]["reasoning_effort"] is None
    assert created[0]["verbosity"] is None
    assert created[1]["reasoning_effort"] == "medium"
    assert created[1]["verbosity"] == "low"
