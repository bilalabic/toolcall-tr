"""Canonical örnek — yayımlanan verinin modelden bağımsız gösterimi.

Canonical biçim **bizimdir**. OpenAI tarzı ``tools``/``messages``, xLAM ve
ShareGPT yalnızca birer exporter'dır; hiçbiri iç gösterimi belirlemez. Bu ayrım
olmadan ``state_delta`` gibi sohbet şemasına sığmayan alanlar kaybolurdu.
"""

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from toolcall_tr.canonical import sha256_of
from toolcall_tr.models.enums import (
    BlueprintKind,
    Decision,
    ExecutionClass,
    MessageRole,
    Split,
    StepOutcome,
)
from toolcall_tr.models.provenance import Provenance
from toolcall_tr.models.state import Assertion, StateDelta
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.models.validation import VerificationFlags

__all__ = [
    "Example",
    "ExecutionRecord",
    "GroundTruth",
    "Localization",
    "Message",
    "Scenario",
    "ToolCallRecord",
]

# Yeni örnekler içerik kökenli 16 haneli hex sonek kullanır. Altı haneli eski
# M1 kimlikleri geriye dönük veri yükleme uyumluluğu için kabul edilir.
EXAMPLE_ID_RE = re.compile(r"^toolcall_tr_[a-z0-9_]+_(?:[a-f0-9]{16}|\d{6})$")


class ToolCallRecord(BaseModel):
    """Tek bir tool çağrısı — mesaj akışındaki ve ground-truth'taki biçim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class Message(BaseModel):
    """Konuşma turu."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: MessageRole
    content: str | None = None
    tool_calls: tuple[ToolCallRecord, ...] | None = None
    #: ``role=tool`` mesajlarında hangi tool'un sonucu olduğu.
    tool_name: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.role is MessageRole.TOOL and not self.tool_name:
            raise ValueError("tool mesajı tool_name içermeli")
        if self.tool_calls and self.role is not MessageRole.ASSISTANT:
            raise ValueError("tool_calls yalnızca assistant mesajında olabilir")
        if self.content is None and not self.tool_calls:
            raise ValueError("mesaj ya içerik ya tool_calls taşımalı")
        return self


class Localization(BaseModel):
    """Örneğin Türkçe'ye ne kadar özgü olduğu.

    Mevcut Türkçe veri setlerinin çoğu çeviri tabanlıdır; bu alanlar farkı
    ölçülebilir kılar ve dataset card'da dürüst karşılaştırma sağlar.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    translation_based: bool = False
    turkey_specific_schema: bool
    turkey_specific_scenario: bool


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Decision
    kind: BlueprintKind
    interaction_type: Literal["single_turn", "multi_turn"]
    difficulty: Literal["easy", "medium", "hard"]
    expected_result: Literal["success", "expected_error", "empty", "no_call"]


class GroundTruth(BaseModel):
    """Koddan derlenmiş doğru cevap. LLM tarafından üretilmez."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    calls: tuple[ToolCallRecord, ...] = ()
    missing_parameters: tuple[str, ...] = ()
    expected_final_state: StateDelta | None = None
    assertions: tuple[Assertion, ...] = ()
    #: Asistanın iletmesi gereken anlam; birebir metin dayatılmaz.
    response_intent_tr: str | None = None
    #: Tool çağrısı olmayan kararlarda messages içindeki birebir asistan
    #: eğitim hedefi. Tool-call trajectory'lerinde final cevap uydurulmaz.
    assistant_response_tr: str | None = None
    #: Tool-call trajectory'sinde son observation'dan deterministik türetilen
    #: kullanıcıya dönük final asistan mesajı. Gizli düşünce zinciri değildir.
    final_response_tr: str | None = None
    #: Final cevabın tek izinli kaynağı. Alan, serbest LLM özetinin ground
    #: truth gibi sunulmasını engeller.
    final_response_source: Literal["terminal_observation"] | None = None

    @model_validator(mode="after")
    def _check_final_response(self) -> Self:
        if (self.final_response_tr is None) != (self.final_response_source is None):
            raise ValueError(
                "final_response_tr ve final_response_source birlikte belirtilmelidir"
            )
        if self.final_response_tr is not None:
            if not self.final_response_tr.strip():
                raise ValueError("final_response_tr boş olamaz")
            if self.final_response_tr != self.final_response_tr.strip():
                raise ValueError("final_response_tr kenar boşluğu içeremez")
        return self


