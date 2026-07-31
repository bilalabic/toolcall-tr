"""Çalıştırma katmanı: cassette transport'u ve executor'lar.

Cassette bir ``httpx.BaseTransport`` alt sınıfıdır; executor'lar ondan
habersizdir. Anahtar **HTTP isteğinden** türetilir, tool argümanından değil —
tool şeması repodaki en oynak artefakttır.
"""
