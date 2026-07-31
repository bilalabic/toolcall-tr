"""Faz B — Runner. Planı bir ortamda çalıştırıp `Trace` üretir.

Determinizm burada kazanılır ya da kaybedilir. Dört kural:

**Saat donmuştur.**
    ``now`` `Environment`'tan gelir. ``datetime.now()`` çağıran bir kod,
    tarih içeren her ground-truth'u nondeterministik yapar -- flaky hash'lerin
    bir numaralı sebebi budur.

**Seed sıradan bağımsızdır.**
    ``episode_seed = sha256(root_seed + blueprint_id + variant_index)``.
    Çalışma sırasına göre ilerleyen global bir RNG, blueprint #21 eklendiğinde
    #1-20'nin verisini değiştirirdi.

**Beklenen hata bir plan çıktısıdır, istisna değil.**
    Runner kaydeder ve devam eder. Yalnızca *beklenmeyen* hata episode'u iptal
    eder. Dört hata sınıfı ayrı ele alınır; birleştirilirse pipeline çürür.

**Sembolik dry-run yoktur.**
    "Dry run" = ``cassette_mode=replay`` ile bu runner. Ayrı bir yan etkisiz
    execution yolu iki hafta içinde gerçek yoldan sapar.

Yeniden üretilebilirlik testi tek satırdır: planı iki taze ortamda çalıştır,
``trace_id`` eşitliğini iddia et.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from toolcall_tr.execution.cassette import CassetteTransport
from toolcall_tr.execution.executor import ExecutionResult, Executor
from toolcall_tr.models import (
    CallPlan,
    EnvironmentFingerprint,
    ExecutedCall,
    ExecutionClass,
    LiteralArg,
    PlannedCall,
    StateDelta,
    StepOutcome,
    StepRefArg,
    Trace,
)
from toolcall_tr.registry.registry import ToolRegistry
from toolcall_tr.seeds import episode_seed

__all__ = ["Environment", "ReferenceResolutionError", "episode_seed", "resolve_path", "run"]

_SEGMENT_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)|\[(\d+)\]")

#: Bu sonuçlar episode'u iptal eder ve **asla veriye dönüşmez**.
_ABORTING: frozenset[StepOutcome] = frozenset(
    {
        StepOutcome.UNEXPECTED_ERROR,
        StepOutcome.TRANSPORT_ERROR,
        StepOutcome.PLAN_ERROR,
        StepOutcome.NONDETERMINISM,
    }
)


class ReferenceResolutionError(LookupError):
    """`$actions[i].result.x` referansı çalışma anında çözülemedi.

    Plan **statik olarak** geçerliydi (alan output şemasında beyan edilmişti)
    ama gerçek yanıtta o alan yok -- ör. boş bir arama sonucunun ``[0]``
    elemanı. Bu bir blueprint hatasıdır: yazar ya sabit bir fixture kimliği
    kullanmalı ya da senaryoyu düzeltmelidir.
    """


def resolve_path(payload: Any, path: str) -> Any:
    """``result.results[0].name`` yolunu yanıt gövdesinde çözer.

    JSONPath'in tamamı kasıtlı olarak desteklenmez: filtre ifadeleri ve
    joker'ler ground-truth'u belirsizleştirir.
    """
    current = payload
    for match in _SEGMENT_RE.finditer(path):
        key, index = match.group(1), match.group(2)
        if key is not None:
            if not isinstance(current, Mapping) or key not in current:
                raise ReferenceResolutionError(
                    f"{path!r}: {key!r} anahtarı yanıtta yok (bulunan: {type(current).__name__})"
                )
            current = current[key]
        else:
            position = int(index or 0)
            if not isinstance(current, Sequence) or isinstance(current, str | bytes):
                raise ReferenceResolutionError(
                    f"{path!r}: [{position}] için liste bekleniyordu, "
                    f"{type(current).__name__} bulundu"
                )
            if position >= len(current):
                raise ReferenceResolutionError(
                    f"{path!r}: liste {len(current)} elemanlı, [{position}] istendi "
                    "-- boş veya beklenenden kısa sonuç"
                )
            current = current[position]
    return current


@dataclass(slots=True)
class Environment:
    """Çalıştırma ortamı. Açıkça kurulur ve geçirilir; global durum yoktur."""

    registry: ToolRegistry
    #: Sağlayıcı adı -> executor.
    executors: Mapping[str, Executor]
    #: **Donmuş** saat. Göreli tarih ifadeleri buna göre çözülür.
    now: datetime
    root_seed: int
    fingerprint: EnvironmentFingerprint
    #: Episode başında sıralı yanıt imleçleri sıfırlanır.
    cassettes: tuple[CassetteTransport, ...] = ()
    #: Bu çalıştırmada tüketilen cassette anahtarları -- yetim tespiti için.
    used_cassette_keys: set[str] = field(default_factory=set)

    def executor_for(self, provider: str) -> Executor:
        executor = self.executors.get(provider)
        if executor is None:
            available = ", ".join(sorted(self.executors)) or "(yok)"
            raise KeyError(f"{provider!r} sağlayıcısı için executor yok. Mevcut: {available}")
        return executor

    def begin_episode(self, seed: int) -> None:
        for cassette in self.cassettes:
            cassette.reset_cursors()
        seen: set[int] = set()
        for executor in self.executors.values():
            if id(executor) in seen:
                continue
            seen.add(id(executor))
            begin = getattr(executor, "begin_episode", None)
            if callable(begin):
                begin(seed)

    def state_delta(self) -> StateDelta | None:
        """Bütün stateful executor'ların episode farklarını tek delta'da birleştirir."""
        seen: set[int] = set()
        found_stateful = False
        ops = []
        volatile_fields: list[str] = []
        for executor in self.executors.values():
            if id(executor) in seen:
                continue
            seen.add(id(executor))
            get_delta = getattr(executor, "state_delta", None)
            if callable(get_delta):
                found_stateful = True
                delta = get_delta()
                ops.extend(delta.ops)
                volatile_fields.extend(delta.volatile_fields)
        if not found_stateful:
            return None
        return StateDelta(
            ops=tuple(ops),
            volatile_fields=tuple(dict.fromkeys(volatile_fields)),
        )

    def cassette_payloads(self, keys: Sequence[str]) -> dict[str, Any]:
        """Belirli cassette anahtarlarının ham gövdelerini validator'a hazırla."""
        payloads: dict[str, Any] = {}
        for cassette in self.cassettes:
            payloads.update(cassette.payloads_for(keys))
        return payloads


