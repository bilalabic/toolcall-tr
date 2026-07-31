"""Ağ ve LLM gerektirmeyen, konservatif korpus kalite kontrolleri.

Bu validator'lar ölçekli üretimde erken uyarı sağlar. Varsayılan boru hattında
bloklayıcı değildirler: yalnızca açık ve makineyle kanıtlanabilir kusurları
raporlar, semantik doğruluk hakkında tahminde bulunmazlar.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator

from toolcall_tr.models import Finding, Message, MessageRole, Severity
from toolcall_tr.turkish import ascii_fold_tr, casefold_tr
from toolcall_tr.validation.base import ValidationSubject

__all__ = [
    "LanguageQualityValidator",
    "ObservationGroundingValidator",
    "TurnConsistencyValidator",
]


def _finding(validator: str, code: str, message: str, *, field: str | None = None) -> Finding:
    return Finding(
        validator=validator,
        code=code,
        severity=Severity.ERROR,
        message_tr=message,
        field=field,
    )


def _text_messages(subject: ValidationSubject) -> Iterator[tuple[int, Message]]:
    if subject.example is None:
        return
    for index, message in enumerate(subject.example.messages):
        if message.role is not MessageRole.TOOL and message.content is not None:
            yield index, message


class LanguageQualityValidator:
    """Mesajlarda açık üretim artığı ve bozuk metin belirtilerini arar.

    Doğallık veya dil bilgisi puanlamaz. Böyle bir karar sözlük/LLM gerektirir
    ve Türkçe özel adlarda yanlış pozitif üretir. Buradaki kurallar yalnızca
    deterministik belirtilerdir: boş içerik, görünmez kontrol karakteri,
    çözülmemiş yer tutucu, mojibake ve sunulan tool adının metne sızması.
    """

    name = "language"

    _PLACEHOLDER = re.compile(
        r"""
        \{\{\s*[^\W\d][\w.-]*\s*\}\}
        |\$\{\s*[^\W\d][\w.-]*\s*\}
        |\{\s*[^\W\d][\w.-]*\s*\}
        |<<\s*[^\W\d][\w.-]*\s*>>
        |<\s*(?:PLACEHOLDER|TODO|TBD|FIXME|[A-Z][A-Z0-9_]{2,})\s*>
        |\[(?:PLACEHOLDER|TODO|TBD|FIXME)\]
        """,
        re.VERBOSE,
    )
    _MOJIBAKE = re.compile(r"(?:Ã\S|Ä\S|Å\S|â€|ï»¿|\ufffd)")
    _EXCESS_SPACES = re.compile(r" {3,}")
    _ALLOWED_CONTROLS = frozenset({"\n", "\r", "\t"})
    _SUSPICIOUS_FORMAT_CHARS = frozenset(
        {
            "\u200b",  # zero-width space
            "\u202a",
            "\u202b",
            "\u202c",
            "\u202d",
            "\u202e",
            "\u2066",
            "\u2067",
            "\u2068",
            "\u2069",
            "\ufeff",  # BOM
        }
    )

    def check(self, subject: ValidationSubject) -> Iterable[Finding]:
        tool_names = self._tool_names(subject)
        for index, message in _text_messages(subject):
            field = f"messages[{index}].content"
            content = message.content
            if content is None:
                continue

            if not content.strip():
                yield _finding(self.name, "blank_message", "mesaj yalnızca boşluk içeriyor", field=field)
                continue

            if content != content.strip():
                yield _finding(
                    self.name,
                    "edge_whitespace",
                    "mesajın başında veya sonunda gereksiz boşluk var",
                    field=field,
                )
            if self._EXCESS_SPACES.search(content):
                yield _finding(
                    self.name,
                    "excessive_whitespace",
                    "mesajda art arda üç veya daha fazla boşluk var",
                    field=field,
                )

            controls = {
                f"U+{ord(char):04X}"
                for char in content
                if unicodedata.category(char) == "Cc" and char not in self._ALLOWED_CONTROLS
            }
            hidden = {
                f"U+{ord(char):04X}" for char in content if char in self._SUSPICIOUS_FORMAT_CHARS
            }
            if controls or hidden:
                codes = ", ".join(sorted(controls | hidden))
                yield _finding(
                    self.name,
                    "control_character",
                    f"mesaj görünmez veya izin verilmeyen kontrol karakteri içeriyor: {codes}",
                    field=field,
                )

            if self._PLACEHOLDER.search(content):
                yield _finding(
                    self.name,
                    "unresolved_placeholder",
                    "mesaj çözülmemiş bir şablon yer tutucusu içeriyor",
                    field=field,
                )
            if self._MOJIBAKE.search(content):
                yield _finding(
                    self.name,
                    "mojibake",
                    "mesaj bozuk karakter kodlaması belirtisi içeriyor",
                    field=field,
                )

            folded = casefold_tr(content)
            leaked = next(
                (
                    name
                    for name in tool_names
                    if re.search(rf"(?<![\w.]){re.escape(casefold_tr(name))}(?![\w.])", folded)
                ),
                None,
            )
            if leaked is not None:
                yield _finding(
                    self.name,
                    "tool_name_leakage",
                    f"doğal dil mesajına tool adı sızmış: {leaked!r}",
                    field=field,
                )

    @staticmethod
    def _tool_names(subject: ValidationSubject) -> tuple[str, ...]:
        names: set[str] = set()
        for tool in subject.tools:
            names.add(tool.tool_id)
            # Alt çizgili işlev adları doğal Türkçe sözcüklerle çakışmaz.
            if "_" in tool.name:
                names.add(tool.name)
        return tuple(sorted(names, key=lambda value: (-len(value), value)))


class ObservationGroundingValidator:
    """Final cevaptaki güçlü tanımlayıcıları önceki gözlemlerle karşılaştırır.

    Serbest metin anlam eşleştirmesi yapmaz. Yalnızca sayı ve URL gibi
    birebir doğrulanabilen değerleri denetler. Final asistan mesajı yoksa veya
    henüz tool gözlemi oluşmadıysa kontrol sessizce geçer.
    """

    name = "observation"

    _NUMBER = re.compile(r"(?<![\w])(?:\d[\d.,:/-]*\d|\d)(?![\w])")
    _URL = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)

    def check(self, subject: ValidationSubject) -> Iterable[Finding]:
        example = subject.example
        if example is None:
            return

        source_parts: list[str] = []
        saw_tool = False
        for index, message in enumerate(example.messages):
            if message.role is MessageRole.USER and message.content:
                source_parts.append(message.content)
                continue
            if message.role is MessageRole.TOOL:
                saw_tool = True
                if message.content:
                    source_parts.append(message.content)
                continue
            if (
                message.role is not MessageRole.ASSISTANT
                or message.tool_calls
                or not message.content
                or not saw_tool
            ):
                continue

            source = "\n".join(source_parts)
            yield from self._check_final(message.content, source, index=index)

    def _check_final(self, final: str, source: str, *, index: int) -> Iterator[Finding]:
        field = f"messages[{index}].content"
        source_numbers = {
            normalized
            for token in self._NUMBER.findall(source)
            if (normalized := self._normalize_number(token)) is not None
        }
        reported: set[str] = set()
        for match in self._NUMBER.finditer(final):
            token = match.group(0)
            normalized = self._normalize_number(token)
            if normalized is None or normalized in source_numbers or normalized in reported:
                continue
            if self._is_list_marker(final, match.start(), match.end()):
                continue
            reported.add(normalized)
            yield _finding(
                self.name,
                "unsupported_numeric_claim",
                f"final cevaptaki sayısal değer gözlemde veya kullanıcı mesajında yok: {token!r}",
                field=field,
            )

        normalized_source = ascii_fold_tr(casefold_tr(source))
        for raw_url in self._URL.findall(final):
            url = raw_url.rstrip(".,;:!?")
            if ascii_fold_tr(casefold_tr(url)) not in normalized_source:
                yield _finding(
                    self.name,
                    "unsupported_url_claim",
                    f"final cevaptaki URL gözlemde veya kullanıcı mesajında yok: {url!r}",
                    field=field,
                )

    @staticmethod
    def _normalize_number(token: str) -> str | None:
        digits = "".join(char for char in token if char.isdigit())
        # Tek haneler madde numarası ve doğal söylemde çok yaygındır.
        if len(digits) < 2:
            return None
        return digits.lstrip("0") or "0"

    @staticmethod
    def _is_list_marker(text: str, start: int, end: int) -> bool:
        line_start = text.rfind("\n", 0, start) + 1
        prefix = text[line_start:start]
        suffix = text[end : end + 2]
        return not prefix.strip() and bool(re.match(r"[.)]\s", suffix))


class TurnConsistencyValidator:
    """Canonical mesaj dizisinin tool çağrısı/yanıt akışını doğrular."""

    name = "turn"

    def check(self, subject: ValidationSubject) -> Iterable[Finding]:
        example = subject.example
        if example is None:
            return

        assistant_call_groups = [
            message.tool_calls
            for message in example.messages
            if message.role is MessageRole.ASSISTANT and message.tool_calls
        ]
        if subject.plan.is_sequential and any(
            len(group) > 1 for group in assistant_call_groups
        ):
            yield _finding(
                self.name,
                "dependent_calls_grouped",
                "önceki tool observation'ına bağlı çağrılar aynı asistan "
                "mesajında paralelmiş gibi gruplanmış",
                field="messages",
            )

        offered = {tool.name for tool in example.tools}
        offered.update(tool.tool_id.split(".", 1)[-1] for tool in example.tools)
        pending: list[str] = []
        user_count = 0
        previous_role: MessageRole | None = None

        for index, message in enumerate(example.messages):
            field = f"messages[{index}]"
            if message.role is MessageRole.USER:
                user_count += 1
                if pending:
                    yield _finding(
                        self.name,
                        "tool_response_missing_before_next_turn",
                        "yeni kullanıcı turundan önce tüm tool yanıtları gelmemiş",
                        field=field,
                    )
                    pending.clear()
                if previous_role is MessageRole.USER:
                    yield _finding(
                        self.name,
                        "consecutive_user_messages",
                        "ardışık iki kullanıcı mesajı tek turda birleştirilmelidir",
                        field=field,
                    )

            elif message.role is MessageRole.ASSISTANT:
                if pending:
                    yield _finding(
                        self.name,
                        "tool_response_missing_before_assistant",
                        "asistanın sonraki mesajından önce tüm tool yanıtları gelmemiş",
                        field=field,
                    )
                    pending.clear()
                if message.tool_calls:
                    for call in message.tool_calls:
                        if call.name not in offered:
                            yield _finding(
                                self.name,
                                "message_unknown_tool",
                                f"mesaj akışında sunulmayan tool çağrılmış: {call.name!r}",
                                field=field,
                            )
                        pending.append(call.name)

            elif message.role is MessageRole.TOOL:
                if not pending:
                    yield _finding(
                        self.name,
                        "orphan_tool_message",
                        "öncesinde karşılık gelen asistan çağrısı olmayan tool mesajı",
                        field=field,
                    )
                elif message.tool_name in pending:
                    # Paralel çağrıların yanıt sırası tanımlı değildir.
                    pending.remove(message.tool_name)
                else:
                    yield _finding(
                        self.name,
                        "tool_response_name_mismatch",
                        f"tool yanıtı bekleyen çağrılarla eşleşmiyor: {message.tool_name!r}",
                        field=field,
                    )

            previous_role = message.role

        if pending:
            yield _finding(
                self.name,
                "missing_tool_responses",
                f"{len(pending)} tool çağrısının yanıt mesajı yok",
                field="messages",
            )

        interaction_type = example.scenario.interaction_type
        if interaction_type == "single_turn" and user_count != 1:
            yield _finding(
                self.name,
                "interaction_type_mismatch",
                f"single_turn senaryosunda kullanıcı mesajı sayısı {user_count}",
                field="scenario.interaction_type",
            )
        elif interaction_type == "multi_turn" and user_count < 2:
            yield _finding(
                self.name,
                "interaction_type_mismatch",
                f"multi_turn senaryosunda yalnızca {user_count} kullanıcı mesajı var",
                field="scenario.interaction_type",
            )
