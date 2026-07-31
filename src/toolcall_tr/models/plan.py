"""CallPlan — Faz A'nın (planner) çıktısı.

Plan **saf** bir artefakttır: hiçbir ağ çağrısı, cassette veya mock olmadan
üretilir ve doğrulanır. Tool varlığı, parametre varlığı, tip uyumu ve referans
geçerliliği burada kesinleşir. Planner'ın hard-fail ettiği bir blueprint asla
çalıştırılmaz.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from toolcall_tr.canonical import sha256_of
from toolcall_tr.models.args import ArgValue, StepRefArg
from toolcall_tr.models.blueprint import ExpectedBehavior, ExpectSpec
from toolcall_tr.models.enums import Decision

__all__ = ["CallPlan", "PlannedCall"]


class PlannedCall(BaseModel):
    """Planlanmış tek bir adım. Argümanlar henüz çözülmemiştir."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_index: int = Field(ge=0)
    step_id: str
    tool_id: str
    arguments: dict[str, ArgValue] = Field(default_factory=dict)
    #: Referanslardan türetilir; DAG kenarları.
    depends_on: tuple[int, ...] = ()
    expect: ExpectSpec = ExpectSpec()

    @model_validator(mode="after")
    def _check(self) -> Self:
        refs = {a.step_index for a in self.arguments.values() if isinstance(a, StepRefArg)}
        if refs != set(self.depends_on):
            raise ValueError(
                f"{self.step_id}: depends_on {sorted(self.depends_on)} "
                f"argüman referanslarıyla ({sorted(refs)}) uyuşmuyor"
            )
        if any(dep >= self.step_index for dep in self.depends_on):
            raise ValueError(f"{self.step_id}: ileri veya kendine bağımlılık")
        return self


class CallPlan(BaseModel):
    """Bir blueprint'in çalıştırılabilir, doğrulanmış DAG'ı."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    blueprint_id: str
    blueprint_hash: str
    registry_hash: str

    decision: Decision
    expected_behavior: ExpectedBehavior
    available_tools: tuple[str, ...]
    steps: tuple[PlannedCall, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> Self:
        for position, step in enumerate(self.steps):
            if step.step_index != position:
                raise ValueError(
                    f"adım sırası bozuk: {position}. eleman step_index={step.step_index}"
                )
        if self.decision is Decision.TOOL_CALL and not self.steps:
            raise ValueError("tool_call planı en az bir adım içermeli")
        if self.decision is not Decision.TOOL_CALL and self.steps:
            raise ValueError(f"{self.decision.value!r} planında adım olmamalı")

        unknown = {s.tool_id for s in self.steps} - set(self.available_tools)
        if unknown:
            raise ValueError(f"plan sunulmayan tool içeriyor: {sorted(unknown)}")
        return self

    @property
    def is_sequential(self) -> bool:
        """En az bir adım önceki adımın çıktısına bağlı mı?"""
        return any(step.depends_on for step in self.steps)

    @property
    def is_parallel(self) -> bool:
        """Birden fazla adım var ve hiçbiri diğerine bağlı değil mi?"""
        return len(self.steps) > 1 and not self.is_sequential

    def plan_hash(self) -> str:
        return sha256_of(self.model_dump(mode="json"))
