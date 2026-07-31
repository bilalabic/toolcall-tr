"""Tool ve parametre şemaları — registry'nin veri sözleşmesi.

Çeviri politikası burada **makine tarafından zorlanır**: tool adı, parametre
anahtarı ve enum değerleri ASCII snake_case kalır; yalnızca açıklamalar
Türkçe'dir. Yanlışlıkla Türkçe bir parametre adı yazmak doğrulama hatası verir.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from toolcall_tr.canonical import sha256_of
from toolcall_tr.models.enums import ExecutionClass, SideEffect

__all__ = [
    "IDENTIFIER_RE",
    "OutputField",
    "ParamSpec",
    "ToolSource",
    "ToolSpec",
]

#: Tool ve parametre adları için izin verilen biçim. Türkçe karakter, boşluk ve
#: büyük harf kasıtlı olarak dışarıdadır -- bunlar çevrilmemesi gereken teknik
#: alanlardır.
IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")

#: ``provider_namespace.tool_name``
TOOL_ID_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")

JsonType = Literal["string", "integer", "number", "boolean", "array", "object"]


class ParamSpec(BaseModel):
    """Tek bir tool parametresi."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    type: JsonType
    description_tr: str = Field(min_length=1)
    required: bool = False

    #: Kompozisyon grafiğinin, grounding kontrolünün ve distractor üretiminin
    #: dayandığı alan. Örn. ``durak_id``, ``resource_id``, ``package_id``.
    #: Elle yazılmış bir function graph yerine bu tipler kullanılır.
    semantic_type: str | None = None

    enum: list[JsonValue] | None = None
    pattern: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    min_items: int | None = None
    max_items: int | None = None
    item_type: JsonType | None = None

    #: ``None`` geçerli bir varsayılan olabileceği için ayrı bayrak tutulur.
    has_default: bool = False
    default: JsonValue | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not IDENTIFIER_RE.match(self.name):
            raise ValueError(
                f"parametre adı ASCII snake_case olmalı (çevrilmez teknik alan): {self.name!r}"
            )
        if self.required and self.has_default:
            raise ValueError(
                f"{self.name!r}: zorunlu parametrenin varsayılanı olamaz -- "
                "varsayılan, eksikliği maskeleyerek clarification senaryolarını bozar"
            )
        if self.type == "array" and self.item_type is None:
            raise ValueError(f"{self.name!r}: array parametresi için item_type zorunlu")
        if self.type != "array" and self.item_type is not None:
            raise ValueError(f"{self.name!r}: item_type yalnızca array için anlamlı")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError(f"{self.name!r}: minimum > maximum")
        return self

    def to_json_schema(self) -> dict[str, Any]:
        """Bu parametrenin JSON Schema karşılığı."""
        schema: dict[str, Any] = {"type": self.type, "description": self.description_tr}
        if self.enum is not None:
            schema["enum"] = list(self.enum)
        if self.pattern is not None:
            schema["pattern"] = self.pattern
        if self.minimum is not None:
            schema["minimum"] = self.minimum
        if self.maximum is not None:
            schema["maximum"] = self.maximum
        if self.min_length is not None:
            schema["minLength"] = self.min_length
        if self.max_length is not None:
            schema["maxLength"] = self.max_length
        if self.min_items is not None:
            schema["minItems"] = self.min_items
        if self.max_items is not None:
            schema["maxItems"] = self.max_items
        if self.item_type is not None:
            schema["items"] = {"type": self.item_type}
        if self.has_default:
            schema["default"] = self.default
        return schema


