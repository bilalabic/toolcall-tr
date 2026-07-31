"""Türkiye'nin sürümlenmiş resmî tatil metadata'sı üzerinde yerel araçlar."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, time
from pathlib import Path
from typing import Any

from toolcall_tr.canonical import sha256_hex
from toolcall_tr.models import ExecutionClass, OutputField, ParamSpec, SideEffect, ToolSource
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.base import (
    LocalProviderAdapter,
    LocalToolBinding,
    ToolExecutionError,
)

__all__ = [
    "IS_PUBLIC_HOLIDAY",
    "LIST_PUBLIC_HOLIDAYS",
    "PROVIDER",
    "TOOLS",
    "build_adapter",
]

PROVIDER = "tr_public_holidays"
LICENSE = "PUBLIC-LAW-AND-OFFICIAL-CALENDAR-METADATA"
ATTRIBUTION = (
    "Türkiye Cumhuriyeti mevzuatı ve Diyanet İşleri Başkanlığı "
    "2026 dinî günler listesi"
)

_SOURCE = ToolSource(
    schema_type="snapshot",
    schema_version="tr_public_holidays/2026-v1",
    upstream_url="https://vakithesaplama.diyanet.gov.tr/icerik.php?icerik=153",
    license=LICENSE,
    attribution=ATTRIBUTION,
)

LIST_PUBLIC_HOLIDAYS = ToolSpec(
    tool_id="calendar.list_public_holidays",
    provider=PROVIDER,
    name="list_public_holidays",
    description_tr="Türkiye'nin desteklenen yıldaki resmî tatillerini listeler.",
    parameters=(
        ParamSpec(
            name="year",
            type="integer",
            description_tr="Takvim yılı; bu snapshot yalnızca 2026 yılını destekler.",
            required=True,
            minimum=2026,
            maximum=2026,
        ),
        ParamSpec(
            name="category",
            type="string",
            description_tr="İsteğe bağlı tatil kategorisi.",
            enum=["all", "national", "religious", "general"],
            has_default=True,
            default="all",
        ),
        ParamSpec(
            name="include_half_days",
            type="boolean",
            description_tr="Yarım gün tatilleri sonuçlara dâhil et.",
            has_default=True,
            default=True,
        ),
    ),
    outputs=(
        OutputField(
            path="count",
            type="integer",
            description_tr="Dönen tatil günü sayısı.",
            semantic_type="result_count",
        ),
        OutputField(
            path="holidays[*].date",
            type="string",
            description_tr="ISO 8601 takvim tarihi.",
            semantic_type="date",
        ),
        OutputField(
            path="holidays[*].name",
            type="string",
            description_tr="Tatil adı.",
        ),
        OutputField(
            path="holidays[*].duration",
            type="string",
            description_tr="Tam veya yarım gün bilgisi.",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.DERIVED_LOCAL,
    allow_empty_result=True,
    source=_SOURCE,
)

IS_PUBLIC_HOLIDAY = ToolSpec(
    tool_id="calendar.is_public_holiday",
    provider=PROVIDER,
    name="is_public_holiday",
    description_tr=(
        "Türkiye'de belirli bir tarih ve isteğe bağlı saat için resmî tatil "
        "durumunu kontrol eder."
    ),
    parameters=(
        ParamSpec(
            name="date",
            type="string",
            description_tr="YYYY-MM-DD biçiminde 2026 tarihi.",
            required=True,
            semantic_type="date",
            pattern=r"^2026-[0-9]{2}-[0-9]{2}$",
            min_length=10,
            max_length=10,
        ),
        ParamSpec(
            name="at_time",
            type="string",
            description_tr="Yarım gün denetimi için HH:MM biçiminde yerel saat.",
            required=False,
            semantic_type="time",
            pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$",
            min_length=5,
            max_length=5,
        ),
    ),
    outputs=(
        OutputField(
            path="date",
            type="string",
            description_tr="Kontrol edilen tarih.",
            semantic_type="date",
        ),
        OutputField(
            path="is_public_holiday",
            type="boolean",
            description_tr="Verilen anda resmî tatil olup olmadığı.",
        ),
        OutputField(
            path="is_half_day",
            type="boolean",
            description_tr="Tarihin yarım gün tatil olup olmadığı.",
        ),
        OutputField(
            path="name",
            type="string",
            description_tr="Varsa tatil adı.",
        ),
    ),
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.DERIVED_LOCAL,
    source=_SOURCE,
)

TOOLS: tuple[ToolSpec, ...] = (LIST_PUBLIC_HOLIDAYS, IS_PUBLIC_HOLIDAY)


def build_adapter(snapshot_dir: Path) -> LocalProviderAdapter:
    data_path = snapshot_dir / "holidays.jsonl"
    manifest = json.loads((snapshot_dir / "SNAPSHOT.json").read_text(encoding="utf-8"))
    content_hash = sha256_hex(data_path.read_bytes())
    if content_hash != manifest["content_hash"]:
        raise ValueError(
            f"resmî tatil snapshot hash uyuşmazlığı: "
            f"{manifest['content_hash']} != {content_hash}"
        )
    rows = [
        json.loads(line)
        for line in data_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != int(manifest["row_count"]):
        raise ValueError("resmî tatil snapshot satır sayısı manifest ile uyuşmuyor")
    by_date = {str(row["date"]): row for row in rows}
    supported_years = {int(year) for year in manifest["supported_years"]}

    def list_public_holidays(arguments: Mapping[str, Any]) -> dict[str, Any]:
        year = int(arguments["year"])
        if year not in supported_years:
            raise ToolExecutionError(
                f"desteklenmeyen resmî tatil yılı: {year}",
                status_code=422,
            )
        category = str(arguments.get("category", "all"))
        include_half_days = bool(arguments.get("include_half_days", True))
        holidays = [
            dict(row)
            for row in rows
            if (category == "all" or row["category"] == category)
            and (include_half_days or row["duration"] != "half_day")
        ]
        return {"count": len(holidays), "holidays": holidays, "year": year}

    def is_public_holiday(arguments: Mapping[str, Any]) -> dict[str, Any]:
        raw_date = str(arguments["date"])
        try:
            parsed_date = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise ToolExecutionError(
                f"geçersiz tarih: {raw_date}",
                status_code=422,
            ) from exc
        if parsed_date.year not in supported_years:
            raise ToolExecutionError(
                f"desteklenmeyen resmî tatil yılı: {parsed_date.year}",
                status_code=422,
            )
        holiday = by_date.get(raw_date)
        if holiday is None:
            return {
                "date": raw_date,
                "is_half_day": False,
                "is_public_holiday": False,
                "name": None,
                "starts_at": None,
            }

        is_half_day = holiday["duration"] == "half_day"
        is_holiday_now = True
        at_time = arguments.get("at_time")
        if is_half_day and at_time is not None:
            try:
                requested_time = time.fromisoformat(str(at_time))
                starts_at = time.fromisoformat(str(holiday["starts_at"]))
            except ValueError as exc:
                raise ToolExecutionError(
                    f"geçersiz saat: {at_time}",
                    status_code=422,
                ) from exc
            is_holiday_now = requested_time >= starts_at

        return {
            "date": raw_date,
            "is_half_day": is_half_day,
            "is_public_holiday": is_holiday_now,
            "name": holiday["name"],
            "starts_at": holiday["starts_at"],
        }

    return LocalProviderAdapter(
        name=PROVIDER,
        license=LICENSE,
        attribution=ATTRIBUTION,
        snapshot_hashes={"tr_public_holidays": content_hash},
        bindings=(
            LocalToolBinding(LIST_PUBLIC_HOLIDAYS, list_public_holidays),
            LocalToolBinding(IS_PUBLIC_HOLIDAY, is_public_holiday),
        ),
    )
