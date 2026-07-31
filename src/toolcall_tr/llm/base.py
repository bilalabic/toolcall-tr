"""Sağlayıcı-bağımsız LLM arayüzü.

LLM bu projede **yalnızca doğal Türkçe ifadeyi** yazar. Ground-truth tool
çağrısı asla LLM'e sorulmaz; `groundtruth.planner` tarafından koddan derlenir.
Bu ayrım korunmazsa "aynı LLM hem soruyu hem cevabı hem değerlendirmeyi
üretiyor" tuzağına düşülür.

Kullanılan model kimliği ve prompt sürümü her örneğin provenance'ına yazılır.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

__all__ = ["LLMClient", "LLMMessage", "LLMResponse"]

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Model yanıtı ve maliyet/kimlik kaydı."""

    text: str
    model: str
    provider: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    #: Sağlayıcının prompt önbelleğinden karşıladığı girdi token'ları.
    #:
    #: Bu alan ``cached`` ile aynı şey değildir: ``cached`` tüm yanıtın yerel
    #: LLMCache'ten geldiğini, bu sayaç ise canlı istekte yalnızca girdi
    #: önekinin sağlayıcı tarafından önbellekten karşılandığını gösterir.
    cached_input_tokens: int | None = None
    #: Önbellekten geldiyse ``True`` -- yeniden üretim maliyetini raporlamak için.
    cached: bool = False
    metadata: dict[str, str] = field(default_factory=dict)


class LLMClient(Protocol):
    """Metin üreten en küçük arayüz."""

    provider: str
    model: str

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 1.0,
        max_tokens: int = 1024,
    ) -> LLMResponse: ...
