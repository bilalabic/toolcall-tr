"""ToolCall-TR komut satırı arayüzü.

Komutlar üç faza karşılık gelir::

    plan      Blueprint -> CallPlan          (saf, I/O yok)
    run       CallPlan  -> Trace             (I/O, seed altında deterministik)
    validate  Trace     -> ValidationResult  (saf)

`generate` üçünü tek adımda çalıştırır ve yayımlanabilir örnekleri yazar.

Varsayılan cassette modu **replay**'dir: hiçbir komut ağa çıkmaz. Kayıt,
kasıtlı ve açık bir eylemdir (`scripts/record_*.py`).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, cast

import typer
from rich.console import Console
from rich.table import Table

from toolcall_tr import __version__
from toolcall_tr.execution.cassette import CassetteStore, read_manifest_hash, write_manifest
from toolcall_tr.generation import (
    CanaryAllocation,
    CorpusBudgetConfig,
    GeneratedQuery,
    GeneralizationHoldoutConfig,
    QueryGenerator,
    RatioConstraint,
    TemplateQueryGenerator,
    allocate_canary,
    build_canary_gate,
    build_corpus_budget_report,
    build_generalization_report,
    build_release_artifact_manifest,
    rebalance_canary,
)
from toolcall_tr.generation.config import GenerationConfigError, load_generation_config
from toolcall_tr.generation.runtime import (
    GenerationRuntime,
    PaidAPINotAllowedError,
    build_generation_runtime,
)
from toolcall_tr.groundtruth.planner import try_plan
from toolcall_tr.groundtruth.runner import Environment
from toolcall_tr.groundtruth.runner import run as run_plan
from toolcall_tr.llm.budget import LLMBudgetExceededError
from toolcall_tr.llm.judge import (
    JudgeExecutionError,
    JudgeOutputError,
    JudgeResult,
    SemanticPolicyJudge,
)
from toolcall_tr.models import (
    Blueprint,
    CallPlan,
    Example,
    Severity,
    Split,
    Trace,
    ValidationResult,
)
from toolcall_tr.pipeline.assemble import assemble_example
from toolcall_tr.pipeline.blueprints import load_blueprints, split_report
from toolcall_tr.pipeline.environment import build_default_registry, open_default_environment
from toolcall_tr.serialize import EXPORTERS, to_canonical_jsonl
from toolcall_tr.validation import (
    ValidationPipeline,
    ValidationSubject,
    build_default_pipeline,
)

for stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")

console = Console(legacy_windows=False)

app = typer.Typer(
    name="toolcall-tr",
    help="Doğrulanabilir Türkçe tool-calling veri üretim pipeline'ı.",
    no_args_is_help=True,
    add_completion=False,
)

cassette_app = typer.Typer(
    name="cassette", help="Cassette kayıtlarını yönet.", no_args_is_help=True
)
app.add_typer(cassette_app)

REPO_ROOT = Path.cwd()

BlueprintDir = Annotated[Path, typer.Option("--blueprints", help="Blueprint YAML dizini.")]
OutDir = Annotated[Path, typer.Option("--out", help="Çıktı dizini.")]


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _load(directory: Path) -> tuple[Blueprint, ...]:
    if not directory.is_dir():
        console.print(f"[red]Blueprint dizini yok:[/red] {directory}")
        raise typer.Exit(code=2)
    blueprints = load_blueprints(directory)
    if not blueprints:
        console.print(f"[red]Dizinde blueprint bulunamadı:[/red] {directory}")
        raise typer.Exit(code=2)
    return blueprints


@app.command()
def version() -> None:
    """Sürüm bilgisini yazdır."""
    console.print(f"toolcall-tr {__version__}")


@app.command("build-registry")
def build_registry_command(
    out: Annotated[Path, typer.Option("--out")] = Path("registry"),
) -> None:
    """Tool registry'sini ve **türetilmiş** kompozisyon grafiğini yazar."""
    registry = build_default_registry()
    out.mkdir(parents=True, exist_ok=True)

    (out / "tools.jsonl").write_text(registry.to_jsonl(), encoding="utf-8", newline="\n")
    _write_json(
        out / "function_graph.json",
        {
            "_note": (
                "Bu graph ELLE YAZILMAZ; tool parametre ve output alanlarındaki "
                "`semantic_type` eşleşmesinden türetilir."
            ),
            "semantic_types": list(registry.semantic_types()),
            "edges": [edge.to_json() for edge in registry.composition_edges()],
        },
    )
    _write_json(out / "registry_hash.json", {"registry_hash": registry.content_hash()})

    console.print(f"[green]{len(registry)} tool[/green] -> {out}")
    console.print(f"  kompozisyon kenarı: {len(registry.composition_edges())}")
    console.print(f"  registry hash     : {registry.content_hash()}")


@app.command()
def plan(
    blueprints: BlueprintDir = Path("data/blueprints"),
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Blueprint'leri doğrulanmış çağrı planlarına derler (ağ gerekmez)."""
    loaded = _load(blueprints)
    registry = build_default_registry()

    planned: list[dict[str, Any]] = []
    failures = 0
    for blueprint in loaded:
        compiled, issues = try_plan(blueprint, registry)
        if compiled is None:
            failures += 1
            console.print(f"[red]PLAN HATASI[/red] {blueprint.blueprint_id}")
            for issue in issues:
                console.print(f"    {issue}")
            continue
        planned.append(compiled.model_dump(mode="json"))

    console.print(f"\n[green]{len(planned)} plan[/green], [red]{failures} hata[/red]")

    if out is not None and not failures:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "".join(json.dumps(p, sort_keys=True, ensure_ascii=False) + "\n" for p in planned),
            encoding="utf-8",
            newline="\n",
        )
        console.print(f"-> {out}")

    if failures:
        raise typer.Exit(code=1)


