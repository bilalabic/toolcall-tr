"""Canonical JSON serileştirme ve hash'leme — yaprak yardımcı modül.

Bu modül **yalnızca standart kütüphaneye** bağlıdır ve `models` dahil her
katman tarafından import edilebilir. Kasıtlı olarak `.importlinter` yasak
listelerinin dışında bırakılmıştır.

Buradaki tek bir biçim tüm hash'lerin tabanıdır: cassette anahtarları, blueprint
hash'leri, `trace_id` ve state hash'leri. Biçim değişirse **her hash değişir**,
yani bu dosya bir uyumluluk sözleşmesidir.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = [
    "CANONICAL_JSON_VERSION",
    "canonical_bytes",
    "canonical_json",
    "sha256_hex",
    "sha256_of",
    "short_hash",
    "type_skeleton",
]

#: Canonical biçimin sürümü. Serileştirme kuralları değişirse artırılır ve
#: mevcut tüm hash'lerin geçersizleştiği kabul edilir.
CANONICAL_JSON_VERSION = 1


def canonical_json(obj: Any) -> str:
    """Deterministik JSON string üretir.

    Kurallar:

    * anahtarlar sıralanır (``sort_keys=True``),
    * ayraçlarda boşluk yoktur,
    * Unicode kaçışlanmaz (``ensure_ascii=False``) — Türkçe karakterler
      okunabilir kalır ve byte gösterimi UTF-8'de kararlıdır,
    * ``NaN``/``Infinity`` reddedilir; JSON'da karşılıkları yoktur ve
      yuvarlama davranışları platforma göre değişir.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_bytes(obj: Any) -> bytes:
    """`canonical_json` çıktısının UTF-8 byte'ları."""
    return canonical_json(obj).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Ham byte'ların sha256'sı, ``sha256:`` önekiyle."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def sha256_of(obj: Any) -> str:
    """Bir nesnenin canonical gösteriminin sha256'sı."""
    return sha256_hex(canonical_bytes(obj))


def short_hash(value: str, length: int = 12) -> str:
    """Hash'in kısa biçimi — dosya adları ve log satırları için.

    ``sha256:`` öneki varsa atılır.
    """
    digest = value.split(":", 1)[-1]
    return digest[:length]


def type_skeleton(obj: Any) -> Any:
    """Bir JSON gövdesinin özyinelemeli tip/anahtar iskeleti.

    Drift tespiti için kullanılır. Değer drift'i (otobüsün varış süresi
    değişti) normaldir ve yok sayılır; **yapısal** drift (bir anahtar
    kayboldu, tip değişti) ground-truth'u geçersiz kılar ve insan müdahalesi
    ister. Bu fonksiyon ikisini ayırmayı mümkün kılar.

    Diziler homojen varsayılır: yalnızca ilk elemanın iskeleti alınır, ancak
    heterojenlik tespit edilirse tüm farklı iskeletler sıralı olarak döner.
    """
    if isinstance(obj, dict):
        return {key: type_skeleton(obj[key]) for key in sorted(obj)}
    if isinstance(obj, list):
        if not obj:
            return ["<empty>"]
        variants = sorted({canonical_json(type_skeleton(item)) for item in obj})
        return [json.loads(variant) for variant in variants]
    if isinstance(obj, bool):
        return "bool"
    if isinstance(obj, int):
        return "int"
    if isinstance(obj, float):
        return "float"
    if isinstance(obj, str):
        return "str"
    if obj is None:
        return "null"
    raise TypeError(f"JSON'a çevrilemeyen tip: {type(obj)!r}")
