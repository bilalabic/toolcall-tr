"""Sağlayıcı-bağımsız LLM adapter'ı.

LLM bu projede **yalnızca doğal Türkçe ifadeyi** yazar; ground-truth tool
çağrısı koddan derlenir. Kullanılan model kimliği ve prompt sürümü her örneğin
provenance'ına yazılır.

Tüm boru hattı API anahtarı olmadan çalışır: `generation.TemplateQueryGenerator`
elle yazılmış ifadelere dayanır ve deterministiktir.
"""

from toolcall_tr.llm.base import LLMClient, LLMMessage, LLMResponse
from toolcall_tr.llm.budget import (
    BudgetedLLMClient,
    LLMBudgetExceededError,
    LLMBudgetLimits,
    LLMBudgetTracker,
)
from toolcall_tr.llm.cache import LLMCache

__all__ = [
    "BudgetedLLMClient",
    "LLMBudgetExceededError",
    "LLMBudgetLimits",
    "LLMBudgetTracker",
    "LLMCache",
    "LLMClient",
    "LLMMessage",
    "LLMResponse",
    "build_client",
]

#: Sağlayıcı adı -> yükleyici. İstemciler **tembel** import edilir: opsiyonel
#: bağımlılıklardır ve kurulu olmadan da boru hattı çalışmalıdır.
_PROVIDERS = ("anthropic", "openai", "stub")


def build_client(provider: str, model: str | None = None) -> LLMClient:
    """Adına göre LLM istemcisi kurar.

    Üretici ve judge'ın **farklı ailelerden** seçilmesi önerilir: aynı model
    hem üretip hem değerlendirirse self-preference bias'a girilir.
    """
    if provider == "anthropic":
        from toolcall_tr.llm.anthropic_client import DEFAULT_MODEL, AnthropicClient

        return AnthropicClient(model or DEFAULT_MODEL)

    if provider == "openai":
        from toolcall_tr.llm.openai_client import DEFAULT_MODEL, OpenAIClient

        return OpenAIClient(model or DEFAULT_MODEL)

    raise ValueError(f"bilinmeyen LLM sağlayıcı: {provider!r}. Geçerli: {', '.join(_PROVIDERS)}")
