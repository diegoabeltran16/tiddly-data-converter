"""
relation_admission_policy.py — S0131

Política de admisión relacional gobernada.

Define:
  - Estados válidos de un candidato relacional (máquina de estados)
  - Transiciones y condiciones de bloqueo
  - Requisitos de evidencia mínima por tipo de relación
  - Contrato de admisión futura

Este módulo es SOLO de evaluación de política.
NO escribe en canon, NO ejecuta --apply, NO modifica tiddlers_*.jsonl.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Importaciones del contrato de candidatos (S0129)
# ---------------------------------------------------------------------------
try:
    from relation_candidate_contract import (
        ALLOWED_RELATION_TYPES,
        ALLOWED_EVIDENCE_KINDS,
        WEAK_EVIDENCE_THRESHOLD,
        is_self_relation,
    )
except ImportError:  # pragma: no cover — fallback para entornos sin el módulo
    ALLOWED_RELATION_TYPES: frozenset[str] = frozenset()  # type: ignore[assignment]
    ALLOWED_EVIDENCE_KINDS: frozenset[str] = frozenset()  # type: ignore[assignment]
    WEAK_EVIDENCE_THRESHOLD: float = 0.50
    def is_self_relation(a: Any, b: Any) -> bool:  # type: ignore[misc]
        return bool(a and b and str(a).strip() == str(b).strip())


# ---------------------------------------------------------------------------
# Estados de la máquina de estados
# ---------------------------------------------------------------------------
STATE_CANDIDATE = "candidate"
STATE_NEEDS_REVIEW = "needs_review"
STATE_REJECTED = "rejected"
STATE_ADMISSIBLE = "admissible"
STATE_ADMITTED_FUTURE = "admitted_to_canon_future"  # conceptual — S0131 no lo implementa

ALL_STATES: frozenset[str] = frozenset({
    STATE_CANDIDATE,
    STATE_NEEDS_REVIEW,
    STATE_REJECTED,
    STATE_ADMISSIBLE,
    STATE_ADMITTED_FUTURE,
})

# Estados terminales (no permiten más transiciones hacia adelante)
TERMINAL_STATES: frozenset[str] = frozenset({STATE_REJECTED, STATE_ADMITTED_FUTURE})


# ---------------------------------------------------------------------------
# Política de evidencia por tipo de relación
# ---------------------------------------------------------------------------

# Tipos de relación que siempre requieren revisión humana explícita,
# independientemente de la calidad de la evidencia.
ALWAYS_HUMAN_REVIEW_TYPES: frozenset[str] = frozenset({
    "depende_de",
    "corrige",
    "contradice",
    "afecta_pipeline",
    "conflicts_with",
    "implements",
    "continues",
    "replaces",
    "validates",
    "valida",
    "produce_artefacto",
})

# Tipos de relación P0 auto-admisibles en el futuro si evidencia es fuerte.
# Requieren igualmente revisión humana de primer ingreso, pero pueden configurarse
# con umbral de confianza diferente.
P0_RELATION_TYPES: frozenset[str] = frozenset({
    "referencia_a",
    "menciona_diagnostico",
    "menciona_script",
    "menciona_sesion",
})

# Umbral de confianza para tipos que PUEDEN ser auto-admisibles en el futuro.
P0_MIN_CONFIDENCE: float = 0.70

# Umbral mínimo absoluto (aplica a todos los tipos).
GLOBAL_MIN_CONFIDENCE: float = WEAK_EVIDENCE_THRESHOLD  # 0.50

# Evidencias que son insuficientes como única fuente de una relación semántica.
WEAK_EVIDENCE_ALONE: frozenset[str] = frozenset({
    "ai_inference",
    "structural_tag",
    "title_mention",
})

# Evidencias fuertes que son suficientes por sí solas para considerar admisibilidad.
STRONG_EVIDENCE_KINDS: frozenset[str] = frozenset({
    "explicit_reference",
    "wikilink",
    "content_embedded",
})

# Política detallada por tipo de relación.
# Para cada tipo:
#   min_evidence_kinds: evidencia mínima aceptable (al menos una debe estar presente)
#   insufficient_alone: evidencia que NO es suficiente por sí sola
#   min_confidence: umbral de confianza mínimo
#   excerpt_required: si el excerpt es obligatorio
#   fp_risk: riesgo de falso positivo (low, medium, high, critical)
#   always_human_review: si siempre requiere revisión humana
EVIDENCE_POLICY: dict[str, dict[str, Any]] = {
    "referencia_a": {
        "min_evidence_kinds": {"explicit_reference", "wikilink", "content_embedded"},
        "insufficient_alone": {"ai_inference", "structural_tag"},
        "min_confidence": P0_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "low",
        "always_human_review": False,
        "valid_example": "El tiddler DT031 cita explícitamente: 'véase DT029 para la tipología'",
        "invalid_example": "El tiddler DT031 tiene un tag 'DT029' (solo tag nativo, sin cita textual)",
    },
    "references": {
        "min_evidence_kinds": {"explicit_reference", "wikilink", "content_embedded"},
        "insufficient_alone": {"ai_inference", "structural_tag"},
        "min_confidence": P0_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "low",
        "always_human_review": False,
        "valid_example": "Texto contiene la URL o ID del tiddler target de forma explícita",
        "invalid_example": "Inferencia IA de que 'probablemente se relacionan' sin cita",
    },
    "deriva_de": {
        "min_evidence_kinds": {"explicit_reference", "content_embedded"},
        "insufficient_alone": {"ai_inference", "title_mention"},
        "min_confidence": P0_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "medium",
        "always_human_review": False,
        "valid_example": "Tiddler B declara 'extendemos el modelo de A con los siguientes cambios'",
        "invalid_example": "IA infiere derivación porque los títulos se parecen",
    },
    "derived_from": {
        "min_evidence_kinds": {"explicit_reference", "content_embedded"},
        "insufficient_alone": {"ai_inference", "title_mention"},
        "min_confidence": P0_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "medium",
        "always_human_review": False,
        "valid_example": "Texto declara explícitamente la fuente de derivación",
        "invalid_example": "Nombres similares interpretados como derivación",
    },
    "menciona_diagnostico": {
        "min_evidence_kinds": {"explicit_reference", "title_mention", "heading_reference", "wikilink"},
        "insufficient_alone": {"structural_tag"},
        "min_confidence": P0_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "low",
        "always_human_review": False,
        "valid_example": "Texto contiene 'DT029' o el título completo del diagnóstico target",
        "invalid_example": "Solo existe un tag que parece coincidir con el nombre del diagnóstico",
    },
    "diagnoses": {
        "min_evidence_kinds": {"explicit_reference", "title_mention", "heading_reference"},
        "insufficient_alone": {"structural_tag", "ai_inference"},
        "min_confidence": P0_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "medium",
        "always_human_review": False,
        "valid_example": "Tiddler fuente contiene referencia explícita al diagnóstico target",
        "invalid_example": "Tag clasificatorio sin mención textual",
    },
    "menciona_sesion": {
        "min_evidence_kinds": {"explicit_reference", "title_mention", "structural_tag", "wikilink"},
        "insufficient_alone": {"ai_inference"},
        "min_confidence": P0_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "low",
        "always_human_review": False,
        "valid_example": "Texto contiene 'S0125' o título de la sesión target",
        "invalid_example": "IA infiere que dos sesiones están relacionadas por tema",
    },
    "menciona_script": {
        "min_evidence_kinds": {"explicit_reference", "title_mention", "wikilink", "content_embedded"},
        "insufficient_alone": {"ai_inference", "structural_tag"},
        "min_confidence": P0_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "low",
        "always_human_review": False,
        "valid_example": "Texto cita el nombre del script: 'validate_relation_candidates.py'",
        "invalid_example": "Tag que contiene el nombre del script sin mención textual",
    },
    "produce_artefacto": {
        "min_evidence_kinds": {"explicit_reference", "structural_tag", "content_embedded"},
        "insufficient_alone": {"ai_inference", "title_mention"},
        "min_confidence": GLOBAL_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "medium",
        "always_human_review": True,
        "valid_example": "Texto declara 'esta sesión produce el artefacto X'",
        "invalid_example": "Inferencia de que el artefacto X fue producido por Y sin declaración",
    },
    "valida": {
        "min_evidence_kinds": {"explicit_reference", "content_embedded"},
        "insufficient_alone": {"ai_inference", "structural_tag"},
        "min_confidence": GLOBAL_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "high",
        "always_human_review": True,
        "valid_example": "Documento de validación cita explícitamente qué valida",
        "invalid_example": "IA asume relación de validación por proximidad temática",
    },
    "validates": {
        "min_evidence_kinds": {"explicit_reference", "content_embedded"},
        "insufficient_alone": {"ai_inference", "structural_tag"},
        "min_confidence": GLOBAL_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "high",
        "always_human_review": True,
        "valid_example": "Test file explicitly names what it validates",
        "invalid_example": "AI assumes validation because topics are similar",
    },
    "depende_de": {
        "min_evidence_kinds": {"explicit_reference", "content_embedded"},
        "insufficient_alone": {"ai_inference", "title_mention", "structural_tag"},
        "min_confidence": GLOBAL_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "high",
        "always_human_review": True,
        "valid_example": "Texto declara explícitamente la dependencia técnica o conceptual",
        "invalid_example": "IA infiere dependencia porque los documentos se relacionan temáticamente",
    },
    "corrige": {
        "min_evidence_kinds": {"explicit_reference"},
        "insufficient_alone": {"ai_inference", "title_mention", "structural_tag", "content_embedded"},
        "min_confidence": GLOBAL_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "critical",
        "always_human_review": True,
        "valid_example": "Texto declara explícitamente que corrige un error del documento X",
        "invalid_example": "IA detecta contradicción parcial y asume corrección",
    },
    "contradice": {
        "min_evidence_kinds": {"explicit_reference"},
        "insufficient_alone": {"ai_inference", "title_mention", "structural_tag", "content_embedded"},
        "min_confidence": GLOBAL_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "critical",
        "always_human_review": True,
        "valid_example": "Texto declara que contradice o invalida la afirmación de otro documento",
        "invalid_example": "IA detecta diferencias de contenido y las interpreta como contradicción",
    },
    "conflicts_with": {
        "min_evidence_kinds": {"explicit_reference"},
        "insufficient_alone": {"ai_inference", "title_mention", "structural_tag"},
        "min_confidence": GLOBAL_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "critical",
        "always_human_review": True,
        "valid_example": "Explicit declaration of conflict in source text",
        "invalid_example": "AI infers conflict from topic similarity",
    },
    "afecta_pipeline": {
        "min_evidence_kinds": {"explicit_reference", "content_embedded"},
        "insufficient_alone": {"ai_inference", "structural_tag"},
        "min_confidence": GLOBAL_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "high",
        "always_human_review": True,
        "valid_example": "Texto cita explícitamente qué parte del pipeline afecta y cómo",
        "invalid_example": "IA infiere efecto de pipeline por proximidad de temas",
    },
    "related_to": {
        "min_evidence_kinds": {"explicit_reference", "content_embedded", "wikilink"},
        "insufficient_alone": {"ai_inference", "structural_tag", "title_mention"},
        "min_confidence": GLOBAL_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "high",
        "always_human_review": True,
        "valid_example": "Texto o estructura vincula explícitamente ambos documentos",
        "invalid_example": "IA sugiere relación porque los documentos pertenecen al mismo módulo",
    },
    "implements": {
        "min_evidence_kinds": {"explicit_reference", "content_embedded"},
        "insufficient_alone": {"ai_inference", "title_mention"},
        "min_confidence": GLOBAL_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "high",
        "always_human_review": True,
        "valid_example": "Código o documento declara que implementa el spec/contract X",
        "invalid_example": "IA infiere implementación porque el nombre es similar",
    },
    "continues": {
        "min_evidence_kinds": {"explicit_reference", "structural_tag"},
        "insufficient_alone": {"ai_inference", "title_mention"},
        "min_confidence": GLOBAL_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "medium",
        "always_human_review": True,
        "valid_example": "Sesión declara 'continúa desde S0125'",
        "invalid_example": "IA infiere continuidad por número de sesión",
    },
    "replaces": {
        "min_evidence_kinds": {"explicit_reference"},
        "insufficient_alone": {"ai_inference", "title_mention", "structural_tag"},
        "min_confidence": GLOBAL_MIN_CONFIDENCE,
        "excerpt_required": True,
        "fp_risk": "critical",
        "always_human_review": True,
        "valid_example": "Documento declara explícitamente que reemplaza o depreca al documento X",
        "invalid_example": "IA infiere reemplazo porque hay versiones de nombres similares",
    },
    "part_of": {
        "min_evidence_kinds": {"structural_tag", "explicit_reference"},
        "insufficient_alone": {"ai_inference", "title_mention"},
        "min_confidence": GLOBAL_MIN_CONFIDENCE,
        "excerpt_required": False,
        "fp_risk": "low",
        "always_human_review": False,
        "valid_example": "Tag estructural o campo de metadata que indica pertenencia",
        "invalid_example": "IA infiere pertenencia por tema común",
    },
}

# Tipos mínimos obligatorios que DEBEN aparecer en la política.
REQUIRED_POLICY_TYPES: frozenset[str] = frozenset({
    "mentions",
    "references",
    "depends_on",
    "part_of",
    "derived_from",
    "implements",
    "validates",
    "conflicts_with",
    "continues",
    "replaces",
})

# Mapa de aliases: tipos del spec S0131 → tipos del catálogo DT029/DT031
POLICY_TYPE_ALIASES: dict[str, str] = {
    "mentions": "menciona_diagnostico",   # alias genérico → tipo P0 más cercano
    "depends_on": "depende_de",
    "derived_from": "deriva_de",
    "part_of": "part_of",               # nativo
    "conflicts_with": "conflicts_with", # nativo
    "continues": "continues",           # nativo
    "replaces": "replaces",             # nativo
    "references": "references",         # nativo DT031
    "implements": "implements",         # nativo
    "validates": "validates",           # nativo DT031
}


# ---------------------------------------------------------------------------
# Condiciones de bloqueo de admisión
# ---------------------------------------------------------------------------

@dataclass
class AdmissibilityResult:
    """Resultado de la evaluación de admisibilidad de un candidato."""
    eligible_state: str  # STATE_* constant
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def is_admissible(self) -> bool:
        return self.eligible_state == STATE_ADMISSIBLE

    @property
    def is_rejected(self) -> bool:
        return self.eligible_state == STATE_REJECTED

    def to_dict(self) -> dict:
        return {
            "eligible_state": self.eligible_state,
            "is_admissible": self.is_admissible,
            "blocking_reasons": self.blocking_reasons,
            "warnings": self.warnings,
            "checks": self.checks,
        }


def _resolve_type(rel_type: str) -> str:
    """Resuelve aliases de tipos de relación al tipo canónico en la política."""
    return POLICY_TYPE_ALIASES.get(rel_type, rel_type)


def evaluate_admissibility(
    candidate: dict,
    canon: dict[str, dict],
    *,
    require_human_approval: bool = True,
    human_approved: bool = False,
) -> AdmissibilityResult:
    """
    Evalúa si un candidato puede avanzar hacia el estado 'admissible'.

    Este evaluador es SOLO de política — no modifica el canon.

    Args:
        candidate: dict con schema relations-candidate/v1
        canon: dict {tiddler_id: record} del canon local
        require_human_approval: si True, human_approved es requisito para 'admissible'
        human_approved: si el operador marcó la relación como revisada y aprobada

    Returns:
        AdmissibilityResult con el estado resultante y las razones de bloqueo.
    """
    blocking: list[str] = []
    warnings: list[str] = []
    checks: dict[str, bool] = {}

    source = candidate.get("source") or {}
    target = candidate.get("target") or {}
    relation = candidate.get("relation") or {}
    evidence = candidate.get("evidence") or {}
    confidence = candidate.get("confidence") or {}

    src_id = (source.get("tiddler_id") or "").strip()
    tgt_id = (target.get("tiddler_id") or "").strip()
    tgt_res = (target.get("resolution_status") or "").strip()
    rel_type = (relation.get("type") or "").strip()
    ev_kind = (evidence.get("kind") or "").strip()
    excerpt = (evidence.get("excerpt") or "").strip()
    score = float(confidence.get("score") or 0.0)

    canonical_rel_type = _resolve_type(rel_type)

    # --- Check 1: tipo de relación en catálogo ---
    checks["relation_type_allowed"] = rel_type in ALLOWED_RELATION_TYPES or rel_type in EVIDENCE_POLICY
    if not checks["relation_type_allowed"]:
        blocking.append(f"relation.type no permitido: {rel_type!r}")

    # --- Check 2: evidencia kind en catálogo ---
    checks["evidence_kind_allowed"] = ev_kind in ALLOWED_EVIDENCE_KINDS
    if not checks["evidence_kind_allowed"]:
        blocking.append(f"evidence.kind no permitido: {ev_kind!r}")

    # --- Check 3: target resolution ---
    valid_resolutions = {"resolved", "resolved_id", "resolved_title_unique"}
    checks["target_resolved"] = tgt_res in valid_resolutions
    if not checks["target_resolved"]:
        blocking.append(
            f"target.resolution_status='{tgt_res}' — target no resuelto o ambiguo; "
            "no puede admitirse sin ID de target verificado"
        )

    # --- Check 4: target en canon ---
    checks["target_in_canon"] = tgt_id in canon if tgt_id else False
    if tgt_id and not checks["target_in_canon"]:
        blocking.append(
            f"target.tiddler_id={tgt_id!r} no encontrado en el canon local"
        )

    # --- Check 5: source en canon ---
    checks["source_in_canon"] = src_id in canon if src_id else False
    if src_id and not checks["source_in_canon"]:
        blocking.append(
            f"source.tiddler_id={src_id!r} no encontrado en el canon local"
        )

    # --- Check 6: auto-relación ---
    checks["no_self_relation"] = not is_self_relation(src_id, tgt_id)
    if not checks["no_self_relation"]:
        blocking.append("auto-relación detectada: source y target son el mismo tiddler")

    # --- Check 7: excerpt presente ---
    policy = EVIDENCE_POLICY.get(canonical_rel_type, {})
    excerpt_required = policy.get("excerpt_required", True)
    checks["excerpt_present"] = bool(excerpt)
    if excerpt_required and not checks["excerpt_present"]:
        blocking.append(
            f"evidence.excerpt vacío — tipo '{rel_type}' requiere excerpt textual"
        )
    elif not excerpt_required and not excerpt:
        warnings.append(f"evidence.excerpt vacío — tipo '{rel_type}' no lo requiere pero es recomendable")

    # --- Check 8: confianza mínima ---
    min_conf = policy.get("min_confidence", GLOBAL_MIN_CONFIDENCE)
    checks["confidence_sufficient"] = score >= min_conf
    if not checks["confidence_sufficient"]:
        blocking.append(
            f"confidence.score={score:.2f} < {min_conf:.2f} mínimo para tipo '{rel_type}'"
        )

    # --- Check 9: evidencia no es solo débil ---
    min_kinds: set[str] = policy.get("min_evidence_kinds", set())
    insufficient_alone: set[str] = policy.get("insufficient_alone", set())
    checks["evidence_strong_enough"] = bool(
        min_kinds and ev_kind in min_kinds
    ) if min_kinds else (ev_kind not in WEAK_EVIDENCE_ALONE)
    if not checks["evidence_strong_enough"]:
        if ev_kind in insufficient_alone:
            blocking.append(
                f"evidence.kind='{ev_kind}' es insuficiente como única fuente "
                f"para tipo '{rel_type}' — se requiere: {sorted(min_kinds)}"
            )
        elif min_kinds and ev_kind not in min_kinds:
            blocking.append(
                f"evidence.kind='{ev_kind}' no está entre los mínimos aceptables "
                f"para tipo '{rel_type}' — se requiere: {sorted(min_kinds)}"
            )

    # --- Check 10: duplicado canónico ---
    src_record = canon.get(src_id, {})
    canonical_targets_to_type: dict[tuple[str, str], bool] = {
        (str(rel.get("target_id", "")), str(rel.get("type", ""))): True
        for rel in (src_record.get("relations") or [])
        if isinstance(rel, dict)
    }
    checks["not_duplicate_canonical"] = (tgt_id, rel_type) not in canonical_targets_to_type
    if not checks["not_duplicate_canonical"]:
        blocking.append(
            f"relación canónica idéntica ya existe: "
            f"source={src_id!r} → target={tgt_id!r} type={rel_type!r}"
        )

    # --- Check 11: revisión humana ---
    always_human = policy.get("always_human_review", False) or (rel_type in ALWAYS_HUMAN_REVIEW_TYPES)
    checks["human_review_done"] = (not require_human_approval) or human_approved
    if require_human_approval and not human_approved:
        if always_human:
            blocking.append(
                f"tipo '{rel_type}' siempre requiere revisión humana explícita — "
                "human_approved=False"
            )
        else:
            warnings.append(
                f"human_approved=False — relación marcada como pendiente de revisión humana"
            )

    # --- Determinar estado resultante ---
    if blocking:
        # Si hay razones estructurales irresolvables → rejected
        hard_blocking = [r for r in blocking if any(
            kw in r for kw in [
                "no permitido", "auto-relación", "no encontrado en el canon",
                "idéntica ya existe"
            ]
        )]
        if hard_blocking:
            state = STATE_REJECTED
        else:
            # Razones soft (target no resuelto, evidencia insuficiente, etc.) → needs_review
            state = STATE_NEEDS_REVIEW
    else:
        state = STATE_ADMISSIBLE

    return AdmissibilityResult(
        eligible_state=state,
        blocking_reasons=blocking,
        warnings=warnings,
        checks=checks,
    )


# ---------------------------------------------------------------------------
# Validación de la política en sí misma
# ---------------------------------------------------------------------------

def validate_policy_completeness() -> list[str]:
    """
    Verifica que la política cubre todos los tipos obligatorios del spec S0131.
    Retorna lista de tipos obligatorios que faltan en EVIDENCE_POLICY (o sus aliases).

    Uso: en tests para garantizar integridad del diseño.
    """
    missing: list[str] = []
    for req_type in REQUIRED_POLICY_TYPES:
        canonical = _resolve_type(req_type)
        if canonical not in EVIDENCE_POLICY and req_type not in EVIDENCE_POLICY:
            missing.append(req_type)
    return missing


def get_policy_for_type(rel_type: str) -> Optional[dict]:
    """
    Retorna la política de evidencia para un tipo de relación.
    Resuelve aliases. Retorna None si el tipo no está en la política.
    """
    canonical = _resolve_type(rel_type)
    return EVIDENCE_POLICY.get(canonical) or EVIDENCE_POLICY.get(rel_type)
