"""Blueprint + Plan + Trace + ifade -> canonical `Example`.

Montaj **hiçbir şey uydurmaz**. Özellikle:

* Tool çağrısı olmayan senaryolarda (clarification / direct_answer /
  cannot_answer), blueprint'te insan tarafından beyan edilen birebir
  `assistant_response_tr` eğitim hedefi mesaj akışına eklenir. Semantik
  `response_intent_tr` tek başına SFT hedefi sayılmaz.
* Tool-call senaryolarında final cevap yalnız son gerçek observation'ın
  kayıpsız, deterministik aktarımıdır; serbest özet veya gizli CoT üretilmez.
* Tool sonuçları mesaj akışına **olduğu gibi** girer; özetlenmez.
* `state_hash` read-only sağlayıcıda `None` kalır; ortam parmak izi ayrıdır.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from toolcall_tr.canonical import CANONICAL_JSON_VERSION, canonical_json, sha256_of
from toolcall_tr.generation.query import GeneratedQuery
from toolcall_tr.groundtruth.runner import Environment
from toolcall_tr.models import (
    Blueprint,
    CallPlan,
    Decision,
    Example,
    ExecutionClass,
    ExecutionRecord,
    GroundTruth,
    Localization,
    Message,
    MessageRole,
    Provenance,
    Scenario,
    Split,
    StepOutcome,
    ToolCallRecord,
    ToolSpec,
    Trace,
    VerificationFlags,
)
from toolcall_tr.pipeline.final_response import render_terminal_observation_tr

__all__ = ["PIPELINE_VERSION", "assemble_example", "example_id"]

PIPELINE_VERSION = "0.4.0"

ExpectedResult = Literal["success", "expected_error", "empty", "no_call"]

_RESULT_BY_OUTCOME: dict[StepOutcome, ExpectedResult] = {
    StepOutcome.OK: "success",
    StepOutcome.EXPECTED_ERROR: "expected_error",
}


def example_id(domain: str, blueprint_id: str, variant_index: int = 0) -> str:
    """Sıra değişiminden etkilenmeyen örnek kimliği üret.

    Blueprint listesine yeni bir öğe eklemek mevcut bütün kimlikleri
    kaydırmamalıdır. Kimlik yalnızca örneğin semantik kaynağı ve varyantından
    türetilir.
    """
    digest = sha256_of(
        {
            "namespace": "toolcall-tr/example-id/v1",
            "blueprint_id": blueprint_id,
            "variant_index": variant_index,
        }
    ).split(":", 1)[1][:16]
    return f"toolcall_tr_{domain}_{digest}"


def assemble_example(
    *,
    blueprint: Blueprint,
    plan: CallPlan,
    trace: Trace,
    query: GeneratedQuery,
    env: Environment,
    index: int,
    created_at: datetime,
    git_sha: str | None = None,
) -> Example:
    """Doğrulanmış bir çalıştırmayı yayımlanabilir örneğe çevirir."""
    tools = _offered_tools(env, plan.available_tools)
    decision = plan.decision

    messages: list[Message] = [
        Message(role=MessageRole(turn.role), content=turn.content)
        for turn in blueprint.conversation_prefix
    ]
    messages.append(Message(role=MessageRole.USER, content=query.text))
    calls: list[ToolCallRecord] = []
    final_response_tr: str | None = None

    if decision is Decision.TOOL_CALL:
        executed_steps = [
            step for step in trace.steps if step.outcome is not StepOutcome.SKIPPED
        ]
        calls = [
            ToolCallRecord(
                name=step.tool_id.split(".", 1)[1],
                arguments=dict(step.arguments),
            )
            for step in executed_steps
        ]

        if plan.is_sequential:
            # Bağımlı çağrı, önceki observation görülmeden üretilemez. Her
            # adımı kendi asistan turunda ve hemen ardından gelen tool
            # observation'ıyla yayımla.
            for call, step in zip(calls, executed_steps, strict=True):
                messages.append(
                    Message(role=MessageRole.ASSISTANT, tool_calls=(call,))
                )
                messages.append(
                    Message(
                        role=MessageRole.TOOL,
                        tool_name=call.name,
                        content=_tool_content(
                            step.response,
                            step.status_code,
                            step.error,
                        ),
                    )
                )
        else:
            # Tek çağrı veya gerçekten bağımsız paralel çağrılar aynı asistan
            # mesajında bulunabilir.
            if calls:
                messages.append(
                    Message(role=MessageRole.ASSISTANT, tool_calls=tuple(calls))
                )
            for call, step in zip(calls, executed_steps, strict=True):
                messages.append(
                    Message(
                        role=MessageRole.TOOL,
                        tool_name=call.name,
                        content=_tool_content(
                            step.response,
                            step.status_code,
                            step.error,
                        ),
                )
            )
        final_response_tr = _final_response_tr(trace)
        messages.append(
            Message(role=MessageRole.ASSISTANT, content=final_response_tr)
        )
    else:
        assistant_response = blueprint.expected_behavior.assistant_response_tr
        if assistant_response is None:  # Model sözleşmesinin son savunma hattı.
            raise ValueError(
                f"{blueprint.blueprint_id}: {decision.value} kararı "
                "assistant_response_tr gerektirir"
            )
        messages.append(Message(role=MessageRole.ASSISTANT, content=assistant_response))

    ground_truth = GroundTruth(
        calls=tuple(calls),
        missing_parameters=blueprint.expected_behavior.missing_parameters,
        expected_final_state=trace.state_delta,
        assertions=blueprint.assertions,
        response_intent_tr=blueprint.expected_behavior.response_intent_tr,
        assistant_response_tr=blueprint.expected_behavior.assistant_response_tr,
        final_response_tr=final_response_tr,
        final_response_source=(
            "terminal_observation" if final_response_tr is not None else None
        ),
    )

    stateful_steps = [
        step
        for step in trace.steps
        if step.state_hash_before is not None and step.state_hash_after is not None
    ]
    execution = ExecutionRecord(
        execution_classes=_execution_classes(trace),
        result=trace.outcome,
        trace_id=trace.trace_id(),
        initial_state_hash=stateful_steps[0].state_hash_before if stateful_steps else None,
        final_state_hash=stateful_steps[-1].state_hash_after if stateful_steps else None,
    )

    provenance = Provenance(
        pipeline_version=PIPELINE_VERSION,
        canonical_json_version=CANONICAL_JSON_VERSION,
        blueprint_id=blueprint.blueprint_id,
        blueprint_hash=blueprint.content_hash(),
        family_id=blueprint.family_id,
        variant_index=query.variant_index,
        plan_hash=plan.plan_hash(),
        trace_id=trace.trace_id(),
        episode_seed=trace.episode_seed,
        environment=env.fingerprint,
        generator=query.usage,
        created_at=created_at,
        git_sha=git_sha,
    )

    return Example(
        id=example_id(blueprint.domain, blueprint.blueprint_id, query.variant_index),
        locale=blueprint.locale,
        domain=blueprint.domain,
        provider=blueprint.provider,
        family_id=blueprint.family_id,
        split=blueprint.split or Split.TRAIN,
        localization=Localization(
            translation_based=False,
            turkey_specific_schema=True,
            turkey_specific_scenario=True,
        ),
        scenario=Scenario(
            decision=decision,
            kind=blueprint.kind,
            interaction_type=blueprint.interaction_type,
            difficulty=blueprint.difficulty,
            expected_result=_expected_result(decision, trace),
        ),
        tools=tools,
        messages=tuple(messages),
        reasoning_summary_tr=query.reasoning_summary_tr,
        ground_truth=ground_truth,
        execution=execution,
        verification=VerificationFlags(),
        provenance=provenance,
    )


def _offered_tools(env: Environment, tool_ids: Iterable[str]) -> tuple[ToolSpec, ...]:
    """Sunulan tool tanımlarının **anlık kopyası**.

    Registry sonradan değişse bile örnek kendi kendine yeterli kalır.
    """
    return tuple(env.registry.require(tool_id) for tool_id in tool_ids)


def _tool_content(response: object, status_code: int | None, error: str | None) -> str:
    """Tool sonucunu mesaj gövdesine çevirir.

    Hata durumunda gövde uydurulmaz: yapılandırılmış bir hata nesnesi yazılır.
    """
    if response is not None:
        return canonical_json(response)
    return canonical_json({"error": error or "bilinmeyen hata", "status_code": status_code})


def _final_response_tr(trace: Trace) -> str:
    """Son gerçek observation'ı yeni iddia üretmeden Türkçe final mesaja taşı."""
    executed_steps = [
        step for step in trace.steps if step.outcome is not StepOutcome.SKIPPED
    ]
    if not executed_steps:
        raise ValueError(
            f"{trace.blueprint_id}: tool_call trajectory final observation içermiyor"
        )
    terminal = executed_steps[-1]
    return render_terminal_observation_tr(
        terminal.response,
        status_code=terminal.status_code,
        error=terminal.error,
    )


def _execution_classes(trace: Trace) -> tuple[ExecutionClass, ...]:
    """Örnekteki çağrıların üretim sınıfları — tekilleştirilmiş ve sıralı.

    Dataset card bu dağılımı raporlar; "tüm cevaplar canlı API'den geldi"
    iddiası asla yapılmaz.
    """
    seen = {step.execution_class for step in trace.steps}
    return tuple(sorted(seen, key=lambda value: value.value))


def _expected_result(decision: Decision, trace: Trace) -> ExpectedResult:
    if decision is not Decision.TOOL_CALL:
        return "no_call"
    mapped = _RESULT_BY_OUTCOME.get(trace.outcome)
    if mapped is None:
        return "success"
    if mapped == "success" and _terminal_result_empty(trace):
        return "empty"
    return mapped


def _terminal_result_empty(trace: Trace) -> bool:
    """Çok adımlı planda kullanıcıya dönen son başarılı sonuç boş mu?"""
    from toolcall_tr.validation.base import looks_empty

    executed = [s for s in trace.steps if s.outcome is StepOutcome.OK]
    return bool(executed) and looks_empty(executed[-1].response)
