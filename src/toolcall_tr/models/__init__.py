"""Canonical Pydantic modelleri — pipeline'ın veri sözleşmesi.

Bu paket **hiçbir iç modülü import etmez** (tek istisna: yaprak yardımcı
`toolcall_tr.canonical`). Buradaki şema kararları geriye dönük
doldurulamayanlardır:

* `ParamSpec.semantic_type` — kompozisyon grafiği elle yazılmaz, bundan türetilir
* `ToolSpec.execution_class` — "canlı mı, yerel mi, simüle mi" dürüstçe taşınır
* `Blueprint.expected_behavior` — negatif senaryolar `tool_calls`'a sığmaz
* `Blueprint.family_id` / `split` — bölme fan-out'tan önce, family seviyesinde
* `StateDelta` — read-only'de null, ama arayüz M1'de var ki M2 şemayı kırmasın
* `EnvironmentFingerprint` — `state_hash` ile kasıtlı olarak ayrı tutulur
"""

from toolcall_tr.models.args import ArgValue, LiteralArg, StepRefArg, parse_step_reference
from toolcall_tr.models.blueprint import (
    NEGATIVE_KINDS,
    Blueprint,
    ConversationTurn,
    ExpectedAction,
    ExpectedBehavior,
    ExpectSpec,
)
from toolcall_tr.models.enums import (
    ArgOrigin,
    BlueprintKind,
    Decision,
    ExecutionClass,
    MessageRole,
    Severity,
    SideEffect,
    Split,
    StateOpKind,
    StepOutcome,
)
from toolcall_tr.models.example import (
    Example,
    ExecutionRecord,
    GroundTruth,
    Localization,
    Message,
    Scenario,
    ToolCallRecord,
)
from toolcall_tr.models.plan import CallPlan, PlannedCall
from toolcall_tr.models.provenance import EnvironmentFingerprint, LLMUsage, Provenance
from toolcall_tr.models.security_eval import (
    SecurityEvalExpectedBehavior,
    SecurityEvalToolCall,
    ToolOutputInjectionEval,
)
from toolcall_tr.models.state import Assertion, StateDelta, StateOp
from toolcall_tr.models.tool import OutputField, ParamSpec, ToolSource, ToolSpec
from toolcall_tr.models.trace import VOLATILE_TRACE_FIELDS, ExecutedCall, Trace
from toolcall_tr.models.validation import Finding, ValidationResult, VerificationFlags

__all__ = [
    "NEGATIVE_KINDS",
    "VOLATILE_TRACE_FIELDS",
    "ArgOrigin",
    "ArgValue",
    "Assertion",
    "Blueprint",
    "BlueprintKind",
    "CallPlan",
    "ConversationTurn",
    "Decision",
    "EnvironmentFingerprint",
    "Example",
    "ExecutedCall",
    "ExecutionClass",
    "ExecutionRecord",
    "ExpectSpec",
    "ExpectedAction",
    "ExpectedBehavior",
    "Finding",
    "GroundTruth",
    "LLMUsage",
    "LiteralArg",
    "Localization",
    "Message",
    "MessageRole",
    "OutputField",
    "ParamSpec",
    "PlannedCall",
    "Provenance",
    "Scenario",
    "SecurityEvalExpectedBehavior",
    "SecurityEvalToolCall",
    "Severity",
    "SideEffect",
    "Split",
    "StateDelta",
    "StateOp",
    "StateOpKind",
    "StepOutcome",
    "StepRefArg",
    "ToolCallRecord",
    "ToolOutputInjectionEval",
    "ToolSource",
    "ToolSpec",
    "Trace",
    "ValidationResult",
    "VerificationFlags",
    "parse_step_reference",
]
