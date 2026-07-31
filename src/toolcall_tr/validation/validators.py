"""Somut validator'lar.

Her biri bağımsızdır ve yalnızca `ValidationSubject` okur. Hata kodları
makine okunurdur; `reports/error_distribution.json` bu alana göre üretilir.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from decimal import Decimal

from toolcall_tr.canonical import canonical_json
from toolcall_tr.models import (
    ArgOrigin,
    Decision,
    ExecutedCall,
    ExecutionClass,
    Finding,
    LiteralArg,
    MessageRole,
    Severity,
    SideEffect,
    StepOutcome,
    StepRefArg,
    ToolSpec,
)
from toolcall_tr.schema import validate_arguments
from toolcall_tr.turkish import (
    NumberParseError,
    ascii_fold_tr,
    casefold_tr,
    loose_match,
    parse_tr_number,
)
from toolcall_tr.validation.base import ValidationSubject, looks_empty
from toolcall_tr.validation.pii import PIIHit, scan_json, scan_text

__all__ = [
    "ConfirmationValidator",
    "DuplicateValidator",
    "ExecutionValidator",
    "FormatValidator",
    "GroundingValidator",
    "PIIValidator",
    "RegistryValidator",
    "SchemaValidator",
]


def _error(validator: str, code: str, message: str, **kwargs: object) -> Finding:
    return Finding(
        validator=validator,
        code=code,
        severity=Severity.ERROR,
        message_tr=message,
        step_index=kwargs.get("step_index"),  # type: ignore[arg-type]
        field=kwargs.get("field"),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------


class FormatValidator:
    """Yapısal bütünlük: JSON'a çevrilebilirlik ve mesaj rolleri."""

    name = "format"

    def check(self, subject: ValidationSubject) -> Iterable[Finding]:
        for step in subject.trace.steps:
            try:
                canonical_json(step.arguments)
            except (TypeError, ValueError) as exc:
                yield _error(
                    self.name,
                    "arguments_not_serializable",
                    f"argümanlar canonical JSON'a çevrilemiyor: {exc}",
                    step_index=step.step_index,
                )
            if step.response is not None:
                try:
                    canonical_json(step.response)
                except (TypeError, ValueError) as exc:
                    yield _error(
                        self.name,
                        "response_not_serializable",
                        f"yanıt canonical JSON'a çevrilemiyor: {exc}",
                        step_index=step.step_index,
                    )

        example = subject.example
        if example is None:
            return
        if not example.messages:
            yield _error(self.name, "empty_conversation", "örnekte hiç mesaj yok")


# ---------------------------------------------------------------------------
# Şema
# ---------------------------------------------------------------------------


class SchemaValidator:
    """Argümanlar tool şemasına uyuyor mu?"""

    name = "schema"

    def check(self, subject: ValidationSubject) -> Iterable[Finding]:
        for step in subject.trace.steps:
            if step.outcome is StepOutcome.SKIPPED:
                continue
            tool = subject.tool(step.tool_id)
            if tool is None:
                continue  # RegistryValidator raporlar
            for message in validate_arguments(tool, step.arguments):
                yield _error(
                    self.name,
                    "schema_violation",
                    message,
                    step_index=step.step_index,
                )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class RegistryValidator:
    """Bilinmeyen tool ve bilinmeyen parametre oranı **sıfır** olmalı."""

    name = "registry"

    def check(self, subject: ValidationSubject) -> Iterable[Finding]:
        offered = {tool.tool_id for tool in subject.tools}

        for tool_id in subject.plan.available_tools:
            if tool_id not in offered:
                yield _error(
                    self.name,
                    "unknown_tool",
                    f"sunulan tool tanımlar arasında yok: {tool_id!r}",
                    field=tool_id,
                )

        for step in subject.trace.steps:
            tool = subject.tool(step.tool_id)
            if tool is None:
                yield _error(
                    self.name,
                    "unknown_tool",
                    f"çağrılan tool sunulmamış: {step.tool_id!r}",
                    step_index=step.step_index,
                )
                continue
            known = {param.name for param in tool.parameters}
            for name in sorted(set(step.arguments) - known):
                yield _error(
                    self.name,
                    "unknown_parameter",
                    f"{tool.tool_id}: şemada olmayan parametre {name!r}",
                    step_index=step.step_index,
                    field=name,
                )


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------


