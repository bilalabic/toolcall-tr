"""Episode-izole stateful ön muhasebe mock executor'ı."""

from __future__ import annotations

import copy
import time
from collections.abc import Mapping
from typing import Any

from toolcall_tr.canonical import sha256_of
from toolcall_tr.execution.executor import ExecutionResult
from toolcall_tr.models import (
    ExecutionClass,
    StateDelta,
    StateOp,
    StateOpKind,
    StepOutcome,
)
from toolcall_tr.models.tool import ToolSpec
from toolcall_tr.providers.onmuhasebe_mock.invoices import (
    CREATE_INVOICE,
    DELETE_DRAFT_INVOICE,
    GET_INVOICE,
    INITIAL_INVOICES,
    UPDATE_INVOICE_NOTE,
)
from toolcall_tr.schema import ArgumentError, normalize_arguments, validate_arguments

__all__ = ["StatefulAccountingExecutor"]


class StatefulAccountingExecutor:
    """Her episode başında aynı fixture'a dönen, gerçek state farkı üreten executor."""

    def __init__(self) -> None:
        self._state: dict[str, dict[str, Any]] = {}
        self._ops: list[StateOp] = []
        self._create_counter = 0
        self.begin_episode(0)

    def begin_episode(self, seed: int) -> None:
        del seed
        self._state = copy.deepcopy(INITIAL_INVOICES)
        self._ops = []
        self._create_counter = 0

    def state_delta(self) -> StateDelta:
        return StateDelta(ops=tuple(self._ops), volatile_fields=("created_at",))

    def state_hash(self) -> str:
        return sha256_of(self._state)

    def execute(self, tool: ToolSpec, arguments: Mapping[str, Any]) -> ExecutionResult:
        started = time.perf_counter()
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
        except KeyError:
            return self._result(
                tool,
                normalized,
                StepOutcome.UNEXPECTED_ERROR,
                started,
                error="Fatura bulunamadı",
                status_code=404,
                before=before,
                after=before,
            )
        except ValueError as exc:
            return self._result(
                tool,
                normalized,
                StepOutcome.UNEXPECTED_ERROR,
                started,
                error=str(exc),
                status_code=409,
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
        if tool_id == GET_INVOICE.tool_id:
            invoice = self._state[str(arguments["invoice_id"])]
            return {"invoice": copy.deepcopy(invoice)}
        if tool_id == CREATE_INVOICE.tool_id:
            self._create_counter += 1
            invoice_id = f"INV-2026-{1000 + self._create_counter:04d}"
            invoice = {
                "invoice_id": invoice_id,
                "customer_ref": str(arguments["customer_ref"]),
                "amount_try": float(arguments["amount_try"]),
                "note": str(arguments["note"]),
                "status": "draft",
            }
            self._state[invoice_id] = invoice
            self._ops.append(
                StateOp(
                    op=StateOpKind.CREATE,
                    entity="invoice",
                    entity_id=f"#{self._create_counter}",
                    fields=copy.deepcopy(invoice),
                )
            )
            return {"invoice": copy.deepcopy(invoice)}
        invoice_id = str(arguments["invoice_id"])
        invoice = self._state[invoice_id]
        if invoice["status"] != "draft":
            raise ValueError("Yalnızca taslak fatura değiştirilebilir")
        if tool_id == UPDATE_INVOICE_NOTE.tool_id:
            invoice["note"] = str(arguments["note"])
            self._ops.append(
                StateOp(
                    op=StateOpKind.UPDATE,
                    entity="invoice",
                    entity_id=invoice_id,
                    fields={"note": invoice["note"]},
                )
            )
            return {"invoice": copy.deepcopy(invoice)}
        if tool_id == DELETE_DRAFT_INVOICE.tool_id:
            del self._state[invoice_id]
            self._ops.append(
                StateOp(
                    op=StateOpKind.DELETE,
                    entity="invoice",
                    entity_id=invoice_id,
                )
            )
            return {"deleted": True, "invoice_id": invoice_id}
        raise ValueError(f"Tanımsız mock tool: {tool_id}")

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