def run(plan: CallPlan, env: Environment, *, variant_index: int = 0) -> Trace:
    """Planı çalıştırır ve `Trace` üretir.

    Aynı plan + aynı seed + aynı cassette seti daima aynı ``trace_id``
    üretmelidir.
    """
    seed = episode_seed(env.root_seed, plan.blueprint_id, variant_index)
    env.begin_episode(seed)

    executed: list[ExecutedCall] = []
    responses: dict[int, Any] = {}
    aborted = False

    for step in plan.steps:
        if aborted:
            executed.append(_skipped(step, env))
            continue

        call = _run_step(step, env, responses)
        executed.append(call)
        if call.outcome in _ABORTING:
            aborted = True
        elif call.outcome is StepOutcome.OK:
            responses[step.step_index] = call.response
        if call.cassette_key is not None:
            env.used_cassette_keys.add(call.cassette_key)

    has_simulated = any(step.execution_class is ExecutionClass.SIMULATED for step in executed)
    return Trace(
        blueprint_id=plan.blueprint_id,
        plan_hash=plan.plan_hash(),
        episode_seed=seed,
        variant_index=variant_index,
        steps=tuple(executed),
        # Read-only sağlayıcılarda state yoktur. Ortam parmak izi ayrı alandadır.
        state_delta=env.state_delta() if has_simulated else None,
        environment=env.fingerprint,
        outcome=_overall(executed),
    )