class GroundingValidator:
    """Her argümanın bir kaynağı olmalı ve o kaynak **doğrulanabilir** olmalı.

    Kaynak beyan edilir (`ArgOrigin`), çıkarsanmaz; ama beyan etmek tek başına
    yetmez -- her tür ayrı biçimde denetlenir:

    ``USER_MESSAGE``
        Değer mesajda **birebir** geçmeli (durak numarası, tutar, tarih).
    ``USER_MESSAGE_DERIVED``
        Değer mesajdan **türetilmiş** olmalı; Türkçe ek soyarak eşleştirilir.
        Bu tür olmadan doğal dil imkânsızlaşır: kullanıcı "otobüs
        duraklarıyla ilgili veri" der, argüman ``"otobüs durak"`` olur.
    ``SYSTEM_STATE``
        Değer `Blueprint.context` içinde beyan edilmiş olmalı -- yani
        uygulamanın gerçekten bildiği bir şey olmalı. Kullanıcı koordinat
        okumaz; konum cihazdan gelir ve bu bağlamda yazılıdır.
    ``PINNED_FIXTURE``
        Yazarın sabitlediği fixture kimliği; beyan yeterlidir.
    ``FABRICATED``
        Her zaman hata.
    """

    name = "grounding"

    def check(self, subject: ValidationSubject) -> Iterable[Finding]:
        user_message = subject.user_message
        context = {str(value) for value in subject.blueprint.context.values()}
        for step in subject.plan.steps:
            tool = subject.tool(step.tool_id)
            for name, value in sorted(step.arguments.items()):
                yield from self._check_value(
                    step.step_index, tool, name, value, user_message, context
                )

    def _check_value(
        self,
        step_index: int,
        tool: ToolSpec | None,
        name: str,
        value: LiteralArg | StepRefArg,
        user_message: str,
        context: set[str],
    ) -> Iterator[Finding]:
        if isinstance(value, StepRefArg):
            # Referansın geçerliliğini planner zaten kanıtladı.
            return

        if value.origin is ArgOrigin.FABRICATED:
            yield _error(
                self.name,
                "fabricated_argument",
                f"{name!r}: argümanın kaynağı yok (fabricated)",
                step_index=step_index,
                field=name,
            )
            return

        if value.origin is ArgOrigin.SCHEMA_DEFAULT:
            param = tool.parameter(name) if tool is not None else None
            if param is None or not param.has_default:
                yield _error(
                    self.name,
                    "false_default_claim",
                    f"{name!r}: şema varsayılanı olduğu beyan edildi ama şemada varsayılan yok",
                    step_index=step_index,
                    field=name,
                )
            return

        if value.origin is ArgOrigin.SYSTEM_STATE:
            if str(value.value) not in context:
                yield _error(
                    self.name,
                    "undeclared_context",
                    f"{name!r}: sistem bağlamından geldiği beyan edildi ama "
                    f"blueprint `context` alanında yok ({value.value!r})",
                    step_index=step_index,
                    field=name,
                )
            return

        if value.origin in {ArgOrigin.USER_MESSAGE, ArgOrigin.USER_MESSAGE_DERIVED}:
            if not user_message:
                return  # örnek henüz üretilmemiş; kontrol edilemez
            if value.origin is ArgOrigin.USER_MESSAGE:
                grounded = _appears_in(value.value, user_message)
                detail = "mesajda birebir bulunamadı"
            else:
                grounded = _derives_from(value.value, user_message)
                detail = "mesajdan türetilemiyor (ek soyma sonrası da eşleşmedi)"

            if not grounded:
                yield Finding(
                    validator=self.name,
                    code="ungrounded_argument",
                    severity=Severity.ERROR,
                    message_tr=f"{name!r}: {detail} ({value.value!r})",
                    step_index=step_index,
                    field=name,
                )


