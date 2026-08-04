"""Dışa aktarım biçimleri.

Canonical veri **bizimdir**; OpenAI tarzı ``tools``/``messages``, xLAM ve
ShareGPT yalnızca birer görünümdür. Exporter'lar canonical veriyi
**değiştirmez** -- her biri için round-trip testi vardır.

Bu ayrım olmadan `state_delta` gibi sohbet şemasına sığmayan alanlar
kaybolurdu; onlar yan alanda taşınır.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from toolcall_tr.canonical import canonical_json
from toolcall_tr.models import Decision, Example, MessageRole, ToolSpec

__all__ = [
    "EXPORTERS",
    "to_canonical_jsonl",
    "to_hf_chat",
    "to_openai",
    "to_openai_call_only",
    "to_openai_trajectory",
    "to_sharegpt",
    "to_xlam",
]


def _tool_schema(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description_tr,
            "parameters": tool.to_json_schema(),
        },
    }


def _provenance(example: Example) -> dict[str, Any]:
    """Hedef sohbet şemasına sığmayan kaynak zincirini kayıpsız taşı."""
    sources: dict[tuple[str, str | None, str, str | None], dict[str, Any]] = {}
    for tool in example.tools:
        source = tool.source
        key = (source.license, source.attribution, source.schema_version, source.upstream_url)
        sources[key] = {
            "provider": tool.provider,
            "license": source.license,
            "attribution": source.attribution,
            "upstream_url": source.upstream_url,
            "schema_version": source.schema_version,
            "source_hash": source.source_hash,
        }
    return {
        "blueprint_id": example.provenance.blueprint_id,
        "blueprint_hash": example.provenance.blueprint_hash,
        "plan_hash": example.provenance.plan_hash,
        "trace_id": example.provenance.trace_id,
        "environment_hash": example.provenance.environment.content_hash(),
        "generator": (
            example.provenance.generator.model_dump(mode="json")
            if example.provenance.generator is not None
            else None
        ),
        "judge": (
            example.provenance.judge.model_dump(mode="json")
            if example.provenance.judge is not None
            else None
        ),
        "sources": list(sources.values()),
    }


def _supervision_sidecar(example: Example) -> dict[str, Any]:
    """Sohbet şemasına sığmayan güvenli eğitim/audit alanları.

    ``assistant_response_tr`` OpenAI ve ShareGPT görünümlerinde zaten gerçek
    assistant mesajı olarak bulunur. xLAM'in ``answers`` alanı no-call doğal
    dil hedefini temsil edemediğinden kayıpsızlık için burada da taşınır.

    ``thinking`` ham/gizli chain-of-thought değildir; yalnız eski veri
    dönüştürücülerinin beklediği uyumluluk takma adıdır.
    """
    return {
        "reasoning_summary_tr": example.reasoning_summary_tr,
        "thinking": example.reasoning_summary_tr,
        "assistant_response_tr": example.ground_truth.assistant_response_tr,
        "final_response_tr": example.ground_truth.final_response_tr,
        "final_response_source": example.ground_truth.final_response_source,
        "trajectory_complete": (
            example.scenario.decision is not Decision.TOOL_CALL
            or example.ground_truth.final_response_tr is not None
        ),
    }


def _openai_messages(messages_source: Iterable[Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for message in messages_source:
        if message.role is MessageRole.TOOL:
            messages.append(
                {"role": "tool", "name": message.tool_name, "content": message.content or ""}
            )
            continue
        entry: dict[str, Any] = {"role": message.role.value}
        if message.content is not None:
            entry["content"] = message.content
        if message.tool_calls:
            entry["tool_calls"] = [
                {
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": canonical_json(call.arguments),
                    },
                }
                for call in message.tool_calls
            ]
        messages.append(entry)
    return messages


def _openai_payload(
    example: Example,
    *,
    messages: list[dict[str, Any]],
    view: str,
) -> dict[str, Any]:
    return {
        "id": example.id,
        "messages": messages,
        "tools": [_tool_schema(tool) for tool in example.tools],
        # Sohbet şemasına sığmayan alanlar yan alanda taşınır.
        "toolcall_tr": {
            "view": view,
            "split": example.split.value,
            "family_id": example.family_id,
            "decision": example.scenario.decision.value,
            "interaction_type": example.scenario.interaction_type,
            "execution_classes": [c.value for c in example.execution.execution_classes],
            **_supervision_sidecar(example),
            "provenance": _provenance(example),
        },
    }


def to_openai(example: Example) -> dict[str, Any]:
    """Geriye uyumlu OpenAI görünümü; canonical mesajları olduğu gibi taşır."""
    return _openai_payload(
        example,
        messages=_openai_messages(example.messages),
        view="canonical_messages",
    )


def to_openai_call_only(example: Example) -> dict[str, Any]:
    """İlk tool seçim kararını öğreten, observation/final içermeyen görünüm.

    Sequential trajectory'de sonraki çağrı önceki observation'a bağlıdır; bu
    yüzden call-only görünüm yalnız ilk asistan tool-call grubunda durur.
    """
    selected = []
    for message in example.messages:
        selected.append(message)
        if message.role is MessageRole.ASSISTANT and message.tool_calls:
            break
    return _openai_payload(
        example,
        messages=_openai_messages(selected),
        view="call_only",
    )


def to_openai_trajectory(example: Example) -> dict[str, Any]:
    """Tool observation ve gözleme dayalı final cevabı içeren tam görünüm."""
    if (
        example.scenario.decision is Decision.TOOL_CALL
        and example.ground_truth.final_response_tr is None
    ):
        raise ValueError(f"{example.id}: tam trajectory exportu final_response_tr gerektirir")
    return _openai_payload(
        example,
        messages=_openai_messages(example.messages),
        view="trajectory",
    )


def to_xlam(example: Example) -> dict[str, Any]:
    """xLAM `query` / `tools` / `answers` biçimi.

    Negatif senaryolarda ``answers`` boş kalır ve karar yan alanda taşınır:
    xLAM şemasında "çağırma" diye bir cevap yoktur, bu yüzden bilgiyi
    kaybetmemek için ayrıca yazılır.
    """
    return {
        "id": example.id,
        "query": example.user_message,
        "tools": canonical_json(
            [
                {
                    "name": tool.name,
                    "description": tool.description_tr,
                    "parameters": {
                        param.name: {
                            "type": param.type,
                            "description": param.description_tr,
                            **({"default": param.default} if param.has_default else {}),
                        }
                        for param in tool.parameters
                    },
                }
                for tool in example.tools
            ]
        ),
        "answers": canonical_json(
            [
                {"name": call.name, "arguments": call.arguments}
                for call in example.ground_truth.calls
            ]
        ),
        "toolcall_tr": {
            "view": "call_only",
            "decision": example.scenario.decision.value,
            "interaction_type": example.scenario.interaction_type,
            "missing_parameters": list(example.ground_truth.missing_parameters),
            "split": example.split.value,
            "family_id": example.family_id,
            **_supervision_sidecar(example),
            "provenance": _provenance(example),
        },
    }


def to_sharegpt(example: Example) -> dict[str, Any]:
    """ShareGPT `conversations` biçimi."""
    role_map = {
        MessageRole.SYSTEM: "system",
        MessageRole.USER: "human",
        MessageRole.ASSISTANT: "gpt",
        MessageRole.TOOL: "observation",
    }

    conversations: list[dict[str, str]] = []
    for message in example.messages:
        if message.tool_calls:
            value = canonical_json(
                [{"name": c.name, "arguments": c.arguments} for c in message.tool_calls]
            )
        else:
            value = message.content or ""
        conversations.append({"from": role_map[message.role], "value": value})

    return {
        "id": example.id,
        "conversations": conversations,
        "tools": canonical_json([_tool_schema(tool)["function"] for tool in example.tools]),
        "toolcall_tr": {
            "view": "trajectory",
            "split": example.split.value,
            "family_id": example.family_id,
            "decision": example.scenario.decision.value,
            "interaction_type": example.scenario.interaction_type,
            **_supervision_sidecar(example),
            "provenance": _provenance(example),
        },
    }


def to_hf_chat(example: Example) -> dict[str, Any]:
    """Hugging Face sohbet şeması: her mesajda sabit bir alan kümesi.

    OpenAI görünümünden farkı, alanların **mesaj başına sabit** olmasıdır:
    ``content``, ``images``, ``role``, ``thinking``, ``tool_calls`` her
    mesajda bulunur ve kullanılmayanlar ``None`` kalır. Bu, sütun tipi sabit
    olduğu için Arrow/`datasets` tarafında şema çıkarımını basitleştirir.

    ``thinking`` **ham düşünce zinciri değildir**; `reasoning_summary_tr`
    yani kısa ve denetlenebilir karar özetidir ve yalnızca ilk tool-call
    kararını taşıyan assistant mesajına yazılır. Özet üretilmemişse ``None``
    kalır -- uydurulmaz.

    ``tool`` mesajlarına ayrıca ``name`` yazılır: HF şemasında tool adı için
    ayrı bir alan yoktur ve `parallel_tool_call` örneklerinde hangi sonucun
    hangi çağrıya ait olduğu aksi hâlde kaybolurdu.
    """
    reasoning_written = False
    messages: list[dict[str, Any]] = []

    for message in example.messages:
        entry: dict[str, Any] = {
            "content": message.content,
            "images": None,
            "role": message.role.value,
            "thinking": None,
            "tool_calls": None,
        }
        if message.tool_calls:
            entry["tool_calls"] = [
                {
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": canonical_json(call.arguments),
                    },
                }
                for call in message.tool_calls
            ]
            if not reasoning_written:
                entry["thinking"] = example.reasoning_summary_tr
                reasoning_written = True
        if message.role is MessageRole.TOOL:
            entry["name"] = message.tool_name
        messages.append(entry)

    return {
        "id": example.id,
        "messages": messages,
        "tools": [_tool_schema(tool) for tool in example.tools],
        "toolcall_tr": {
            "view": "hf_chat",
            "split": example.split.value,
            "family_id": example.family_id,
            "decision": example.scenario.decision.value,
            "interaction_type": example.scenario.interaction_type,
            "execution_classes": [c.value for c in example.execution.execution_classes],
            **_supervision_sidecar(example),
            "provenance": _provenance(example),
        },
    }


def to_canonical_jsonl(examples: Iterable[Example]) -> str:
    """Canonical biçim — kayıpsız, yeniden yüklenebilir.

    `Example.model_validate` ile birebir geri yüklenir; round-trip testi bunu
    zorlar.
    """
    return "".join(
        json.dumps(example.model_dump(mode="json"), sort_keys=True, ensure_ascii=False) + "\n"
        for example in examples
    )


#: `toolcall-tr export --format <ad>` ile eşleşen kayıt.
EXPORTERS = {
    "openai": to_openai,
    "openai_call_only": to_openai_call_only,
    "openai_trajectory": to_openai_trajectory,
    "xlam": to_xlam,
    "sharegpt": to_sharegpt,
    "hf_chat": to_hf_chat,
}


def decision_is_call(example: Example) -> bool:
    return example.scenario.decision is Decision.TOOL_CALL
