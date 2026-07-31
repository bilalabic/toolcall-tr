"""Stateful ön muhasebe mock'u ve onay kapısı."""

from __future__ import annotations

from toolcall_tr.execution.stateful_mock import StatefulAccountingExecutor
from toolcall_tr.models import StateOpKind, StepOutcome
from toolcall_tr.pipeline.environment import build_default_registry
from toolcall_tr.providers.onmuhasebe_mock.invoices import (
    CREATE_INVOICE,
    DELETE_DRAFT_INVOICE,
    GET_INVOICE,
    UPDATE_INVOICE_NOTE,
)


def test_create_ardindan_get_gercek_statei_okur() -> None:
    executor = StatefulAccountingExecutor()
    executor.begin_episode(123)
    created = executor.execute(
        CREATE_INVOICE,
        {
            "customer_ref": "CUST-042",
            "amount_try": 2750,
            "note": "Temmuz danışmanlık",
            "confirmed": True,
        },
    )
    invoice_id = created.response["invoice"]["invoice_id"]
    fetched = executor.execute(GET_INVOICE, {"invoice_id": invoice_id})
    assert created.outcome is StepOutcome.OK
    assert fetched.response == created.response
    assert created.state_hash_before != created.state_hash_after
    assert fetched.state_hash_before == fetched.state_hash_after
    assert executor.state_delta().ops[0].op is StateOpKind.CREATE
    assert executor.state_delta().ops[0].entity_id == "#1"


def test_episode_basinda_state_fixturea_doner() -> None:
    executor = StatefulAccountingExecutor()
    executor.execute(
        DELETE_DRAFT_INVOICE,
        {"invoice_id": "INV-2026-0001", "confirmed": True},
    )
    executor.begin_episode(456)
    result = executor.execute(GET_INVOICE, {"invoice_id": "INV-2026-0001"})
    assert result.outcome is StepOutcome.OK
    assert executor.state_delta().is_empty


def test_onaysiz_yazma_statei_degistirmez() -> None:
    executor = StatefulAccountingExecutor()
    before = executor.state_hash()
    result = executor.execute(
        UPDATE_INVOICE_NOTE,
        {
            "invoice_id": "INV-2026-0001",
            "note": "Yeni not",
            "confirmed": False,
        },
    )
    assert result.status_code == 409
    assert executor.state_hash() == before
    assert executor.state_delta().is_empty


def test_accounting_default_uretim_katalogunda_yok() -> None:
    registry = build_default_registry()
    assert registry.get("accounting.create_invoice") is None
    assert registry.get("accounting.get_invoice") is None
