"""Argüman değerleri — sabit değer veya önceki adıma referans.

Her argümanın **kaynağı beyan edilir** (``origin``). Grounding validator bunu
çıkarsamaz, okur: kaynağı beyan edilmemiş bir değer ``FABRICATED`` sayılır.
Bu, "argümanın kullanıcı mesajından mı geldiği" sorusunu tahmin işi olmaktan
çıkarıp veri sözleşmesinin parçası yapar.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from toolcall_tr.models.enums import ArgOrigin

__all__ = [
    "STEP_REF_PATH_RE",
    "ArgValue",
    "LiteralArg",
    "StepRefArg",
    "parse_step_reference",
]

#: ``result.results[0].id`` gibi sade yollar. JSONPath'in tamamı kasıtlı olarak
#: desteklenmez: filtre ifadeleri ve joker'ler ground-truth'u belirsizleştirir.
STEP_REF_PATH_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\[\d+\]|\.[a-zA-Z_][a-zA-Z0-9_]*)*$")

#: Blueprint yazarken kullanılan kısa gösterim: ``$actions[0].result.id``
_SHORTHAND_RE = re.compile(r"^\$actions\[(\d+)\]\.(.+)$")


class LiteralArg(BaseModel):
    """Sabit bir argüman değeri."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["literal"] = "literal"
    value: JsonValue
    origin: ArgOrigin

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.origin is ArgOrigin.PRIOR_OBSERVATION:
            raise ValueError(
                "sabit değerin kaynağı 'prior_observation' olamaz -- "
                "önceki adımdan gelen değer StepRefArg ile ifade edilir"
            )
        return self


class StepRefArg(BaseModel):
    """Önceki bir adımın yanıtından türetilen argüman.

    Yeniden üretilebilirlik açısından her dinamik referans bir risktir. Zaten
    seed verisinde var olan varlıklar için sabitlenmiş fixture kimlikleri
    tercih edilir; ``StepRefArg`` gerçekten **o çalıştırmada oluşturulan**
    varlıklar için saklanır.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["step_ref"] = "step_ref"
    #: Plandaki adım sırası. Her zaman bu argümanı kullanan adımdan küçüktür.
    step_index: int = Field(ge=0)
    #: Adımın yanıt gövdesine göreli yol.
    path: str
    semantic_type: str | None = None
    origin: Literal[ArgOrigin.PRIOR_OBSERVATION] = ArgOrigin.PRIOR_OBSERVATION

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not STEP_REF_PATH_RE.match(self.path):
            raise ValueError(
                f"desteklenmeyen referans yolu {self.path!r} -- "
                "yalnızca nokta ve [n] biçimi kabul edilir"
            )
        return self


ArgValue = Annotated[LiteralArg | StepRefArg, Field(discriminator="kind")]


def parse_step_reference(text: str) -> tuple[int, str] | None:
    """``$actions[0].result.id`` kısa gösterimini ``(0, "result.id")`` yapar.

    Blueprint dosyalarında okunabilirlik için bu kısa biçim kullanılır; yükleme
    sırasında ``StepRefArg``'a çevrilir. Biçime uymayan metinler için ``None``
    döner (yani sıradan bir string değeridir).
    """
    match = _SHORTHAND_RE.match(text)
    if match is None:
        return None
    return int(match.group(1)), match.group(2)
