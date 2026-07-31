"""Tool registry ve **türetilmiş** kompozisyon grafiği.

Function graph elle yazılmaz da çıkarsanmaz da. Elle yazılan graph ~20 tool'dan
sonra ölçeklenmez ve şemalardan sapar; ad benzerliğinden çıkarım ise bu domainde
gürültüdür -- CKAN her şeye ``id``, ``name``, ``q`` der.

Bunun yerine parametre ve output alanlarında ``semantic_type`` bulunur; graph
ondan **türetilir**. Aynı alan üç şeyi daha bedava sağlar: grounding kontrolü,
distractor üretimi ve "bu ``durak_id`` snapshot'ta var mı" doğrulaması.

Decorator tabanlı kayıt singleton'ı kasıtlı olarak yoktur: import sırası
bug'ları üretir ve test izolasyonunu bozar. Sağlayıcılar ``TOOLS`` export eder,
``build_registry()`` birleştirir, registry açıkça geçirilir.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from toolcall_tr.canonical import sha256_of
from toolcall_tr.models import ToolSpec

__all__ = ["CompositionEdge", "ToolRegistry", "build_registry"]


class CompositionEdge:
    """İki tool arasında semantik tip üzerinden türetilmiş bağımlılık."""

    __slots__ = ("semantic_type", "source_path", "source_tool", "target_parameter", "target_tool")

    def __init__(
        self,
        source_tool: str,
        source_path: str,
        target_tool: str,
        target_parameter: str,
        semantic_type: str,
    ) -> None:
        self.source_tool = source_tool
        self.source_path = source_path
        self.target_tool = target_tool
        self.target_parameter = target_parameter
        self.semantic_type = semantic_type

    def __repr__(self) -> str:  # pragma: no cover - teşhis amaçlı
        return (
            f"CompositionEdge({self.source_tool}.{self.source_path} -> "
            f"{self.target_tool}.{self.target_parameter} [{self.semantic_type}])"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CompositionEdge):
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    def _key(self) -> tuple[str, str, str, str, str]:
        return (
            self.source_tool,
            self.source_path,
            self.target_tool,
            self.target_parameter,
            self.semantic_type,
        )

    def to_json(self) -> dict[str, str]:
        return {
            "source_tool": self.source_tool,
            "source_path": self.source_path,
            "target_tool": self.target_tool,
            "target_parameter": self.target_parameter,
            "semantic_type": self.semantic_type,
        }


class ToolRegistry:
    """Tool tanımlarının salt-okunur koleksiyonu."""

    def __init__(self, tools: Iterable[ToolSpec]) -> None:
        self._tools: dict[str, ToolSpec] = {}
        for tool in tools:
            if tool.tool_id in self._tools:
                raise ValueError(f"registry'de yinelenen tool_id: {tool.tool_id!r}")
            self._tools[tool.tool_id] = tool

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, tool_id: object) -> bool:
        return tool_id in self._tools

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self._tools[key] for key in sorted(self._tools))

    def get(self, tool_id: str) -> ToolSpec | None:
        return self._tools.get(tool_id)

    def require(self, tool_id: str) -> ToolSpec:
        """Tool'u döner; yoksa hata.

        Bilinmeyen tool oranı sıfır toleranslıdır, bu yüzden sessizce ``None``
        dönmek yerine erken ve gürültülü patlamak tercih edilir.
        """
        tool = self._tools.get(tool_id)
        if tool is None:
            available = ", ".join(sorted(self._tools)) or "(boş)"
            raise KeyError(f"registry'de bulunmayan tool: {tool_id!r}. Mevcut: {available}")
        return tool

    def tool_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def by_provider(self, provider: str) -> tuple[ToolSpec, ...]:
        return tuple(t for t in self if t.provider == provider)

    # -- semantik tipler ---------------------------------------------------

    def producers(self, semantic_type: str) -> tuple[tuple[ToolSpec, str], ...]:
        """Bu semantik tipte değer **üreten** (tool, output yolu) çiftleri."""
        return tuple(
            (tool, field.path)
            for tool in self
            for field in tool.outputs
            if field.semantic_type == semantic_type
        )

    def consumers(self, semantic_type: str) -> tuple[tuple[ToolSpec, str], ...]:
        """Bu semantik tipte değer **tüketen** (tool, parametre adı) çiftleri."""
        return tuple(
            (tool, param.name)
            for tool in self
            for param in tool.parameters
            if param.semantic_type == semantic_type
        )

    def semantic_types(self) -> tuple[str, ...]:
        found = {
            value
            for tool in self
            for value in (
                *(p.semantic_type for p in tool.parameters),
                *(o.semantic_type for o in tool.outputs),
            )
            if value is not None
        }
        return tuple(sorted(found))

    def composition_edges(self) -> tuple[CompositionEdge, ...]:
        """Semantik tip eşleşmesinden türetilen kompozisyon grafiği.

        Kendine dönen kenarlar elenir: bir tool'un kendi çıktısını kendi
        girdisine beslemesi bu domainde anlamlı bir görev yolu üretmez.
        """
        edges: list[CompositionEdge] = []
        for semantic_type in self.semantic_types():
            for source, path in self.producers(semantic_type):
                for target, parameter in self.consumers(semantic_type):
                    if source.tool_id == target.tool_id:
                        continue
                    edges.append(
                        CompositionEdge(
                            source_tool=source.tool_id,
                            source_path=path,
                            target_tool=target.tool_id,
                            target_parameter=parameter,
                            semantic_type=semantic_type,
                        )
                    )
        return tuple(
            sorted(
                edges,
                key=lambda e: (e.source_tool, e.target_tool, e.target_parameter, e.source_path),
            )
        )

    # -- kimlik ------------------------------------------------------------

    def content_hash(self) -> str:
        """Registry'nin bütününün hash'i — provenance'a ve ortam parmak izine yazılır."""
        return sha256_of([tool.model_dump(mode="json") for tool in self])

    def to_jsonl(self) -> str:
        """`registry/tools.jsonl` içeriği; tool_id'ye göre sıralı."""
        import json

        return "".join(
            json.dumps(tool.model_dump(mode="json"), sort_keys=True, ensure_ascii=False) + "\n"
            for tool in self
        )


def build_registry(*tool_groups: Iterable[ToolSpec]) -> ToolRegistry:
    """Birden fazla sağlayıcının ``TOOLS`` listesini tek registry'de birleştirir."""
    return ToolRegistry([tool for group in tool_groups for tool in group])
