"""Tool observation'ından güvenli ve okunabilir Türkçe final cevap üretimi.

Bu modül bir LLM finalizer değildir. Yalnızca çalıştırılmış son tool adımının
gerçek observation'ını deterministik biçimde sunar:

* yeni olgu, yorum veya öneri eklemez;
* string değerleri JSON tırnakları içinde veri olarak gösterir;
* sözlük anahtarlarını sıralayarak aynı observation için aynı metni üretir;
* hata response'u uydurmaz, runner'ın kaydettiği hata ve durum kodunu taşır.

Böylece tam trajectory görünümü ham JSON dökümüyle bitmez; buna rağmen eğitim
hedefi terminal observation'a yüzde yüz bağlı kalır.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeGuard

from toolcall_tr.canonical import canonical_json

__all__ = ["render_terminal_observation_tr"]


_KEY_LABELS_TR: dict[str, str] = {
    "count": "Kayıt sayısı",
    "date": "Tarih",
    "description": "Açıklama",
    "error": "Hata",
    "id": "Kimlik",
    "latitude": "Enlem",
    "longitude": "Boylam",
    "message": "Mesaj",
    "name": "Ad",
    "results": "Sonuçlar",
    "source": "Kaynak",
    "status": "Durum",
    "status_code": "Durum kodu",
    "timezone": "Saat dilimi",
    "title": "Başlık",
    "total": "Toplam",
    "unit": "Birim",
    "url": "Bağlantı",
    "value": "Değer",
}


def render_terminal_observation_tr(
    response: object,
    *,
    status_code: int | None,
    error: str | None,
) -> str:
    """Terminal tool observation'ını iddia eklemeden Türkçe metne dönüştür."""
    if response is None:
        error_payload: dict[str, object] = {
            "error": error or "bilinmeyen hata",
            "status_code": status_code,
        }
        lines = _render_value(error_payload, indent=0)
        return "Araç işlemi tamamlanamadı. Doğrulanan hata ayrıntıları:\n" + "\n".join(
            lines
        )

    if _is_empty(response):
        return "Araç işlemi tamamlandı, ancak sonuçta gösterilecek veri bulunamadı."

    lines = _render_value(response, indent=0)
    return "Araçtan doğrulanan sonuçlar:\n" + "\n".join(lines)


def _render_value(value: object, *, indent: int) -> list[str]:
    prefix = " " * indent
    if isinstance(value, Mapping):
        if not value:
            return [f"{prefix}Boş nesne."]
        lines: list[str] = []
        for raw_key in sorted(value, key=lambda item: str(item)):
            key = str(raw_key)
            item = value[raw_key]
            label = _key_label(key)
            if _is_collection(item):
                lines.append(f"{prefix}- {label}:")
                lines.extend(_render_value(item, indent=indent + 2))
            else:
                lines.append(f"{prefix}- {label}: {_render_scalar(item)}")
        return lines

    if _is_sequence(value):
        sequence = list(value)
        if not sequence:
            return [f"{prefix}Boş liste."]
        lines = []
        for index, item in enumerate(sequence, start=1):
            if _is_collection(item):
                lines.append(f"{prefix}{index}.")
                lines.extend(_render_value(item, indent=indent + 2))
            else:
                lines.append(f"{prefix}{index}. {_render_scalar(item)}")
        return lines

    return [f"{prefix}{_render_scalar(value)}"]


def _render_scalar(value: object) -> str:
    # canonical_json stringleri tırnaklar ve satır sonlarını kaçırır. Tool
    # içeriğindeki bir talimat böylece assistant talimatına dönüşmez; veri olarak
    # görünür. Sayı/bool/null değerleri de kayıpsız kalır.
    return canonical_json(value)


def _key_label(key: str) -> str:
    translated = _KEY_LABELS_TR.get(key)
    if translated is not None:
        return translated
    return key.replace("_", " ").strip().capitalize() or "Alan"


def _is_collection(value: object) -> bool:
    return isinstance(value, Mapping) or _is_sequence(value)


def _is_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _is_empty(value: object) -> bool:
    return (
        (isinstance(value, Mapping) and not value)
        or (_is_sequence(value) and not value)
    )
