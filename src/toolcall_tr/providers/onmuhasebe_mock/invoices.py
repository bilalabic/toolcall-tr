"""Gerçek ticari sistemle bağlantısı olmayan, episode-izole fatura mock'u."""

from __future__ import annotations

from typing import Any

from toolcall_tr.models import (
    ExecutionClass,
    OutputField,
    ParamSpec,
    SideEffect,
    ToolSource,
)
from toolcall_tr.models.tool import ToolSpec

PROVIDER = "onmuhasebe_mock"
VERSION = "onmuhasebe_mock/1.0.0"
LICENSE = "Apache-2.0"
ATTRIBUTION = "ToolCall-TR katkıcıları; tamamen kurgusal veri ve servis"

_SOURCE = ToolSource(
    schema_type="manual",
    schema_version=VERSION,
    upstream_url="https://api.ornek-onmuhasebe.test",
    license=LICENSE,
    attribution=ATTRIBUTION,
)

INITIAL_INVOICES: dict[str, dict[str, Any]] = {
    "INV-2026-0001": {
        "invoice_id": "INV-2026-0001",
        "customer_ref": "CUST-001",
        "amount_try": 1250.0,
        "note": "Pilot taslak",
        "status": "draft",
    }
}

_INVOICE_OUTPUTS = (
    OutputField(path="invoice.invoice_id", type="string", description_tr="Kurgusal fatura kimliği.", semantic_type="invoice_id"),
    OutputField(path="invoice.customer_ref", type="string", description_tr="Sentetik müşteri referansı."),
    OutputField(path="invoice.amount_try", type="number", description_tr="Fatura tutarı (TRY)."),
    OutputField(path="invoice.note", type="string", description_tr="Fatura notu."),
    OutputField(path="invoice.status", type="string", description_tr="Fatura durumu."),
)

GET_INVOICE = ToolSpec(
    tool_id="accounting.get_invoice",
    provider=PROVIDER,
    name="get_invoice",
    description_tr="Kurgusal ön muhasebe durumundan bir faturayı getirir.",
    parameters=(
        ParamSpec(name="invoice_id", type="string", description_tr="Kurgusal fatura kimliği.", required=True, semantic_type="invoice_id"),
    ),
    outputs=_INVOICE_OUTPUTS,
    side_effect=SideEffect.READ,
    execution_class=ExecutionClass.SIMULATED,
    source=_SOURCE,
)

CREATE_INVOICE = ToolSpec(
    tool_id="accounting.create_invoice",
    provider=PROVIDER,
    name="create_invoice",
    description_tr="Açık kullanıcı onayından sonra kurgusal bir taslak fatura oluşturur.",
    parameters=(
        ParamSpec(name="customer_ref", type="string", description_tr="Sentetik müşteri referansı.", required=True, pattern=r"^CUST-[0-9]{3}$"),
        ParamSpec(name="amount_try", type="number", description_tr="Fatura tutarı (TRY).", required=True, minimum=0.01, maximum=1_000_000),
        ParamSpec(name="note", type="string", description_tr="Fatura notu.", required=True, min_length=2, max_length=120),
        ParamSpec(name="confirmed", type="boolean", description_tr="Kullanıcının açık işlem onayı.", required=True),
    ),
    outputs=_INVOICE_OUTPUTS,
    side_effect=SideEffect.CREATE,
    execution_class=ExecutionClass.SIMULATED,
    confirmation_required=True,
    source=_SOURCE,
)

UPDATE_INVOICE_NOTE = ToolSpec(
    tool_id="accounting.update_invoice_note",
    provider=PROVIDER,
    name="update_invoice_note",
    description_tr="Açık kullanıcı onayından sonra taslak faturanın notunu günceller.",
    parameters=(
        ParamSpec(name="invoice_id", type="string", description_tr="Kurgusal fatura kimliği.", required=True, semantic_type="invoice_id"),
        ParamSpec(name="note", type="string", description_tr="Yeni fatura notu.", required=True, min_length=2, max_length=120),
        ParamSpec(name="confirmed", type="boolean", description_tr="Kullanıcının açık işlem onayı.", required=True),
    ),
    outputs=_INVOICE_OUTPUTS,
    side_effect=SideEffect.UPDATE,
    execution_class=ExecutionClass.SIMULATED,
    confirmation_required=True,
    source=_SOURCE,
)

DELETE_DRAFT_INVOICE = ToolSpec(
    tool_id="accounting.delete_draft_invoice",
    provider=PROVIDER,
    name="delete_draft_invoice",
    description_tr="Açık kullanıcı onayından sonra yalnızca taslak faturayı siler.",
    parameters=(
        ParamSpec(name="invoice_id", type="string", description_tr="Kurgusal fatura kimliği.", required=True, semantic_type="invoice_id"),
        ParamSpec(name="confirmed", type="boolean", description_tr="Kullanıcının açık işlem onayı.", required=True),
    ),
    outputs=(
        OutputField(path="deleted", type="boolean", description_tr="Silme işleminin sonucu."),
        OutputField(path="invoice_id", type="string", description_tr="Silinen kurgusal fatura kimliği.", semantic_type="invoice_id"),
    ),
    side_effect=SideEffect.DELETE,
    execution_class=ExecutionClass.SIMULATED,
    confirmation_required=True,
    source=_SOURCE,
)

TOOLS: tuple[ToolSpec, ...] = (
    GET_INVOICE,
    CREATE_INVOICE,
    UPDATE_INVOICE_NOTE,
    DELETE_DRAFT_INVOICE,
)
