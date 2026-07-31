"""Doğrulama sonuçları.

Reddedilen örnekler **gerekçesiyle saklanır**. "Ne kadarını attınız ve neden?"
sorusuna "sakladık değil" cevabı vermek, bu tür bir çalışmada kabul edilebilir
bir cevap değildir.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from toolcall_tr.models.enums import Severity

__all__ = ["Finding", "ValidationResult"]


class Finding(BaseModel):
    """Tek bir validator bulgusu."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    validator: str
    #: Makine okunur hata türü. Rapordaki dağılım bu alana göre çıkarılır.
    #: Örn. ``unknown_tool``, ``fabricated_argument``, ``unsupported_claim``.
    code: str
    severity: Severity = Severity.ERROR
    message_tr: str

    #: Hatanın konumu: adım sırası ve/veya argüman adı.
    step_index: int | None = None
    field: str | None = None


class ValidationResult(BaseModel):
    """Bir örneğin tüm validator'lardan geçiş raporu."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    blueprint_id: str
    trace_id: str
    findings: tuple[Finding, ...] = ()
    #: Çalıştırılan validator adları -- hangi kontrollerin *yapılmadığını*
    #: bilmek, yapılanları bilmek kadar önemlidir.
    validators_run: tuple[str, ...] = ()
    validators_skipped: tuple[str, ...] = ()

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.WARNING)

    @property
    def accepted(self) -> bool:
        return not self.errors

    def code_counts(self) -> dict[str, int]:
        """Hata kodu dağılımı — `reports/error_distribution.json` için."""
        return dict(Counter(f.code for f in self.findings))

    def by_validator(self, name: str) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.validator == name)


class VerificationFlags(BaseModel):
    """Örnek üzerinde taşınan özet doğrulama durumu.

    ``None`` "bu kontrol çalıştırılmadı" demektir ve ``False``'tan farklıdır.
    Dataset card "kaç örnek yalnızca schema-valid?" sorusunu bu ayrım sayesinde
    dürüstçe cevaplayabilir.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_valid: bool | None = None
    schema_valid: bool | None = None
    registry_valid: bool | None = None
    argument_grounded: bool | None = None
    pii_clean: bool | None = None
    execution_valid: bool | None = None
    state_valid: bool | None = None
    semantic_valid: bool | None = None
    policy_valid: bool | None = None
    observation_grounded: bool | None = None
    language_valid: bool | None = None
    trajectory_valid: bool | None = None
    human_reviewed: bool = False

    #: İnceleyen kişinin etiketi (varsa).
    human_label: str | None = Field(default=None)