def _appears_in(value: object, text: str) -> bool:
    if value is None or isinstance(value, bool):
        return True

    haystacks = (text, casefold_tr(text), ascii_fold_tr(casefold_tr(text)))
    needle = str(value)
    candidates = {needle, casefold_tr(needle), ascii_fold_tr(casefold_tr(needle))}

    if isinstance(value, int | float | Decimal):
        # Kullanıcı "18.500 TL" yazar, argüman 18500'dür.
        for haystack in haystacks:
            for token in haystack.replace("\n", " ").split(" "):
                try:
                    if parse_tr_number(token) == Decimal(str(value)):
                        return True
                except NumberParseError:
                    continue
        # Ek almış yıllar (`2010'dan`) ve aralık yazımı (`2010–2024`) ayrı
        # whitespace tokenları değildir. Rakam sınırıyla birebir eşleştir;
        # böylece 3 yine 300 veya 3,5 içinde grounded sayılmaz.
        canonical_number = str(value)
        return any(
            re.search(
                rf"(?<![\d.,]){re.escape(canonical_number)}(?![\d.,])",
                haystack,
            )
            is not None
            for haystack in haystacks
        )

    return any(
        re.search(rf"(?<!\w){re.escape(candidate)}(?!\w)", haystack) is not None
        for candidate in candidates
        for haystack in haystacks
    )


def _derives_from(value: object, text: str) -> bool:
    """Değer kullanıcının sözlerinden türetilebilir mi?

    Sayılar için birebir arama yeterlidir; metin için Türkçe ek soyan gevşek
    eşleştirme kullanılır.
    """
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, int | float | Decimal):
        return _appears_in(value, text)
    return loose_match(str(value), text)


# ---------------------------------------------------------------------------
# Confirmation
# ---------------------------------------------------------------------------


class ConfirmationValidator:
    """Yan etkili çağrının açık kullanıcı onayına dayandığını doğrular."""

    name = "confirmation"
    _PHRASES = (
        "onaylıyorum",
        "onay veriyorum",
        "açıkça onaylıyorum",
        "kabul ediyorum",
    )

    def check(self, subject: ValidationSubject) -> Iterable[Finding]:
        message = casefold_tr(subject.user_message)
        for step in subject.plan.steps:
            tool = subject.tool(step.tool_id)
            if tool is None or not tool.confirmation_required:
                continue
            confirmed = step.arguments.get("confirmed")
            if not isinstance(confirmed, LiteralArg) or confirmed.value is not True:
                yield _error(
                    self.name,
                    "missing_confirmation_argument",
                    f"{step.tool_id}: yan etkili çağrıda confirmed=true yok",
                    step_index=step.step_index,
                    field="confirmed",
                )
            if message and not any(phrase in message for phrase in self._PHRASES):
                yield _error(
                    self.name,
                    "confirmation_not_in_user_message",
                    f"{step.tool_id}: kullanıcı mesajında açık onay ifadesi yok",
                    step_index=step.step_index,
                )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class ExecutionValidator:
    """Kaydedilmiş `Trace` üzerinde çalışır; hiçbir şeyi yeniden çalıştırmaz.

    Yalnızca HTTP 200 başarı sayılmaz: beklenen hata senaryolarında 404/409/422
    doğru sonuçtur.
    """

    name = "execution"

    def check(self, subject: ValidationSubject) -> Iterable[Finding]:
        trace = subject.trace

        if not trace.is_usable:
            yield _error(
                self.name,
                f"unusable_trace_{trace.outcome.value}",
                f"çalıştırma veriye dönüşemez: {trace.outcome.value}",
            )

        if subject.plan.decision is Decision.TOOL_CALL and not trace.steps:
            yield _error(self.name, "no_calls_executed", "tool_call kararında hiç çağrı yok")

        for step in trace.steps:
            yield from self._check_step(subject, step)

        if (
            any(step.execution_class is ExecutionClass.SIMULATED for step in trace.steps)
            and trace.state_delta is None
        ):
            yield _error(
                self.name,
                "missing_state_delta",
                "simulated episode state_delta üretmedi",
            )

    def _check_step(self, subject: ValidationSubject, step: ExecutedCall) -> Iterator[Finding]:
        if step.outcome is StepOutcome.OK and step.response is None:
            yield _error(
                self.name,
                "missing_response",
                "başarılı adımın yanıtı yok",
                step_index=step.step_index,
            )

        tool = subject.tool(step.tool_id)
        if (
            tool is not None
            and tool.execution_class is ExecutionClass.SIMULATED
            and step.outcome is StepOutcome.OK
        ):
            if step.state_hash_before is None or step.state_hash_after is None:
                yield _error(
                    self.name,
                    "missing_state_hash",
                    f"{tool.tool_id}: simulated çağrıda state hash eksik",
                    step_index=step.step_index,
                )
            elif tool.side_effect is not SideEffect.READ and not step.wrote_state:
                yield _error(
                    self.name,
                    "write_did_not_change_state",
                    f"{tool.tool_id}: başarılı yazma state'i değiştirmedi",
                    step_index=step.step_index,
                )
        if (
            tool is not None
            and step.outcome is StepOutcome.OK
            and looks_empty(step.response)
            and not tool.allow_empty_result
        ):
            yield _error(
                self.name,
                "unexpected_empty_result",
                f"{tool.tool_id}: boş sonuç döndü ama allow_empty_result tanımlı değil",
                step_index=step.step_index,
            )

        planned = next((s for s in subject.plan.steps if s.step_index == step.step_index), None)
        if planned is None:
            return

        if planned.expect.outcome == "error" and step.outcome is not StepOutcome.EXPECTED_ERROR:
            yield _error(
                self.name,
                "expected_error_not_observed",
                f"hata bekleniyordu ama sonuç {step.outcome.value}",
                step_index=step.step_index,
            )
        if planned.expect.outcome == "ok" and step.outcome not in {
            StepOutcome.OK,
            StepOutcome.SKIPPED,
        }:
            yield _error(
                self.name,
                "unexpected_step_failure",
                f"başarı bekleniyordu ama sonuç {step.outcome.value}: {step.error}",
                step_index=step.step_index,
            )


