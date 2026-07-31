"""Gerçek kişi veya servisle ilişkisi olmayan sentetik takvim şemaları."""

from __future__ import annotations

from typing import Any

from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec

PROVIDER = "calendar_mock"
VERSION = "calendar_mock/1.0.0"
LICENSE = "Apache-2.0"
ATTRIBUTION = "ToolCall-TR katkıcıları; tamamen kurgusal takvim verisi ve servisi"

CALENDAR_IDS = ("personal", "work", "team")
TIMEZONES = (
    "UTC",
    "Europe/Istanbul",
    "Europe/London",
    "America/New_York",
    "Asia/Tokyo",
)

_SOURCE = ToolSource(
    schema_type="manual",
    schema_version=VERSION,
    upstream_url="https://calendar-api.toolcall-tr.test",
    license=LICENSE,
    attribution=ATTRIBUTION,
)

INITIAL_EVENTS: dict[str, dict[str, Any]] = {
    "EVT-2026-0001": {
        "event_id": "EVT-2026-0001",
        "calendar_id": "work",
        "title": "Ürün planlama toplantısı",
        "description": "Tamamen sentetik pilot takvim kaydı.",
        "start_at": "2026-07-29T10:00:00+03:00",
        "end_at": "2026-07-29T10:45:00+03:00",
        "timezone": "Europe/Istanbul",
        "attendee_emails": [
            "katilimci1@calendar.test",
            "katilimci2@calendar.test",
        ],
        "reminders_minutes": [10],
        "visibility": "private",
        "send_updates": False,
        "status": "confirmed",
        "location": "https://meet.calendar.test/urun-planlama",
    },
    "EVT-2026-0002": {
        "event_id": "EVT-2026-0002",
        "calendar_id": "personal",
        "title": "Odak zamanı",
        "description": "Tamamen sentetik kişisel takvim kaydı.",
        "start_at": "2026-07-30T14:00:00+03:00",
        "end_at": "2026-07-30T15:00:00+03:00",
        "timezone": "Europe/Istanbul",
        "attendee_emails": [],
        "reminders_minutes": [5],
        "visibility": "private",
        "send_updates": False,
        "status": "confirmed",
        "location": "https://calendar.test/locations/focus-room",
    },
}

_EVENT_OUTPUTS = (
    OutputField(
        path="event.event_id",
        type="string",
        description_tr="Sentetik etkinlik kimliği.",
        semantic_type="event_id",
    ),
    OutputField(
        path="event.calendar_id",
        type="string",
        description_tr="Etkinliğin sentetik takvim kimliği.",
        semantic_type="calendar_id",
    ),
    OutputField(path="event.title", type="string", description_tr="Etkinlik başlığı."),
    OutputField(
        path="event.start_at",
        type="string",
        description_tr="ISO 8601 başlangıç zamanı.",
        semantic_type="datetime",
    ),
    OutputField(
        path="event.end_at",
        type="string",
        description_tr="ISO 8601 bitiş zamanı.",
        semantic_type="datetime",
    ),
    OutputField(
        path="event.timezone",
        type="string",
        description_tr="Etkinliğin IANA saat dilimi.",
        semantic_type="timezone",
    ),
    OutputField(path="event.status", type="string", description_tr="Etkinliğin durumu."),
    OutputField(
        path="event.attendee_emails",
        type="array",
        description_tr="Yalnızca .test alan adındaki sentetik katılımcılar.",
    ),
    OutputField(
        path="event.reminders_minutes",
        type="array",
        description_tr="Dakika cinsinden hatırlatıcılar.",
    ),
    OutputField(
        path="event.visibility",
        type="string",
        description_tr="Etkinliğin görünürlük düzeyi.",
    ),
    OutputField(
        path="event.send_updates",
        type="boolean",
        description_tr="Sentetik katılımcı güncelleme seçeneği.",
    ),
)

