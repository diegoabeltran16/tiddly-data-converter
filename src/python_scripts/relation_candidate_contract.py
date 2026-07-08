"""
relation_candidate_contract.py — S0129

Módulo auxiliar de contratos y catálogos para el validador de relaciones candidatas.
Extrae las constantes DT029/DT031 y las funciones de verificación de evidencia que
de otro modo inflarían validate_relation_candidates.py.

Uso:
    from relation_candidate_contract import (
        ALLOWED_RELATION_TYPES,
        ALLOWED_EVIDENCE_KINDS,
        ALLOWED_STATUSES,
        ALLOWED_RESOLUTION_STATUSES,
        WEAK_EVIDENCE_THRESHOLD,
        CANDIDATE_ID_RE,
        verify_excerpt_in_source,
        is_self_relation,
    )
"""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Catálogos — tipos de relación permitidos (DT029 P0 + DT031)
# ---------------------------------------------------------------------------
ALLOWED_RELATION_TYPES: frozenset[str] = frozenset({
    # DT029 P0 — generación automática segura en pipeline
    "referencia_a",
    "deriva_de",
    "menciona_script",
    "menciona_diagnostico",
    "menciona_sesion",
    "produce_artefacto",
    "valida",
    # DT031 schema — tipos del contrato de salida
    "references",
    "derived_from",
    "validates",
    "diagnoses",
    "related_to",
    # DT029 P1/P2 — de alta semántica, requieren revisión humana explícita
    "depende_de",
    "corrige",
    "contradice",
    "afecta_pipeline",
})

RELATION_CANDIDATE_SCHEMAS: frozenset[str] = frozenset({
    "relations-candidate/v1",
    "technical-relation-candidates/v1",
})

VALID_HUMAN_REVIEW_DECISIONS: frozenset[str] = frozenset({
    "approved_for_admission",
    "rejected",
    "deferred",
})

ADMISSION_HUMAN_REVIEW_DECISION = "approved_for_admission"

CURRENT_REPO_LIFECYCLE_STATES: frozenset[str] = frozenset({
    "current_repo_artifact",
})

HISTORICAL_REPO_LIFECYCLE_STATES: frozenset[str] = frozenset({
    "historical_snapshot",
    "deleted_historical",
    "moved_candidate",
})

BUILD_ARTIFACT_PATH_PARTS: frozenset[str] = frozenset({
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    "target",
})

BUILD_ARTIFACT_PREFIXES: tuple[str, ...] = (
    "data/tmp/",
    "data/out/local/enriched/",
    "data/out/local/ai/",
    "data/out/local/microsoft_copilot/",
    "data/out/local/reverse_html/",
)

# ---------------------------------------------------------------------------
# Catálogos — tipos de evidencia permitidos (DT028 + DT031)
# ---------------------------------------------------------------------------
ALLOWED_EVIDENCE_KINDS: frozenset[str] = frozenset({
    "explicit_reference",    # cita literal o referencia explícita en texto
    "wikilink",              # enlace wikilink en markup
    "structural_tag",        # tag o campo estructural
    "content_embedded",      # referencia embebida en contenido
    "ai_inference",          # inferencia generada por IA — evidencia débil por definición
    "title_mention",         # mención de título sin enlace formal
    "heading_reference",     # referencia a heading/sección
})

# ---------------------------------------------------------------------------
# Catálogos — status y resolution_status permitidos
# ---------------------------------------------------------------------------
ALLOWED_STATUSES: frozenset[str] = frozenset({
    "candidate",
    "needs_review",
    "rejected",
    "unresolved_target",
    "duplicate",
    "accepted_for_admission",
})

ALLOWED_RESOLUTION_STATUSES: frozenset[str] = frozenset({
    "resolved",
    "resolved_id",
    "resolved_title_unique",
    "unresolved",
    "ambiguous",
})

# ---------------------------------------------------------------------------
# Constantes de validación
# ---------------------------------------------------------------------------

# Umbral de confianza bajo la cual se considera evidencia débil
WEAK_EVIDENCE_THRESHOLD: float = 0.50

# Regex para candidate_id válido (DT031): prefijo rc1_ seguido de 16-64 hex
CANDIDATE_ID_RE = re.compile(r"^rc1_[a-f0-9]{16,64}$")

# ---------------------------------------------------------------------------
# Funciones de verificación
# ---------------------------------------------------------------------------

def verify_excerpt_in_source(excerpt: str, source_text: Optional[str]) -> bool:
    """
    Verifica si el excerpt existe textualmente en el source_text del tiddler.

    Reglas:
    - Si source_text es None o vacío, no se puede verificar → devuelve None
      (el llamador puede emitir un warning de no-verificable, no un error).
    - La búsqueda es case-insensitive y normaliza espacios múltiples.
    - Un excerpt vacío siempre devuelve False.

    Returns:
        True  — excerpt encontrado en source_text
        False — excerpt NO encontrado en source_text
        None  — no se pudo verificar (source_text ausente)
    """
    if not excerpt or not excerpt.strip():
        return False
    if not source_text or not source_text.strip():
        return None  # type: ignore[return-value]

    # Normalizar: lowercase + colapsar espacios múltiples
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.strip().lower())

    return _norm(excerpt) in _norm(source_text)


def is_self_relation(source_id: Optional[str], target_id: Optional[str]) -> bool:
    """
    Devuelve True si source.tiddler_id == target.tiddler_id (auto-relación).

    Una auto-relación puede ser válida en casos excepcionales (e.g., bucle de revisión),
    pero debe estar justificada explícitamente. Sin justificación, es un error.

    Si alguno de los IDs es None o vacío, devuelve False (no es posible determinar
    auto-relación sin IDs completos).
    """
    if not source_id or not target_id:
        return False
    return source_id.strip() == target_id.strip()
