"""Episode-izole, tamamen sentetik takvim mock executor'ı."""

from __future__ import annotations

import copy
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from toolcall_tr.canonical import sha256_of
from toolcall_tr.execution.executor import ExecutionResult
from toolcall_tr.models import ExecutionClass, StateDelta, StateOp, StateOpKind, StepOutcome
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.calendar_mock.events import (
    CALENDAR_IDS,
    CANCEL_EVENT,
    CREATE_EVENT,
    INITIAL_EVENTS,
    SEARCH_EVENTS,
)
from toolcall_tr.schema import ArgumentError, normalize_arguments, validate_arguments

__all__ = ["StatefulCalendarExecutor"]


class _CalendarError(ValueError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class StatefulCalendarExecutor:
    """Her episode başında aynı sentetik fixture'a dönen takvim yürütücüsü."""

    def __init__(self, *, now: datetime) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("calendar_mock için saat timezone-aware olmalıdır")
        self._now = now.astimezone(UTC)
        self._state: dict[str, dict[str, Any]] = {}
        self._ops: list[StateOp] = []
        self._create_counter = 0
        self.begin_episode(0)

    def begin_episode(self, seed: int) -> None:
        del seed
        self._state = copy.deepcopy(INITIAL_EVENTS)
        self._ops = []
        self._create_counter = 0

    def state_delta(self) -> StateDelta:
        return StateDelta(
            ops=tuple(self._ops),
            volatile_fields=("created_at", "cancelled_at"),
        )

    def state_hash(self) -> str:
        return sha256_of(self._state)

    def execute(self, tool: ToolSpec, arguments: Mapping[str, Any]) -> ExecutionResult:
        started = time.perf_counter()
        if tool.tool_id not in {item.tool_id for item in (SEARCH_EVENTS, CREATE_EVENT, CANCEL_EVENT)}:
            return self._result(
                tool,
                dict(arguments),
                StepOutcome.PLAN_ERROR,
                started,
                error=f"calendar_mock sağlayıcısında tanımsız tool: {tool.tool_id}",
            )

        normalized = normalize_arguments(tool, arguments)
        errors = validate_arguments(tool, normalized)
        if errors:
            return self._result(
                tool,
                normalized,
                StepOutcome.PLAN_ERROR,
                started,
                error=str(ArgumentError(tool.tool_id, errors)),
            )

        before = self.state_hash()
        if tool.confirmation_required and normalized.get("confirmed") is not True:
            return self._result(
                tool,
                normalized,
                StepOutcome.UNEXPECTED_ERROR,
                started,
                error="Açık kullanıcı onayı gerekli",
                status_code=409,
                before=before,
                after=before,
            )

        try:
            response = self._dispatch(tool.tool_id, normalized)
        except _CalendarError as exc:
            return self._result(
                tool,
                normalized,
                StepOutcome.UNEXPECTED_ERROR,
                started,
                error=str(exc),
                status_code=exc.status_code,
                before=before,
                after=before,
            )

        return self._result(
            tool,
            normalized,
            StepOutcome.OK,
            started,
            response=response,
            before=before,
            after=self.state_hash(),
        )

    def _dispatch(self, tool_id: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if tool_id == SEARCH_EVENTS.tool_id:
            return self._search(arguments)
        if tool_id == CREATE_EVENT.tool_id:
            return self._create(arguments)
        if tool_id == CANCEL_EVENT.tool_id:
            return self._cancel(arguments)
        raise _CalendarError(f"Tanımsız mock tool: {tool_id}", 422)

    def _search(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        start_at = _parse_aware_datetime(str(arguments["start_at"]), "start_at")
        end_at = _parse_aware_datetime(str(arguments["end_at"]), "end_at")
        if start_at >= end_at:
            raise _CalendarError("end_at, start_at değerinden sonra olmalıdır", 422)

        calendar_ids = _string_array(arguments["calendar_ids"], "calendar_ids")
        unknown = sorted(set(calendar_ids) - set(CALENDAR_IDS))
        if unknown:
            raise _CalendarError(
                f"Desteklenmeyen sentetik takvim kimliği: {', '.join(unknown)}",
                422,
            )
        query = str(arguments["query"]).casefold().strip()
        include_cancelled = bool(arguments["include_cancelled"])

        events: list[dict[str, Any]] = []
        for event in self._state.values():
            event_start = _parse_aware_datetime(str(event["start_at"]), "event.start_at")
            event_end = _parse_aware_datetime(str(event["end_at"]), "event.end_at")
            if event["calendar_id"] not in calendar_ids:
                continue
            if event_end <= start_at or event_start >= end_at:
                continue
            if not include_cancelled and event["status"] == "cancelled":
                continue
            if query and query not in str(event["title"]).casefold():
                continue
            events.append(copy.deepcopy(event))
        events.sort(key=lambda event: (str(event["start_at"]), str(event["event_id"])))
        return {"count": len(events), "events": events}

    def _create(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        timezone_name = str(arguments["timezone"])
        timezone = ZoneInfo(timezone_name)
        start_at = _parse_aware_datetime(str(arguments["start_at"]), "start_at")
        end_at = _parse_aware_datetime(str(arguments["end_at"]), "end_at")
        if start_at >= end_at:
            raise _CalendarError("end_at, start_at değerinden sonra olmalıdır", 422)

        attendee_emails = _string_array(arguments["attendee_emails"], "attendee_emails")
        invalid_emails = [email for email in attendee_emails if not _is_test_email(email)]
        if invalid_emails:
            raise _CalendarError(
                "Katılımcı adresleri yalnızca ayrılmış .test alan adını kullanmalıdır",
                422,
            )
        reminders = _integer_array(arguments["reminders_minutes"], "reminders_minutes")
        if any(value < 0 or value > 10_080 for value in reminders):
            raise _CalendarError("Hatırlatıcılar 0-10080 dakika aralığında olmalıdır", 422)

        self._create_counter += 1
        event_id = f"EVT-2026-{1000 + self._create_counter:04d}"
        event: dict[str, Any] = {
            "event_id": event_id,
            "calendar_id": str(arguments["calendar_id"]),
            "title": str(arguments["title"]),
            "start_at": start_at.astimezone(timezone).isoformat(timespec="seconds"),
            "end_at": end_at.astimezone(timezone).isoformat(timespec="seconds"),
            "timezone": timezone_name,
            "attendee_emails": attendee_emails,
            "reminders_minutes": reminders,
            "visibility": str(arguments["visibility"]),
            "send_updates": bool(arguments["send_updates"]),
            "status": "confirmed",
            "created_at": self._now.isoformat(timespec="seconds"),
        }
        self._state[event_id] = event
        self._ops.append(
            StateOp(
                op=StateOpKind.CREATE,
                entity="calendar_event",
                entity_id=f"#{self._create_counter}",
                fields=copy.deepcopy(event),
            )
        )
        return {"event": copy.deepcopy(event)}

    def _cancel(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        event_id = str(arguments["event_id"])
        event = self._state.get(event_id)
        if event is None:
            raise _CalendarError("Etkinlik bulunamadı", 404)
        if event["status"] == "cancelled":
            raise _CalendarError("Etkinlik zaten iptal edilmiş", 409)

        reason = str(arguments["cancellation_reason"])
        notify_attendees = bool(arguments["notify_attendees"])
        event["status"] = "cancelled"
        event["cancellation_reason"] = reason
        event["notify_attendees"] = notify_attendees
        event["cancelled_at"] = self._now.isoformat(timespec="seconds")
        self._ops.append(
            StateOp(
                op=StateOpKind.UPDATE,
                entity="calendar_event",
                entity_id=event_id,
                fields={
                    "status": "cancelled",
                    "cancellation_reason": reason,
                    "notify_attendees": notify_attendees,
                    "cancelled_at": event["cancelled_at"],
                },
            )
        )
        return {"cancelled": True, "event": copy.deepcopy(event)}

    def _result(
        self,
        tool: ToolSpec,
        arguments: dict[str, Any],
        outcome: StepOutcome,
        started: float,
        *,
        response: Any = None,
        error: str | None = None,
        status_code: int | None = None,
        before: str | None = None,
        after: str | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            tool_id=tool.tool_id,
            execution_class=ExecutionClass.SIMULATED,
            arguments=arguments,
            outcome=outcome,
            status_code=status_code,
            response=response,
            error=error,
            latency_ms=(time.perf_counter() - started) * 1000,
            state_hash_before=before,
            state_hash_after=after,
        )


def _parse_aware_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _CalendarError(f"{field_name} geçerli ISO 8601 olmalıdır", 422) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _CalendarError(f"{field_name} UTC farkı içermelidir", 422)
    return parsed


def _string_array(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise _CalendarError(f"{field_name} bir dizi olmalıdır", 422)
    if any(not isinstance(item, str) for item in value):
        raise _CalendarError(f"{field_name} yalnızca metin değerleri içermelidir", 422)
    return list(value)


def _integer_array(value: Any, field_name: str) -> list[int]:
    if not isinstance(value, list):
        raise _CalendarError(f"{field_name} bir dizi olmalıdır", 422)
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise _CalendarError(f"{field_name} yalnızca tam sayılar içermelidir", 422)
    return list(value)


def _is_test_email(value: str) -> bool:
    if value != value.strip() or value.count("@") != 1:
        return False
    local, domain = value.rsplit("@", 1)
    return bool(local) and domain.casefold().endswith(".test")