@app.command()
def generate(
    blueprints: BlueprintDir = Path("data/blueprints"),
    out: OutDir = Path("data"),
    reports: Annotated[Path, typer.Option("--reports")] = Path("reports"),
    variants: Annotated[int, typer.Option("--variants", help="Blueprint başına varyant.")] = 1,
    config: Annotated[Path, typer.Option("--config")] = Path("configs/generation.yaml"),
    generator_provider: Annotated[
        str,
        typer.Option(
            "--generator",
            help="'config', 'template' veya 'openai'. OpenAI yalnız doğal dili üretir.",
        ),
    ] = "config",
    judge: Annotated[
        bool,
        typer.Option(
            "--judge/--no-judge",
            help="gpt-5-mini semantik, politika, kapasite ve doğallık hakemi.",
        ),
    ] = False,
    allow_paid_api: Annotated[
        bool,
        typer.Option("--allow-paid-api", help="Ücretli OpenAI çağrılarını bilerek etkinleştir."),
    ] = False,
) -> None:
    """Uçtan uca üretim: planla, çalıştır, ifade üret, doğrula, yaz.

    Reddedilen örnekler **gerekçesiyle** saklanır; sessizce silinmez.
    """
    loaded = _load(blueprints)
    registry = build_default_registry()
    runtime = _resolve_generation_runtime(
        config=config,
        generator_provider=generator_provider,
        judge=judge,
        allow_paid_api=allow_paid_api,
    )
    if runtime.max_in_flight > 1:
        console.print(
            f"[cyan]OpenAI paralelliği:[/cyan] en fazla "
            f"{runtime.max_in_flight} eşzamanlı aday"
        )
    _require_template_capacity(
        runtime.generator,
        {
            blueprint.blueprint_id: (blueprint, variants)
            for blueprint in loaded
        },
    )
    pipeline = build_default_pipeline()
    created_at = datetime.now(UTC)
    git_sha = _git_sha()

    accepted: list[Example] = []
    rejected: list[dict[str, Any]] = []
    codes: Counter[str] = Counter()
    index = 0

    with open_default_environment(repo_root=REPO_ROOT) as env:
        for blueprint in loaded:
            compiled, issues = try_plan(blueprint, registry)
            if compiled is None:
                rejected.append(
                    {
                        "blueprint_id": blueprint.blueprint_id,
                        "stage": "plan",
                        "issues": [str(issue) for issue in issues],
                    }
                )
                codes.update(issue.code for issue in issues)
                continue

            for variant in range(variants):
                index += 1
                _process_variant(
                    blueprint=blueprint,
                    compiled=compiled,
                    variant=variant,
                    env=env,
                    generator=runtime.generator,
                    judge=runtime.judge,
                    pipeline=pipeline,
                    index=index,
                    created_at=created_at,
                    git_sha=git_sha,
                    accepted=accepted,
                    rejected=rejected,
                    codes=codes,
                )

        used_cassettes = set(env.used_cassette_keys)
        fingerprint = env.fingerprint

    _persist(out, reports, loaded, accepted, rejected, codes, used_cassettes, fingerprint)
    _persist_llm_report(reports, runtime, accepted)
    _print_summary(accepted, rejected, loaded)

    if not accepted:
        raise typer.Exit(code=1)


