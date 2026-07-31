"""Task Blueprint — pipeline'ın girdisi ve tek doğruluk kaynağı.

Blueprint doğal dile çevrilmeden **önce** planner tarafından doğrulanır ve
runner tarafından çalıştırılır. Buradaki model doğrulayıcıları, yazım
hatalarını hiçbir ağ çağrısı yapılmadan yükleme anında yakalar.

``family_id`` ve ``split`` **beyan edilir**, sonradan çıkarsanmaz. Bölme
fan-out'tan önce yapıldığı için paraphrase varyantları yapısal olarak test
kümesine sızamaz.
"""

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from toolcall_tr.canonical import sha256_of
from toolcall_tr.models.args import ArgValue, StepRefArg
from toolcall_tr.models.enums import BlueprintKind, Decision, Split
from toolcall_tr.models.state import Assertion

__all__ = [
    "NEGATIVE_KINDS",
    "Blueprint",
    "ConversationTurn",
    "ExpectSpec",
    "ExpectedAction",
    "ExpectedBehavior",
]

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

#: Tool çağrısı beklenmeyen senaryolar. Bunları M1'de rezerve etmek zorunludur:
#: yalnızca mutlu yollardan oluşan bir korpus, her zaman tool çağıran bir model
#: eğitir.
NEGATIVE_KINDS: frozenset[BlueprintKind] = frozenset(
    {
        BlueprintKind.SHOULD_ASK_CLARIFICATION,
        BlueprintKind.SHOULD_ANSWER_DIRECTLY,
        BlueprintKind.SHOULD_REFUSE,
    }
)

_KIND_DECISION: dict[BlueprintKind, Decision] = {
    BlueprintKind.SHOULD_ASK_CLARIFICATION: Decision.CLARIFICATION,
    BlueprintKind.SHOULD_ANSWER_DIRECTLY: Decision.DIRECT_ANSWER,
    BlueprintKind.SHOULD_REFUSE: Decision.CANNOT_ANSWER,
}


class ConversationTurn(BaseModel):
    """Ana kullanıcı sorgusundan önceki deterministik konuşma bağlamı.

    Prefix tool çağrısı taşımaz; çok turlu örnekte yalnız aynı kullanıcı
    amacını netleştiren kullanıcı/asistan metin çiftleri için kullanılır.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.content != self.content.strip():
            raise ValueError("conversation_prefix içeriği kenar boşluğu içeremez")
        return self


class ExpectSpec(BaseModel):
    """Bir adımın beklenen sonucu.

    Beklenen hata bir **plan çıktısıdır**, istisna değil: runner bunu kaydeder
    ve devam eder. Yalnızca *beklenmeyen* hata episode'u iptal eder.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["ok", "error"] = "ok"
    #: Beklenen HTTP durum kodu. Yalnızca 200 başarı sayılmaz; 404/409/422
    #: tanımlı senaryolarda doğru sonuçtur.
    status_code: int | None = None
    error_class: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.outcome == "ok" and (self.status_code is not None or self.error_class is not None):
            raise ValueError("başarı beklenen adımda status_code/error_class belirtilemez")
        if self.outcome == "error" and self.status_code is None and self.error_class is None:
            raise ValueError("hata beklenen adımda status_code veya error_class zorunlu")
        return self


