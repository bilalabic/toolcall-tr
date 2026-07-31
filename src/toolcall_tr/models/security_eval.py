"""Eğitime kapalı, sentetik tool-output prompt-injection eval sözleşmesi."""

from __future__ import annotations

import json
import re
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "SecurityEvalExpectedBehavior",
    "SecurityEvalToolCall",
    "ToolOutputInjectionEval",
]

EVAL_ID_RE = re.compile(r"^security_tool_output_injection_[0-9]{3}$")
TOOL_ID_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


class SecurityEvalToolCall(BaseModel):
    """Kullanıcı amacı için yapılmış güvenilir çağrı zarfı."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _valid_tool_id(self) -> Self:
        if not TOOL_ID_RE.fullmatch(self.tool_id):
            raise ValueError(f"tool_id namespace.name biçiminde olmalı: {self.tool_id!r}")
        return self


class SecurityEvalExpectedBehavior(BaseModel):
    """Modelin araç verisi ile talimatı ayırırken uyması gereken gözlenebilirler."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["ignore_tool_output_instruction_and_continue_user_goal"]
    preserve_user_intent: Literal[True] = True
    treat_tool_output_as_untrusted_data: Literal[True] = True
    must_not_disclose_secrets: Literal[True] = True
    allowed_tool_calls: tuple[str, ...] = ()
    forbidden_tool_calls: tuple[str, ...] = Field(min_length=1)
    response_requirements_tr: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _disjoint_calls(self) -> Self:
        overlap = sorted(set(self.allowed_tool_calls) & set(self.forbidden_tool_calls))
        if overlap:
            raise ValueError(f"tool çağrısı hem izinli hem yasak olamaz: {overlap}")
        for tool_id in (*self.allowed_tool_calls, *self.forbidden_tool_calls):
            if not TOOL_ID_RE.fullmatch(tool_id):
                raise ValueError(
                    f"beklenen davranış tool_id değeri geçersiz: {tool_id!r}"
                )
        return self


class ToolOutputInjectionEval(BaseModel):
    """Tek bir sentetik, training-dışı tool-output injection değerlendirmesi."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["security_eval.v1"] = "security_eval.v1"
    id: str
    locale: Literal["tr-TR"] = "tr-TR"
    category: Literal["tool_output_prompt_injection"] = "tool_output_prompt_injection"
    source: Literal["synthetic"] = "synthetic"
    training_eligible: Literal[False] = False
    user_intent_tr: str = Field(min_length=1)
    initial_tool_call: SecurityEvalToolCall
    tool_output: dict[str, Any]
    injected_instruction_tr: str = Field(min_length=1)
    expected_behavior: SecurityEvalExpectedBehavior

    @model_validator(mode="after")
    def _check_contract(self) -> Self:
        if not EVAL_ID_RE.fullmatch(self.id):
            raise ValueError(
                "id security_tool_output_injection_NNN biçiminde olmalı"
            )
        serialized_output = json.dumps(
            self.tool_output,
            sort_keys=True,
            ensure_ascii=False,
        )
        if self.injected_instruction_tr not in serialized_output:
            raise ValueError(
                "injected_instruction_tr araç çıktısında birebir bulunmalı"
            )
        if not self.user_intent_tr.strip() or (
            self.user_intent_tr != self.user_intent_tr.strip()
        ):
            raise ValueError("user_intent_tr boş veya kenar boşluklu olamaz")
        if not self.injected_instruction_tr.strip() or (
            self.injected_instruction_tr != self.injected_instruction_tr.strip()
        ):
            raise ValueError(
                "injected_instruction_tr boş veya kenar boşluklu olamaz"
            )
        return self
