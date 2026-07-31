"""Tam tool trajectory ve çok turlu blueprint sözleşmesi."""

from __future__ import annotations

from tests.factories import FROZEN_NOW, make_blueprint, make_environment
from toolcall_tr.generation.query import GeneratedQuery
from toolcall_tr.groundtruth.planner import plan
from toolcall_tr.groundtruth.runner import Environment
from toolcall_tr.models import (
    ConversationTurn,
    ExecutedCall,
    ExecutionClass,
    MessageRole,
    StepOutcome,
    Trace,
)
from toolcall_tr.pipeline.assemble import assemble_example
from toolcall_tr.pipeline.environment import build_izmir_registry
from toolcall_tr.validation import TurnConsistencyValidator, ValidationSubject


def test_multi_turn_tool_trajectory_final_asistan_cevabiyla_biter() -> None:
    registry = build_izmir_registry()
    blueprint = make_blueprint(
        interaction_type="multi_turn",
        conversation_prefix=(
            ConversationTurn(
                role="user",
                content="İzmir'deki ulaşım verileriyle ilgileniyorum.",
            ),
            ConversationTurn(
                role="assistant",
                content="Hangi bilgiyi aramamı istersiniz?",
            ),
        ),
    )
    compiled = plan(blueprint, registry)
    trace = Trace(
        blueprint_id=blueprint.blueprint_id,
        plan_hash=compiled.plan_hash(),
        episode_seed=123,
        steps=(
            ExecutedCall(
                step_index=0,
                step_id="step_0",
                tool_id="izmir.search_datasets",
                execution_class=ExecutionClass.LIVE_RECORDED,
                arguments={"q": "otobüs"},
                outcome=StepOutcome.OK,
                status_code=200,
                response={"count": 1, "results": []},
            ),
        ),
        environment=make_environment(),
        outcome=StepOutcome.OK,
    )
    environment = Environment(
        registry=registry,
        executors={},
        now=FROZEN_NOW,
        root_seed=42891,
        fingerprint=make_environment(),
    )

    example = assemble_example(
        blueprint=blueprint,
        plan=compiled,
        trace=trace,
        query=GeneratedQuery(
            text="Otobüs veri setlerini bulur musun?",
            style="resmi",
            variant_index=0,
            prompt_version="test-v1",
        ),
        env=environment,
        index=1,
        created_at=FROZEN_NOW,
    )

    assert example.scenario.interaction_type == "multi_turn"
    assert [message.role for message in example.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.ASSISTANT,
    ]
    assert example.ground_truth.final_response_source == "terminal_observation"
    assert example.messages[-1].content == (
        "Araçtan doğrulanan sonuçlar:\n"
        "- Kayıt sayısı: 1\n"
        "- Sonuçlar:\n"
        "  Boş liste."
    )
    assert list(
        TurnConsistencyValidator().check(
            ValidationSubject(
                blueprint=blueprint,
                plan=compiled,
                trace=trace,
                tools=example.tools,
                example=example,
            )
        )
    ) == []
