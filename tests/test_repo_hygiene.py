"""Depo hijyeni — ucuz ama pahalı hataları önleyen kontroller.

Buradaki testler kod davranışını değil, **geri alınması pahalı olan repo
kararlarını** korur: satır sonu politikası, lisans envanterinin kod ile tutarlı
kalması ve çözülmemiş lisans maddesinin sessizce kaybolmaması.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Satır sonu politikası
# ---------------------------------------------------------------------------


def test_gitattributes_cassette_kurali_var(repo_root: Path) -> None:
    """Cassette içerik hash'leri byte'a duyarlıdır.

    Bir katkıcının git'i cassette JSON'unu CRLF'e çevirirse MANIFEST.json'daki
    her hash değişir ve replay bozulur. Bu kural ilk cassette repoya inmeden
    ÖNCE var olmalıdır.
    """
    text = (repo_root / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in text
    assert "data/cassettes/**    -text" in text
    assert "data/snapshots/**    -text" in text


# ---------------------------------------------------------------------------
# Lisans dosyaları
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel_path",
    [
        "LICENSE",
        "LICENSE-DATA",
        "NOTICE.md",
        "legal/THIRD_PARTY_LICENSES.csv",
        "legal/DATA_SOURCES.md",
        "legal/CITATIONS.md",
    ],
)
def test_lisans_dosyasi_var_ve_bos_degil(repo_root: Path, rel_path: str) -> None:
    path = repo_root / rel_path
    assert path.is_file(), f"eksik: {rel_path}"
    assert path.stat().st_size > 0, f"boş: {rel_path}"


def test_ucuncu_taraf_envanteri_eksiksiz(legal_dir: Path) -> None:
    """Her bileşenin lisansı ve son doğrulama tarihi kayıtlı olmalı."""
    expected = {
        "component",
        "type",
        "source",
        "license",
        "usage",
        "commercial_allowed",
        "attribution",
        "last_checked",
    }
    with (legal_dir / "THIRD_PARTY_LICENSES.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    assert rows, "envanter boş"
    assert set(rows[0]) == expected

    for row in rows:
        assert row["license"], f"{row['component']}: lisans alanı boş"
        assert row["last_checked"], f"{row['component']}: son doğrulama tarihi yok"


def test_nc_lisansli_veri_setleri_disarida(legal_dir: Path) -> None:
    """CC BY-NC ve lisansı çelişkili kaynaklar `excluded_dataset` olarak işaretli olmalı."""
    with (legal_dir / "THIRD_PARTY_LICENSES.csv").open(encoding="utf-8", newline="") as fh:
        rows = {r["component"]: r for r in csv.DictReader(fh)}

    for name in ("apigen_mt_5k_dataset", "xlam_60k_dataset"):
        assert rows[name]["type"] == "excluded_dataset"
        assert rows[name]["commercial_allowed"] in {"no", "unknown"}


# ---------------------------------------------------------------------------
# Yapılandırma
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["project.yaml", "providers.yaml", "validation.yaml", "generation.yaml"],
)
def test_config_yaml_parse_edilebilir(configs_dir: Path, name: str) -> None:
    data = yaml.safe_load((configs_dir / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data


def test_pii_validator_kapatilamaz(configs_dir: Path) -> None:
    """PIIScanner asla devre dışı bırakılmamalı ve bloklayıcı olmalı."""
    cfg = yaml.safe_load((configs_dir / "validation.yaml").read_text(encoding="utf-8"))
    assert cfg["validators"]["pii"]["enabled"] is True
    assert "pii" in cfg["pipeline"]["blocking"]
    checks = cfg["validators"]["pii"]["checks"]
    assert checks["real_tckn_checksum"] is True
    assert checks["require_synthetic_tckn_prefix"] is True
    assert "cassettes" in cfg["validators"]["pii"]["scan_targets"]


def test_reddedilenler_saklaniyor(configs_dir: Path) -> None:
    """Başarısız örnekler sessizce silinmemeli."""
    cfg = yaml.safe_load((configs_dir / "validation.yaml").read_text(encoding="utf-8"))
    assert cfg["reporting"]["persist_rejected"] is True


def test_default_katalog_ve_holdout_profilleri_guncel(configs_dir: Path) -> None:
    project = yaml.safe_load(
        (configs_dir / "project.yaml").read_text(encoding="utf-8")
    )

    assert project["project"]["scope"] == "turkey_general"
    assert project["catalog"] == {
        "registered_tools": 35,
        "active_families": 74,
        "archived_blueprints": 8,
        "archived_scope": "izmir",
    }
    split = project["split"]
    assert split["default_holdout_profile"] == "standard"
    assert split["holdout_profiles"]["unseen_tool"]["tool_disjoint"] is True
    assert (
        split["holdout_profiles"]["unseen_provider"]["provider_disjoint"] is True
    )


def test_yerel_ve_stateful_provider_configleri_etkin(configs_dir: Path) -> None:
    providers = yaml.safe_load(
        (configs_dir / "providers.yaml").read_text(encoding="utf-8")
    )["providers"]
    validation = yaml.safe_load(
        (configs_dir / "validation.yaml").read_text(encoding="utf-8")
    )

    assert providers["general_local"]["enabled"] is True
    assert providers["general_local"]["execution_class"] == "derived_local"
    assert providers["calendar_mock"]["enabled"] is True
    assert providers["calendar_mock"]["stateful"] is True
    assert providers["calendar_mock"]["state_validation"] is True
    assert validation["validators"]["state"] == {
        "enabled": True,
        "implemented_by": "execution",
        "applies_to": ["calendar_mock"],
        "description": (
            "Stateful takvim mock çağrılarında initial/final state hash, "
            "state_delta ve assertion kontrolü. Salt-okunur sağlayıcılarda "
            "state alanı null kalır."
        ),
    }


# ---------------------------------------------------------------------------
# Çözülmemiş lisans maddesi — sessizce kaybolmamalı
# ---------------------------------------------------------------------------


def test_realtime_lisans_maddesi_tutarli(repo_root: Path, configs_dir: Path) -> None:
    """`openapi.izmir.bel.tr` lisans belirsizliği her yerde aynı işaretlenmeli.

    CC BY 4.0 teyidi yalnızca `acikveri.bizizmir.com` içindir. Gerçek zamanlı
    host ayrıdır ve beyan edilmiş lisansı yoktur. Bu madde çözülene dek
    işaretin üç yerde birden tutarlı kalması gerekir; biri düzeltilip diğerleri
    unutulursa bu test kırılır.
    """
    providers = yaml.safe_load((configs_dir / "providers.yaml").read_text(encoding="utf-8"))
    realtime = providers["providers"]["izmir_realtime"]

    assert realtime["license"] == "UNDETERMINED"
    assert realtime["unresolved_license"] is True
    # Kayıt sayısı sınırlı tutulur: lisans belirsizken toplu dağıtım riski.
    assert realtime["max_cassettes"] <= 100

    # Doğrulanmış CC BY 4.0 sağlayıcısı ile karıştırılmamalı.
    assert providers["providers"]["izmir_ckan"]["license"] == "CC-BY-4.0"

    assert "UNDETERMINED" in (repo_root / "LICENSE-DATA").read_text(encoding="utf-8")

    with (repo_root / "legal" / "THIRD_PARTY_LICENSES.csv").open(
        encoding="utf-8", newline=""
    ) as fh:
        rows = {r["component"]: r for r in csv.DictReader(fh)}
    assert rows["izmir_iztek_realtime"]["license"] == "UNDETERMINED"


def test_ticari_karisim_belirsiz_lisansi_disliyor(repo_root: Path) -> None:
    mixture = yaml.safe_load(
        (repo_root / "mixtures" / "commercial_safe.yaml").read_text(encoding="utf-8")
    )
    excluded_providers = {e.get("provider") for e in mixture["exclude"]}
    assert "izmir_realtime" in excluded_providers

    included_providers = {p for inc in mixture["include"] for p in inc["provider_filter"]}
    assert "izmir_realtime" not in included_providers


# ---------------------------------------------------------------------------
# Determinizm yapılandırması
# ---------------------------------------------------------------------------


def test_donmus_saat_tanimli(configs_dir: Path) -> None:
    """Göreli tarih ifadeleri bu ana göre çözülür; tanımsızsa hash'ler kayar."""
    cfg = yaml.safe_load((configs_dir / "project.yaml").read_text(encoding="utf-8"))
    determinism = cfg["determinism"]
    assert determinism["frozen_now"]
    assert determinism["timezone"] == "Europe/Istanbul"
    assert isinstance(determinism["root_seed"], int)


def test_split_oranlari_toplami_bir(configs_dir: Path) -> None:
    cfg = yaml.safe_load((configs_dir / "project.yaml").read_text(encoding="utf-8"))["split"]
    total = cfg["train_ratio"] + cfg["validation_ratio"] + cfg["test_ratio"]
    assert total == pytest.approx(1.0)
