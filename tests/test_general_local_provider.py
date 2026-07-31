"""Deterministik genel amaçlı yerel araçların sözleşmesi."""

from __future__ import annotations

from datetime import UTC, datetime

from toolcall_tr.execution.local_executor import DerivedLocalExecutor
from toolcall_tr.models import ExecutionClass, StepOutcome
from toolcall_tr.providers.general_local.tools import (
    CALCULATOR_EVALUATE,
    TIME_GET_LOCAL_TIME,
    build_adapter,
)

FROZEN_NOW = datetime(2026, 7, 28, 6, 0, tzinfo=UTC)


def test_calculator_guvenli_aritmetigi_hesaplar() -> None:
    executor = DerivedLocalExecutor(build_adapter(FROZEN_NOW))
    result = executor.execute(
        CALCULATOR_EVALUATE,
        {"expression": "(12.5 * 3) / 2", "precision": 2},
    )
    assert result.outcome is StepOutcome.OK
    assert result.execution_class is ExecutionClass.DERIVED_LOCAL
    assert result.response == {
        "expression": "(12.5 * 3) / 2",
        "result": 18.75,
        "precision": 2,
    }


def test_calculator_kod_calistirmayi_ve_sifira_bolmeyi_reddeder() -> None:
    executor = DerivedLocalExecutor(build_adapter(FROZEN_NOW))
    unsafe = executor.execute(CALCULATOR_EVALUATE, {"expression": "open('x')"})
    division_by_zero = executor.execute(CALCULATOR_EVALUATE, {"expression": "10 / 0"})
    assert unsafe.outcome is StepOutcome.UNEXPECTED_ERROR
    assert unsafe.status_code == 422
    assert division_by_zero.outcome is StepOutcome.UNEXPECTED_ERROR
    assert division_by_zero.status_code == 422


def test_local_time_gercek_saat_yerine_frozen_now_kullanir() -> None:
    executor = DerivedLocalExecutor(build_adapter(FROZEN_NOW))
    result = executor.execute(
        TIME_GET_LOCAL_TIME,
        {"timezone": "Europe/Istanbul"},
    )
    assert result.outcome is StepOutcome.OK
    assert result.response == {
        "timezone": "Europe/Istanbul",
        "local_time": "2026-07-28T09:00:00+03:00",
        "utc_offset": "+03:00",
        "is_dst": False,
        "frozen_utc_time": "2026-07-28T06:00:00+00:00",
    }


def test_local_time_boolean_false_utc_farkini_cikarir() -> None:
    executor = DerivedLocalExecutor(build_adapter(FROZEN_NOW))
    result = executor.execute(
        TIME_GET_LOCAL_TIME,
        {"timezone": "UTC", "include_utc_offset": False},
    )
    assert result.outcome is StepOutcome.OK
    assert "utc_offset" not in result.response


def test_genel_tool_semalari_enum_ve_boolean_cesitliligi_tasir() -> None:
    calculator_schema = CALCULATOR_EVALUATE.to_json_schema()
    time_schema = TIME_GET_LOCAL_TIME.to_json_schema()
    assert calculator_schema["properties"]["precision"]["enum"] == [0, 2, 4, 6]
    assert time_schema["properties"]["timezone"]["enum"] == [
        "UTC",
        "Europe/Istanbul",
        "Europe/London",
        "America/New_York",
        "Asia/Tokyo",
    ]
    assert time_schema["properties"]["include_utc_offset"]["type"] == "boolean"

