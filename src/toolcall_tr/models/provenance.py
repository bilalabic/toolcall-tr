"""Provenance ve ortam parmak izi.

Provenance ilk gün tasarlanır çünkü **geriye dönük doldurulamaz**. Bir örneğin
hangi şemadan, hangi prompt sürümüyle, hangi modelle ve hangi cassette setiyle
üretildiği sonradan öğrenilemez.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from toolcall_tr.canonical import sha256_of

__all__ = ["EnvironmentFingerprint", "LLMUsage", "Provenance"]


class EnvironmentFingerprint(BaseModel):
    """Bir çalıştırmanın ortamını tanımlayan hash'ler.

    Bu **state değildir.** Read-only sağlayıcıda ``state_hash`` ``None``'dır;
    cassette manifest hash'i buraya yazılır. İkisini birleştirmek her downstream
    tüketiciye kalıcı olarak yanlış bir zihinsel model öğretir: cassette seti bir
    ortam sürümüdür, sistemin durumu değil.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: `data/cassettes/MANIFEST.json` içerik hash'i.
    cassette_manifest_hash: str | None = None
    #: Dondurulmuş tablo adı -> içerik hash'i.
    snapshot_hashes: dict[str, str] = Field(default_factory=dict)
    #: M2 mock'unun sürümü. Üçüncü tarafların benchmark'ı yeniden
    #: üretebilmesi için pinlenir.
    mock_version: str | None = None
    #: Göreli tarih ifadelerinin çözüldüğü an. Değişirse tarih içeren tüm
    #: ground-truth yeniden üretilmelidir.
    frozen_now: datetime
    root_seed: int
    #: Tool registry'sinin bütününün hash'i.
    registry_hash: str

    def content_hash(self) -> str:
        return sha256_of(self.model_dump(mode="json"))


class LLMUsage(BaseModel):
    """Tek bir LLM çağrısının maliyet ve kimlik kaydı."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    prompt_version: str
    temperature: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    #: Sağlayıcı tarafındaki prompt cache'ten karşılanan girdi token'ları.
    cached_input_tokens: int | None = None
    #: Önbellekten geldiyse ``True`` -- yeniden üretim maliyetini raporlamak için.
    cached: bool = False


class Provenance(BaseModel):
    """Bir örneğin tam üretim geçmişi."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pipeline_version: str
    canonical_json_version: int

    blueprint_id: str
    blueprint_hash: str
    family_id: str
    variant_index: int = 0

    plan_hash: str
    trace_id: str
    episode_seed: int

    environment: EnvironmentFingerprint

    #: Türkçe ifadeyi üreten model. Ground-truth **LLM tarafından
    #: üretilmediği** için bu alan yalnızca doğal dili kapsar.
    generator: LLMUsage | None = None
    #: Varsa LLM judge (M2).
    judge: LLMUsage | None = None

    created_at: datetime
    git_sha: str | None = None

    def content_hash(self) -> str:
        """``created_at`` ve ``git_sha`` hariç içerik hash'i.

        Bu ikisi çalıştırmaya özgüdür ve determinizm karşılaştırmasında
        gürültü yaratır.
        """
        payload = self.model_dump(mode="json", exclude={"created_at", "git_sha"})
        return sha256_of(payload)
