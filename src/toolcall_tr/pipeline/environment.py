"""Türkiye geneli üretim ve geçmiş İzmir uyumluluk ortamlarının kurulumu.

Varsayılan ortam yalnız lisansı ve yürütme politikası incelenmiş 35 aracı
sunmaktadır. İzmir ve ön muhasebe sağlayıcıları varsayılan üretim yolunda
değildir; geçmiş testlerin yeniden üretilebilmesi için ayrı uyumluluk
fonksiyonları korunur.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from toolcall_tr.execution.calendar_mock import StatefulCalendarExecutor
from toolcall_tr.execution.cassette import CassetteMode, read_manifest_hash
from toolcall_tr.execution.environment import HTTPProviderRuntime, build_http_runtime
from toolcall_tr.execution.executor import Executor
from toolcall_tr.execution.local_executor import DerivedLocalExecutor
from toolcall_tr.groundtruth.runner import Environment
from toolcall_tr.models import EnvironmentFingerprint
from toolcall_tr.providers.calendar_mock import events as calendar_mock
from toolcall_tr.providers.crossref import works as crossref_works
from toolcall_tr.providers.federated_web import metadata as federated_web
from toolcall_tr.providers.frankfurter import rates
from toolcall_tr.providers.gbif import biodiversity
from toolcall_tr.providers.general_local import tools as general_tools
from toolcall_tr.providers.geonames import geography
from toolcall_tr.providers.github_metadata import repositories as github_repositories
from toolcall_tr.providers.izmir import ckan, eshot
from toolcall_tr.providers.izmir import stops as stops_provider
from toolcall_tr.providers.met import weather
from toolcall_tr.providers.tr_calendar import holidays
from toolcall_tr.providers.usgs import earthquakes
from toolcall_tr.providers.wikidata import entities as wikidata_entities
from toolcall_tr.providers.wikimedia import metadata as wikimedia_metadata
from toolcall_tr.providers.worldbank import indicators as wdi_indicators
from toolcall_tr.providers.worldbank import search as wdi_search
from toolcall_tr.registry.registry import ToolRegistry, build_registry

__all__ = [
    "DEFAULT_FROZEN_NOW",
    "DEFAULT_ROOT_SEED",
    "build_default_registry",
    "build_izmir_registry",
    "open_default_environment",
    "open_izmir_environment",
]

#: `configs/project.yaml` ile aynı değer. Göreli tarih ifadeleri buna göre
#: çözülür; değişirse tarih içeren tüm ground-truth yeniden üretilmelidir.
DEFAULT_FROZEN_NOW = datetime(2026, 7, 28, 6, 0, tzinfo=UTC)
DEFAULT_ROOT_SEED = 42891


def build_izmir_registry() -> ToolRegistry:
    """Beş İzmir tool'unu tek registry'de birleştirir."""
    return build_registry(ckan.TOOLS, eshot.TOOLS, stops_provider.TOOLS)


def build_default_registry() -> ToolRegistry:
    """Türkiye geneli üretim kataloğundaki tam 35 aracı döndürür."""
    return build_registry(
        weather.TOOLS,
        rates.TOOLS,
        earthquakes.TOOLS,
        wdi_search.TOOLS,
        wdi_indicators.TOOLS,
        biodiversity.TOOLS,
        wikimedia_metadata.TOOLS,
        github_repositories.TOOLS,
        geography.TOOLS,
        holidays.TOOLS,
        wikidata_entities.TOOLS,
        crossref_works.TOOLS,
        federated_web.TOOLS,
        general_tools.TOOLS,
        calendar_mock.TOOLS,
    )


@contextmanager
def open_default_environment(
    *,
    repo_root: Path,
    mode: CassetteMode = CassetteMode.REPLAY,
    now: datetime = DEFAULT_FROZEN_NOW,
    root_seed: int = DEFAULT_ROOT_SEED,
    snapshot_dir: Path | None = None,
) -> Iterator[Environment]:
    """Etkin sağlayıcı ortamını kurar ve çıkışta kayıtları diske yazar."""
    cassette_root = repo_root / "data" / "cassettes"
    registry = build_default_registry()

    del snapshot_dir  # Eski imza uyumluluğu; production snapshot yolları sabittir.
    geonames_dir = repo_root / "data" / "snapshots" / "geonames_tr"
    holidays_dir = repo_root / "data" / "snapshots" / "tr_public_holidays"
    wdi_dir = repo_root / "data" / "snapshots" / "wdi_indicators"
    geography_adapter = geography.build_adapter(geonames_dir)
    holidays_adapter = holidays.build_adapter(holidays_dir)
    wdi_search_adapter = wdi_search.build_adapter(
        wdi_dir
    )
    federated_adapter = federated_web.build_adapter(
        geonames_dir=geonames_dir,
        wdi_dir=wdi_dir,
        holidays_dir=holidays_dir,
    )
    general_adapter = general_tools.build_adapter(now)
    calendar_executor = StatefulCalendarExecutor(now=now)

    runtimes: list[HTTPProviderRuntime] = []
    try:
        met_runtime = build_http_runtime(
            weather.adapter,
            cassette_root=cassette_root,
            mode=mode,
        )
        runtimes.append(met_runtime)
        rates_runtime = build_http_runtime(
            rates.adapter,
            cassette_root=cassette_root,
            mode=mode,
        )
        runtimes.append(rates_runtime)
        usgs_runtime = build_http_runtime(
            earthquakes.adapter,
            cassette_root=cassette_root,
            mode=mode,
        )
        runtimes.append(usgs_runtime)
        wdi_runtime = build_http_runtime(
            wdi_indicators.adapter,
            cassette_root=cassette_root,
            mode=mode,
        )
        runtimes.append(wdi_runtime)
        gbif_runtime = build_http_runtime(
            biodiversity.adapter,
            cassette_root=cassette_root,
            mode=mode,
        )
        runtimes.append(gbif_runtime)
        wikimedia_runtime = build_http_runtime(
            wikimedia_metadata.adapter,
            cassette_root=cassette_root,
            mode=mode,
        )
        runtimes.append(wikimedia_runtime)
        github_runtime = build_http_runtime(
            github_repositories.adapter,
            cassette_root=cassette_root,
            mode=mode,
        )
        runtimes.append(github_runtime)
        wikidata_runtime = build_http_runtime(
            wikidata_entities.adapter,
            cassette_root=cassette_root,
            mode=mode,
        )
        runtimes.append(wikidata_runtime)
        crossref_runtime = build_http_runtime(
            crossref_works.adapter,
            cassette_root=cassette_root,
            mode=mode,
        )
        runtimes.append(crossref_runtime)

        executors: dict[str, Executor] = {
            weather.PROVIDER: met_runtime.executor,
            rates.PROVIDER: rates_runtime.executor,
            earthquakes.PROVIDER: usgs_runtime.executor,
            wdi_search.PROVIDER: DerivedLocalExecutor(wdi_search_adapter),
            wdi_indicators.PROVIDER: wdi_runtime.executor,
            biodiversity.PROVIDER: gbif_runtime.executor,
            wikimedia_metadata.PROVIDER: wikimedia_runtime.executor,
            github_repositories.PROVIDER: github_runtime.executor,
            geography.PROVIDER: DerivedLocalExecutor(geography_adapter),
            holidays.PROVIDER: DerivedLocalExecutor(holidays_adapter),
            wikidata_entities.PROVIDER: wikidata_runtime.executor,
            crossref_works.PROVIDER: crossref_runtime.executor,
            federated_web.PROVIDER: DerivedLocalExecutor(federated_adapter),
            general_tools.PROVIDER: DerivedLocalExecutor(general_adapter),
            calendar_mock.PROVIDER: calendar_executor,
        }

        fingerprint = EnvironmentFingerprint(
            cassette_manifest_hash=read_manifest_hash(cassette_root),
            snapshot_hashes={
                **dict(geography_adapter.snapshot_hashes),
                **dict(holidays_adapter.snapshot_hashes),
                **dict(wdi_search_adapter.snapshot_hashes),
                **dict(federated_adapter.snapshot_hashes),
            },
            mock_version=calendar_mock.VERSION,
            frozen_now=now,
            root_seed=root_seed,
            registry_hash=registry.content_hash(),
        )

        yield Environment(
            registry=registry,
            executors=executors,
            now=now,
            root_seed=root_seed,
            fingerprint=fingerprint,
            cassettes=tuple(runtime.transport for runtime in runtimes),
        )
    finally:
        for runtime in runtimes:
            runtime.close()


@contextmanager
def open_izmir_environment(
    *,
    repo_root: Path,
    mode: CassetteMode = CassetteMode.REPLAY,
    now: datetime = DEFAULT_FROZEN_NOW,
    root_seed: int = DEFAULT_ROOT_SEED,
    snapshot_dir: Path | None = None,
) -> Iterator[Environment]:
    """Geçmiş M1 testleri için İzmir araçlarını ayrı ve açıkça kurar."""
    cassette_root = repo_root / "data" / "cassettes"
    registry = build_izmir_registry()
    local_adapter = stops_provider.build_adapter(
        snapshot_dir or (repo_root / "data" / "snapshots" / "eshot_stops")
    )
    ckan_runtime = build_http_runtime(
        ckan.adapter,
        cassette_root=cassette_root,
        mode=mode,
    )
    eshot_runtime = build_http_runtime(
        eshot.adapter,
        cassette_root=cassette_root,
        mode=mode,
        max_entries=eshot.MAX_CASSETTES,
    )
    try:
        executors: dict[str, Executor] = {
            ckan.PROVIDER: ckan_runtime.executor,
            eshot.PROVIDER: eshot_runtime.executor,
            stops_provider.PROVIDER: DerivedLocalExecutor(local_adapter),
        }
        fingerprint = EnvironmentFingerprint(
            cassette_manifest_hash=read_manifest_hash(cassette_root),
            snapshot_hashes=dict(local_adapter.snapshot_hashes),
            frozen_now=now,
            root_seed=root_seed,
            registry_hash=registry.content_hash(),
        )
        yield Environment(
            registry=registry,
            executors=executors,
            now=now,
            root_seed=root_seed,
            fingerprint=fingerprint,
            cassettes=(ckan_runtime.transport, eshot_runtime.transport),
        )
    finally:
        eshot_runtime.close()
        ckan_runtime.close()