def _skipped(step: PlannedCall, env: Environment) -> ExecutedCall:
    tool = env.registry.require(step.tool_id)
    return ExecutedCall(
        step_index=step.step_index,
        step_id=step.step_id,
        tool_id=step.tool_id,
        execution_class=tool.execution_class,
        arguments={},
        outcome=StepOutcome.SKIPPED,
        error="önceki adım başarısız olduğu için atlandı",
    )


def _run_step(step: PlannedCall, env: Environment, responses: dict[int, Any]) -> ExecutedCall:
    tool = env.registry.require(step.tool_id)

    try:
        arguments = _resolve_arguments(step, responses)
    except ReferenceResolutionError as exc:
        return ExecutedCall(
            step_index=step.step_index,
            step_id=step.step_id,
            tool_id=step.tool_id,
            execution_class=tool.execution_class,
            arguments={},
            outcome=StepOutcome.PLAN_ERROR,
            error=str(exc),
        )

    result = env.executor_for(tool.provider).execute(tool, arguments)
    outcome = _classify(step, result)

    return ExecutedCall(
        step_index=step.step_index,
        step_id=step.step_id,
        tool_id=step.tool_id,
        execution_class=result.execution_class,
        arguments=result.arguments,
        outcome=outcome,
        status_code=result.status_code,
        response=result.response if outcome is StepOutcome.OK else None,
        error=_error_for(outcome, step, result),
        cassette_key=result.cassette_key,
        raw_response_hash=result.raw_response_hash,
        latency_ms=result.latency_ms,
        state_hash_before=result.state_hash_before,
        state_hash_after=result.state_hash_after,
    )


def _resolve_arguments(step: PlannedCall, responses: dict[int, Any]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for name, value in step.arguments.items():
        if isinstance(value, LiteralArg):
            resolved[name] = value.value
            continue
        resolved[name] = _resolve_reference(name, value, responses)
    return resolved


def _resolve_reference(name: str, ref: StepRefArg, responses: dict[int, Any]) -> Any:
    if ref.step_index not in responses:
        raise ReferenceResolutionError(
            f"{name!r}: adım {ref.step_index} başarılı bir sonuç üretmedi"
        )
    return resolve_path(responses[ref.step_index], ref.path)


def _classify(step: PlannedCall, result: ExecutionResult) -> StepOutcome:
    """Executor sonucunu **beklentiyle** karşılaştırır.

    Executor "başarılı mı?" sorusunu cevaplar; "beklenen bu muydu?" sorusunu
    burada cevaplarız. Bir 404, plan onu bekliyorsa ground-truth'un kendisidir.
    """
    if result.outcome in {StepOutcome.TRANSPORT_ERROR, StepOutcome.PLAN_ERROR}:
        return result.outcome

    if step.expect.outcome == "ok":
        return StepOutcome.OK if result.outcome is StepOutcome.OK else StepOutcome.UNEXPECTED_ERROR

    # Hata bekleniyordu.
    if result.outcome is StepOutcome.OK:
        return StepOutcome.UNEXPECTED_ERROR
    if step.expect.status_code is not None and result.status_code != step.expect.status_code:
        return StepOutcome.UNEXPECTED_ERROR
    return StepOutcome.EXPECTED_ERROR


def _error_for(outcome: StepOutcome, step: PlannedCall, result: ExecutionResult) -> str | None:
    if outcome is StepOutcome.OK:
        return None
    if outcome is StepOutcome.UNEXPECTED_ERROR and step.expect.outcome == "error":
        if result.outcome is StepOutcome.OK:
            return f"hata bekleniyordu (status={step.expect.status_code}) ama çağrı başarılı oldu"
        return (
            f"beklenen durum kodu {step.expect.status_code}, "
            f"gelen {result.status_code}: {result.error}"
        )
    return result.error


def _overall(steps: Sequence[ExecutedCall]) -> StepOutcome:
    """Episode'un bütün sonucu.

    İptal ettiren bir sonuç varsa o kazanır; yoksa beklenen hata varsa o;
    yoksa başarı.
    """
    for step in steps:
        if step.outcome in _ABORTING:
            return step.outcome
    if any(step.outcome is StepOutcome.EXPECTED_ERROR for step in steps):
        return StepOutcome.EXPECTED_ERROR
    return StepOutcome.OK
