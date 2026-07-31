"""Validator zinciri — Faz C. Saf.

Validator'lar **kaydedilmiş bir Trace'i** doğrular; hiçbir şeyi yeniden
çalıştırmaz. Bu yüzden ``execution`` veya ``providers`` import etmezler —
``.importlinter`` bunu zorlar. Yeniden çalıştırma gerekiyorsa o bir
``groundtruth`` adımıdır, validator değil.
"""

from toolcall_tr.validation.base import (
    ValidationPipeline,
    ValidationSubject,
    Validator,
    looks_empty,
)
from toolcall_tr.validation.identifiers import (
    SYNTHETIC_TCKN_PREFIX,
    is_synthetic_tckn,
    is_valid_iban,
    is_valid_tckn,
    is_valid_vkn,
)
from toolcall_tr.validation.pii import PIIHit, scan_json, scan_text
from toolcall_tr.validation.quality import (
    LanguageQualityValidator,
    ObservationGroundingValidator,
    TurnConsistencyValidator,
)
from toolcall_tr.validation.validators import (
    ConfirmationValidator,
    DuplicateValidator,
    ExecutionValidator,
    FormatValidator,
    GroundingValidator,
    PIIValidator,
    RegistryValidator,
    SchemaValidator,
)

__all__ = [
    "M1_BLOCKING",
    "RELEASE_BLOCKING",
    "SYNTHETIC_TCKN_PREFIX",
    "ConfirmationValidator",
    "DuplicateValidator",
    "ExecutionValidator",
    "FormatValidator",
    "GroundingValidator",
    "LanguageQualityValidator",
    "ObservationGroundingValidator",
    "PIIHit",
    "PIIValidator",
    "RegistryValidator",
    "SchemaValidator",
    "TurnConsistencyValidator",
    "ValidationPipeline",
    "ValidationSubject",
    "Validator",
    "build_default_pipeline",
    "is_synthetic_tckn",
    "is_valid_iban",
    "is_valid_tckn",
    "is_valid_vkn",
    "looks_empty",
    "scan_json",
    "scan_text",
]

#: Bu validator'lardan biri bile ``ERROR`` üretirse örnek reddedilir.
#: ``pii`` **asla** bu listeden çıkarılmaz.
M1_BLOCKING: frozenset[str] = frozenset(
    {"format", "schema", "registry", "grounding", "confirmation", "pii", "execution"}
)

#: Release adayında doğal dil ve korpus-geneli tekrar denetimleri de sert kapıdır.
#: Semantik/politika/dil hakemi sonuçları CLI'daki release gate tarafından ayrıca
#: doğrulanır; bunlar ``ValidationSubject`` tabanlı yerel validator değildir.
RELEASE_BLOCKING: frozenset[str] = M1_BLOCKING | frozenset({"language", "duplicate"})


def build_default_pipeline(
    *,
    fail_fast: bool = False,
    max_similarity: float = 0.95,
    release: bool = False,
) -> ValidationPipeline:
    """M1 validator zinciri.

    Sıra ucuzdan pahalıya: yapısal kontroller önce, korpus geneli tekrar
    tespiti en son.
    """
    return ValidationPipeline(
        [
            FormatValidator(),
            SchemaValidator(),
            RegistryValidator(),
            GroundingValidator(),
            ConfirmationValidator(),
            PIIValidator(),
            ExecutionValidator(),
            LanguageQualityValidator(),
            ObservationGroundingValidator(),
            TurnConsistencyValidator(),
            DuplicateValidator(max_similarity=max_similarity),
        ],
        blocking=RELEASE_BLOCKING if release else M1_BLOCKING,
        fail_fast=fail_fast,
    )