class ExpectedAction(BaseModel):
    """Blueprint'in beklediği tek bir tool çağrısı."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_id: str
    arguments: dict[str, ArgValue] = Field(default_factory=dict)
    expect: ExpectSpec = ExpectSpec()

    @property
    def step_references(self) -> tuple[StepRefArg, ...]:
        return tuple(a for a in self.arguments.values() if isinstance(a, StepRefArg))


class ExpectedBehavior(BaseModel):
    """Tool çağrısı dışındaki beklenen davranış.

    ``tool_calls`` tek başına yetmez: negatif senaryolarda doğru cevap bir
    çağrı değil, bir soru veya bir rettir.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Decision

    #: ``clarification`` için: hangi zorunlu parametreler eksik.
    missing_parameters: tuple[str, ...] = ()

    #: Asistanın iletmesi gereken **anlam** -- birebir metin değil. Birebir
    #: metin dayatmak Türkçe doğallığını öldürür ve değerlendirmeyi
    #: kelime eşleştirmesine indirger.
    response_intent_tr: str | None = None

    #: Tool çağrısı olmayan kararlarda modele öğretilecek birebir asistan
    #: mesajı. ``response_intent_tr`` yalnız semantik değerlendirme ölçütüdür;
    #: tek başına bir SFT hedefi değildir. Bu alan clarification,
    #: direct_answer ve cannot_answer kararlarında zorunlu, tool_call
    #: kararında yasaktır.
    assistant_response_tr: str | None = None

    #: ``cannot_answer`` için gerekçe.
    unsupported_reason_tr: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.decision is Decision.CLARIFICATION and not self.missing_parameters:
            raise ValueError("clarification kararı en az bir eksik parametre gerektirir")
        if self.decision is not Decision.CLARIFICATION and self.missing_parameters:
            raise ValueError("missing_parameters yalnızca clarification kararında anlamlı")
        if self.decision is Decision.CANNOT_ANSWER and not self.unsupported_reason_tr:
            raise ValueError("cannot_answer kararı bir gerekçe gerektirir")
        if self.decision is Decision.TOOL_CALL:
            if self.assistant_response_tr is not None:
                raise ValueError("assistant_response_tr tool_call kararında kullanılamaz")
        elif not self.assistant_response_tr or not self.assistant_response_tr.strip():
            raise ValueError(
                f"{self.decision.value} kararı birebir assistant_response_tr hedefi gerektirir"
            )
        elif self.assistant_response_tr != self.assistant_response_tr.strip():
            raise ValueError("assistant_response_tr başında veya sonunda boşluk içeremez")
        return self


