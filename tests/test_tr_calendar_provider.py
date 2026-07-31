"""Türkiye resmî tatil snapshot sağlayıcısı."""

from __future__ import annotations

from pathlib import Path

from toolcall_tr.execution.local_executor import DerivedLocalExecutor
from toolcall_tr.models import StepOutcome
from toolcall_tr.providers.tr_calendar.holidays import (
    IS_PUBLIC_HOLIDAY,
    LIST_PUBLIC_HOLIDAYS,
    build_adapter,
)


def _executor(repo_root: Path) -> DerivedLocalExecutor:
    return DerivedLocalExecutor(
        build_adapter(repo_root / "data" / "snapshots" / "tr_public_holidays")
    )


def test_2026_tatil_listesi_yarim_gunleri_ayirir(repo_root: Path) -> None:
    executor = _executor(repo_root)
    all_days = executor.execute(
        LIST_PUBLIC_HOLIDAYS,
        {"year": 2026, "category": "all", "include_half_days": True},
    )
    full_days = executor.execute(
        LIST_PUBLIC_HOLIDAYS,
        {"year": 2026, "category": "all", "include_half_days": False},
    )
    assert all_days.outcome is StepOutcome.OK
    assert all_days.response["count"] == 17
    assert full_days.response["count"] == 14


def test_arefe_saate_gore_tatil_olur(repo_root: Path) -> None:
    executor = _executor(repo_root)
    morning = executor.execute(
        IS_PUBLIC_HOLIDAY,
        {"date": "2026-05-26", "at_time": "09:00"},
    )
    afternoon = executor.execute(
        IS_PUBLIC_HOLIDAY,
        {"date": "2026-05-26", "at_time": "14:00"},
    )
    assert morning.response["is_half_day"] is True
    assert morning.response["is_public_holiday"] is False
    assert afternoon.response["is_public_holiday"] is True


def test_normal_gun_tatil_degildir(repo_root: Path) -> None:
    result = _executor(repo_root).execute(
        IS_PUBLIC_HOLIDAY,
        {"date": "2026-07-29"},
    )
    assert result.outcome is StepOutcome.OK
    assert result.response["is_public_holiday"] is False
    assert result.response["name"] is None


def test_liste_semasi_enum_ve_boolean_tasir() -> None:
    parameters = {parameter.name: parameter for parameter in LIST_PUBLIC_HOLIDAYS.parameters}
    assert parameters["category"].enum == ["all", "national", "religious", "general"]
    assert parameters["include_half_days"].type == "boolean"
