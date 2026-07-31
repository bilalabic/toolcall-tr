"""PII tarayıcı — **asla devre dışı bırakılmaz**.

Bu, projeyi bitirebilecek tek teknik hatanın önündeki tek engeldir:
checksum-geçerli bir T.C. Kimlik Numarası yayımlamak, gerçek bir vatandaşın
KVKK korumalı kimliğini açık lisansla dağıtmak demektir.

Tarayıcı **üretilen örnekler kadar cassette'ler üzerinde de** çalışır. İki
sebep:

1. Doğal Türkçe yazan bir LLM, istenmeden gerçekçi TCKN ve IBAN uydurur.
2. Kaynak API'ler (şikâyet kayıtları, abone verisi) kişisel veri sızdırabilir.

Katman kuralı gereği bu modül `execution`'ı import etmez; cassette gövdeleri
çağıran tarafından düz veri olarak geçirilir.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from toolcall_tr.validation.identifiers import (
    SYNTHETIC_TCKN_PREFIX,
    is_synthetic_tckn,
    is_valid_iban,
    is_valid_tckn,
    is_valid_vkn,
)

__all__ = ["PIIHit", "scan_json", "scan_text"]

#: Rakam dizileri. Kelime sınırı yerine "rakam olmayan" sınırı kullanılır ki
#: "TCKN:12345678901" gibi bitişik yazımlar da yakalansın.
_DIGIT_RUN_RE = re.compile(r"(?<!\d)(\d{10,11})(?!\d)")

#: IBAN adayı: ülke kodu + kontrol hanesi + gruplar. Boşluklu veya bitişik.
#: Yalnızca ``TR`` aranmaz -- geçerli bir IBAN hangi ülkeden olursa olsun
#: finansal kişisel veridir ve veri setine giremez.
_IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{2,4}){2,8})\b")


@dataclass(frozen=True, slots=True)
class PIIHit:
    """Tespit edilen olası kişisel veri."""

    kind: str
    value: str
    path: str
    message_tr: str

    @property
    def redacted(self) -> str:
        """Bulguyu raporlarken ham değeri yaymamak için maskelenmiş hâli.

        Bulgunun kendisi de kişisel veridir; log'a ve rapora maskelenmiş
        gider.
        """
        if len(self.value) <= 4:
            return "*" * len(self.value)
        return f"{self.value[:2]}{'*' * (len(self.value) - 4)}{self.value[-2:]}"


def scan_text(text: str, *, path: str = "", policy: bool = False) -> list[PIIHit]:
    """Metinde gerçek TCKN / VKN / IBAN arar.

    ``policy=True`` ek olarak **sentetik aralık politikasını** dayatır: 11
    haneli her sayının ``0`` ile başlaması beklenir.

    Bu ayrım zorunludur ve pratikte kanıtlanmıştır. Politika kontrolü
    yalnızca **bizim ürettiğimiz** içerik için anlamlıdır (elle yazılmış
    ifadeler, M2 mock kayıtları). Üçüncü taraf API yanıtlarında 11 haneli
    sayılar sıradandır: İzmir taksi durak tablosundaki bir belediye referans
    numarası (``10861282522``) bu kontrolü tetikleyip geçerli bir örneği
    reddetmişti. Gerçek TCKN/VKN/IBAN taraması ise **her yerde** açık kalır.
    """
    hits: list[PIIHit] = []

    for match in _DIGIT_RUN_RE.finditer(text):
        candidate = match.group(1)
        if len(candidate) == 11:
            if is_valid_tckn(candidate):
                hits.append(
                    PIIHit(
                        kind="real_tckn",
                        value=candidate,
                        path=path,
                        message_tr=(
                            "checksum-geçerli TCKN tespit edildi. Sentetik kimlikler "
                            f"{SYNTHETIC_TCKN_PREFIX!r} ile başlamalıdır."
                        ),
                    )
                )
            elif policy and not is_synthetic_tckn(candidate):
                # Checksum tutmuyor, yani gerçek bir kimlik değil; ama bizim
                # ürettiğimiz içerikte sentetik aralıkta olmalıydı.
                hits.append(
                    PIIHit(
                        kind="nonconforming_tckn",
                        value=candidate,
                        path=path,
                        message_tr=(
                            "11 haneli kimlik benzeri sayı sentetik aralıkta değil; "
                            f"{SYNTHETIC_TCKN_PREFIX!r} ile başlamalıdır."
                        ),
                    )
                )
        elif len(candidate) == 10 and is_valid_vkn(candidate):
            hits.append(
                PIIHit(
                    kind="real_vkn",
                    value=candidate,
                    path=path,
                    message_tr=(
                        "checksum-geçerli VKN tespit edildi. Sentetik VKN'ler "
                        "kasten checksum-geçersiz olmalıdır."
                    ),
                )
            )

    for match in _IBAN_RE.finditer(text):
        candidate = "".join(match.group(0).split())
        if is_valid_iban(candidate):
            hits.append(
                PIIHit(
                    kind="valid_iban",
                    value=candidate,
                    path=path,
                    message_tr=(
                        "mod-97 geçerli IBAN tespit edildi. Sentetik IBAN'lar "
                        "kasten geçersiz olmalıdır."
                    ),
                )
            )

    return hits


def scan_json(
    payload: Any,
    *,
    path: str = "$",
    policy: bool = False,
    ignored_numeric_keys: frozenset[str] = frozenset(),
) -> list[PIIHit]:
    """JSON benzeri bir yapıyı özyinelemeli tarar.

    Sayısal alanlar da string'e çevrilerek taranır: bir TCKN'nin JSON'da
    ``int`` olarak durması onu daha az kişisel veri yapmaz.

    ``policy`` için bkz. `scan_text`.
    """
    return list(_walk(payload, path, policy, ignored_numeric_keys))


def _walk(
    payload: Any,
    path: str,
    policy: bool,
    ignored_numeric_keys: frozenset[str],
) -> Iterator[PIIHit]:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if str(key) in ignored_numeric_keys and (
                isinstance(value, int)
                or (isinstance(value, str) and value.isdigit())
            ):
                continue
            yield from _walk(value, f"{path}.{key}", policy, ignored_numeric_keys)
    elif isinstance(payload, Sequence) and not isinstance(payload, str | bytes):
        for index, item in enumerate(payload):
            yield from _walk(item, f"{path}[{index}]", policy, ignored_numeric_keys)
    elif isinstance(payload, str):
        yield from scan_text(payload, path=path, policy=policy)
    elif isinstance(payload, bool):
        return
    elif isinstance(payload, int):
        yield from scan_text(str(payload), path=path, policy=policy)