class OutputField(BaseModel):
    """Tool yanıtında adreslenebilir bir alan.

    Planner, ``$actions[i].result.<path>`` referanslarını **bu listeye karşı**
    doğrular. Burada beyan edilmemiş bir alana referans veren blueprint, hiçbir
    ağ çağrısı yapılmadan reddedilir.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: Nokta ve ``[*]`` içeren sade yol. Örn. ``result.results[*].id``.
    path: str = Field(min_length=1)
    type: JsonType
    description_tr: str = Field(min_length=1)
    semantic_type: str | None = None

    @property
    def is_collection(self) -> bool:
        return "[*]" in self.path


class ToolSource(BaseModel):
    """Tool tanımının nereden türetildiği — provenance zincirinin ilk halkası."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_type: Literal["ckan", "openapi", "manual", "snapshot"]
    schema_version: str
    operation_id: str | None = None
    upstream_url: str | None = None
    source_hash: str | None = None
    #: Bu tool'un verisinin lisansı. ``UNDETERMINED`` bilinçli bir işarettir.
    license: str = "UNDETERMINED"
    attribution: str | None = None


class ToolSpec(BaseModel):
    """Canonical tool tanımı."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_id: str
    provider: str
    name: str
    description_tr: str = Field(min_length=1)
    parameters: tuple[ParamSpec, ...] = ()
    outputs: tuple[OutputField, ...] = ()

    side_effect: SideEffect = SideEffect.READ
    execution_class: ExecutionClass
    confirmation_required: bool = False

    #: Boş sonuç geçerli bir cevaptır (ör. "yaklaşan otobüs yok"). Bu bayrak
    #: olmadan execution validator en ilginç vakayı hata sayıp reddeder.
    allow_empty_result: bool = False

    #: Aynı episode içinde art arda çağrıldığında yanıtın meşru olarak
    #: değişebileceği tool'lar. Cassette bu durumda sıralı yanıt listesi tutar.
    #: Varsayılan ``False``: örneklerin %95'i tek yanıtlı olduğu için %5'in
    #: maliyetini hepsine ödetmeyiz.
    sequenced: bool = False

    source: ToolSource

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not IDENTIFIER_RE.match(self.name):
            raise ValueError(f"tool adı ASCII snake_case olmalı: {self.name!r}")
        if not TOOL_ID_RE.match(self.tool_id):
            raise ValueError(f"tool_id 'namespace.name' biçiminde olmalı: {self.tool_id!r}")
        if self.tool_id.split(".", 1)[1] != self.name:
            raise ValueError(
                f"tool_id soneki ({self.tool_id!r}) name ({self.name!r}) ile uyuşmuyor"
            )

        seen: set[str] = set()
        for param in self.parameters:
            if param.name in seen:
                raise ValueError(f"{self.tool_id}: yinelenen parametre {param.name!r}")
            seen.add(param.name)

        paths: set[str] = set()
        for field in self.outputs:
            if field.path in paths:
                raise ValueError(f"{self.tool_id}: yinelenen output yolu {field.path!r}")
            paths.add(field.path)

        if self.side_effect is not SideEffect.READ and self.execution_class is (
            ExecutionClass.LIVE_RECORDED
        ):
            raise ValueError(
                f"{self.tool_id}: yazma işlemi canlı ortamda çalıştırılamaz -- "
                "mock veya resmî sandbox kullanın"
            )
        return self

    @property
    def required_parameters(self) -> tuple[ParamSpec, ...]:
        return tuple(p for p in self.parameters if p.required)

    def parameter(self, name: str) -> ParamSpec | None:
        return next((p for p in self.parameters if p.name == name), None)

    def output(self, path: str) -> OutputField | None:
        return next((o for o in self.outputs if o.path == path), None)

    def to_json_schema(self) -> dict[str, Any]:
        """Tool parametrelerinin JSON Schema karşılığı.

        ``additionalProperties: false`` kasıtlıdır: şemada olmayan bir argüman
        üretmek "unknown parameter" hatasıdır ve kabul kriterinde toleransı
        sıfırdır.
        """
        return {
            "type": "object",
            "properties": {p.name: p.to_json_schema() for p in self.parameters},
            "required": [p.name for p in self.parameters if p.required],
            "additionalProperties": False,
        }

    def content_hash(self) -> str:
        """Tool tanımının içerik hash'i — registry hash'inin bileşeni."""
        return sha256_of(self.model_dump(mode="json"))


ToolSpecTuple = Annotated[tuple[ToolSpec, ...], Field(default=())]