@app.command("generate-canary")
def generate_canary(
    blueprints: BlueprintDir = Path("data/blueprints"),
    out: OutDir = Path("data/canary"),
    reports: Annotated[Path, typer.Option("--reports")] = Path("reports/canary"),
    target: Annotated[int, typer.Option("--target", min=1)] = 100,
    max_candidates: Annotated[
        int | None,
        typer.Option(
            "--max-candidates",
            min=1,
            help="Retleri telafi etmek için üretilebilecek en fazla aday.",
        ),
    ] = None,
    profile: Annotated[
        Literal["smoke", "release"],
        typer.Option(
            "--profile",
            help="'smoke' yapısal boru hattını, 'release' tüm kalite kapılarını sınar.",
        ),
    ] = "smoke",
    holdout_profile: Annotated[
        Literal["standard", "unseen_tool", "unseen_provider"],
        typer.Option(
            "--holdout-profile",
            help="Train/test için standard, unseen_tool veya unseen_provider ayrıklığı.",
        ),
    ] = "standard",
    config: Annotated[Path, typer.Option("--config")] = Path("configs/generation.yaml"),
    generator_provider: Annotated[
        str,
        typer.Option("--generator", help="'config', 'template' veya 'openai'."),
    ] = "config",
    judge: Annotated[
        bool,
        typer.Option(
            "--judge/--no-judge",
            help="gpt-5-mini semantik, politika, kapasite ve doğallık hakemi.",
        ),
    ] = False,
    allow_paid_api: Annotated[
        bool,
        typer.Option("--allow-paid-api", help="Ücretli OpenAI çağrılarını bilerek etkinleştir."),
    ] = False,
) -> None:
    """Dengeli split bütçesiyle canary korpusu üret.

    Varsayılan 100 örnek; train/validation/test için tam olarak %70/%10/%20
    ayrılır. Her kayıt yeniden planlanır, cassette/snapshot üzerinde çalıştırılır
    ve normal validator zincirinden geçer. Template üretici yalnız smoke içindir;
    release profili semantik/politika/dil doğrulamasını zorunlu tutar.
    """
    if profile == "release" and not judge:
        console.print(
            "[red]Release profili --judge gerektirir:[/red] semantic_valid, "
            "policy_valid ve language_valid doğrulanmadan release üretilemez."
        )
        raise typer.Exit(code=2)

    candidate_limit = (
        max_candidates
        if max_candidates is not None
        else target + max(25, target // 8)
        if profile == "release"
        else target
    )
    if candidate_limit < target:
        console.print("[red]--max-candidates hedef örnek sayısından küçük olamaz.[/red]")
        raise typer.Exit(code=2)

    loaded = _load(blueprints)
    allocations = allocate_canary(loaded, target=target)
    expected_splits = Counter(
        cast(Split, allocation.blueprint.split).value for allocation in allocations
    )
    budget_config = _canary_budget_config(
        target=target,
        split_counts=expected_splits,
    )
    try:
        allocations = rebalance_canary(
            allocations,
            blueprints=loaded,
            budget=budget_config,
        )
    except ValueError as exc:
        console.print(f"[red]Canary kota planı oluşturulamadı:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    registry = build_default_registry()
    runtime = _resolve_generation_runtime(
        config=config,
        generator_provider=generator_provider,
        judge=judge,
        allow_paid_api=allow_paid_api,
    )
    requested_per_blueprint = Counter(
        allocation.blueprint.blueprint_id for allocation in allocations
    )
    _require_template_capacity(
        runtime.generator,
        {
            blueprint.blueprint_id: (
                blueprint,
                requested_per_blueprint[blueprint.blueprint_id],
            )
            for blueprint in loaded
        },
    )
    pipeline = build_default_pipeline(release=profile == "release")
    created_at = datetime.now(UTC)
    git_sha = _git_sha()
    run_id = created_at.strftime("%Y%m%dT%H%M%S%fZ")
    staging_root = reports.parent / ".runs" / f"{reports.name}-{run_id}"
    staging_out = staging_root / "data"
    staging_reports = staging_root / "reports"

    plans: dict[str, Any] = {}
    plan_failures: dict[str, list[str]] = {}
    for blueprint in loaded:
        compiled, issues = try_plan(blueprint, registry)
        if compiled is None:
            plan_failures[blueprint.blueprint_id] = [str(issue) for issue in issues]
        else:
            plans[blueprint.blueprint_id] = compiled

    accepted: list[Example] = []
    rejected: list[dict[str, Any]] = []
    codes: Counter[str] = Counter()

    with open_default_environment(repo_root=REPO_ROOT) as env:
        attempted, budget_stop_reason = _run_canary_allocations(
            allocations=allocations,
            plans=plans,
            plan_failures=plan_failures,
            env=env,
            runtime=runtime,
            pipeline=pipeline,
            profile=profile,
            candidate_limit=candidate_limit,
            created_at=created_at,
            git_sha=git_sha,
            accepted=accepted,
            rejected=rejected,
            codes=codes,
        )

        used_cassettes = set(env.used_cassette_keys)
        fingerprint = env.fingerprint

    _persist(
        staging_out,
        staging_reports,
        loaded,
        accepted,
        rejected,
        codes,
        used_cassettes,
        fingerprint,
    )
    _persist_llm_report(staging_reports, runtime, accepted)
    _write_exports(staging_out / "sft", accepted)
    budget = build_corpus_budget_report(
        accepted,
        budget_config,
    )
    _write_json(staging_reports / "corpus_budget_report.json", budget)
    budget_violations = budget["violations"]
    assert isinstance(budget_violations, list)
    generalization = build_generalization_report(
        accepted,
        GeneralizationHoldoutConfig(profile=holdout_profile),
    )
    _write_json(staging_reports / "generalization_report.json", generalization)
    generalization_violations = generalization["violations"]
    assert isinstance(generalization_violations, list)
    gate = build_canary_gate(
        profile=profile,
        target=target,
        accepted=accepted,
        rejected_count=len(rejected),
        budget_violations=budget_violations,
        finding_counts=codes,
        generalization_violations=generalization_violations,
    )
    gate["holdout_profile"] = holdout_profile
    gate["split"] = dict(Counter(example.split.value for example in accepted))
    gate["attempted_candidates"] = attempted
    gate["max_candidates"] = candidate_limit
    gate["budget_stop_reason"] = budget_stop_reason
    gate["max_in_flight"] = runtime.max_in_flight
    _write_json(
        staging_reports / "canary_gate.json",
        gate,
    )
    _write_json(
        staging_reports / "artifact_manifest.json",
        build_release_artifact_manifest(
            training_paths=(
                staging_out / "accepted" / "examples.jsonl",
                staging_out / "sft" / "openai.jsonl",
                staging_out / "sft" / "openai_call_only.jsonl",
                staging_out / "sft" / "openai_trajectory.jsonl",
                staging_out / "sft" / "xlam.jsonl",
                staging_out / "sft" / "sharegpt.jsonl",
            ),
            report_paths=(
                staging_reports / "generation_report.json",
                staging_reports / "corpus_budget_report.json",
                staging_reports / "generalization_report.json",
                staging_reports / "canary_gate.json",
            ),
            relative_to=staging_root,
        ),
    )
    _print_summary(accepted, rejected, loaded)

    if not bool(gate["passed"]):
        release_detail = (
            f", release engeli={len(gate['release_blockers'])}"
            if profile == "release"
            else ""
        )
        console.print(
            f"[red]{profile.title()} canary eşiği geçilemedi:[/red] "
            f"hedef={target}, kabul={len(accepted)}, ret={len(rejected)}, "
            f"bütçe ihlali={len(budget_violations)}"
            f"{release_detail}"
        )
        console.print(
            f"[yellow]Başarısız koşu production çıktısına yazılmadı:[/yellow] "
            f"{staging_root}"
        )
        raise typer.Exit(code=1)

    _promote_tree(staging_out, out)
    _promote_tree(staging_reports, reports)
    if profile == "smoke":
        console.print(
            f"[green]Smoke canary geçti:[/green] {len(accepted)}/{target}; "
            "bu sonuç release onayı değildir."
        )
    else:
        console.print(f"[green]Release canary geçti:[/green] {len(accepted)}/{target}")


def _process_variant(
    *,
    blueprint: Blueprint,
    compiled: Any,
    variant: int,
    env: Environment,
    generator: QueryGenerator,
    judge: SemanticPolicyJudge | None,
    pipeline: Any,
    index: int,
    created_at: datetime,
    git_sha: str | None,
    accepted: list[Example],
    rejected: list[dict[str, Any]],
    codes: Counter[str],
    repair_feedback: tuple[str, ...] = (),
    judge_error_policy: Literal["reject", "fail"] = "fail",
) -> tuple[str, ...]:
    trace = run_plan(compiled, env, variant_index=variant)
    query = generator.generate(
        blueprint,
        variant_index=variant,
        root_seed=env.root_seed,
        repair_feedback=repair_feedback,
    )

    example = assemble_example(
        blueprint=blueprint,
        plan=compiled,
        trace=trace,
        query=query,
        env=env,
        index=index,
        created_at=created_at,
        git_sha=git_sha,
    )

    validation_subject = ValidationSubject(
        blueprint=blueprint,
        plan=compiled,
        trace=trace,
        tools=example.tools,
        example=example,
        cassette_payloads=env.cassette_payloads(
            [step.cassette_key for step in trace.steps if step.cassette_key is not None]
        ),
    )
    # Duplicate validator adayı ancak LLM hakemi de geçtikten sonra kabul
    # kümesine ekler. Judge tarafından reddedilen bir aday sonraki iyi adayı
    # "duplicate" diye zehirleyemez.
    result = pipeline.run(validation_subject, commit=False)
    codes.update(result.code_counts())

    if not result.accepted:
        issues = tuple(
            f"{finding.validator}/{finding.code}: {finding.message_tr}"
            for finding in result.errors
        )
        rejected.append(
            {
                "blueprint_id": blueprint.blueprint_id,
                "variant_index": variant,
                "stage": "validation",
                "trace_id": trace.trace_id(),
                "query": query.text,
                "reasoning_summary_tr": query.reasoning_summary_tr,
                "generator_usage": (
                    query.usage.model_dump(mode="json")
                    if query.usage is not None
                    else None
                ),
                "issues": list(issues),
            }
        )
        return issues

    try:
        judge_result = (
            judge.judge(
                blueprint,
                compiled,
                tools=example.tools,
                user_message=query.text,
                reasoning_summary_tr=query.reasoning_summary_tr,
            )
            if judge is not None
            else None
        )
    except (JudgeExecutionError, JudgeOutputError) as exc:
        if judge_error_policy == "fail":
            raise
        code = (
            "judge_execution_error"
            if isinstance(exc, JudgeExecutionError)
            else "judge_output_error"
        )
        codes[code] += 1
        issue = f"openai_semantic_policy_judge/{code}: {exc}"
        failed_response = exc.response
        rejected.append(
            {
                "blueprint_id": blueprint.blueprint_id,
                "variant_index": variant,
                "stage": "judge_error",
                "trace_id": trace.trace_id(),
                "query": query.text,
                "reasoning_summary_tr": query.reasoning_summary_tr,
                "generator_usage": (
                    query.usage.model_dump(mode="json")
                    if query.usage is not None
                    else None
                ),
                "judge_error": {
                    "type": type(exc).__name__,
                    "provider": (
                        failed_response.provider if failed_response is not None else None
                    ),
                    "model": (
                        failed_response.model if failed_response is not None else None
                    ),
                    "input_tokens": (
                        failed_response.input_tokens
                        if failed_response is not None
                        else None
                    ),
                    "output_tokens": (
                        failed_response.output_tokens
                        if failed_response is not None
                        else None
                    ),
                    "metadata": (
                        failed_response.metadata if failed_response is not None else {}
                    ),
                },
                "issues": [issue],
            }
        )
        # Altyapı hatası kullanıcı sorusundaki bir kusur değildir; sonraki
        # üretim isteğine anlamsal "onarım geri bildirimi" olarak taşınmaz.
        return ()
    judge_findings = (
        judge_result.to_findings(severity=Severity.ERROR) if judge_result is not None else ()
    )
    codes.update(finding.code for finding in judge_findings)
    if judge_findings:
        assert judge_result is not None
        issues = tuple(
            f"{finding.validator}/{finding.code}: {finding.message_tr}"
            for finding in judge_findings
        )
        rejected.append(
            {
                "blueprint_id": blueprint.blueprint_id,
                "variant_index": variant,
                "stage": "judge",
                "trace_id": trace.trace_id(),
                "query": query.text,
                "reasoning_summary_tr": query.reasoning_summary_tr,
                "generator_usage": (
                    query.usage.model_dump(mode="json")
                    if query.usage is not None
                    else None
                ),
                "judge_usage": judge_result.usage.model_dump(mode="json"),
                "issues": list(issues),
            }
        )
        return issues

    pipeline.commit(
        validation_subject,
        skip={finding.validator for finding in result.findings},
    )

    if judge_result is not None:
        example = example.model_copy(
            update={
                "provenance": example.provenance.model_copy(
                    update={"judge": judge_result.usage}
                )
            }
        )

    accepted.append(
        example.model_copy(
            update={
                "verification": example.verification.model_copy(
                    update={
                        "format_valid": True,
                        "schema_valid": True,
                        "registry_valid": True,
                        "argument_grounded": True,
                        "pii_clean": True,
                        "execution_valid": True,
                        "semantic_valid": (
                            judge_result.assessment.semantic_match
                            if judge_result is not None
                            else None
                        ),
                        "policy_valid": (
                            judge_result.assessment.policy_compliant
                            if judge_result is not None
                            else None
                        ),
                        "language_valid": (
                            judge_result.assessment.language_natural
                            if judge_result is not None
                            else None
                        ),
                    }
                )
            }
        )
    )
    return ()


def _resolve_generation_runtime(
    *,
    config: Path,
    generator_provider: str,
    judge: bool,
    allow_paid_api: bool,
) -> GenerationRuntime:
    if generator_provider not in {"config", "template", "openai"}:
        console.print(
            "[red]Geçersiz --generator:[/red] "
            f"{generator_provider}. Geçerli: config, template, openai"
        )
        raise typer.Exit(code=2)
    try:
        loaded_config = load_generation_config(config)
        provider = None if generator_provider == "config" else generator_provider
        return build_generation_runtime(
            loaded_config,
            provider=cast(Any, provider),
            judge_enabled=judge,
            allow_paid_api=allow_paid_api,
        )
    except (GenerationConfigError, PaidAPINotAllowedError, OSError, ValueError) as exc:
        console.print(f"[red]Üretim çalışma zamanı kurulamadı:[/red] {exc}")
        raise typer.Exit(code=2) from exc


def _require_template_capacity(
    generator: QueryGenerator,
    requests: dict[str, tuple[Blueprint, int]],
) -> None:
    """Şablon üreticisinin aynı soruları döndürerek hedefi doldurmasını engelle."""
    if not isinstance(generator, TemplateQueryGenerator):
        return

    exceeded = [
        (blueprint_id, requested, generator.capacity(blueprint))
        for blueprint_id, (blueprint, requested) in sorted(requests.items())
        if requested > generator.capacity(blueprint)
    ]
    if not exceeded:
        return

    details = ", ".join(
        f"{blueprint_id}: istenen={requested}, kapasite={capacity}"
        for blueprint_id, requested, capacity in exceeded[:5]
    )
    if len(exceeded) > 5:
        details += f", +{len(exceeded) - 5} blueprint"
    console.print(
        "[red]Şablon üretim kapasitesi aşıldı.[/red] "
        "Aynı soruları tekrar ederek hedef doldurulmayacak. "
        f"{details}"
    )
    raise typer.Exit(code=2)


def _persist_llm_report(
    reports: Path,
    runtime: GenerationRuntime,
    accepted: list[Example],
) -> None:
    if runtime.budget is None:
        return
    generator_cache_hits = sum(
        int(example.provenance.generator is not None and example.provenance.generator.cached)
        for example in accepted
    )
    judge_cache_hits = sum(
        int(example.provenance.judge is not None and example.provenance.judge.cached)
        for example in accepted
    )
    _write_json(
        reports / "llm_usage_report.json",
        {
            "provider": runtime.provider,
            "live_api": runtime.budget.report(),
            "accepted_local_cache_hits": {
                "generator": generator_cache_hits,
                "judge": judge_cache_hits,
            },
        },
    )


def _persist(
    out: Path,
    reports: Path,
    blueprints: tuple[Blueprint, ...],
    accepted: list[Example],
    rejected: list[dict[str, Any]],
    codes: Counter[str],
    used_cassettes: set[str],
    fingerprint: Any,
) -> None:
    accepted_path = out / "accepted" / "examples.jsonl"
    accepted_path.parent.mkdir(parents=True, exist_ok=True)
    accepted_path.write_text(to_canonical_jsonl(accepted), encoding="utf-8", newline="\n")

    _write_json(out / "rejected" / "rejected.json", rejected)

    total = len(accepted) + len(rejected)
    _write_json(
        reports / "generation_report.json",
        {
            "blueprints": len(blueprints),
            "examples_total": total,
            "accepted": len(accepted),
            "rejected": len(rejected),
            "yield_rate": round(len(accepted) / total, 4) if total else 0.0,
            "split": split_report(blueprints),
            "example_split": dict(Counter(e.split.value for e in accepted)),
            "decisions": dict(Counter(e.scenario.decision.value for e in accepted)),
            "kinds": dict(Counter(e.scenario.kind.value for e in accepted)),
            "execution_classes": dict(
                Counter(c.value for e in accepted for c in e.execution.execution_classes)
            ),
            "results": dict(Counter(e.scenario.expected_result for e in accepted)),
            "cassettes_used": len(used_cassettes),
            "environment": fingerprint.model_dump(mode="json"),
        },
    )
    _write_json(reports / "error_distribution.json", dict(codes.most_common()))
    _write_json(
        reports / "rejection_summary.json",
        {
            "rejected": len(rejected),
            "by_blueprint": dict(Counter(item["blueprint_id"] for item in rejected)),
        },
    )


def _write_exports(directory: Path, examples: list[Example]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, exporter in EXPORTERS.items():
        payload = "".join(
            json.dumps(exporter(example), sort_keys=True, ensure_ascii=False) + "\n"
            for example in examples
        )
        (directory / f"{name}.jsonl").write_text(payload, encoding="utf-8", newline="\n")


def _promote_tree(staging: Path, destination: Path) -> None:
    """Yalnız kapı geçtikten sonra staging ağacını görünür hedefe kopyala."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(staging, destination, dirs_exist_ok=True)


def _canary_budget_config(
    *,
    target: int,
    split_counts: Counter[str],
) -> CorpusBudgetConfig:
    """1k canary'nin yayın kapısı.

    Sınırlar mevcut pilotun dağılımını körlemesine kopyalamaz; negatif karar,
    tek ve iki adımlı çağrı, boş sonuç ve üç zorluk seviyesinin kaybolmasını
    engelleyen geniş ama anlamlı aralıklardır.
    """
    split_constraints = {
        split.value: RatioConstraint(
            minimum=split_counts[split.value] / target,
            maximum=split_counts[split.value] / target,
        )
        for split in Split
    }
    # Küçük smoke koşusunda 29 family, split başına round-robin dağıtılır.
    # Özellikle validation=10 ve test=20 olduğunda tek bir family iki-üç örnek
    # oynatabildiği için üretim hedeflerinden daha geniş tolerans gerekir.
    small_smoke = target <= 100
    decision_constraints = (
        {
            "tool_call": RatioConstraint(minimum=0.65, maximum=0.72),
            "clarification": RatioConstraint(minimum=0.04, maximum=0.12),
            "direct_answer": RatioConstraint(minimum=0.08, maximum=0.18),
            "cannot_answer": RatioConstraint(minimum=0.07, maximum=0.15),
        }
        if small_smoke
        else {
            "tool_call": RatioConstraint(minimum=0.68, maximum=0.72),
            "clarification": RatioConstraint(minimum=0.04, maximum=0.10),
            "direct_answer": RatioConstraint(minimum=0.08, maximum=0.16),
            "cannot_answer": RatioConstraint(minimum=0.07, maximum=0.13),
        }
    )
    call_count_constraints = (
        {
            "0": RatioConstraint(minimum=0.28, maximum=0.35),
            "1": RatioConstraint(minimum=0.45, maximum=0.55),
            "2": RatioConstraint(minimum=0.17, maximum=0.27),
            "3": RatioConstraint(minimum=0.01, maximum=0.04),
        }
        if small_smoke
        else {
            "0": RatioConstraint(minimum=0.28, maximum=0.33),
            "1": RatioConstraint(minimum=0.45, maximum=0.52),
            "2": RatioConstraint(minimum=0.19, maximum=0.27),
            "3": RatioConstraint(minimum=0.01, maximum=0.04),
        }
    )
    kind_constraints = {
        "successful_tool_call": RatioConstraint(minimum=0.30, maximum=0.50),
        "sequential_tool_call": RatioConstraint(minimum=0.08, maximum=0.20),
        "parallel_tool_call": RatioConstraint(minimum=0.05, maximum=0.09),
        "empty_result": RatioConstraint(minimum=0.02, maximum=0.08),
        "expected_error": RatioConstraint(minimum=0.06, maximum=0.08),
        "error_recovery": RatioConstraint(minimum=0.02, maximum=0.03),
        "confirmation_required": RatioConstraint(minimum=0.05, maximum=0.10),
        "user_cancellation": RatioConstraint(minimum=0.02, maximum=0.06),
    }
    return CorpusBudgetConfig(
        target_total=target,
        constraints={
            "split": split_constraints,
            "decision": decision_constraints,
            "kind": kind_constraints,
            "difficulty": {
                "easy": RatioConstraint(minimum=0.20),
                "medium": RatioConstraint(minimum=0.50),
                "hard": RatioConstraint(minimum=0.05),
            },
            "interaction_type": {
                "multi_turn": RatioConstraint(
                    minimum=0.12,
                    maximum=0.15,
                ),
            },
            "tool_call_count": call_count_constraints,
        },
    )


def _print_summary(
    accepted: list[Example], rejected: list[dict[str, Any]], blueprints: tuple[Blueprint, ...]
) -> None:
    table = Table(title="Üretim özeti")
    table.add_column("Ölçüt")
    table.add_column("Değer", justify="right")

    total = len(accepted) + len(rejected)
    table.add_row("blueprint", str(len(blueprints)))
    table.add_row("örnek", str(total))
    table.add_row("kabul", f"[green]{len(accepted)}[/green]")
    table.add_row("ret", f"[red]{len(rejected)}[/red]" if rejected else "0")

    counts = Counter(e.split.value for e in accepted)
    for split in Split:
        table.add_row(f"  {split.value}", str(counts.get(split.value, 0)))

    decisions = Counter(e.scenario.decision.value for e in accepted)
    for decision, count in sorted(decisions.items()):
        table.add_row(f"  karar: {decision}", str(count))

    console.print(table)
    for item in rejected:
        console.print(f"[red]RET[/red] {item['blueprint_id']}")
        for issue in item["issues"]:
            console.print(f"    {issue}")


@app.command()
def export(
    fmt: Annotated[str, typer.Option("--format", help=f"Biçim: {', '.join(EXPORTERS)}")],
    source: Annotated[Path, typer.Option("--in")] = Path("data/accepted/examples.jsonl"),
    out: Annotated[Path | None, typer.Option("--out")] = None,
) -> None:
    """Canonical veriyi hedef biçime çevirir. Canonical veri **değişmez**."""
    if fmt not in EXPORTERS:
        console.print(f"[red]Bilinmeyen biçim:[/red] {fmt}. Geçerli: {', '.join(EXPORTERS)}")
        raise typer.Exit(code=2)
    if not source.is_file():
        console.print(f"[red]Kaynak yok:[/red] {source}. Önce `toolcall-tr generate` çalıştırın.")
        raise typer.Exit(code=2)

    exporter = EXPORTERS[fmt]
    examples = [
        Example.model_validate(json.loads(line))
        for line in source.read_text(encoding="utf-8").splitlines()
        if line
    ]
    lines = "".join(
        json.dumps(exporter(example), sort_keys=True, ensure_ascii=False) + "\n"
        for example in examples
    )

    target = out or Path("data/sft") / f"{fmt}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(lines, encoding="utf-8", newline="\n")
    console.print(f"[green]{len(examples)} örnek[/green] -> {target} ({fmt})")


@app.command("quality-report")
def quality_report(reports: Annotated[Path, typer.Option("--reports")] = Path("reports")) -> None:
    """Üretim raporunu okunabilir biçimde özetler."""
    path = reports / "generation_report.json"
    if not path.is_file():
        console.print(f"[red]Rapor yok:[/red] {path}. Önce `toolcall-tr generate` çalıştırın.")
        raise typer.Exit(code=2)

    data = json.loads(path.read_text(encoding="utf-8"))
    table = Table(title="Kalite raporu")
    table.add_column("Ölçüt")
    table.add_column("Değer", justify="right")
    table.add_row("kabul oranı", f"{data['yield_rate']:.1%}")
    table.add_row("örnek", str(data["examples_total"]))
    table.add_row("blueprint", str(data["blueprints"]))
    table.add_row("family", str(data["split"]["family_count"]))
    leaked = data["split"]["leaked_families"]
    table.add_row(
        "split sızıntısı", "[green]yok[/green]" if not leaked else f"[red]{len(leaked)}[/red]"
    )
    for name, count in sorted(data["execution_classes"].items()):
        table.add_row(f"  {name}", str(count))
    console.print(table)

    if leaked:
        console.print(f"[red]Sızan family'ler:[/red] {leaked}")
        raise typer.Exit(code=1)


@cassette_app.command("verify")
def cassette_verify(
    root: Annotated[Path, typer.Option("--root")] = Path("data/cassettes"),
    blueprints: BlueprintDir = Path("data/blueprints"),
) -> None:
    """Kayıt bütünlüğünü denetler: eksik kayıt, yetim kayıt, manifest hash."""
    loaded = _load(blueprints)
    registry = build_default_registry()

    with open_default_environment(repo_root=REPO_ROOT) as env:
        for blueprint in loaded:
            compiled, _ = try_plan(blueprint, registry)
            if compiled is not None:
                run_plan(compiled, env)
        used = set(env.used_cassette_keys)

    problems = 0
    table = Table(title="Cassette denetimi")
    table.add_column("Sağlayıcı")
    table.add_column("Kayıt", justify="right")
    table.add_column("Yetim", justify="right")
    table.add_column("Lisans")

    for namespace in sorted(p.name for p in root.iterdir() if p.is_dir()):
        store = CassetteStore(root, namespace)
        orphans = store.orphans(used)
        problems += len(orphans)
        entries = [store.get(key) for key in sorted(store.keys())]
        licenses = {entry.metadata.get("license", "?") for entry in entries if entry is not None}
        table.add_row(
            namespace,
            str(len(store)),
            f"[yellow]{len(orphans)}[/yellow]" if orphans else "0",
            ", ".join(sorted(licenses)) or "-",
        )

    console.print(table)
    console.print(f"manifest hash: {read_manifest_hash(root)}")
    console.print(f"bu çalıştırmada kullanılan: {len(used)}")

    if problems:
        console.print(
            f"[yellow]{problems} yetim kayıt.[/yellow] Temizlemek için: toolcall-tr cassette prune"
        )


@cassette_app.command("prune")
def cassette_prune(
    root: Annotated[Path, typer.Option("--root")] = Path("data/cassettes"),
    blueprints: BlueprintDir = Path("data/blueprints"),
    yes: Annotated[bool, typer.Option("--yes", help="Onay sorma.")] = False,
) -> None:
    """Hiçbir örnek tarafından kullanılmayan kayıtları siler.

    Yetim kayıt yalnızca ölü ağırlık değildir: lisansı belirsiz kaynaklarda
    gereksiz yere dağıtım yüzeyi büyütür.
    """
    loaded = _load(blueprints)
    registry = build_default_registry()

    with open_default_environment(repo_root=REPO_ROOT) as env:
        for blueprint in loaded:
            compiled, _ = try_plan(blueprint, registry)
            if compiled is not None:
                run_plan(compiled, env)
        used = set(env.used_cassette_keys)

    stores = [CassetteStore(root, path.name) for path in sorted(root.iterdir()) if path.is_dir()]
    planned = {store.namespace: store.orphans(used) for store in stores}
    total = sum(len(orphans) for orphans in planned.values())

    if not total:
        console.print("[green]Yetim kayıt yok.[/green]")
        return

    for namespace, orphans in planned.items():
        console.print(f"  {namespace}: {len(orphans)} yetim")
    if not yes and not typer.confirm(f"{total} kayıt silinsin mi?"):
        console.print("İptal edildi.")
        raise typer.Exit(code=1)

    for store in stores:
        store.prune(used)
        store.save()

    digest = write_manifest(root, stores)
    console.print(f"[green]{total} kayıt silindi.[/green] Yeni manifest: {digest}")


@app.command()
def stats(blueprints: BlueprintDir = Path("data/blueprints")) -> None:
    """Blueprint korpusunun dağılımını gösterir."""
    loaded = _load(blueprints)

    table = Table(title=f"{len(loaded)} blueprint")
    table.add_column("Tür")
    table.add_column("Adet", justify="right")
    for kind, count in sorted(Counter(b.kind.value for b in loaded).items()):
        table.add_row(kind, str(count))
    console.print(table)

    report = split_report(loaded)
    console.print(f"bölme: {report['counts']}  family: {report['family_count']}")
    if report["leaked_families"]:
        console.print(f"[red]SIZINTI:[/red] {report['leaked_families']}")
        raise typer.Exit(code=1)
    console.print("[green]split sızıntısı yok[/green]")


@app.command()
def validate(
    blueprints: BlueprintDir = Path("data/blueprints"),
    reports: Annotated[Path, typer.Option("--reports")] = Path("reports"),
) -> None:
    """Korpusu doğrular ve rapor yazar (örnek dosyası yazmaz)."""
    loaded = _load(blueprints)
    registry = build_default_registry()
    generator = TemplateQueryGenerator()
    pipeline = build_default_pipeline()
    created_at = datetime.now(UTC)

    codes: Counter[str] = Counter()
    failures: list[str] = []

    with open_default_environment(repo_root=REPO_ROOT) as env:
        for index, blueprint in enumerate(loaded, start=1):
            compiled, issues = try_plan(blueprint, registry)
            if compiled is None:
                failures.append(blueprint.blueprint_id)
                codes.update(issue.code for issue in issues)
                continue

            trace = run_plan(compiled, env)
            query = generator.generate(blueprint, variant_index=0, root_seed=env.root_seed)
            example = assemble_example(
                blueprint=blueprint,
                plan=compiled,
                trace=trace,
                query=query,
                env=env,
                index=index,
                created_at=created_at,
            )
            result = pipeline.run(
                ValidationSubject(
                    blueprint=blueprint,
                    plan=compiled,
                    trace=trace,
                    tools=example.tools,
                    example=example,
                    cassette_payloads=env.cassette_payloads(
                        [
                            step.cassette_key
                            for step in trace.steps
                            if step.cassette_key is not None
                        ]
                    ),
                )
            )
            codes.update(result.code_counts())
            if not result.accepted:
                failures.append(blueprint.blueprint_id)
                for finding in result.errors:
                    console.print(
                        f"[red]{blueprint.blueprint_id}[/red] "
                        f"{finding.validator}/{finding.code}: {finding.message_tr}"
                    )

    _write_json(reports / "error_distribution.json", dict(codes.most_common()))
    console.print(
        f"\n{len(loaded) - len(failures)}/{len(loaded)} geçti; "
        f"rapor -> {reports / 'error_distribution.json'}"
    )
    if failures:
        raise typer.Exit(code=1)


@app.command("run")
def run_command(
    blueprints: BlueprintDir = Path("data/blueprints"),
    out: Annotated[Path, typer.Option("--out")] = Path("data/traces/traces.jsonl"),
) -> None:
    """Planları çalıştırır ve `Trace` kayıtlarını yazar."""
    loaded = _load(blueprints)
    registry = build_default_registry()
    traces: list[str] = []
    failures = 0

    with open_default_environment(repo_root=REPO_ROOT) as env:
        for blueprint in loaded:
            compiled, _ = try_plan(blueprint, registry)
            if compiled is None:
                failures += 1
                continue
            trace = run_plan(compiled, env)
            if not trace.is_usable:
                failures += 1
                console.print(f"[red]{blueprint.blueprint_id}[/red]: {trace.outcome.value}")
            traces.append(
                json.dumps(trace.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
            )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(line + "\n" for line in traces), encoding="utf-8", newline="\n")
    console.print(f"[green]{len(traces)} trace[/green] -> {out} ({failures} sorunlu)")
    if failures:
        raise typer.Exit(code=1)


if __name__ == "__main__":  # pragma: no cover
    app()
