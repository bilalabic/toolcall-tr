"""State gösterimi — M1'de null, M2'de gerçek.

Arayüzler M1'de tanımlanır ki M2'nin stateful sağlayıcısı ``Example`` şemasını
kırmasın ve ilk 100 örnek geçersizleşmesin.

Üç katman kasıtlıdır:

``state_hash``
    Tam eşleşme. Yalnızca **dahili yeniden üretilebilirlik** kontrolü. Bir
    notlandırma sözleşmesi olarak kötüdür: %95 doğru bir model sıfır alır ve
    hiçbir teşhis vermez.
``state_delta``
    Veri setinin **yayımladığı** ve benchmark'ın notladığı şey.
``assertions``
    Az sayıda okunabilir bildirimsel kontrol; kısmi puan ve niyet belgesi.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from toolcall_tr.models.enums import StateOpKind

__all__ = ["Assertion", "AssertionOp", "StateDelta", "StateOp"]

AssertionOp = Literal[
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "contains",
    "not_contains",
    "exists",
    "not_exists",
    "len_eq",
    "len_gte",
]

#: Değeri karşılaştırılmayan işlemler.
_UNARY_OPS: frozenset[str] = frozenset({"exists", "not_exists"})


class StateOp(BaseModel):
    """Normalize edilmiş state farkındaki tek bir işlem.

    ``entity_id`` **normalize edilmiştir**: oluşturulan varlıklar diff'ten önce
    oluşturulma sırasına göre ``#1``, ``#2`` ... şeklinde yeniden numaralanır.
    Autoincrement kimlikler farklı implementasyonlar arasında
    karşılaştırılamaz olduğu için ham kimlik kullanılmaz.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    op: StateOpKind
    entity: str
    entity_id: str
    fields: dict[str, JsonValue] = Field(default_factory=dict)


class StateDelta(BaseModel):
    """Bir episode'un state üzerindeki net etkisi."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ops: tuple[StateOp, ...] = ()

    #: Diff'ten hariç tutulan alanlar -- **allowlist**, biriken bir denylist değil.
    #: Örn. ``created_at``, ``ettn``.
    volatile_fields: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """Read-only sağlayıcılarda ve reddedilen yazma işlemlerinde ``True``.

        Başarısız bir yazma işleminin arkasında hiçbir şey bırakmadığını
        doğrulamak, yazılabilecek en değerli tek assertion'dır.
        """
        return not self.ops


class Assertion(BaseModel):
    """Blueprint yazarının elle yazdığı bildirimsel kontrol."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    op: AssertionOp
    value: JsonValue | None = None
    description_tr: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.op in _UNARY_OPS:
            if self.value is not None:
                raise ValueError(f"{self.op!r} işlemi değer almaz")
        elif self.value is None:
            raise ValueError(f"{self.op!r} işlemi bir değer gerektirir")
        return self
