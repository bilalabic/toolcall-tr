"""Trace — Faz B'nin (runner) çıktısı ve Faz C'nin (validation) tek girdisi.

Validator'lar **yalnızca** bu artefaktı okur; hiçbir şeyi yeniden çalıştırmaz.
Bu ayrım sayesinde doğrulama saf, hızlı ve ağdan bağımsız kalır.

``trace_id`` **oynak alanları dışlar**. Yeniden üretilebilirlik testi tek
satırdır: planı iki taze ortamda çalıştır, ``trace_id``'lerin eşitliğini iddia
et. Gecikme süresi veya zaman damgası hash'e girseydi bu test her zaman
başarısız olurdu.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from toolcall_tr.canonical import sha256_of
from toolcall_tr.models.enums import ExecutionClass, StepOutcome
from toolcall_tr.models.provenance import EnvironmentFingerprint
from toolcall_tr.models.state import StateDelta

__all__ = ["VOLATILE_TRACE_FIELDS", "ExecutedCall", "Trace"]

#: ``trace_id`` hesabından dışlanan alanlar. Çalıştırmaya özgüdürler ve
#: determinizm karşılaştırmasında gürültüden başka bir şey değildirler.
VOLATILE_TRACE_FIELDS: frozenset[str] = frozenset({"latency_ms", "raw_response_hash"})

#: Episode'u iptal ettiren, veriye asla dönüşmemesi gereken sonuçlar.
_ABORTING_OUTCOMES: frozenset[StepOutcome] = frozenset(
    {
        StepOutcome.UNEXPECTED_ERROR,
        StepOutcome.TRANSPORT_ERROR,
        StepOutcome.PLAN_ERROR,
        StepOutcome.NONDETERMINISM,
    }
)


class ExecutedCall(BaseModel):
    """Gerçekten çalıştırılmış tek bir adım."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_index: int = Field(ge=0)
    step_id: str
    tool_id: str
    execution_class: ExecutionClass

    #: Referansları çözülmüş, somut argümanlar.
    arguments: dict[str, JsonValue] = Field(default_factory=dict)

    outcome: StepOutcome
    status_code: int | None = None
    #: Tool'un **normalize edilmiş** sonucu. Ham gövde cassette'te kalır;
    #: örneğe giren budur.
    response: JsonValue | None = None
    error: str | None = None

    #: Hangi kaydın kullanıldığı. ``derived_local`` adımlarda ``None``.
    cassette_key: str | None = None
    #: Ham gövdenin hash'i -- drift teşhisi için, ``trace_id``'ye girmez.
    raw_response_hash: str | None = None
    latency_ms: float | None = None

    #: Read-only sağlayıcılarda daima ``None``. Bkz. `EnvironmentFingerprint`.
    state_hash_before: str | None = None
    state_hash_after: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.outcome is StepOutcome.OK and self.error is not None:
            raise ValueError(f"{self.step_id}: başarılı adımda hata mesajı olamaz")
        if self.outcome in {StepOutcome.EXPECTED_ERROR, StepOutcome.UNEXPECTED_ERROR} and (
            self.status_code is None and self.error is None
        ):
            raise ValueError(f"{self.step_id}: hata sonucunda status_code veya error zorunlu")
        if self.execution_class is ExecutionClass.DERIVED_LOCAL and self.cassette_key is not None:
            raise ValueError(
                f"{self.step_id}: derived_local adım ağ çağrısı yapmaz, cassette anahtarı olamaz"
            )
        return self

    @property
    def wrote_state(self) -> bool:
        """State gerçekten değişti mi?

        Başarısız bir yazma işleminin arkasında hiçbir şey bırakmadığını
        doğrulamak, mock hatalarını en çok yakalayan tek kontroldür.
        """
        if self.state_hash_before is None or self.state_hash_after is None:
            return False
        return self.state_hash_before != self.state_hash_after


class Trace(BaseModel):
    """Bir episode'un tam çalıştırma kaydı."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    blueprint_id: str
    plan_hash: str
    episode_seed: int
    variant_index: int = 0

    steps: tuple[ExecutedCall, ...] = ()
    state_delta: StateDelta | None = None
    environment: EnvironmentFingerprint

    outcome: StepOutcome

    @model_validator(mode="after")
    def _check(self) -> Self:
        for position, step in enumerate(self.steps):
            if step.step_index != position:
                raise ValueError(
                    f"adım sırası bozuk: {position}. eleman step_index={step.step_index}"
                )
        return self

    @property
    def is_usable(self) -> bool:
        """Bu trace veriye dönüşebilir mi?

        Beklenen hata **ground-truth'un kendisidir** ve örnek korunur.
        Taşıma hatası, plan hatası ve nondeterminizm ise asla veri olmaz.
        """
        return self.outcome not in _ABORTING_OUTCOMES

    def _hashable(self) -> dict[str, object]:
        steps = [
            {
                k: v
                for k, v in step.model_dump(mode="json").items()
                if k not in VOLATILE_TRACE_FIELDS
            }
            for step in self.steps
        ]
        return {
            "blueprint_id": self.blueprint_id,
            "plan_hash": self.plan_hash,
            "episode_seed": self.episode_seed,
            "variant_index": self.variant_index,
            "outcome": self.outcome.value,
            "steps": steps,
            "state_delta": (
                self.state_delta.model_dump(mode="json") if self.state_delta is not None else None
            ),
        }

    def trace_id(self) -> str:
        """Oynak alanlar hariç, çalıştırmanın içerik kimliği.

        Aynı plan + aynı seed + aynı cassette seti daima aynı ``trace_id``
        üretmelidir. Üretmiyorsa bir yerde donmamış bir saat, global bir RNG
        veya sıralanmamış bir sorgu vardır.
        """
        return sha256_of(self._hashable())