class ExecutionRecord(BaseModel):
    """Çalıştırmanın özeti — "bu örnek gerçekten çalıştırıldı mı?" sorusunun cevabı."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: Örnekteki çağrıların üretim sınıfları. Dataset card bu dağılımı
    #: raporlar; "hepsi canlı API'den geldi" iddiası asla yapılmaz.
    execution_classes: tuple[ExecutionClass, ...] = ()
    result: StepOutcome
    trace_id: str
    #: Read-only sağlayıcılarda ``None`` -- ortam parmak izi ile karıştırılmaz.
    initial_state_hash: str | None = None
    final_state_hash: str | None = None


class Example(BaseModel):
    """Yayımlanan tek bir kayıt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    locale: str = "tr-TR"
    domain: str
    provider: str
    family_id: str
    split: Split

    localization: Localization
    scenario: Scenario

    #: Modele sunulan tool tanımlarının anlık kopyası. Registry sonradan
    #: değişse bile örnek kendi kendine yeterli kalır.
    tools: tuple[ToolSpec, ...]
    messages: tuple[Message, ...]
    #: Modelin gizli düşünce zinciri değil; gözlenebilir kararın kısa,
    #: denetlenebilir Türkçe açıklaması.
    reasoning_summary_tr: str | None = None
    ground_truth: GroundTruth
    execution: ExecutionRecord
    verification: VerificationFlags
    provenance: Provenance

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not EXAMPLE_ID_RE.match(self.id):
            raise ValueError(
                "id 'toolcall_tr_<domain>_<16 hex>' biçiminde olmalı "
                f"(eski 6 haneli kimlikler de okunur): {self.id!r}"
            )
        if not self.messages:
            raise ValueError("örnek en az bir mesaj içermeli")
        if self.messages[0].role is not MessageRole.USER:
            raise ValueError("ilk mesaj kullanıcıdan gelmeli")

        available = {tool.tool_id.split(".", 1)[1] for tool in self.tools}
        for call in self.ground_truth.calls:
            if call.name not in available:
                raise ValueError(
                    f"ground truth sunulmayan tool'u çağırıyor: {call.name!r} -- "
                    "unknown tool oranı sıfır olmalıdır"
                )

        if self.scenario.decision is Decision.TOOL_CALL and not self.ground_truth.calls:
            raise ValueError("tool_call kararında ground truth çağrısı zorunlu")
        if self.scenario.decision is not Decision.TOOL_CALL and self.ground_truth.calls:
            raise ValueError(f"{self.scenario.decision.value!r} kararında çağrı olmamalı")
        if self.scenario.decision is Decision.CLARIFICATION and (
            not self.ground_truth.missing_parameters
        ):
            raise ValueError("clarification kararında eksik parametre listelenmeli")

        assistant_response = self.ground_truth.assistant_response_tr
        if self.scenario.decision is Decision.TOOL_CALL:
            if assistant_response is not None:
                raise ValueError(
                    "tool_call kararında ground_truth.assistant_response_tr kullanılamaz"
                )
            final_response = self.ground_truth.final_response_tr
            if final_response is not None:
                final_message = self.messages[-1]
                if (
                    final_message.role is not MessageRole.ASSISTANT
                    or final_message.tool_calls
                    or final_message.content != final_response
                ):
                    raise ValueError(
                        "tool_call final mesajı ground_truth.final_response_tr ile "
                        "aynı assistant hedefi olmalı"
                    )
        else:
            if self.ground_truth.final_response_tr is not None:
                raise ValueError(
                    "tool çağrısı olmayan kararda final_response_tr kullanılamaz"
                )
            if not assistant_response or not assistant_response.strip():
                raise ValueError(
                    f"{self.scenario.decision.value!r} kararında birebir asistan hedefi zorunlu"
                )
            if any(message.tool_calls for message in self.messages):
                raise ValueError("tool çağrısı olmayan kararda assistant tool_calls bulunamaz")
            if any(message.role is MessageRole.TOOL for message in self.messages):
                raise ValueError("tool çağrısı olmayan kararda tool mesajı bulunamaz")
            final_message = self.messages[-1]
            if (
                final_message.role is not MessageRole.ASSISTANT
                or final_message.tool_calls
                or final_message.content != assistant_response
            ):
                raise ValueError(
                    "tool çağrısı olmayan kararda son mesaj, "
                    "ground_truth.assistant_response_tr ile aynı assistant hedefi olmalı"
                )

        if self.provenance.family_id != self.family_id:
            raise ValueError("provenance.family_id örnekle uyuşmuyor")
        if self.execution.trace_id != self.provenance.trace_id:
            raise ValueError("execution.trace_id provenance ile uyuşmuyor")
        return self

    @property
    def user_message(self) -> str:
        """Tool kararını tetikleyen son kullanıcı mesajı."""
        return next(
            (
                message.content or ""
                for message in reversed(self.messages)
                if message.role is MessageRole.USER
            ),
            "",
        )

    @property
    def user_context(self) -> str:
        """Grounding/duplicate için tüm kullanıcı turlarının sıralı metni."""
        return "\n".join(
            message.content or ""
            for message in self.messages
            if message.role is MessageRole.USER
        )

    def content_hash(self) -> str:
        """Duplicate tespiti için içerik hash'i; provenance hariç."""
        payload = self.model_dump(mode="json", exclude={"provenance", "id"})
        return sha256_of(payload)
