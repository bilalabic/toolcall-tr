"""Üretim sağlayıcısı, model rolleri ve harcama sınırları için tipli yapılandırma.

Varsayılan sağlayıcı ``template`` olduğundan bu modülü kullanmak ağ erişimi veya
bir API anahtarı gerektirmez. ``openai`` seçildiğinde anahtar yalnızca
``OPENAI_API_KEY`` ortam değişkeninden okunmalıdır; bu şema bilerek herhangi bir
secret alanı sunmaz.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

__all__ = [
    "CacheConfig",
    "ConcurrencyConfig",
    "FallbackConfig",
    "GenerationConfig",
    "GenerationConfigError",
    "LLMConfig",
    "ModelRoleConfig",
    "ModelRolesConfig",
    "RetryConfig",
    "RunBudgetConfig",
    "load_generation_config",
]

GenerationProvider = Literal["template", "openai"]
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]
Verbosity = Literal["low", "medium", "high"]

DEFAULT_GENERATOR_MODEL = "gpt-4.1-mini"
DEFAULT_JUDGE_MODEL = "gpt-5-mini"

_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "openai_api_key",
        "secret",
        "token",
        "access_token",
    }
)


class GenerationConfigError(ValueError):
    """Yapılandırma dosyası okunamadığında veya doğrulanamadığında oluşur."""


class ModelRoleConfig(BaseModel):
    """Bir OpenAI model rolünün Responses API çalışma ayarları."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    reasoning_effort: ReasoningEffort = "none"
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=512, ge=1, le=128_000)
    verbosity: Verbosity = "low"

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_names(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        legacy_provider = data.pop("provider", None)
        if legacy_provider not in (None, "openai"):
            raise ValueError(
                "model rolündeki eski 'provider' yalnızca 'openai' olabilir; "
                "sağlayıcıyı llm.provider alanından seçin"
            )
        for old_name in ("max_tokens", "max_completion_tokens"):
            if old_name in data:
                if "max_output_tokens" in data:
                    raise ValueError(
                        f"'{old_name}' ile 'max_output_tokens' birlikte kullanılamaz; "
                        "Responses API için yalnızca 'max_output_tokens' kullanın"
                    )
                data["max_output_tokens"] = data.pop(old_name)
        if "reasoning" in data:
            if "reasoning_effort" in data:
                raise ValueError(
                    "'reasoning' ile 'reasoning_effort' birlikte kullanılamaz"
                )
            data["reasoning_effort"] = data.pop("reasoning")
        return data

    @model_validator(mode="after")
    def _non_empty_model(self) -> Self:
        if not self.model.strip():
            raise ValueError("model adı boş olamaz")
        return self


class ModelRolesConfig(BaseModel):
    """Doğal dil üretimi ve bağımsız kalite değerlendirmesi rolleri."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    generator: ModelRoleConfig = Field(
        default_factory=lambda: ModelRoleConfig(
            model=DEFAULT_GENERATOR_MODEL,
            reasoning_effort="none",
            temperature=1.0,
            max_output_tokens=512,
            verbosity="low",
        )
    )
    judge: ModelRoleConfig = Field(
        default_factory=lambda: ModelRoleConfig(
            model=DEFAULT_JUDGE_MODEL,
            reasoning_effort="medium",
            temperature=None,
            max_output_tokens=2048,
            verbosity="low",
        )
    )

    @model_validator(mode="after")
    def _separate_roles(self) -> Self:
        if self.generator.model == self.judge.model:
            raise ValueError(
                "generator ve judge farklı modeller olmalı; aynı model "
                "self-preference yanlılığı oluşturur"
            )
        return self


class CacheConfig(BaseModel):
    """Aynı isteğin yeniden ücretlendirilmesini önleyen yerel önbellek."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    path: Path = Path("data/llm_cache")
    key_fields: tuple[str, ...] = (
        "prompt_version",
        "blueprint_id",
        "variant_index",
        "model",
    )

    @model_validator(mode="after")
    def _valid_keys(self) -> Self:
        if not self.key_fields:
            raise ValueError("cache.key_fields en az bir alan içermeli")
        if any(not field.strip() for field in self.key_fields):
            raise ValueError("cache.key_fields boş değer içeremez")
        if len(self.key_fields) != len(set(self.key_fields)):
            raise ValueError("cache.key_fields yinelenen değer içeremez")
        return self


class ConcurrencyConfig(BaseModel):
    """OpenAI isteklerinin yerel eşzamanlılık sınırı."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_in_flight: int = Field(default=8, ge=1, le=128)


class RetryConfig(BaseModel):
    """Geçici API hataları için sınırlı exponential-backoff politikası."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_attempts: int = Field(default=4, ge=1, le=10)
    initial_delay_seconds: float = Field(default=1.0, ge=0.0, le=60.0)
    max_delay_seconds: float = Field(default=30.0, ge=0.0, le=300.0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0, le=10.0)
    jitter: bool = True

    @model_validator(mode="after")
    def _ordered_delays(self) -> Self:
        if self.max_delay_seconds < self.initial_delay_seconds:
            raise ValueError(
                "retry.max_delay_seconds, initial_delay_seconds değerinden küçük olamaz"
            )
        return self


class RunBudgetConfig(BaseModel):
    """Tek bir çalıştırmanın aşamayacağı sert OpenAI kullanım sınırları."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_requests: int = Field(default=1_200, ge=1)
    max_input_tokens: int = Field(default=3_000_000, ge=1)
    max_output_tokens: int = Field(default=600_000, ge=1)


class FallbackConfig(BaseModel):
    """Ağ, bütçe ve judge hatalarında deterministik, fail-closed davranış."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    on_generation_error: Literal["template", "fail"] = "fail"
    on_budget_exceeded: Literal["template", "stop"] = "stop"
    on_judge_error: Literal["reject", "fail"] = "fail"


class LLMConfig(BaseModel):
    """Üretim motorunun ağ ve operasyon ayarları."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: GenerationProvider = "template"
    api: Literal["responses"] = "responses"
    models: ModelRolesConfig = Field(default_factory=ModelRolesConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    budget: RunBudgetConfig = Field(default_factory=RunBudgetConfig)
    fallback: FallbackConfig = Field(default_factory=FallbackConfig)

    @model_validator(mode="before")
    @classmethod
    def _reject_retired_keys(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "candidates" in data:
            raise ValueError(
                "'llm.candidates' üretim yapılandırmasından kaldırıldı; model "
                "karşılaştırmalarını ayrı benchmark yapılandırmasında tutun"
            )
        return data


class PromptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_query: str
    path: Path
    file: Path = Path("user_query_v6.md")
    mode: Literal["paraphrase", "synthesize"] = "synthesize"


class ConstraintConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    no_new_ground_truth: bool = True
    no_tool_names_in_message: bool = True
    no_leaking_missing_params: bool = True
    no_unsupported_tasks: bool = True
    no_real_personal_data: bool = True


class NormalizationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    money: bool = True
    dates: bool = True
    phone: bool = True


class GenerationConfig(BaseModel):
    """``configs/generation.yaml`` dosyasının tamamı."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    llm: LLMConfig = Field(default_factory=LLMConfig)
    prompts: PromptConfig = Field(
        default_factory=lambda: PromptConfig(
            user_query="toolcall-tr-user-v6",
            path=Path("prompts"),
            file=Path("user_query_v6.md"),
            mode="synthesize",
        )
    )
    styles: tuple[str, ...]
    constraints: ConstraintConfig = Field(default_factory=ConstraintConfig)
    normalization: NormalizationConfig = Field(default_factory=NormalizationConfig)

    @model_validator(mode="before")
    @classmethod
    def _reject_secrets(cls, value: Any) -> Any:
        def walk(node: Any, path: tuple[str, ...] = ()) -> None:
            if isinstance(node, dict):
                for key, child in node.items():
                    normalized = str(key).lower().replace("-", "_")
                    current = (*path, str(key))
                    if normalized in _SECRET_KEYS:
                        dotted = ".".join(current)
                        raise ValueError(
                            f"secret alanı yapılandırmaya yazılamaz: {dotted}; "
                            "OPENAI_API_KEY ortam değişkenini kullanın"
                        )
                    walk(child, current)
            elif isinstance(node, list):
                for index, child in enumerate(node):
                    walk(child, (*path, str(index)))

        walk(value)
        return value

    @model_validator(mode="after")
    def _valid_styles(self) -> Self:
        if not self.styles:
            raise ValueError("styles en az bir Türkçe ifade stili içermeli")
        if any(not style.strip() for style in self.styles):
            raise ValueError("styles boş değer içeremez")
        if len(self.styles) != len(set(self.styles)):
            raise ValueError("styles yinelenen değer içeremez")
        return self


def load_generation_config(path: str | Path = Path("configs/generation.yaml")) -> GenerationConfig:
    """UTF-8 YAML dosyasını okuyup tam ve tipli yapılandırma döndürür."""

    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GenerationConfigError(
            f"üretim yapılandırması okunamadı: {config_path}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise GenerationConfigError(
            f"üretim yapılandırması geçerli YAML değil: {config_path}: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise GenerationConfigError(
            f"üretim yapılandırmasının kökü mapping olmalı: {config_path}"
        )
    try:
        return GenerationConfig.model_validate(raw)
    except ValidationError as exc:
        raise GenerationConfigError(
            f"üretim yapılandırması geçersiz: {config_path}\n{exc}"
        ) from exc
