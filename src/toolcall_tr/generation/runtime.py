"""Üretim komutları için güvenli OpenAI çalışma zamanı kurulumu."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from toolcall_tr.generation.config import FallbackConfig, GenerationConfig
from toolcall_tr.generation.query import LLMQueryGenerator, QueryGenerator, TemplateQueryGenerator
from toolcall_tr.llm.budget import BudgetedLLMClient, LLMBudgetLimits, LLMBudgetTracker
from toolcall_tr.llm.cache import LLMCache
from toolcall_tr.llm.judge import SemanticPolicyJudge
from toolcall_tr.llm.openai_client import OpenAIClient

__all__ = [
    "GenerationRuntime",
    "PaidAPINotAllowedError",
    "build_generation_runtime",
]

GeneratorProvider = Literal["template", "openai"]


class PaidAPINotAllowedError(RuntimeError):
    """Ücretli API kullanımı açıkça onaylanmadığında oluşur."""


@dataclass(frozen=True, slots=True)
class GenerationRuntime:
    """Bir üretim koşusunun üretici, hakem ve ortak bütçe bileşenleri."""

    generator: QueryGenerator
    judge: SemanticPolicyJudge | None
    budget: LLMBudgetTracker | None
    provider: GeneratorProvider
    fallback: FallbackConfig
    max_in_flight: int


def build_generation_runtime(
    config: GenerationConfig,
    *,
    provider: GeneratorProvider | None = None,
    judge_enabled: bool = False,
    allow_paid_api: bool = False,
) -> GenerationRuntime:
    """Yapılandırmadan çevrimdışı veya OpenAI çalışma zamanı kur.

    OpenAI üreticisi veya hakemi seçildiyse ``allow_paid_api`` zorunludur. Bu
    kapı, yapılandırma dosyasındaki yanlış bir değişikliğin tek başına maliyet
    oluşturmasını engeller.
    """
    selected_provider = provider or config.llm.provider
    uses_openai = selected_provider == "openai" or judge_enabled
    if uses_openai and not allow_paid_api:
        raise PaidAPINotAllowedError(
            "OpenAI çağrıları ücretli olabilir. Bilerek çalıştırmak için "
            "--allow-paid-api seçeneğini ekleyin."
        )

    if not uses_openai:
        return GenerationRuntime(
            generator=TemplateQueryGenerator(cycle_utterances=True),
            judge=None,
            budget=None,
            provider="template",
            fallback=config.llm.fallback,
            max_in_flight=1,
        )

    budget_config = config.llm.budget
    tracker = LLMBudgetTracker(
        LLMBudgetLimits(
            max_requests=budget_config.max_requests,
            max_input_tokens=budget_config.max_input_tokens,
            max_output_tokens=budget_config.max_output_tokens,
        )
    )
    cache_config = config.llm.cache
    cache = LLMCache(cache_config.path, enabled=cache_config.enabled)

    if selected_provider == "openai":
        generator_config = config.llm.models.generator
        generator_client = OpenAIClient(
            generator_config.model,
            reasoning_effort=(
                None
                if generator_config.reasoning_effort == "none"
                else generator_config.reasoning_effort
            ),
            # GPT-4.1 mini için verbosity göndermiyoruz; bu Responses API
            # seçeneği GPT-5 ailesinde anlamlıdır.
            verbosity=(
                generator_config.verbosity
                if generator_config.model.startswith("gpt-5")
                else None
            ),
            max_retries=config.llm.retry.max_attempts - 1,
            send_temperature=generator_config.temperature is not None,
        )
        generator: QueryGenerator = LLMQueryGenerator(
            BudgetedLLMClient(generator_client, tracker),
            system_prompt=_load_prompt(config),
            cache=cache,
            temperature=generator_config.temperature or 1.0,
            max_tokens=generator_config.max_output_tokens,
            structured_output=True,
            cycle_utterances=False,
            question_mode=config.prompts.mode,
        )
    else:
        generator = TemplateQueryGenerator(cycle_utterances=True)

    judge: SemanticPolicyJudge | None = None
    if judge_enabled:
        judge_config = config.llm.models.judge
        judge_client = OpenAIClient(
            judge_config.model,
            reasoning_effort=(
                None if judge_config.reasoning_effort == "none" else judge_config.reasoning_effort
            ),
            verbosity=judge_config.verbosity,
            max_retries=config.llm.retry.max_attempts - 1,
            send_temperature=judge_config.temperature is not None,
        )
        judge = SemanticPolicyJudge(
            BudgetedLLMClient(judge_client, tracker),
            cache=cache,
            temperature=judge_config.temperature or 0.0,
            max_tokens=judge_config.max_output_tokens,
        )

    return GenerationRuntime(
        generator=generator,
        judge=judge,
        budget=tracker,
        provider=selected_provider,
        fallback=config.llm.fallback,
        max_in_flight=config.llm.concurrency.max_in_flight,
    )


def _load_prompt(config: GenerationConfig) -> str:
    prompt_path = config.prompts.path / config.prompts.file
    payload = prompt_path.read_text(encoding="utf-8")
    parts = payload.split("---", 2)
    if len(parts) != 3:
        raise ValueError(f"prompt frontmatter bulunamadı: {prompt_path}")
    frontmatter, body = parts[1], parts[2].strip()
    expected = f"version: {config.prompts.user_query}"
    if expected not in frontmatter:
        raise ValueError(
            f"prompt sürümü uyuşmuyor: yapılandırma={config.prompts.user_query}, "
            f"dosya={prompt_path}"
        )
    if not body:
        raise ValueError(f"prompt gövdesi boş: {prompt_path}")
    return body
