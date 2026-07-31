"""Türkçe kullanıcı ifadesi üretimi.

LLM **yalnızca** doğal dili yazar. Ground-truth tool çağrısı asla LLM'e
sorulmaz — o `groundtruth.planner` tarafından koddan derlenir.

Çevrimdışı modda korpusun temeli elle yazılmış Türkçe ifadelerdir. OpenAI
modunda LLM, blueprint kısıtlarından özgün soru ve kısa karar gerekçesi üretir;
elle yazılmış ifade yalnız doğal dil referansıdır. Her iki durumda da metin
doğrulanır: argüman değerleri metinde geçmiyorsa grounding validator örneği reddeder.
"""

from toolcall_tr.generation.artifacts import (
    TrainingArtifactPolicyError,
    build_release_artifact_manifest,
)
from toolcall_tr.generation.canary import (
    CanaryAllocation,
    allocate_canary,
    rebalance_canary,
)
from toolcall_tr.generation.corpus_budget import (
    BudgetDimension,
    CorpusBudgetConfig,
    RatioConstraint,
    build_corpus_budget_report,
)
from toolcall_tr.generation.generalization import (
    GeneralizationHoldoutConfig,
    HoldoutProfile,
    build_generalization_report,
)
from toolcall_tr.generation.query import (
    PROMPT_VERSION,
    STYLES,
    TEMPLATE_FRAMES,
    GeneratedQuery,
    LLMQueryGenerator,
    QueryGenerator,
    TemplateCapacityExceededError,
    TemplateQueryGenerator,
)
from toolcall_tr.generation.release_gate import CanaryProfile, build_canary_gate
from toolcall_tr.generation.security_eval import (
    build_security_evaluation_report,
    load_security_evaluations,
)

__all__ = [
    "PROMPT_VERSION",
    "STYLES",
    "TEMPLATE_FRAMES",
    "BudgetDimension",
    "CanaryAllocation",
    "CanaryProfile",
    "CorpusBudgetConfig",
    "GeneralizationHoldoutConfig",
    "GeneratedQuery",
    "HoldoutProfile",
    "LLMQueryGenerator",
    "QueryGenerator",
    "RatioConstraint",
    "TemplateCapacityExceededError",
    "TemplateQueryGenerator",
    "TrainingArtifactPolicyError",
    "allocate_canary",
    "build_canary_gate",
    "build_corpus_budget_report",
    "build_generalization_report",
    "build_release_artifact_manifest",
    "build_security_evaluation_report",
    "load_security_evaluations",
    "rebalance_canary",
]
