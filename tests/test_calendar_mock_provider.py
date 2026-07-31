"""Episode-izole sentetik takvim sağlayıcısının davranış testleri."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from toolcall_tr.execution.calendar_mock import StatefulCalendarExecutor
from toolcall_tr.models import StateOpKind, StepOutcome
from toolcall_tr.pipeline.environment import build_default_registry, open_default_environment
from toolcall_tr.providers.calendar_mock.events import (
    CANCEL_EVENT,
    CREATE_EVENT,
    INITIAL_EVENTS,
    PROVIDER,
    SEARCH_EVENTS,
)
from toolcall_tr.providers.general_local.tools import PROVIDER as GENERAL_PROVIDER

FROZEN_NOW = datetime(2026, 7, 28, 6, 0, tzinfo=UTC)


def _create_arguments(*, confirmed: bool = True) -> dict[str, object]:
    return {
        "calendar_id": "team",
        "title": "Sentetik tasarım değerlendirmesi",
        "start_at": "2026-07-31T11:00:00+03:00",
        "end_at": "2026-07-31T11:45:00+03:00",
        "timezone": "Europe/Istanbul",
        "attendee_emails": ["tasarimci@calendar.test"],
        "reminders_minutes": [10, 30],
        "visibility": "private",
        "send_updates": True,
        "confirmed": confirmed,
    }


def test_search_fixture_event_id_dondurulmus_sonucla_doner() -> None:
    executor = StatefulCalendarExecutor(now=FROZEN_NOW)
    result = executor.execute(
        SEARCH_EVENTS,
        {
            "start_at": "2026-07-29T00:00:00+03:00",
            "end_at": "2026-07-30T00:00:00+03:00",
            "calendar_ids": ["work"],
            "query": "planlama",
        },
    )
    assert result.outcome is StepOutcome.OK
    assert result.response["count"] == 1
    assert result.response["events"][0]["event_id"] == "EVT-2026-0001"
    assert result.state_hash_before == result.state_hash_after


def test_create_sonraki_search_ayni_episode_stateini_okur() -> None:
    executor = StatefulCalendarExecutor(now=FROZEN_NOW)
    created = executor.execute(CREATE_EVENT, _create_arguments())
    searched = executor.execute(
        SEARCH_EVENTS,
        {
            "start_at": "2026-07-31T00:00:00+03:00",
            "end_at": "2026-08-01T00:00:00+03:00",
            "calendar_ids": ["team"],
        },
    )
    assert created.outcome is StepOutcome.OK
    assert created.response["event"]["event_id"] == "EVT-2026-1001"
    assert searched.response["events"][0]["event_id"] == "EVT-2026-1001"
    assert executor.state_delta().ops[0].op is StateOpKind.CREATE
    assert executor.state_delta().ops[0].entity_id == "#1"


def test_cancel_onay_ve_hata_durumlari_statei_korur() -> None:
    executor = StatefulCalendarExecutor(now=FROZEN_NOW)
    before = executor.state_hash()
    unconfirmed = executor.execute(
        CANCEL_EVENT,
        {"event_id": "EVT-2026-0001", "confirmed": False},
    )
    missing = executor.execute(
        CANCEL_EVENT,
        {"event_id": "EVT-2026-9999", "confirmed": True},
    )
    assert unconfirmed.status_code == 409
    assert missing.status_code == 404
    assert executor.state_hash() == before
    assert executor.state_delta().is_empty


def test_cancel_eventi_gunceller_ve_episode_reset_fixturea_doner() -> None:
    executor = StatefulCalendarExecutor(now=FROZEN_NOW)
    cancelled = executor.execute(
        CANCEL_EVENT,
        {
            "event_id": "EVT-2026-0001",
            "cancellation_reason": "Sentetik program değişikliği",
            "notify_attendees": True,
            "confirmed": True,
        },
    )
    assert cancelled.outcome is StepOutcome.OK
    assert cancelled.response["event"]["status"] == "cancelled"
    assert executor.state_delta().ops[0].op is StateOpKind.UPDATE
    executor.begin_episode(123)
    searched = executor.execute(
        SEARCH_EVENTS,
        {
            "start_at": "2026-07-29T00:00:00+03:00",
            "end_at": "2026-07-30T00:00:00+03:00",
            "calendar_ids": ["work"],
        },
    )
    assert searched.response["count"] == 1
    assert searched.response["events"][0]["status"] == "confirmed"
    assert executor.state_delta().is_empty


def test_create_test_disindaki_epostayi_reddeder() -> None:
    executor = StatefulCalendarExecutor(now=FROZEN_NOW)
    arguments = _create_arguments()
    arguments["attendee_emails"] = ["gercek@example.com"]
    result = executor.execute(CREATE_EVENT, arguments)
    assert result.outcome is StepOutcome.UNEXPECTED_ERROR
    assert result.status_code == 422
    assert executor.state_delta().is_empty


def test_fixturelar_gercek_pii_ve_dis_servis_referansi_tasimaz() -> None:
    for event in INITIAL_EVENTS.values():
        assert all(str(email).endswith(".test") for email in event["attendee_emails"])
        assert str(event["location"]).split("/", 3)[2].endswith(".test")
    assert SEARCH_EVENTS.source.upstream_url is not None
    assert SEARCH_EVENTS.source.upstream_url.split("/", 3)[2].endswith(".test")


def test_calendar_semalari_array_enum_boolean_ve_onay_kapisi_tasir() -> None:
    search_schema = SEARCH_EVENTS.to_json_schema()
    create_schema = CREATE_EVENT.to_json_schema()
    assert search_schema["properties"]["calendar_ids"]["items"] == {"type": "string"}
    assert create_schema["properties"]["calendar_id"]["enum"] == [
        "personal",
        "work",
        "team",
    ]
    assert create_schema["properties"]["reminders_minutes"]["items"] == {"type": "integer"}
    assert create_schema["properties"]["send_updates"]["type"] == "boolean"
    assert CREATE_EVENT.confirmation_required
    assert CANCEL_EVENT.confirmation_required


def test_default_environment_registry_ve_executorlari_kablolar(repo_root: Path) -> None:
    registry = build_default_registry()
    assert registry.require("calendar.search_events").provider == PROVIDER
    assert registry.require("calculator.evaluate").provider == GENERAL_PROVIDER
    assert registry.require("time.get_local_time").provider == GENERAL_PROVIDER

    with open_default_environment(repo_root=repo_root) as environment:
        calendar_result = environment.executor_for(PROVIDER).execute(
            SEARCH_EVENTS,
            {
                "start_at": "2026-07-29T00:00:00+03:00",
                "end_at": "2026-07-30T00:00:00+03:00",
            },
        )
        time_result = environment.executor_for(GENERAL_PROVIDER).execute(
            registry.require("time.get_local_time"),
            {"timezone": "Europe/Istanbul"},
        )
        assert calendar_result.outcome is StepOutcome.OK
        assert time_result.response["local_time"] == "2026-07-28T09:00:00+03:00"
        assert environment.fingerprint.mock_version is not None
        assert "calendar_mock/1.0.0" in environment.fingerprint.mock_version

