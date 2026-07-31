"""Pipeline genelinde kullanılan sabit değer kümeleri.

Bu enum'lar veri sözleşmesinin parçasıdır: değerleri JSONL'e yazılır ve
yayımlanan veri setlerinde görünür. Değer **yeniden adlandırmak** kırıcı bir
değişikliktir; yeni değer eklemek değildir.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "ArgOrigin",
    "BlueprintKind",
    "Decision",
    "ExecutionClass",
    "MessageRole",
    "Severity",
    "SideEffect",
    "Split",
    "StateOpKind",
    "StepOutcome",
]


class Decision(StrEnum):
    """Bir örneğin beklenen üst düzey kararı (When2Call taksonomisi)."""

    TOOL_CALL = "tool_call"
    CLARIFICATION = "clarification"
    DIRECT_ANSWER = "direct_answer"
    CANNOT_ANSWER = "cannot_answer"


class BlueprintKind(StrEnum):
    """Senaryo ailesi. Negatif türler M1'de rezerve edilir.

    Sonradan eklemek ``Example`` şemasını kırardı: pozitif-olmayan senaryolar
    ``tool_calls`` yerine ``expected_behavior`` gerektirir.
    """

    SUCCESSFUL_TOOL_CALL = "successful_tool_call"
    PARALLEL_TOOL_CALL = "parallel_tool_call"
    SEQUENTIAL_TOOL_CALL = "sequential_tool_call"
    EMPTY_RESULT = "empty_result"
    EXPECTED_ERROR = "expected_error"
    ERROR_RECOVERY = "error_recovery"
    SHOULD_ASK_CLARIFICATION = "should_ask_clarification"
    SHOULD_ANSWER_DIRECTLY = "should_answer_directly"
    SHOULD_REFUSE = "should_refuse"
    CONFIRMATION_REQUIRED = "confirmation_required"
    USER_CANCELLATION = "user_cancellation"


class ExecutionClass(StrEnum):
    """Bir tool çıktısının nasıl üretildiği.

    Veri setinde her tool ve her örnek için yayımlanır. Savunulabilir iddia
    "her çağrı gerçek bir implementasyonla çalıştırıldı"dır; asla "tüm
    cevaplar canlı API'den geldi" değil.
    """

    #: Üçüncü taraf API'ye gerçek HTTP; yanıt cassette'e kaydedilmiş.
    LIVE_RECORDED = "live_recorded"
    #: Dondurulmuş, lisanslı bir snapshot üzerinde deterministik yerel hesaplama.
    DERIVED_LOCAL = "derived_local"
    #: Kurgusal ama gerçek dünya semantiğine sahip servis (M2 mock).
    SIMULATED = "simulated"


class SideEffect(StrEnum):
    """Tool'un sistem durumuna etkisi."""

    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class ArgOrigin(StrEnum):
    """Bir argüman değerinin nereden geldiği — grounding validator'ın temeli.

    Kaynağı **beyan edilir**, çıkarsanmaz. Beyan edilmemiş bir değer
    ``FABRICATED`` sayılır ve örnek reddedilir.
    """

    #: Kullanıcı mesajında **birebir** geçiyor (durak numarası, tarih, tutar).
    USER_MESSAGE = "user_message"
    #: Kullanıcının sözlerinden **türetildi**: ek soyma, normalizasyon, çıkarım.
    #:
    #: Türkçe eklemeli bir dildir ve bu ayrım olmadan doğal dil imkânsızlaşır.
    #: Gerçek kullanıcı "otobüs duraklarıyla ilgili veri var mı?" der; arama
    #: terimi ``"otobüs durak"`` olur. Birebir alıntı değildir ama uydurma da
    #: değildir -- ajanın yapması gereken gerçek iş budur. Portalın Solr
    #: indeksi de kök bulma yapmadığı için (``durağı`` -> 0 sonuç) bu dönüşüm
    #: doğru cevabın **ön koşuludur**.
    USER_MESSAGE_DERIVED = "user_message_derived"
    #: Önceki bir adımın çıktısından geldi.
    PRIOR_OBSERVATION = "prior_observation"
    #: Uygulamanın/ortamın bildiği ama kullanıcının söylemediği bilgi:
    #: cihaz konumu, o an görüntülenen kayıt, oturum bağlamı.
    #: `Blueprint.context` içinde beyan edilmiş olmalıdır.
    SYSTEM_STATE = "system_state"
    #: Tool şemasında tanımlı varsayılan.
    SCHEMA_DEFAULT = "schema_default"
    #: Blueprint yazarının sabitlediği fixture değeri.
    PINNED_FIXTURE = "pinned_fixture"
    #: Kaynağı yok -- reddedilir.
    FABRICATED = "fabricated"


class StepOutcome(StrEnum):
    """Bir adımın çalıştırma sonucu.

    Dört hata sınıfı kasıtlı olarak ayrıdır; birleştirilirse pipeline çürür:

    * ``OK`` / ``EXPECTED_ERROR`` -> ground-truth'un kendisi, örnek korunur
    * ``TRANSPORT_ERROR``         -> episode iptal, asla veri olmaz
    * ``PLAN_ERROR``              -> gürültülü build failure
    * ``NONDETERMINISM``          -> karantina, sessizce atılmaz
    """

    OK = "ok"
    EXPECTED_ERROR = "expected_error"
    UNEXPECTED_ERROR = "unexpected_error"
    TRANSPORT_ERROR = "transport_error"
    PLAN_ERROR = "plan_error"
    NONDETERMINISM = "nondeterminism"
    SKIPPED = "skipped"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Split(StrEnum):
    """Bölme, fan-out'tan ÖNCE ve family seviyesinde atanır."""

    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class StateOpKind(StrEnum):
    """State delta işlemi (M2)."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class Severity(StrEnum):
    """Validator bulgusunun ağırlığı."""

    #: Örnek reddedilir.
    ERROR = "error"
    #: Örnek kabul edilir ama raporlanır.
    WARNING = "warning"
    INFO = "info"
