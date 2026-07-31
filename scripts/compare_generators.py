"""Aday üretici modelleri aynı korpus üzerinde karşılaştırır.

**Neden var:** hangi modelin daha iyi Türkçe yazdığı bir kanaat sorusu değil,
ölçüm sorusudur. Boru hattı zaten ölçüyor:

``ungrounded_argument``
    Paraphrase sırasında argüman değeri kaybolmuş. Model cümleyi yeniden
    yazarken "otobüs durak" ifadesini düşürdüyse örnek kullanılamaz.
``near_duplicate``
    Beş varyant istendiğinde virgülle ayrılan beş cümle üretilmiş.
``pii``
    Model doğal yazarken gerçekçi bir TCKN/IBAN uydurmuş.

**Ama yalnızca ret oranına bakmak yanıltıcıdır.** Validator'lar yapısaldır;
26 blueprint x 4 varyantlık bir korpusta birden fazla model %100'e ulaşır ve
tablo ayırt etmeyi bırakır. Bu yüzden çeşitlilik de ölçülür:

``benzersiz``
    Üretilen ifadelerin kaçı gerçekten farklı.
``benzerlik``
    Aynı blueprint'in varyantları arasındaki ortalama karakter n-gram
    benzerliği. Düşük olan iyidir: model gerçekten yeniden yazıyor demektir.
    Yüksek olan, virgül oynatıp aynı cümleyi beş kez veren modeldir.
``uzunluk``
    Ortalama karakter, kaynak ifadelere göre oranlanmış. **Bu ölçüt gerçek bir
    yanlış pozitifi yakaladı:** bir model %100 kabul aldı ama ortalama 22
    karakter üretiyordu -- çağrı başına ~440 çıkış token'ı harcayıp geriye
    kırpılmış bir kalıntı bırakıyordu (muhakeme token'ı bütçeyi yiyor).
    Kalıntı argümanı hâlâ içerdiği için yapısal validator'lar geçiriyordu.

Karar bu üçüne birlikte bakılarak verilir; ret oranı eşitse çeşitlilik ayırır
ve şüpheli kısa çıktı üreten aday **diskalifiye** edilir.

    uv run python scripts/compare_generators.py --variants 4

API anahtarı gerektirir (`OPENAI_API_KEY`). Anahtar yoksa script hiçbir şey
uydurmaz, açıkça durur.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from toolcall_tr.generation.query import LLMQueryGenerator
from toolcall_tr.groundtruth.planner import try_plan
from toolcall_tr.groundtruth.runner import run as run_plan
from toolcall_tr.llm import build_client
from toolcall_tr.llm.cache import LLMCache
from toolcall_tr.pipeline.assemble import assemble_example
from toolcall_tr.pipeline.blueprints import load_blueprints
from toolcall_tr.pipeline.environment import build_izmir_registry, open_izmir_environment
from toolcall_tr.validation import ValidationSubject, build_default_pipeline

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = REPO_ROOT / "prompts" / "user_query_v1.md"

#: `configs/generation.yaml` -> llm.candidates ile aynı liste.
CANDIDATES: list[tuple[str, str]] = [
    ("openai", "gpt-5.4-mini"),
    ("openai", "gpt-5-mini"),
    ("openai", "gpt-4.1-mini"),
]

#: Çıktı, kaynak ifadelerin ortalamasının bu oranının altına düşerse model
#: cümleyi budamış sayılır ve öneriden diskalifiye edilir. Ölçülmüş bir vaka
#: üzerine kondu: 22 karakterlik çıktılar tüm yapısal validator'ları geçmişti.
MIN_LENGTH_RATIO = 0.6

#: Çıkış token'ının ne kadarı görünür metne dönüşüyor. Çok düşükse bütçe
#: muhakemeye gidiyor ve cevap kırpılıyor demektir.
MIN_VISIBLE_TOKEN_RATIO = 0.25


def _progress(model: str, done: int, expected: int, started: float, cached: int) -> None:
    """Canlı ilerleme satırı.

    Yüzlerce ardışık API çağrısı dakikalar sürer; çıktı olmadan script'in
    asılı mı yoksa çalışıyor mu olduğu anlaşılmaz.
    """
    elapsed = time.monotonic() - started
    rate = done / elapsed if elapsed > 0 else 0.0
    remaining = (expected - done) / rate if rate > 0 else 0.0
    print(
        f"\r   {model:<18} {done:>3}/{expected}  "
        f"önbellek {cached:>3}  ~{remaining:>4.0f}sn kaldı   ",
        end="",
        file=sys.stderr,
        flush=True,
    )


def _system_prompt() -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    # YAML front matter atılır; kalan kısım sistem istemidir.
    if text.startswith("---"):
        _, _, body = text.partition("---\n")
        _, _, body = body.partition("---\n")
        return body.strip()
    return text.strip()


def evaluate(provider: str, model: str, *, variants: int, use_cache: bool = True) -> dict[str, Any]:
    """Bir adayı korpus üzerinde çalıştırır ve ret istatistiklerini döner.

    Yanıtlar önbelleğe alınır: aynı adayı yeniden çalıştırmak API'ye hiç
    gitmez. Önbellek anahtarı modeli de içerir, yani adaylar birbirinin
    yanıtını görmez.
    """
    blueprints = load_blueprints(REPO_ROOT / "data" / "blueprints")
    registry = build_izmir_registry()
    pipeline = build_default_pipeline()
    generator = LLMQueryGenerator(
        build_client(provider, model),
        system_prompt=_system_prompt(),
        cache=LLMCache(REPO_ROOT / "data" / "llm_cache", enabled=use_cache),
    )
    created_at = datetime.now(UTC)

    codes: Counter[str] = Counter()
    total = accepted = cached_hits = 0
    input_tokens = output_tokens = 0
    #: blueprint_id -> üretilen ifadeler (çeşitlilik ölçümü için)
    texts: dict[str, list[str]] = {}
    expected = len(blueprints) * variants
    started = time.monotonic()

    with open_izmir_environment(repo_root=REPO_ROOT) as env:
        for index, blueprint in enumerate(blueprints, start=1):
            compiled, _ = try_plan(blueprint, registry)
            if compiled is None:
                continue
            trace = run_plan(compiled, env)
            if not trace.is_usable:
                continue

            # Varyant 0 elle yazılmış ifadedir; modeli onunla değil,
            # ürettiği paraphrase'lerle ölçüyoruz.
            for variant in range(1, variants + 1):
                total += 1
                query = generator.generate(
                    blueprint, variant_index=variant, root_seed=env.root_seed
                )
                if query.usage is not None:
                    input_tokens += query.usage.input_tokens or 0
                    output_tokens += query.usage.output_tokens or 0
                    cached_hits += int(query.usage.cached)
                texts.setdefault(blueprint.blueprint_id, []).append(query.text)
                _progress(model, total, expected, started, cached_hits)

                example = assemble_example(
                    blueprint=blueprint,
                    plan=compiled,
                    trace=trace,
                    query=query,
                    env=env,
                    index=index * 100 + variant,
                    created_at=created_at,
                )
                result = pipeline.run(
                    ValidationSubject(
                        blueprint=blueprint,
                        plan=compiled,
                        trace=trace,
                        tools=example.tools,
                        example=example,
                    )
                )
                if result.accepted:
                    accepted += 1
                else:
                    codes.update(f.code for f in result.errors)

    print(file=sys.stderr)  # ilerleme satırını kapat

    flat = [text for group in texts.values() for text in group]
    mean_length = sum(len(t) for t in flat) / len(flat) if flat else 0.0
    source_length = _source_utterance_length(blueprints)

    # Görünür metnin çıkış token'ına oranı. ~4 karakter/token kabası yeterli:
    # aradığımız şey ince fark değil, büyüklük mertebesi sapması.
    visible_tokens = sum(len(t) for t in flat) / 4
    visible_ratio = visible_tokens / output_tokens if output_tokens else 1.0

    warnings: list[str] = []
    if source_length and mean_length < source_length * MIN_LENGTH_RATIO:
        warnings.append(
            f"çıktı kaynak ifadelerin %{100 * mean_length / source_length:.0f}'i "
            "kadar -- cümle budanmış olabilir"
        )
    if visible_ratio < MIN_VISIBLE_TOKEN_RATIO:
        warnings.append(
            f"çıkış token'ının yalnızca %{100 * visible_ratio:.0f}'i görünür metin -- "
            "bütçe muhakemeye gidiyor ve cevap kırpılıyor olabilir"
        )

    return {
        "mean_length": mean_length,
        "warnings": warnings,
        "provider": provider,
        "model": model,
        "total": total,
        "accepted": accepted,
        "cached_hits": cached_hits,
        "elapsed_s": time.monotonic() - started,
        "yield_rate": accepted / total if total else 0.0,
        "rejections": dict(codes.most_common()),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "unique_rate": len(set(flat)) / len(flat) if flat else 0.0,
        "mean_similarity": _mean_within_group_similarity(texts),
    }


def _source_utterance_length(blueprints: Any) -> float:
    """Elle yazılmış ifadelerin ortalama uzunluğu — karşılaştırma referansı."""
    lengths = [len(text) for bp in blueprints for text in bp.utterances]
    return sum(lengths) / len(lengths) if lengths else 0.0


def _char_ngrams(text: str, size: int = 4) -> frozenset[str]:
    lowered = text.casefold()
    if len(lowered) < size:
        return frozenset({lowered})
    return frozenset(lowered[i : i + size] for i in range(len(lowered) - size + 1))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _mean_within_group_similarity(texts: dict[str, list[str]]) -> float:
    """Aynı blueprint'in varyantları birbirine ne kadar benziyor?

    Düşük olan iyidir: model gerçekten yeniden yazıyor demektir. Yüksek olan,
    virgül oynatıp aynı cümleyi tekrarlayan modeldir.
    """
    scores: list[float] = []
    for group in texts.values():
        if len(group) < 2:
            continue
        grams = [_char_ngrams(text) for text in group]
        for i in range(len(grams)):
            for j in range(i + 1, len(grams)):
                scores.append(_jaccard(grams[i], grams[j]))
    return sum(scores) / len(scores) if scores else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants", type=int, default=4, help="Blueprint başına paraphrase.")
    parser.add_argument("--model", action="append", help="provider:model (yinelenebilir).")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Önbelleği yok say ve her çağrıyı yeniden yap.",
    )
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY tanımlı değil. .env dosyasına ekleyin.", file=sys.stderr)
        return 2

    candidates = CANDIDATES
    if args.model:
        candidates = [tuple(item.split(":", 1)) for item in args.model]  # type: ignore[misc]

    blueprint_count = len(load_blueprints(REPO_ROOT / "data" / "blueprints"))
    print(
        f"{len(candidates)} aday x {blueprint_count} blueprint x {args.variants} varyant "
        f"= {len(candidates) * blueprint_count * args.variants} çağrı\n"
        "Yanıtlar önbelleğe alınır; yeniden çalıştırma API'ye gitmez.\n",
        file=sys.stderr,
    )

    results: list[dict[str, Any]] = []
    for provider, model in candidates:
        print(f"-> {provider}:{model}", file=sys.stderr)
        try:
            results.append(
                evaluate(provider, model, variants=args.variants, use_cache=not args.no_cache)
            )
        except Exception as exc:
            print(f"\n   ATLANDI: {type(exc).__name__}: {exc}", file=sys.stderr)

    if not results:
        print("Hiçbir aday çalıştırılamadı.", file=sys.stderr)
        return 1

    print()
    header = (
        f"{'model':<22} {'kabul':>9} {'oran':>7} {'benzersiz':>10} "
        f"{'benzerlik':>10} {'uzunluk':>8} {'çıkış tok':>10}"
    )
    print(header)
    print("-" * len(header))
    for row in sorted(results, key=lambda r: (-r["yield_rate"], r["mean_similarity"])):
        print(
            f"{row['model']:<22} {row['accepted']:>4}/{row['total']:<4} "
            f"{row['yield_rate']:>6.1%} {row['unique_rate']:>10.1%} "
            f"{row['mean_similarity']:>10.3f} {row['mean_length']:>8.0f} "
            f"{row['output_tokens']:>10,}"
        )
    print()
    print("benzerlik: DÜŞÜK olan iyi (varyantlar gerçekten farklı)")
    for row in results:
        print(
            f"  {row['model']:<22} {row['elapsed_s']:>5.0f} sn, "
            f"{row['cached_hits']}/{row['total']} önbellekten"
        )

    if any(row["rejections"] for row in results):
        print()
        print("ret gerekçeleri:")
        for row in results:
            if row["rejections"]:
                print(f"  {row['model']}: {row['rejections']}")

    flagged = [row for row in results if row["warnings"]]
    if flagged:
        print()
        print("UYARI -- yapısal validator'ların yakalayamadığı sorunlar:")
        for row in flagged:
            for warning in row["warnings"]:
                print(f"  {row['model']}: {warning}")

    # Uyarı alan aday, kabul oranı %100 olsa bile öneriden çıkarılır:
    # kırpılmış bir cevap tüm yapısal kontrolleri geçebilir.
    eligible = [row for row in results if not row["warnings"]] or results
    top_yield = max(row["yield_rate"] for row in eligible)
    tied = [row for row in eligible if row["yield_rate"] >= top_yield - 1e-9]
    best = min(tied, key=lambda r: r["mean_similarity"])

    print()
    if flagged:
        print(f"{len(flagged)} aday uyarı aldığı için öneriden çıkarıldı.")
    if len(tied) > 1:
        print(
            f"{len(tied)} model kabul oranında eşit ({top_yield:.1%}); "
            "karar çeşitliliğe göre verildi."
        )
    print(
        f"Öneri: {best['model']}  "
        f"(kabul {best['yield_rate']:.1%}, benzerlik {best['mean_similarity']:.3f}, "
        f"uzunluk {best['mean_length']:.0f})"
    )
    print("configs/generation.yaml -> llm.models.generator.model alanını buna göre güncelleyin.")
    print()
    print(
        "NOT: ret oranı yapısal validator'lardan gelir ve küçük korpusta tavana vurur.\n"
        "Nihai karar için insan incelemesi yapılmalıdır (dataset card: human_reviewed)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
