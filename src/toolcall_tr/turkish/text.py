"""Türkçe metin işleme — büyük/küçük harf, ASCII katlama.

**Neden ayrı bir modül:** Python'un varsayılan ``"I".lower()`` davranışı
Türkçe'de yanlıştır ve müşteri adı eşleştirmesini *sessizce* bozar. Bu hata
kodun on ayrı yerine dağılırsa dokuzunda yanlış yapılır; bu yüzden tek nokta.

Türkçe'de dört harf çifti standart eşlemeden farklıdır::

    I  <-> ı   (noktasız)
    İ  <-> i   (noktalı)

``"IZMIR".lower()`` Python'da ``"izmir"`` verir; doğrusu ``"ızmır"``.
``"izmir".upper()`` ``"IZMIR"`` verir; doğrusu ``"İZMİR"``.
"""

from __future__ import annotations

__all__ = ["ascii_fold_tr", "casefold_tr", "lower_tr", "title_tr", "upper_tr"]

_LOWER_MAP = str.maketrans({"I": "ı", "İ": "i"})
_UPPER_MAP = str.maketrans({"i": "İ", "ı": "I"})

#: Türkçe'ye özgü harflerin ASCII karşılıkları. Solr analyzer'ı ü/u'yu
#: eşitlemediği için (``q=otobüs`` -> 17 sonuç, ``q=otobus`` -> 9) her iki
#: biçimi de üretebilmek gerekir.
_ASCII_MAP = str.maketrans(
    {
        "ç": "c",
        "Ç": "C",
        "ğ": "g",
        "Ğ": "G",
        "ı": "i",
        "İ": "I",
        "ö": "o",
        "Ö": "O",
        "ş": "s",
        "Ş": "S",
        "ü": "u",
        "Ü": "U",
        "â": "a",
        "Â": "A",
        "î": "i",
        "Î": "I",
        "û": "u",
        "Û": "U",
    }
)


def lower_tr(text: str) -> str:
    """Türkçe kurallarına göre küçük harfe çevirir.

    >>> lower_tr("IZMIR")
    'ızmır'
    >>> lower_tr("İSTANBUL")
    'istanbul'
    """
    return text.translate(_LOWER_MAP).lower()


def upper_tr(text: str) -> str:
    """Türkçe kurallarına göre büyük harfe çevirir.

    >>> upper_tr("izmir")
    'İZMİR'
    >>> upper_tr("ırmak")
    'IRMAK'
    """
    return text.translate(_UPPER_MAP).upper()


def casefold_tr(text: str) -> str:
    """Karşılaştırma için normalize eder (Türkçe duyarlı küçük harf).

    Ad eşleştirmesinde ``str.casefold()`` yerine bu kullanılır.
    """
    return lower_tr(text).strip()


def title_tr(text: str) -> str:
    """Her kelimenin ilk harfini Türkçe kurallarıyla büyütür.

    >>> title_tr("izmir büyükşehir belediyesi")
    'İzmir Büyükşehir Belediyesi'
    """
    return " ".join(
        upper_tr(word[:1]) + lower_tr(word[1:]) if word else word for word in text.split(" ")
    )


def ascii_fold_tr(text: str) -> str:
    """Türkçe'ye özgü harfleri ASCII karşılıklarına indirger.

    Arama karşılaştırmaları için; **veriye yazılmaz**. Kullanıcının Türkçe
    karakter kullanıp kullanmaması sonucu değiştirir ve bu gerçek bir hata
    modudur -- gizlemek değil, temsil etmek istiyoruz.

    >>> ascii_fold_tr("otobüs durağı")
    'otobus duragi'
    """
    return text.translate(_ASCII_MAP)