class Blueprint(BaseModel):
    """Deterministik, çalıştırılabilir görev tanımı."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    blueprint_id: str
    #: Train/test bölmesinin yapıldığı seviye. **Beyan edilir**, çıkarsanmaz.
    #: Aynı senaryonun paraphrase'leri aynı family'yi paylaşır.
    family_id: str
    #: ``hash(family_id)``'den türetilir; blueprint eklemek mevcut atamaları
    #: karıştırmaz.
    split: Split | None = None

    domain: str
    kind: BlueprintKind
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    interaction_type: Literal["single_turn", "multi_turn"] = "single_turn"
    locale: str = "tr-TR"
    provider: str

    user_goal: str = Field(min_length=1)
    known_information: dict[str, JsonValue] = Field(default_factory=dict)
    missing_information: tuple[str, ...] = ()

    #: Çok turlu senaryoda son üretilmiş kullanıcı sorgusundan önceki,
    #: deterministik kullanıcı/asistan metin çiftleri. Her tur aynı
    #: ``user_goal`` amacına hizmet etmelidir.
    conversation_prefix: tuple[ConversationTurn, ...] = ()

    #: Uygulamanın bildiği ama kullanıcının **söylemediği** bilgi.
    #:
    #: Gerçek kullanıcı koordinat okumaz ("Buralarda durak var mı?" der);
    #: konum cihazdan gelir. UUID de yapıştırmaz; o an görüntülediği kayıt
    #: bağlamdadır. Bu alan olmadan `ArgOrigin.SYSTEM_STATE` denetlenemez ve
    #: doğal dili bozup değerleri kullanıcının ağzına koymak gerekir.
    context: dict[str, JsonValue] = Field(default_factory=dict)

    #: Modele sunulan tool listesi. Distractor'lar dâhildir: doğru tool'u
    #: seçmek ancak yanlış seçenekler varken anlamlıdır.
    available_tools: tuple[str, ...]

    expected_actions: tuple[ExpectedAction, ...] = ()
    expected_behavior: ExpectedBehavior
    assertions: tuple[Assertion, ...] = ()

    #: Elle yazılmış doğal Türkçe referans ifadeler. Çevrimdışı template bunları
    #: doğrudan kullanır; AI soru üretimi blueprint kısıtlarından yeni bir ifade
    #: yazarken bunları doğal dil çıpası olarak görür.
    #:
    #: Argüman değerleri bu metinlerde geçmelidir: grounding validator
    #: `ArgOrigin.USER_MESSAGE` beyan edilen her değeri burada arar.
    utterances: tuple[str, ...] = ()

    notes: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not ID_RE.match(self.blueprint_id):
            raise ValueError(f"blueprint_id snake_case olmalı: {self.blueprint_id!r}")
        if not ID_RE.match(self.family_id):
            raise ValueError(f"family_id snake_case olmalı: {self.family_id!r}")
        if not self.available_tools:
            raise ValueError("available_tools boş olamaz")
        if self.interaction_type == "single_turn" and self.conversation_prefix:
            raise ValueError("single_turn blueprint conversation_prefix taşıyamaz")
        if self.interaction_type == "multi_turn":
            if len(self.conversation_prefix) < 2:
                raise ValueError(
                    "multi_turn blueprint en az bir kullanıcı/asistan prefix çifti gerektirir"
                )
            expected_roles = ("user", "assistant")
            for index, turn in enumerate(self.conversation_prefix):
                expected_role = expected_roles[index % 2]
                if turn.role != expected_role:
                    raise ValueError(
                        "conversation_prefix kullanıcı/asistan sırasıyla ilerlemeli; "
                        f"{index}. tur {expected_role!r} olmalı"
                    )
            if self.conversation_prefix[-1].role != "assistant":
                raise ValueError(
                    "conversation_prefix assistant ile bitmeli; üretilmiş ana sorgu "
                    "sonraki user turudur"
                )

        decision = self.expected_behavior.decision

        expected = _KIND_DECISION.get(self.kind)
        if expected is not None and decision is not expected:
            raise ValueError(
                f"{self.kind.value!r} türü {expected.value!r} kararı gerektirir, "
                f"{decision.value!r} verildi"
            )

        if self.kind in NEGATIVE_KINDS and self.expected_actions:
            raise ValueError(f"{self.kind.value!r} türünde beklenen tool çağrısı olmamalı")

        if decision is Decision.TOOL_CALL and not self.expected_actions:
            raise ValueError("tool_call kararı en az bir beklenen çağrı gerektirir")

        if self.kind is BlueprintKind.EXPECTED_ERROR and not any(
            a.expect.outcome == "error" for a in self.expected_actions
        ):
            raise ValueError("expected_error türü hata bekleyen en az bir adım gerektirir")

        unknown = {a.tool_id for a in self.expected_actions} - set(self.available_tools)
        if unknown:
            raise ValueError(
                f"beklenen çağrılar available_tools dışında: {sorted(unknown)} -- "
                "model sunulmayan bir tool'u çağıramaz"
            )

        for index, action in enumerate(self.expected_actions):
            for ref in action.step_references:
                if ref.step_index >= index:
                    raise ValueError(
                        f"adım {index}: ileri veya kendine referans "
                        f"(step_index={ref.step_index}) -- referanslar yalnızca "
                        "önceki adımlara verilebilir"
                    )

        for name in self.expected_behavior.missing_parameters:
            if name in self.known_information:
                raise ValueError(f"{name!r} hem eksik parametre hem bilinen bilgi olarak işaretli")
        return self

    @property
    def is_negative(self) -> bool:
        return self.kind in NEGATIVE_KINDS

    def content_hash(self) -> str:
        """Blueprint'in içerik hash'i — provenance'a yazılır.

        ``split`` hariç tutulur: bölme ataması blueprint'in *içeriğini*
        değiştirmez, yalnızca nereye düştüğünü söyler.
        """
        payload = self.model_dump(mode="json", exclude={"split"})
        return sha256_of(payload)
