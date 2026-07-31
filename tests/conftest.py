"""Ortak test fixture'ları."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Depo kökü (tests/ dizininin bir üstü)."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def configs_dir(repo_root: Path) -> Path:
    return repo_root / "configs"


@pytest.fixture(scope="session")
def legal_dir(repo_root: Path) -> Path:
    return repo_root / "legal"
