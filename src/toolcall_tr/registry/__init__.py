"""Tool registry — sağlayıcıların ``TOOLS`` listelerini birleştirir.

Decorator tabanlı kayıt singleton'ı **kullanılmaz**: import sırası bug'ları
üretir ve test izolasyonunu bozar. Sağlayıcılar ``TOOLS: list[ToolSpec]``
export eder, ``build_registry()`` birleştirir, registry açıkça geçirilir.
"""
