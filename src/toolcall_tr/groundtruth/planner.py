"""Faz A — Planner. Blueprint'i doğrulanmış bir çağrı DAG'ına derler.

**Gerçek derleyici burasıdır.** Spec'in tek bir ``compile_ground_truth()``
fonksiyonu yanlış bir soyutlamaydı: adımlar arası referansları çözmek
çalıştırma gerektirir, dolayısıyla "derleme" yan etkili olurdu. Bu yüzden
üretim üçe bölünmüştür ve bu faz **saftır**:

* ağ yok, cassette yok, mock yok, saat yok,
* tüm hard-fail'ler burada,
* tamamen unit test edilebilir.

Yakalanan hatalar (hepsi tek geçişte toplanır, ilk hatada durulmaz):

``unknown_tool``
    Registry'de olmayan tool. Bilinen tool oranı sıfır toleranslıdır.
``unknown_parameter``
    Şemada olmayan argüman.
``missing_required_parameter``
    Zorunlu parametre ne sabit değer ne referans olarak verilmiş.
``type_mismatch``
    Sabit değerin tipi şemayla uyuşmuyor.
``invalid_reference``
    ``$actions[i].result.x`` ileri/kendine referans veriyor ya da hedef
    tool'un **output şemasında beyan edilmemiş** bir alana işaret ediyor.
``semantic_type_mismatch``
    Referansın ürettiği semantik tip, hedef parametrenin beklediğiyle
    uyuşmuyor (ör. bir ``package_id`` bir ``resource_id`` yerine geçemez).

Son madde, elle yazılmış function graph yerine ``semantic_type`` kullanmanın
bedava kazançlarından biridir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from toolcall_tr.models import (
    Blueprint,
    CallPlan,
    Decision,
    ExpectedAction,
    LiteralArg,
    PlannedCall,
    StepRefArg,
    ToolSpec,
)
from toolcall_tr.models.args import ArgValue
from toolcall_tr.registry.registry import ToolRegistry
from toolcall_tr.schema import type_matches

__all__ = ["PlanIssue", "PlanningError", "normalize_ref_path", "plan", "try_plan"]

#: Somut dizin ``[0]`` -> koleksiyon işareti ``[*]``. Output şemaları
#: koleksiyonları ``[*]`` ile beyan eder; referanslar somut indeks kullanır.
_INDEX_RE = re.compile(r"\[\d+\]")


def normalize_ref_path(path: str) -> str:
    """``result.results[0].id`` -> ``result.results[*].id``."""
    return _INDEX_RE.sub("[*]", path)


@dataclass(frozen=True, slots=True)
class PlanIssue:
    """Tek bir planlama hatası."""

    code: str
    message_tr: str
    step_index: int | None = None
    field: str | None = None

    def __str__(self) -> str:
        location = ""
        if self.step_index is not None:
            location = f"adım {self.step_index}"
            if self.field:
                location += f", {self.field!r}"
            location = f"[{location}] "
        elif self.field:
            location = f"[{self.field!r}] "
        return f"{location}{self.code}: {self.message_tr}"


class PlanningError(ValueError):
    """Blueprint çalıştırılabilir bir plana derlenemedi.

    Bu bir **build hatasıdır**: gürültülü patlar, asla veriye dönüşmez.
    """

    def __init__(self, blueprint_id: str, issues: list[PlanIssue]) -> None:
        self.blueprint_id = blueprint_id
        self.issues = issues
        detail = "\n  ".join(str(issue) for issue in issues)
        super().__init__(f"{blueprint_id}: {len(issues)} planlama hatası\n  {detail}")


@dataclass(slots=True)
class _Context:
    registry: ToolRegistry
    issues: list[PlanIssue] = field(default_factory=list)

    def add(
        self,
        code: str,
        message: str,
        *,
        step_index: int | None = None,
        field_name: str | None = None,
    ) -> None:
        self.issues.append(
            PlanIssue(code=code, message_tr=message, step_index=step_index, field=field_name)
        )


def try_plan(
    blueprint: Blueprint, registry: ToolRegistry
) -> tuple[CallPlan | None, list[PlanIssue]]:
    """Planlar ve **tüm** sorunları toplar.

    İlk hatada durmak, bir blueprint'in kaç ayrı sebeple hatalı olduğunu
    gizlerdi; rapor üretimi için hepsi gerekir.
    """
    ctx = _Context(registry=registry)

    for tool_id in blueprint.available_tools:
        if tool_id not in registry:
            ctx.add(
                "unknown_tool",
                f"sunulan tool registry'de yok: {tool_id!r}",
                field_name=tool_id,
            )

    steps: list[PlannedCall] = []
    for index, action in enumerate(blueprint.expected_actions):
        planned = _plan_step(ctx, blueprint, index, action)
        if planned is not None:
            steps.append(planned)

    if ctx.issues:
        return None, ctx.issues

    try:
        plan_obj = CallPlan(
            blueprint_id=blueprint.blueprint_id,
            blueprint_hash=blueprint.content_hash(),
            registry_hash=registry.content_hash(),
            decision=blueprint.expected_behavior.decision,
            expected_behavior=blueprint.expected_behavior,
            available_tools=blueprint.available_tools,
            steps=tuple(steps),
        )
    except ValueError as exc:
        # `CallPlan` doğrulayıcıları son savunma hattı; buraya düşmek
        # planner'da bir boşluk olduğu anlamına gelir.
        ctx.add("invalid_plan", str(exc))
        return None, ctx.issues

    return plan_obj, []


def plan(blueprint: Blueprint, registry: ToolRegistry) -> CallPlan:
    """Planlar; hata varsa `PlanningError` fırlatır."""
    plan_obj, issues = try_plan(blueprint, registry)
    if plan_obj is None:
        raise PlanningError(blueprint.blueprint_id, issues)
    return plan_obj


def _plan_step(
    ctx: _Context,
    blueprint: Blueprint,
    index: int,
    action: ExpectedAction,
) -> PlannedCall | None:
    tool = ctx.registry.get(action.tool_id)
    if tool is None:
        ctx.add(
            "unknown_tool",
            f"registry'de olmayan tool çağrılıyor: {action.tool_id!r}",
            step_index=index,
        )
        return None

    for name, value in sorted(action.arguments.items()):
        _check_argument(ctx, blueprint, index, tool, name, value)

    provided = set(action.arguments)
    for param in tool.required_parameters:
        if param.name not in provided:
            ctx.add(
                "missing_required_parameter",
                f"{tool.tool_id}: zorunlu parametre verilmemiş: {param.name!r}",
                step_index=index,
                field_name=param.name,
            )

    depends_on = tuple(
        sorted({a.step_index for a in action.arguments.values() if isinstance(a, StepRefArg)})
    )

    try:
        return PlannedCall(
            step_index=index,
            step_id=f"{blueprint.blueprint_id}_s{index}",
            tool_id=action.tool_id,
            arguments=dict(action.arguments),
            depends_on=depends_on,
            expect=action.expect,
        )
    except ValueError as exc:
        ctx.add("invalid_step", str(exc), step_index=index)
        return None


def _check_argument(
    ctx: _Context,
    blueprint: Blueprint,
    index: int,
    tool: ToolSpec,
    name: str,
    value: ArgValue,
) -> None:
    param = tool.parameter(name)
    if param is None:
        available = ", ".join(p.name for p in tool.parameters) or "(yok)"
        ctx.add(
            "unknown_parameter",
            f"{tool.tool_id}: şemada olmayan parametre {name!r}. Mevcut: {available}",
            step_index=index,
            field_name=name,
        )
        return

    if isinstance(value, LiteralArg):
        if value.value is not None and not type_matches(param.type, value.value):
            ctx.add(
                "type_mismatch",
                f"{name!r}: beklenen tip {param.type}, verilen "
                f"{type(value.value).__name__} ({value.value!r})",
                step_index=index,
                field_name=name,
            )
        if param.enum is not None and value.value not in param.enum:
            ctx.add(
                "type_mismatch",
                f"{name!r}: izin verilen değerler {param.enum}, verilen {value.value!r}",
                step_index=index,
                field_name=name,
            )
        return

    _check_reference(ctx, blueprint, index, tool, name, value)


def _check_reference(
    ctx: _Context,
    blueprint: Blueprint,
    index: int,
    tool: ToolSpec,
    name: str,
    ref: StepRefArg,
) -> None:
    if ref.step_index >= index:
        ctx.add(
            "invalid_reference",
            f"{name!r}: ileri veya kendine referans (step_index={ref.step_index})",
            step_index=index,
            field_name=name,
        )
        return

    source_action = blueprint.expected_actions[ref.step_index]
    source_tool = ctx.registry.get(source_action.tool_id)
    if source_tool is None:
        # Kaynak adımın kendi hatası zaten raporlandı.
        return

    normalized = normalize_ref_path(ref.path)
    output = source_tool.output(normalized)
    if output is None:
        declared = ", ".join(o.path for o in source_tool.outputs) or "(yok)"
        ctx.add(
            "invalid_reference",
            f"{name!r}: {source_tool.tool_id} output şemasında {ref.path!r} "
            f"({normalized!r}) beyan edilmemiş. Beyan edilenler: {declared}",
            step_index=index,
            field_name=name,
        )
        return

    param = tool.parameter(name)
    if param is None:  # pragma: no cover - çağıran zaten kontrol etti
        return

    if (
        param.semantic_type is not None
        and output.semantic_type is not None
        and param.semantic_type != output.semantic_type
    ):
        ctx.add(
            "semantic_type_mismatch",
            f"{name!r}: {param.semantic_type!r} bekleniyor ama "
            f"{source_tool.tool_id}.{output.path} {output.semantic_type!r} üretiyor",
            step_index=index,
            field_name=name,
        )

    if not type_matches(param.type, _sample_for(output.type)):
        ctx.add(
            "type_mismatch",
            f"{name!r}: beklenen tip {param.type}, "
            f"{source_tool.tool_id}.{output.path} {output.type} üretiyor",
            step_index=index,
            field_name=name,
        )


def _sample_for(json_type: str) -> object:
    """Tip uyumunu statik kontrol etmek için temsilci değer."""
    return {
        "string": "",
        "integer": 0,
        "number": 0.0,
        "boolean": False,
        "array": [],
        "object": {},
    }[json_type]


def negative_plan(blueprint: Blueprint, registry: ToolRegistry) -> CallPlan:
    """Tool çağrısı beklenmeyen senaryolar için boş plan.

    `plan()` bunları zaten doğru işler; bu yardımcı yalnızca niyeti okunur
    kılmak içindir.
    """
    if blueprint.expected_behavior.decision is Decision.TOOL_CALL:
        raise ValueError("tool_call kararı için negative_plan kullanılamaz")
    return plan(blueprint, registry)