SEARCH_EVENTS = ToolSpec(
    tool_id="calendar.search_events",
    provider=PROVIDER,
    name="search_events",
    description_tr=(
        "Sentetik takvim durumunda tarih aralığı, takvim ve isteğe bağlı başlık "
        "metnine göre etkinlik arar."
    ),
    parameters=(
        ParamSpec(
            name="start_at",
            type="string",
            description_tr="Arama aralığının timezone-aware ISO 8601 başlangıcı.",
            required=True,
            semantic_type="datetime",
        ),
        ParamSpec(
            name="end_at",
            type="string",
            description_tr="Arama aralığının timezone-aware ISO 8601 bitişi.",
            required=True,
            semantic_type="datetime",
        ),
        ParamSpec(
            name="calendar_ids",
            type="array",
            item_type="string",
            description_tr="Aranacak sentetik takvim kimlikleri.",
            min_items=1,
            max_items=3,
            has_default=True,
            default=list(CALENDAR_IDS),
            semantic_type="calendar_id",
        ),
        ParamSpec(
            name="query",
            type="string",
            description_tr="Başlıkta aranacak metin.",
            min_length=0,
            max_length=120,
            has_default=True,
            default="",
        ),
        ParamSpec(
            name="include_cancelled",
            type="boolean",
            description_tr="İptal edilmiş etkinliklerin de döndürülüp döndürülmeyeceği.",
            has_default=True,
            default=False,
        ),
    ),
    outputs=(
        OutputField(
            path="count",
            type="integer",
            description_tr="Eşleşen etkinlik sayısı.",
            semantic_type="result_count",
        ),
        OutputField(
            path="events[*].event_id",
            type="string",
            description_tr="Sentetik etkinlik kimliği.",
            semantic_type="event_id",
        ),
        OutputField(
            path="events[*].calendar_id",
            type="string",
            description_tr="Sentetik takvim kimliği.",
            semantic_type="calendar_id",
        ),
        OutputField(path="events[*].title", type="string", description_tr="Etkinlik başlığı."),
        OutputField(
            path="events[*].start_at",
            type="string",
            description_tr="ISO 8601 başlangıç zamanı.",
            semantic_type="datetime",
        ),
        OutputField(
            path="events[*].end_at",
            type="string",
            description_tr="ISO 8601 bitiş zamanı.",
            semantic_type="datetime",
        ),
        OutputField(
            path="events[*].timezone",
            type="string",
            description_tr="IANA saat dilimi.",
            semantic_type="timezone",
        ),
        OutputField(
            path="events[*].status",
            type="string",
            description_tr="Etkinlik durumu.",
        ),
        OutputField(
            path="events[*].attendee_emails",
            type="array",
            description_tr="Sentetik katılımcı adresleri.",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.SIMULATED,
    allow_empty_result=True,
    source=_SOURCE,
)

CREATE_EVENT = ToolSpec(
    tool_id="calendar.create_event",
    provider=PROVIDER,
    name="create_event",
    description_tr=(
        "Açık kullanıcı onayından sonra episode-izole sentetik takvimde etkinlik oluşturur."
    ),
    parameters=(
        ParamSpec(
            name="calendar_id",
            type="string",
            description_tr="Hedef sentetik takvim.",
            required=True,
            enum=list(CALENDAR_IDS),
            semantic_type="calendar_id",
        ),
        ParamSpec(
            name="title",
            type="string",
            description_tr="Etkinlik başlığı.",
            required=True,
            min_length=2,
            max_length=120,
        ),
        ParamSpec(
            name="start_at",
            type="string",
            description_tr="Timezone-aware ISO 8601 başlangıç zamanı.",
            required=True,
            semantic_type="datetime",
        ),
        ParamSpec(
            name="end_at",
            type="string",
            description_tr="Timezone-aware ISO 8601 bitiş zamanı.",
            required=True,
            semantic_type="datetime",
        ),
        ParamSpec(
            name="timezone",
            type="string",
            description_tr="Etkinliğin desteklenen IANA saat dilimi.",
            required=True,
            enum=list(TIMEZONES),
            semantic_type="timezone",
        ),
        ParamSpec(
            name="attendee_emails",
            type="array",
            item_type="string",
            description_tr="Yalnızca .test alan adındaki sentetik katılımcılar.",
            max_items=20,
            has_default=True,
            default=[],
        ),
        ParamSpec(
            name="reminders_minutes",
            type="array",
            item_type="integer",
            description_tr="0-10080 aralığındaki dakika cinsinden hatırlatıcılar.",
            max_items=5,
            has_default=True,
            default=[],
        ),
        ParamSpec(
            name="visibility",
            type="string",
            description_tr="Etkinliğin görünürlük düzeyi.",
            enum=["default", "private", "public"],
            has_default=True,
            default="default",
        ),
        ParamSpec(
            name="send_updates",
            type="boolean",
            description_tr="Sentetik katılımcı güncellemelerinin işaretlenmesi.",
            has_default=True,
            default=False,
        ),
        ParamSpec(
            name="confirmed",
            type="boolean",
            description_tr="Kullanıcının açık işlem onayı.",
            required=True,
        ),
    ),
    outputs=_EVENT_OUTPUTS,
    side_effect=SideEffect.CREATE,
    execution_class=ExecutionClass.SIMULATED,
    confirmation_required=True,
    source=_SOURCE,
)

CANCEL_EVENT = ToolSpec(
    tool_id="calendar.cancel_event",
    provider=PROVIDER,
    name="cancel_event",
    description_tr=(
        "Açık kullanıcı onayından sonra sentetik bir etkinliği iptal edilmiş olarak işaretler."
    ),
    parameters=(
        ParamSpec(
            name="event_id",
            type="string",
            description_tr="İptal edilecek sentetik etkinlik kimliği.",
            required=True,
            pattern=r"^EVT-2026-[0-9]{4}$",
            semantic_type="event_id",
        ),
        ParamSpec(
            name="cancellation_reason",
            type="string",
            description_tr="Sentetik iptal nedeni.",
            min_length=2,
            max_length=200,
            has_default=True,
            default="Kullanıcı talebi",
        ),
        ParamSpec(
            name="notify_attendees",
            type="boolean",
            description_tr="Sentetik katılımcı bildiriminin işaretlenmesi.",
            has_default=True,
            default=False,
        ),
        ParamSpec(
            name="confirmed",
            type="boolean",
            description_tr="Kullanıcının açık işlem onayı.",
            required=True,
        ),
    ),
    outputs=(
        OutputField(
            path="cancelled",
            type="boolean",
            description_tr="İptal işleminin başarı durumu.",
        ),
        OutputField(
            path="event.event_id",
            type="string",
            description_tr="İptal edilen sentetik etkinlik kimliği.",
            semantic_type="event_id",
        ),
        OutputField(
            path="event.status",
            type="string",
            description_tr="Etkinliğin yeni durumu.",
        ),
        OutputField(
            path="event.cancellation_reason",
            type="string",
            description_tr="Kaydedilen sentetik iptal nedeni.",
        ),
        OutputField(
            path="event.notify_attendees",
            type="boolean",
            description_tr="Sentetik bildirim seçeneği.",
        ),
    ),
    side_effect=SideEffect.UPDATE,
    execution_class=ExecutionClass.SIMULATED,
    confirmation_required=True,
    source=_SOURCE,
)

TOOLS: tuple[ToolSpec, ...] = (SEARCH_EVENTS, CREATE_EVENT, CANCEL_EVENT)
