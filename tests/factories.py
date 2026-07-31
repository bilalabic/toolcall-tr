"""Test nesnesi kurucuları.

Testlerin okunabilir kalması için: her test yalnızca **ilgilendiği** alanı
belirtir, gerisi buradan gelir.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from toolcall_tr.models import (
    Blueprint,
    BlueprintKind,
    Decision,
    EnvironmentFingerprint,
    Example,
    ExecutionClass,
    ExecutionRecord,
    ExpectedAction,
    ExpectedBehavior,
    GroundTruth,
    LiteralArg,
    Localization,
    Message,
    MessageRole,
    OutputField,
    ParamSpec,
    Provenance,
    Scenario,
    SideEffect,
    Split,
    StepOutcome,
    ToolCallRecord,
    ToolSource,
    ToolSpec,
    VerificationFlags,
)
from toolcall_tr.models.enums import ArgOrigin

FROZEN_NOW = datetime(2026, 7, 28, 6, 0, tzinfo=UTC)


def make_tool(
    *,
    tool_id: str = "izmir.search_datasets",
    name: str | None = None,
    parameters: tuple[ParamSpec, ...] | None = None,
    outputs: tuple[OutputField, ...] | None = None,
    **overrides: Any,
) -> ToolSpec:
    if name is None:
        name = tool_id.split(".", 1)[1]
    if parameters is None:
        parameters = (
            ParamSpec(
                name="q",
                type="string",
                description_tr="Aranacak anahtar kelime.",
                required=True,
                semantic_type="search_query",
            ),
        )
    if outputs is None:
        outputs = (
            OutputField(
                path="result.results[*].id",
                type="string",
                description_tr="Veri seti kimliği.",
                semantic_type="package_id",
            ),
        )
    defaults: dict[str, Any] = {
        "tool_id": tool_id,
        "provider": "izmir_ckan",
        "name": name,
        "description_tr": "Açık veri portalında veri seti arar.",
        "parameters": parameters,
        "outputs": outputs,
        "side_effect": SideEffect.READ,
        "execution_class": ExecutionClass.LIVE_RECORDED,
        "source": ToolSource(
            schema_type="ckan",
            schema_version="2026-07",
            operation_id="package_search",
            license="CC-BY-4.0",
        ),
    }
    defaults.update(overrides)
    return ToolSpec(**defaults)


def literal(value: Any, origin: ArgOrigin = ArgOrigin.USER_MESSAGE) -> LiteralArg:
    return LiteralArg(value=value, origin=origin)


def make_blueprint(**overrides: Any) -> Blueprint:
    defaults: dict[str, Any] = {
        "blueprint_id": "izmir_search_001",
        "family_id": "izmir_dataset_search",
        "domain": "open_data",
        "kind": BlueprintKind.SUCCESSFUL_TOOL_CALL,
        "provider": "izmir_ckan",
        "user_goal": "Otobüs verisi içeren veri setlerini bulmak",
        "available_tools": ("izmir.search_datasets",),
        "expected_actions": (
            ExpectedAction(
                tool_id="izmir.search_datasets",
                arguments={"q": literal("otobüs")},
            ),
        ),
        "expected_behavior": ExpectedBehavior(decision=Decision.TOOL_CALL),
    }
    defaults.update(overrides)
    return Blueprint(**defaults)


def make_environment(**overrides: Any) -> EnvironmentFingerprint:
    defaults: dict[str, Any] = {
        "cassette_manifest_hash": "sha256:" + "a" * 64,
        "snapshot_hashes": {"eshot_stops": "sha256:" + "b" * 64},
        "frozen_now": FROZEN_NOW,
        "root_seed": 42891,
        "registry_hash": "sha256:" + "c" * 64,
    }
    defaults.update(overrides)
    return EnvironmentFingerprint(**defaults)


def make_example(
    *,
    example_id: str = "toolcall_tr_open_data_000001",
    user_text: str = "Otobüs duraklarıyla ilgili veri setlerini bulur musun?",
    **overrides: Any,
) -> Example:
    """Minimal ama geçerli bir canonical örnek."""
    tool = make_tool()
    trace_id = "sha256:" + "f" * 64
    defaults: dict[str, Any] = {
        "id": example_id,
        "domain": "open_data",
        "provider": "izmir_ckan",
        "family_id": "izmir_dataset_search",
        "split": Split.TRAIN,
        "localization": Localization(turkey_specific_schema=True, turkey_specific_scenario=True),
        "scenario": Scenario(
            decision=Decision.TOOL_CALL,
            kind=BlueprintKind.SUCCESSFUL_TOOL_CALL,
            interaction_type="single_turn",
            difficulty="easy",
            expected_result="success",
        ),
        "tools": (tool,),
        "messages": (
            Message(role=MessageRole.USER, content=user_text),
            Message(
                role=MessageRole.ASSISTANT,
                tool_calls=(ToolCallRecord(name="search_datasets", arguments={"q": "otobüs"}),),
            ),
            Message(
                role=MessageRole.TOOL,
                tool_name="search_datasets",
                content='{"count":1}',
            ),
            Message(
                role=MessageRole.ASSISTANT,
                content='Doğrulanmış araç sonucu:\n{"count":1}',
            ),
        ),
        "ground_truth": GroundTruth(
            calls=(ToolCallRecord(name="search_datasets", arguments={"q": "otobüs"}),),
            final_response_tr='Doğrulanmış araç sonucu:\n{"count":1}',
            final_response_source="terminal_observation",
        ),
        "execution": ExecutionRecord(
            execution_classes=(ExecutionClass.LIVE_RECORDED,),
            result=StepOutcome.OK,
            trace_id=trace_id,
        ),
        "verification": VerificationFlags(format_valid=True, schema_valid=True),
        "provenance": make_provenance(trace_id=trace_id),
    }
    if "messages" in overrides and "ground_truth" not in overrides:
        supplied_messages = tuple(overrides["messages"])
        has_tool_observation = any(
            message.role is MessageRole.TOOL for message in supplied_messages
        )
        final_message = supplied_messages[-1] if supplied_messages else None
        has_grounded_final = (
            has_tool_observation
            and final_message is not None
            and final_message.role is MessageRole.ASSISTANT
            and not final_message.tool_calls
            and final_message.content is not None
        )
        defaults["ground_truth"] = GroundTruth(
            calls=(ToolCallRecord(name="search_datasets", arguments={"q": "otobüs"}),),
            final_response_tr=final_message.content if has_grounded_final else None,
            final_response_source=(
                "terminal_observation" if has_grounded_final else None
            ),
        )
    defaults.update(overrides)
    return Example(**defaults)


def make_provenance(**overrides: Any) -> Provenance:
    defaults: dict[str, Any] = {
        "pipeline_version": "0.1.0",
        "canonical_json_version": 1,
        "blueprint_id": "izmir_search_001",
        "blueprint_hash": "sha256:" + "d" * 64,
        "family_id": "izmir_dataset_search",
        "plan_hash": "sha256:" + "e" * 64,
        "trace_id": "sha256:" + "f" * 64,
        "episode_seed": 12345,
        "environment": make_environment(),
        "created_at": FROZEN_NOW,
    }
    defaults.update(overrides)
    return Provenance(**defaults)