# ---------------------------------------------------------------------------
# PII
# ---------------------------------------------------------------------------


class PIIValidator:
    """Gerçek kişisel veri sızıntısı taraması. **Asla kapatılmaz.**

    Hem üretilen örnek hem de tüketilen cassette'ler taranır: LLM doğal
    Türkçe yazarken gerçekçi TCKN/IBAN uydurur, kaynak API'ler ise kişisel
    veri sızdırabilir.
    """

    name = "pii"

    _GBIF_NUMERIC_IDENTIFIER_KEYS = frozenset(
        {
            "acceptedKey",
            "classKey",
            "familyKey",
            "genusKey",
            "gbifID",
            "gbifId",
            "key",
            "kingdomKey",
            "nubKey",
            "occurrence_id",
            "orderKey",
            "parentKey",
            "phylumKey",
            "speciesKey",
            "taxonKey",
            "taxon_key",
            "usageKey",
            "usage_key",
        }
    )
    _GITHUB_NUMERIC_IDENTIFIER_KEYS = frozenset(
        {"id", "release_id", "repository_id"}
    )

    def _ignored_numeric_keys(self, *, tool_id: str = "", cassette_key: str = "") -> frozenset[str]:
        if tool_id.startswith("biodiversity.") or cassette_key.startswith("gbif:"):
            return self._GBIF_NUMERIC_IDENTIFIER_KEYS
        if tool_id.startswith("developer.") or cassette_key.startswith("github_metadata:"):
            return self._GITHUB_NUMERIC_IDENTIFIER_KEYS
        return frozenset()

    def check(self, subject: ValidationSubject) -> Iterable[Finding]:
        example = subject.example
        if example is not None:
            # Mesajlar ve argümanlar **bizim ürettiğimiz** içeriktir:
            # sentetik aralık politikası burada dayatılır.
            for index, message in enumerate(example.messages):
                is_terminal_observation_final = (
                    message.role is MessageRole.ASSISTANT
                    and example.ground_truth.final_response_source
                    == "terminal_observation"
                    and message.content == example.ground_truth.final_response_tr
                )
                if (
                    message.content
                    and message.role is not MessageRole.TOOL
                    and not is_terminal_observation_final
                ):
                    yield from self._hits(
                        scan_text(message.content, path=f"messages[{index}].content", policy=True)
                    )

        for step in subject.trace.steps:
            yield from self._hits(
                scan_json(step.arguments, path=f"steps[{step.step_index}].arguments", policy=True)
            )
            if step.response is not None:
                # Yanıt gövdeleri üçüncü taraf verisidir; orada 11 haneli
                # sayılar sıradandır (belediye referans numaraları gibi).
                # Politika değil, yalnızca gerçek PII aranır. `simulated`
                # sağlayıcılar (M2 mock) bizim ürettiğimiz veridir ve
                # politikaya tabidir.
                is_ours = step.execution_class is ExecutionClass.SIMULATED
                ignored_numeric_keys = self._ignored_numeric_keys(tool_id=step.tool_id)
                yield from self._hits(
                    scan_json(
                        step.response,
                        path=f"steps[{step.step_index}].response",
                        policy=is_ours,
                        ignored_numeric_keys=ignored_numeric_keys,
                    )
                )

        for key, payload in subject.cassette_payloads.items():
            ignored_numeric_keys = self._ignored_numeric_keys(cassette_key=key)
            yield from self._hits(
                scan_json(
                    payload,
                    path=f"cassette[{key[:24]}]",
                    ignored_numeric_keys=ignored_numeric_keys,
                )
            )

    def _hits(self, hits: Iterable[PIIHit]) -> Iterator[Finding]:
        for hit in hits:
            # Bulgunun kendisi de kişisel veridir: rapora **maskelenmiş** gider.
            yield _error(
                self.name,
                hit.kind,
                f"{hit.message_tr} (yol: {hit.path}, değer: {hit.redacted})",
                field=hit.path,
            )


