"""Sağlayıcı adaptör arayüzü.

Bir sağlayıcı üç şey sunar: tool tanımları, argümanları HTTP isteğine çeviren
kurucular ve ham yanıtı normalize eden fonksiyonlar.

Normalizasyon **tek noktada** yapılır. Ham gövde cassette'e, normalize gövde
tool sonucuna yazılır; ikisi kasıtlı olarak farklıdır. Böylece ESHOT'un
``KoorX``/``KoorY`` takası gibi kaynak tuzakları veri setine sızmaz ama ham
kayıt da bozulmadan saklanır.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from toolcall_tr.models import ToolSpec

__all__ = [
    "LocalProviderAdapter",
    "LocalToolBinding",
    "ProviderAdapter",
    "ToolBinding",
    "ToolExecutionError",
    "identity_normalizer",
]

#: Argümanları HTTP isteğine çevirir. İkinci parametre sağlayıcının taban URL'i.
RequestBuilder = Callable[[Mapping[str, Any], str], httpx.Request]

#: Ham (ayrıştırılmış JSON) yanıtı tool sonucuna çevirir.
Normalizer = Callable[[Any], Any]
CassetteSanitizer = Callable[[Any], Any]


class ToolExecutionError(RuntimeError):
    """Tool çağrısı sağlayıcı tarafından reddedildi veya yanıt yorumlanamadı."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def identity_normalizer(payload: Any) -> Any:
    return payload


@dataclass(frozen=True, slots=True)
class ToolBinding:
    """Bir tool tanımını çalıştırılabilir hâle bağlar."""

    spec: ToolSpec
    build_request: RequestBuilder
    normalize: Normalizer = identity_normalizer
    #: Ham API gövdesi yeniden dağıtıma uygun değilse, diske yazılmadan önce
    #: izinli bir alt kümeye indirger. Replay ve canlı sonuç aynı güvenli gövdeyi görür.
    cassette_sanitizer: CassetteSanitizer | None = None

    @property
    def tool_id(self) -> str:
        return self.spec.tool_id


@dataclass(frozen=True, slots=True)
class ProviderAdapter:
    """Tek bir sağlayıcının çalıştırılabilir tool kümesi."""

    name: str
    base_url: str | None
    bindings: tuple[ToolBinding, ...]
    license: str = "UNDETERMINED"
    attribution: str | None = None
    cassette_namespace: str | None = None
    #: Aynı episode içinde yanıtı meşru olarak değişen tool'lar.
    sequenced_tools: frozenset[str] = field(default_factory=frozenset)

    @property
    def tools(self) -> tuple[ToolSpec, ...]:
        return tuple(binding.spec for binding in self.bindings)

    def binding(self, tool_id: str) -> ToolBinding | None:
        return next((b for b in self.bindings if b.tool_id == tool_id), None)


@dataclass(frozen=True, slots=True)
class LocalToolBinding:
    """Ağ çağrısı yapmayan, dondurulmuş veri üzerinde hesaplayan tool.

    Bu bir "sahte çalıştırma" değildir: gerçek bir implementasyon gerçekten
    çalışır ve çıktısı doğrulanır. Fark, verinin canlı API yerine lisanslı ve
    dondurulmuş bir snapshot'tan gelmesidir -- `execution_class` bunu her tool
    ve her örnekte açıkça taşır.
    """

    spec: ToolSpec
    run: Callable[[Mapping[str, Any]], Any]

    @property
    def tool_id(self) -> str:
        return self.spec.tool_id


@dataclass(frozen=True, slots=True)
class LocalProviderAdapter:
    """Yerel hesaplama sağlayıcısı. Cassette kullanmaz -- ağa hiç çıkmaz."""

    name: str
    bindings: tuple[LocalToolBinding, ...]
    license: str = "UNDETERMINED"
    attribution: str | None = None
    #: Hangi snapshot'lara dayandığı; `EnvironmentFingerprint` bunları taşır.
    snapshot_hashes: Mapping[str, str] = field(default_factory=dict)

    @property
    def tools(self) -> tuple[ToolSpec, ...]:
        return tuple(binding.spec for binding in self.bindings)

    def binding(self, tool_id: str) -> LocalToolBinding | None:
        return next((b for b in self.bindings if b.tool_id == tool_id), None)
