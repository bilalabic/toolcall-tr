"""Çalıştırma ortamının kurulumu: istemci + cassette + executor.

Ortam **açıkça** kurulur ve geçirilir; global bir istemci veya singleton yoktur.
Bu, testlerin her birinin kendi izole ortamını kurabilmesini sağlar.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import httpx

from toolcall_tr.execution.cassette import (
    CassetteMode,
    CassetteStore,
    CassetteTransport,
    NoNetworkTransport,
)
from toolcall_tr.execution.executor import ReadOnlyHTTPExecutor
from toolcall_tr.providers.base import ProviderAdapter

__all__ = [
    "CASSETTE_MODE_ENV",
    "HTTPProviderRuntime",
    "build_http_runtime",
    "cassette_mode_from_env",
]

CASSETTE_MODE_ENV = "TOOLCALL_TR_CASSETTE_MODE"


def cassette_mode_from_env(default: CassetteMode = CassetteMode.REPLAY) -> CassetteMode:
    """Cassette modunu ortamdan okur.

    Varsayılan **replay**: kayıt, kasıtlı ve açık bir eylem olmalıdır.
    """
    raw = os.environ.get(CASSETTE_MODE_ENV)
    if not raw:
        return default
    try:
        return CassetteMode(raw.strip().lower())
    except ValueError:
        valid = ", ".join(mode.value for mode in CassetteMode)
        raise ValueError(
            f"{CASSETTE_MODE_ENV} geçersiz: {raw!r}. Geçerli değerler: {valid}"
        ) from None


@dataclass(slots=True)
class HTTPProviderRuntime:
    """Bir sağlayıcı için kurulmuş çalıştırma bileşenleri."""

    adapter: ProviderAdapter
    store: CassetteStore
    transport: CassetteTransport
    client: httpx.Client
    executor: ReadOnlyHTTPExecutor

    def close(self) -> None:
        """İstemciyi kapatır ve kayıtları diske yazar."""
        self.client.close()
        self.store.save()

    def __enter__(self) -> HTTPProviderRuntime:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def build_http_runtime(
    adapter: ProviderAdapter,
    *,
    cassette_root: Path,
    mode: CassetteMode = CassetteMode.REPLAY,
    timeout: float = 15.0,
    max_entries: int | None = None,
    git_sha: str | None = None,
) -> HTTPProviderRuntime:
    """Sağlayıcı için istemci, cassette ve executor kurar.

    Replay modunda iç taşıma katmanı `NoNetworkTransport`'tur: bir yapılandırma
    regresyonu "doğrulanmış" bir derlemeyi sessizce canlı-getirme derlemesine
    çeviremez.

    Retry kasıtlı olarak **kapalıdır**. Replay altında yeniden deneme anlamsız,
    kayıt altında ise ağa uzanan bir döngü CI'da flake üreticisidir.
    """
    if adapter.base_url is None:
        raise ValueError(f"{adapter.name}: HTTP çalıştırması için base_url gerekli")
    if adapter.cassette_namespace is None:
        raise ValueError(f"{adapter.name}: cassette namespace tanımlı değil")

    store = CassetteStore(
        cassette_root,
        adapter.cassette_namespace,
        license=adapter.license,
        attribution=adapter.attribution,
        max_entries=max_entries,
    )

    inner: httpx.BaseTransport = (
        NoNetworkTransport() if mode is CassetteMode.REPLAY else httpx.HTTPTransport(retries=0)
    )

    # Sıralı yanıtlar istek anahtarına bağlıdır ve önceden bilinemez; executor
    # `mark_sequenced()` ile çalışma anında bildirir.
    transport = CassetteTransport(
        store,
        mode,
        inner=inner,
        git_sha=git_sha,
    )
    client = httpx.Client(
        transport=transport,
        timeout=timeout,
        follow_redirects=False,
        headers={
            "User-Agent": "toolcall-tr/0.1 (+https://github.com/toolcall-tr/toolcall-tr)",
            # MET Norway yalnızca gzip/deflate desteğini şart koşuyor. İsteği
            # ortamda kurulu opsiyonel decoder'lara göre değişken bırakma.
            "Accept-Encoding": "gzip, deflate",
        },
    )
    executor = ReadOnlyHTTPExecutor(adapter, client, cassette=transport)
    return HTTPProviderRuntime(
        adapter=adapter,
        store=store,
        transport=transport,
        client=client,
        executor=executor,
    )