# ---------------------------------------------------------------------------
# Duplicate
# ---------------------------------------------------------------------------


class DuplicateValidator:
    """Tekrar tespiti.

    Durum tutar: aynı korpus üzerinde ardışık çağrılarla kullanılır.
    Paraphrase fan-out'u, virgülle ayrılan beş cümle üretmeye çok eğilimlidir;
    tavan burada uygulanır ve ret oranı raporlanır.
    """

    name = "duplicate"

    def __init__(self, *, max_similarity: float = 0.95, ngram: int = 4) -> None:
        self.max_similarity = max_similarity
        self.ngram = ngram
        self._seen_hashes: dict[str, str] = {}
        self._seen_exact_messages: dict[str, str] = {}
        self._seen_normalized_messages: dict[str, str] = {}
        self._seen_messages: list[tuple[str, frozenset[str]]] = []

    def reset(self) -> None:
        self._seen_hashes.clear()
        self._seen_exact_messages.clear()
        self._seen_normalized_messages.clear()
        self._seen_messages.clear()

    def check(self, subject: ValidationSubject) -> Iterable[Finding]:
        """Adayı mevcut kabul kümesiyle karşılaştır; henüz durumu değiştirme."""
        example = subject.example
        if example is None:
            return []

        findings: list[Finding] = []

        digest = example.content_hash()
        message = example.user_context
        previous_content = self._seen_hashes.get(digest)
        previous_message = self._seen_exact_messages.get(message) if message else None
        previous = previous_content or previous_message
        if previous is not None:
            findings.append(
                _error(
                    self.name,
                    "exact_duplicate",
                    f"birebir aynı içerik daha önce görüldü: {previous}",
                )
            )
            return findings
        if not message:
            return findings

        normalized = _normalize_duplicate_text(message)
        previous_normalized = self._seen_normalized_messages.get(normalized)
        if previous_normalized is not None:
            findings.append(
                _error(
                    self.name,
                    "normalized_duplicate",
                    "normalize edilmiş kullanıcı mesajı daha önce görüldü: "
                    f"{previous_normalized}",
                )
            )
            return findings
        grams = _char_ngrams(normalized, self.ngram)
        for other_id, other_grams in self._seen_messages:
            similarity = _jaccard(grams, other_grams)
            if similarity > self.max_similarity:
                findings.append(
                    _error(
                        self.name,
                        "near_duplicate",
                        f"{other_id} ile benzerlik {similarity:.3f} > {self.max_similarity}",
                    )
                )
                return findings

        return findings

    def commit(self, subject: ValidationSubject) -> None:
        """Yalnız bütün kalite kapılarından geçen adayı kabul kümesine ekle."""
        example = subject.example
        if example is None:
            return

        self._seen_hashes.setdefault(example.content_hash(), example.id)
        message = example.user_context
        if not message:
            return
        self._seen_exact_messages.setdefault(message, example.id)
        normalized = _normalize_duplicate_text(message)
        self._seen_normalized_messages.setdefault(normalized, example.id)
        grams = _char_ngrams(normalized, self.ngram)
        if not any(other_id == example.id for other_id, _ in self._seen_messages):
            self._seen_messages.append((example.id, grams))


def _normalize_duplicate_text(text: str) -> str:
    """Türkçe/ASCII harf farkını ve gereksiz boşluğu tekrar için normalize eder."""
    return " ".join(ascii_fold_tr(casefold_tr(text)).split())


def _char_ngrams(text: str, size: int) -> frozenset[str]:
    if len(text) < size:
        return frozenset({text})
    return frozenset(text[i : i + size] for i in range(len(text) - size + 1))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 1.0
    return len(left & right) / len(union)
