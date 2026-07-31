"""Validator arayüzü ve boru hattı — Faz C.

Validator'lar **kaydedilmiş bir `Trace`'i** doğrular; hiçbir şeyi yeniden
çalıştırmaz. Bu yüzden `execution` veya `providers` import etmezler ve
`.importlinter` bunu zorlar. Yeniden çalıştırma gerekiyorsa o bir
`groundtruth` adımıdır.

Cassette gövdeleri gibi katman dışı veriler `ValidationSubject`'e **düz veri**
olarak geçirilir; validator'ın onları kendi okuması katman ihlali olurdu.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from toolcall_tr.models import (
    Blueprint,
    CallPlan,
    Example,
    Finding,
    Severity,
    ToolSpec,
    Trace,
    ValidationResult,
)

__all__ = [
    "ValidationPipeline",
    "ValidationSubject",
    "Validator",
    "looks_empty",
]


@dataclass(frozen=True, slots=True)
class ValidationSubject:
    """Bir örneğin doğrulanabilir tüm bileşenleri."""

    blueprint: Blueprint
    plan: CallPlan
    trace: Trace
    #: Modele sunulan tool tanımları (distractor'lar dâhil).
    tools: tuple[ToolSpec, ...]
    example: Example | None = None
    #: Cassette anahtarı -> ham gövde. PII taraması için; çağıran doldurur.
    cassette_payloads: Mapping[str, Any] = field(default_factory=dict)

    def tool(self, tool_id: str) -> ToolSpec | None:
        return next((t for t in self.tools if t.tool_id == tool_id), None)

    @property
    def user_message(self) -> str:
        if self.example is not None:
            return self.example.user_context
        return ""


class Validator(Protocol):
    """Tek bir doğrulama kuralı ailesi."""

    name: str

    def check(self, subject: ValidationSubject) -> Iterable[Finding]: ...


def looks_empty(response: Any) -> bool:
    """Yanıt "sonuç yok" anlamına mı geliyor?

    Sağlayıcıların boş sonuç biçimleri farklıdır: ESHOT ``[]`` döner, CKAN
    ``{"result": {"count": 0, "results": []}}`` döner, yerel hesaplama
    ``{"count": 0, "results": []}``. Hepsi geçerli bir cevaptır -- bu
    fonksiyon onları tanır ki `allow_empty_result` kontrolü anlamlı olsun.
    """
    if response is None:
        return True
    if isinstance(response, Sequence) and not isinstance(response, str | bytes):
        return len(response) == 0
    if isinstance(response, Mapping):
        inner = response.get("result")
        if isinstance(inner, Mapping):
            return looks_empty(inner)
        for key in ("count", "total"):
            value = response.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value == 0
        for key in ("results", "records", "items"):
            value = response.get(key)
            if isinstance(value, Sequence) and not isinstance(value, str | bytes):
                return len(value) == 0
    return False


class ValidationPipeline:
    """Validator'ları sırayla çalıştırır ve bulguları toplar.

    ``blocking`` kümesinde **olmayan** bir validator'ın ``ERROR`` bulguları
    ``WARNING``'e indirilir: kural raporlanır ama örneği reddetmez. Böylece
    olgunlaşmamış bir kontrol (ör. semantik judge) korpusu sessizce
    budayamaz.
    """

    def __init__(
        self,
        validators: Sequence[Validator],
        *,
        blocking: frozenset[str],
        fail_fast: bool = False,
    ) -> None:
        self.validators = tuple(validators)
        self.blocking = blocking
        self.fail_fast = fail_fast

        unknown = blocking - {v.name for v in self.validators}
        if unknown:
            raise ValueError(f"bloklayıcı listede tanımsız validator: {sorted(unknown)}")

    def run(
        self,
        subject: ValidationSubject,
        *,
        commit: bool = True,
    ) -> ValidationResult:
        """Kontrolleri çalıştır.

        ``commit=False``, LLM hakemi gibi pipeline dışı bir kapı daha varsa
        durum tutan validator'ların adayı erkenden korpusa kaydetmesini önler.
        Bütün dış kapılar geçtikten sonra çağıran ``commit`` metodunu kullanır.
        """
        findings: list[Finding] = []
        ran: list[str] = []
        finding_validators: set[str] = set()

        for validator in self.validators:
            ran.append(validator.name)
            is_blocking = validator.name in self.blocking

            for finding in validator.check(subject):
                if finding.severity is Severity.ERROR and not is_blocking:
                    finding = finding.model_copy(update={"severity": Severity.WARNING})
                findings.append(finding)
                finding_validators.add(validator.name)

            if self.fail_fast and any(f.severity is Severity.ERROR for f in findings):
                break

        result = ValidationResult(
            blueprint_id=subject.blueprint.blueprint_id,
            trace_id=subject.trace.trace_id(),
            findings=tuple(findings),
            validators_run=tuple(ran),
            validators_skipped=tuple(v.name for v in self.validators if v.name not in ran),
        )
        if commit and result.accepted:
            self.commit(subject, skip=finding_validators)
        return result

    def commit(
        self,
        subject: ValidationSubject,
        *,
        skip: set[str] | frozenset[str] = frozenset(),
    ) -> None:
        """Durum tutan validator'lara nihai kabul edilen adayı kaydet."""
        for validator in self.validators:
            if validator.name in skip:
                continue
            commit_candidate = getattr(validator, "commit", None)
            if callable(commit_candidate):
                commit_candidate(subject)
