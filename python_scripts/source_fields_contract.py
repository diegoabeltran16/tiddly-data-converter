"""
source_fields_contract.py — S0133

Contrato operativo de source_fields por artifact_family.

Implementa el contrato formal definido en el Diagnóstico temático 035:
'contrato formal de source_fields por artifact_family'.

Uso:
    from source_fields_contract import (
        validate_source_fields,
        BASELINE_REQUIRED_FIELDS,
        DT035_MINIMUM_COMMON_FIELDS,
        FORBIDDEN_FIELDS,
        LEGACY_FIELDS,
        FAMILY_DECLARED_FIELDS,
        ALLOWED_CANONICAL_STATUSES,
        KNOWN_ARTIFACT_FAMILIES,
        ValidationIssue,
    )

Diseño (DT035 §4):
    - source_fields es una capa plana de pares string→string (map[string]string).
    - No debe contener estructuras anidadas, relaciones ni markdown completo.
    - Todo campo derivado debe poder regenerarse desde metadata canónica.
    - La validación es prospectiva: obligatoria para nuevos artefactos,
      no retroactiva sobre el canon histórico.

Niveles de validación:
    LEVEL_BASELINE  — 5 campos mínimos (sesión 7.2 de S0133)
    LEVEL_DT035     — 11 campos mínimos comunes (DT035 §5.1)
    LEVEL_FAMILY    — campos declared_* específicos de family (DT035 §6)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── Niveles de severidad ──────────────────────────────────────────────────────

ERROR = "error"
WARNING = "warning"
INFO = "info"

# ── Códigos de issue ──────────────────────────────────────────────────────────

CODE_MISSING_SOURCE_FIELDS = "SF001"
CODE_SOURCE_FIELDS_NOT_DICT = "SF002"
CODE_MISSING_BASELINE_FIELD = "SF003"
CODE_MISSING_DT035_FIELD = "SF004"
CODE_MISSING_FAMILY_DECLARED_FIELD = "SF005"
CODE_FORBIDDEN_FIELD = "SF006"
CODE_LEGACY_FIELD = "SF007"
CODE_INVALID_CANONICAL_STATUS = "SF008"
CODE_UNSAFE_SOURCE_PATH = "SF009"
CODE_FAMILY_MISMATCH = "SF010"
CODE_UNKNOWN_ARTIFACT_FAMILY = "SF011"
CODE_ARBITRARY_EXTENSION_FIELD = "SF012"
CODE_SOURCE_FIELDS_NOT_FLAT = "SF013"

# ── Campos mínimos baseline (S0133 §7.2) ─────────────────────────────────────

BASELINE_REQUIRED_FIELDS: frozenset[str] = frozenset({
    "artifact_family",
    "canonical_status",
    "session_origin",
    "source_path",
    "provenance_ref",
})

# ── Campos DT035 v1 extendidos (DT035 §5.1 — mínimos comunes adicionales) ────

DT035_EXTENDED_COMMON_FIELDS: frozenset[str] = frozenset({
    "document_key",
    "source_title",
    "source_type",      # DT035 §5.1 lo define explícitamente; prevalece sobre lista genérica S0133 §7.4
    "source_created",
    "source_modified",
    "source_tags_json",
})

# Conjunto completo DT035 v1 = baseline + extended
DT035_MINIMUM_COMMON_FIELDS: frozenset[str] = BASELINE_REQUIRED_FIELDS | DT035_EXTENDED_COMMON_FIELDS

# ── Campos opcionales comunes (DT035 §5.2) ───────────────────────────────────

OPTIONAL_COMMON_FIELDS: frozenset[str] = frozenset({
    "source_module",
    "source_session_label",
    "source_remote_relative_path",
    "source_status",
    "source_role",
    "source_slug",
    "cited_session_ids_json",
    "cited_diagnostic_ids_json",
    "cited_script_paths_json",
    "cited_artifact_paths_json",
})

# ── Campos derivados comunes (DT035 §5.3) ────────────────────────────────────

DERIVED_COMMON_FIELDS: frozenset[str] = frozenset({
    "source_filename",
    "source_basename",
    "source_text_sha256",
    "source_title_normalized",
    "source_tags_normalized_json",
    "source_heading_map_json",
    "source_reference_density",
    "source_family_order",
    "path_equivalence_status",
    "needs_title_normalization",
})

# ── Campos prohibidos dentro de source_fields (S0133 §7.4 + DT035 §8) ────────
# Nota: source_type NO está en esta lista porque DT035 §5.1 lo define
# explícitamente como mínimo común ("Si el contrato vigente del repositorio
# ya contiene una lista más precisa, esa lista prevalece" — S0133 §7.4).

FORBIDDEN_FIELDS: frozenset[str] = frozenset({
    # Campos de identidad canónica
    "schema_version", "id", "key", "canonical_slug", "version_id",
    # Campos semánticos de lectura
    "title", "text", "content", "content_type", "modality", "encoding",
    "is_binary", "is_reference_only",
    # Campos de clasificación canónica
    "role_primary", "roles_secondary", "taxonomy_path", "semantic_text",
    # Campos de payload
    "raw_payload_ref", "asset_id", "mime_type",
    # Campos de contexto de documento
    "document_id", "section_path", "order_in_document",
    # Campos de relaciones
    "relations",
    # Campos de normalización (gestionados por pipeline, no por source_fields)
    "source_tags",       # usar source_tags_json
    "normalized_tags",   # campo normalizado, no fuente
    "source_fields",     # no puede anidarse a sí mismo
    "source_position",
})

# ── Campos legados (en canon histórico; generar WARNING no ERROR) ─────────────
# Estos campos están en el canon porque se copiaron desde TiddlyWiki,
# pero el contrato DT035 recomienda renombrarlos con prefijo source_*.
# Para nuevos artefactos deben usarse los campos DT035.
# - "type"     → source_type
# - "tags"     → source_tags_json
# - "created"  → source_created
# - "modified" → source_modified
# - "tmap.id"  → campo TiddlyMap, no debe replicarse en source_fields nuevo

LEGACY_FIELDS: frozenset[str] = frozenset({
    "type",
    "tags",
    "created",
    "modified",
    "tmap.id",
})

# ── Estados canónicos permitidos ──────────────────────────────────────────────

ALLOWED_CANONICAL_STATUSES: frozenset[str] = frozenset({
    # Valores DT035 / S0133 §7.7
    "candidate_not_admitted",
    "admitted",
    "rejected",
    "superseded",
    # Valor histórico en canon existente
    "local_admitted",
    # Valor alternativo en artefactos de sesión pre-admisión
    "delivered",
    # Variantes de admisión
    "local_admitted_dry_run",
    "pending_review",
})

# ── Familias de artefacto conocidas ──────────────────────────────────────────

KNOWN_ARTIFACT_FAMILIES: frozenset[str] = frozenset({
    # Familias de sesión (DT035 §2)
    "contrato_de_sesion",
    "procedencia_de_sesion",
    "detalles_de_sesion",
    "hipotesis_de_sesion",
    "balance_de_sesion",
    "propuesta_de_sesion",
    "diagnostico_de_sesion",
    # Familias de diagnóstico
    "diagnostico_tematico",
    "diagnostico_de_micro_ciclo",
    "diagnostico_de_meso_ciclo",
    "diagnostico_de_proyecto",
    # Familias relacionales (S0129–S0132)
    "relation_candidate",
    "relation_review",
    "relation_admissibility_report",
    # Alias cortos aceptados (map a familias canónicas)
    "contrato",
    "procedencia",
    "detalles",
    "hipotesis",
    "balance",
    "propuesta",
    "diagnostico_sesion",
    "micro_ciclo",
    "meso_ciclo",
    "diagnostico_proyecto",
})

# Mapa de alias → nombre canónico DT035
FAMILY_ALIASES: dict[str, str] = {
    "contrato":           "contrato_de_sesion",
    "procedencia":        "procedencia_de_sesion",
    "detalles":           "detalles_de_sesion",
    "hipotesis":          "hipotesis_de_sesion",
    "balance":            "balance_de_sesion",
    "propuesta":          "propuesta_de_sesion",
    "diagnostico_sesion": "diagnostico_de_sesion",
    "micro_ciclo":        "diagnostico_de_micro_ciclo",
    "meso_ciclo":         "diagnostico_de_meso_ciclo",
    "diagnostico_proyecto": "diagnostico_de_proyecto",
}

# ── Campos declared_* requeridos por familia (DT035 §6) ──────────────────────

FAMILY_DECLARED_FIELDS: dict[str, frozenset[str]] = {
    "contrato_de_sesion": frozenset({
        "declared_objective",
        "declared_inputs_json",
        "declared_outputs_json",
        "declared_constraints_json",
    }),
    "procedencia_de_sesion": frozenset({
        "declared_origin_summary",
        "declared_upstream_refs_json",
        "declared_sources_consulted_json",
    }),
    "detalles_de_sesion": frozenset({
        "declared_work_summary",
        "declared_touched_paths_json",
        "declared_validations_json",
    }),
    "hipotesis_de_sesion": frozenset({
        "declared_hypotheses_json",
        "declared_verdicts_json",
    }),
    "balance_de_sesion": frozenset({
        "declared_delivered_outputs_json",
        "declared_pending_gaps_json",
        "declared_metrics_json",
    }),
    "propuesta_de_sesion": frozenset({
        "declared_next_step",
        "declared_options_json",
        "declared_blockers_json",
    }),
    "diagnostico_de_sesion": frozenset({
        "declared_questions_json",
        "declared_findings_json",
        "declared_verdict",
    }),
    "diagnostico_tematico": frozenset({
        "declared_central_question",
        "declared_analyzed_families_json",
        "declared_recommendations_json",
    }),
    "diagnostico_de_micro_ciclo": frozenset({
        "declared_session_range",
        "declared_sessions_covered_json",
        "declared_patterns_json",
    }),
    "diagnostico_de_meso_ciclo": frozenset({
        "declared_microcycle_range",
        "declared_session_range",
        "declared_cross_cycle_findings_json",
    }),
    "diagnostico_de_proyecto": frozenset({
        "declared_scope",
        "declared_components_json",
        "declared_governance_findings_json",
    }),
    # Familias relacionales — campos mínimos de trazabilidad
    "relation_candidate": frozenset({
        "declared_source_tiddler_id",
        "declared_target_tiddler_id",
        "declared_relation_type",
    }),
    "relation_review": frozenset({
        "declared_review_status",
        "declared_reviewed_candidate_id",
    }),
    "relation_admissibility_report": frozenset({
        "declared_evaluated_candidates_count",
        "declared_session_scope",
    }),
}

# Rutas permitidas como prefijo de source_path
ALLOWED_SOURCE_PATH_PREFIXES: tuple[str, ...] = (
    "data/out/local/sessions/",
    "data/out/local/pipeline/",
    "data/sessions/",           # legacy — aceptado con advertencia
)

# Patrón que indica apuntamiento directo al canon (prohibido como fuente)
_CANON_JSONL_RE = re.compile(r"tiddlers_\d+\.jsonl$")

# Patrón para campos extendidos válidos
_X_PREFIX_RE = re.compile(r"^x_[a-z][a-z0-9_]*$")

# ── Tipo de resultado ─────────────────────────────────────────────────────────

@dataclass
class ValidationIssue:
    code: str
    severity: str   # ERROR | WARNING | INFO
    field: str      # campo afectado o "__record__"
    message: str
    recommendation: str = ""


# ── Función principal de validación ──────────────────────────────────────────

def validate_source_fields(
    record: dict[str, Any],
    *,
    level: str = "baseline",
    family_check: bool = False,
    strict_status: bool = True,
    strict_path: bool = True,
    strict_forbidden: bool = True,
    legacy_as_error: bool = False,
) -> list[ValidationIssue]:
    """Valida el campo source_fields de un registro canon candidato.

    Parámetros
    ----------
    record:
        Diccionario con el registro completo (no solo source_fields).
    level:
        "baseline"  — valida 5 campos mínimos (S0133 §7.2).
        "dt035"     — valida 11 campos mínimos DT035 v1 (DT035 §5.1).
        "family"    — valida baseline + dt035 + declared_* por familia.
    family_check:
        Si True, valida los campos declared_* específicos de familia.
        Se ignora cuando level != "family".
    strict_status:
        Si True, emite ERROR en canonical_status desconocido (no WARNING).
    strict_path:
        Si True, emite ERROR en source_path inseguro (no WARNING).
    strict_forbidden:
        Si True, emite ERROR en campo prohibido (no WARNING).
    legacy_as_error:
        Si True, trata campos legados como ERROR en lugar de WARNING.

    Returns
    -------
    Lista de ValidationIssue (vacía si el registro es válido).
    """
    issues: list[ValidationIssue] = []

    top_family = record.get("artifact_family") or ""
    sf = record.get("source_fields")

    # SF001 — source_fields ausente cuando artifact_family lo requiere
    if sf is None:
        if top_family and top_family in KNOWN_ARTIFACT_FAMILIES:
            issues.append(ValidationIssue(
                code=CODE_MISSING_SOURCE_FIELDS,
                severity=WARNING,
                field="source_fields",
                message=f"source_fields ausente; artifact_family='{top_family}' lo requiere.",
                recommendation="Agregar source_fields con los campos mínimos del contrato DT035.",
            ))
        return issues

    # SF002 — source_fields no es dict
    if not isinstance(sf, dict):
        issues.append(ValidationIssue(
            code=CODE_SOURCE_FIELDS_NOT_DICT,
            severity=ERROR,
            field="source_fields",
            message=f"source_fields debe ser un objeto/dict, no {type(sf).__name__}.",
            recommendation="Reescribir source_fields como objeto con pares string→string.",
        ))
        return issues

    # SF013 — source_fields tiene valores no string (viola map[string]string)
    non_string = {k: type(v).__name__ for k, v in sf.items() if not isinstance(v, str)}
    for k, t in non_string.items():
        issues.append(ValidationIssue(
            code=CODE_SOURCE_FIELDS_NOT_FLAT,
            severity=ERROR,
            field=f"source_fields.{k}",
            message=f"El valor de source_fields.{k} es {t}, no string. source_fields debe ser map[string]string.",
            recommendation=f"Serializar el valor de '{k}' como JSON string (ej. json.dumps(valor)).",
        ))

    sf_family = sf.get("artifact_family") or ""
    canonical_family = FAMILY_ALIASES.get(sf_family, sf_family) or FAMILY_ALIASES.get(top_family, top_family)

    # ── SF010 — coherencia artifact_family superior vs source_fields ──────────
    if top_family and sf_family:
        norm_top = FAMILY_ALIASES.get(top_family, top_family)
        norm_sf = FAMILY_ALIASES.get(sf_family, sf_family)
        if norm_top != norm_sf:
            issues.append(ValidationIssue(
                code=CODE_FAMILY_MISMATCH,
                severity=ERROR,
                field="source_fields.artifact_family",
                message=(
                    f"Discrepancia: artifact_family superior='{top_family}' vs "
                    f"source_fields.artifact_family='{sf_family}'."
                ),
                recommendation="Unificar artifact_family en el registro superior y en source_fields.",
            ))

    # ── SF011 — familia desconocida ───────────────────────────────────────────
    effective_family = top_family or sf_family
    if effective_family and effective_family not in KNOWN_ARTIFACT_FAMILIES:
        issues.append(ValidationIssue(
            code=CODE_UNKNOWN_ARTIFACT_FAMILY,
            severity=WARNING,
            field="artifact_family",
            message=f"artifact_family='{effective_family}' no pertenece al catálogo conocido.",
            recommendation="Verificar si la familia es nueva y agregarla al contrato, o usar una familia existente.",
        ))

    # ── SF006 — campos prohibidos ─────────────────────────────────────────────
    if strict_forbidden:
        for fld in FORBIDDEN_FIELDS:
            if fld in sf:
                sev = ERROR if strict_forbidden else WARNING
                issues.append(ValidationIssue(
                    code=CODE_FORBIDDEN_FIELD,
                    severity=sev,
                    field=f"source_fields.{fld}",
                    message=f"Campo prohibido '{fld}' encontrado en source_fields.",
                    recommendation=_forbidden_recommendation(fld),
                ))

    # ── SF007 — campos legados ────────────────────────────────────────────────
    for fld in LEGACY_FIELDS:
        if fld in sf:
            sev = ERROR if legacy_as_error else WARNING
            issues.append(ValidationIssue(
                code=CODE_LEGACY_FIELD,
                severity=sev,
                field=f"source_fields.{fld}",
                message=(
                    f"Campo legado '{fld}' en source_fields (patrón TW histórico). "
                    f"DT035 recomienda usar '{_legacy_replacement(fld)}' en su lugar."
                ),
                recommendation=(
                    f"Migrar a '{_legacy_replacement(fld)}' para nuevos artefactos. "
                    "No es bloqueante para artefactos ya en el canon histórico."
                ),
            ))

    # ── SF012 — campos arbitrarios sin prefijo x_ ─────────────────────────────
    all_known_fields = (
        BASELINE_REQUIRED_FIELDS
        | DT035_MINIMUM_COMMON_FIELDS
        | OPTIONAL_COMMON_FIELDS
        | DERIVED_COMMON_FIELDS
        | FORBIDDEN_FIELDS
        | LEGACY_FIELDS
        | frozenset({"needs_title_normalization", "document_key", "color",
                     "correction_note", "correction_session", "source",
                     "tmap.edges", "tmap.id"})
    )
    for fld in sf:
        if (
            fld not in all_known_fields
            and not fld.startswith("declared_")
            and not fld.startswith("optional_")
            and not fld.startswith("derived_")
            and not _X_PREFIX_RE.match(fld)
        ):
            issues.append(ValidationIssue(
                code=CODE_ARBITRARY_EXTENSION_FIELD,
                severity=WARNING,
                field=f"source_fields.{fld}",
                message=(
                    f"Campo '{fld}' no es estándar y no usa prefijo x_. "
                    "Los campos extendidos deben usar prefijo x_."
                ),
                recommendation=f"Renombrar a 'x_{fld}' o verificar si pertenece al contrato DT035.",
            ))

    # ── Campos requeridos baseline (S0133 §7.2) ───────────────────────────────
    # Solo se validan cuando el registro declara artifact_family (es un artefacto
    # de sesión/diagnóstico), no para tiddlers regulares sin familia declarada.
    if effective_family:
        for req in BASELINE_REQUIRED_FIELDS:
            if req not in sf or not sf[req].strip():
                issues.append(ValidationIssue(
                    code=CODE_MISSING_BASELINE_FIELD,
                    severity=ERROR,
                    field=f"source_fields.{req}",
                    message=f"Campo mínimo baseline '{req}' ausente o vacío en source_fields.",
                    recommendation=f"Agregar '{req}' con valor no vacío al contrato DT035 v1.",
                ))

    # ── SF008 — canonical_status con valor inválido ───────────────────────────
    cs = sf.get("canonical_status", "")
    if cs and cs not in ALLOWED_CANONICAL_STATUSES:
        sev = ERROR if strict_status else WARNING
        issues.append(ValidationIssue(
            code=CODE_INVALID_CANONICAL_STATUS,
            severity=sev,
            field="source_fields.canonical_status",
            message=f"canonical_status='{cs}' no es un valor admitido.",
            recommendation=(
                f"Usar uno de: {', '.join(sorted(ALLOWED_CANONICAL_STATUSES))}. "
                "Para nuevos candidatos usar 'candidate_not_admitted'."
            ),
        ))

    # ── SF009 — source_path inseguro ──────────────────────────────────────────
    sp = sf.get("source_path", "")
    if sp:
        path_issues = _check_source_path(sp)
        for pi_sev, pi_msg, pi_rec in path_issues:
            sev = ERROR if (strict_path and pi_sev == ERROR) else pi_sev
            issues.append(ValidationIssue(
                code=CODE_UNSAFE_SOURCE_PATH,
                severity=sev,
                field="source_fields.source_path",
                message=pi_msg,
                recommendation=pi_rec,
            ))

    # ── Campos DT035 extendidos (level=dt035 o family) ────────────────────────
    # Solo aplica a artefactos con artifact_family conocida.
    if level in ("dt035", "family") and effective_family:
        for req in DT035_EXTENDED_COMMON_FIELDS:
            if req not in sf or not sf[req].strip():
                issues.append(ValidationIssue(
                    code=CODE_MISSING_DT035_FIELD,
                    severity=WARNING,
                    field=f"source_fields.{req}",
                    message=f"Campo DT035 v1 recomendado '{req}' ausente o vacío.",
                    recommendation=(
                        f"Agregar '{req}' para completar el contrato DT035 v1 completo. "
                        "Requerido para nuevos artefactos canonizables."
                    ),
                ))

    # ── Campos declared_* por familia (level=family) ─────────────────────────
    if (level == "family" or family_check) and effective_family:
        norm_family = FAMILY_ALIASES.get(canonical_family, canonical_family)
        declared = FAMILY_DECLARED_FIELDS.get(norm_family, frozenset())
        for req in declared:
            if req not in sf or not sf[req].strip():
                issues.append(ValidationIssue(
                    code=CODE_MISSING_FAMILY_DECLARED_FIELD,
                    severity=WARNING,
                    field=f"source_fields.{req}",
                    message=(
                        f"Campo declared '{req}' requerido para familia "
                        f"'{norm_family}' ausente o vacío."
                    ),
                    recommendation=(
                        f"Agregar '{req}' en source_fields con el valor semántico "
                        "correspondiente a esta familia. Ver DT035 §6 para el contenido esperado."
                    ),
                ))

    return issues


# ── Helpers internos ──────────────────────────────────────────────────────────

def _check_source_path(sp: str) -> list[tuple[str, str, str]]:
    """Verifica seguridad de source_path. Devuelve lista de (severidad, msg, rec)."""
    issues = []

    if sp.startswith("/"):
        issues.append((
            ERROR,
            f"source_path='{sp}' es una ruta absoluta (prohibida).",
            "Usar ruta relativa desde la raíz del repositorio.",
        ))
        return issues

    if ".." in sp.split("/"):
        issues.append((
            ERROR,
            f"source_path='{sp}' contiene '..', lo que permite path traversal.",
            "Usar ruta relativa simple sin componentes '..'.",
        ))

    if _CANON_JSONL_RE.search(sp):
        issues.append((
            ERROR,
            f"source_path='{sp}' apunta directamente a un archivo de canon tiddlers_*.jsonl.",
            "source_path debe apuntar a la fuente en data/out/local/sessions/ o data/out/local/pipeline/.",
        ))

    starts_with_allowed = any(sp.startswith(p) for p in ALLOWED_SOURCE_PATH_PREFIXES)
    if not starts_with_allowed:
        issues.append((
            WARNING,
            f"source_path='{sp}' no comienza con una ruta gobernada permitida.",
            (
                "source_path debe comenzar con: "
                + " | ".join(ALLOWED_SOURCE_PATH_PREFIXES)
            ),
        ))

    if sp.startswith("data/sessions/"):
        issues.append((
            WARNING,
            f"source_path='{sp}' usa la ruta legada 'data/sessions/' (pre-S66).",
            "Para nuevos artefactos usar 'data/out/local/sessions/'.",
        ))

    return issues


_LEGACY_MAP: dict[str, str] = {
    "type":     "source_type",
    "tags":     "source_tags_json",
    "created":  "source_created",
    "modified": "source_modified",
    "tmap.id":  "(eliminar; no replicar campos TiddlyMap en nuevos artefactos)",
}


def _legacy_replacement(fld: str) -> str:
    return _LEGACY_MAP.get(fld, f"source_{fld}")


def _forbidden_recommendation(fld: str) -> str:
    recs: dict[str, str] = {
        "source_tags":    "Usar 'source_tags_json' (JSON serializado).",
        "normalized_tags": "Este campo es derivado; no incluirlo en source_fields.",
        "source_fields":  "source_fields no puede anidarse a sí mismo.",
        "source_position": "Este campo es reservado por el pipeline de canonical_position.",
        "source_role":    "Usar 'x_source_role' si se necesita como extensión no canónica.",
        "relations":      "Las relaciones van en el campo top-level 'relations', no en source_fields.",
        "id":             "El campo 'id' es identidad canónica; no replicar en source_fields.",
        "title":          "El campo 'title' es identidad canónica; no replicar en source_fields.",
        "content":        "El contenido va en 'text' o 'content' top-level; no en source_fields.",
        "normalized_tags": "Derivado regenerable; no incluirlo en source_fields.",
    }
    return recs.get(fld, f"Eliminar '{fld}' de source_fields o verificar el contrato DT035.")


# ── Función de resumen rápido ─────────────────────────────────────────────────

def summarize_issues(issues: list[ValidationIssue]) -> dict[str, Any]:
    """Devuelve un dict con conteos y lista de issues para reportes."""
    errors = [i for i in issues if i.severity == ERROR]
    warnings = [i for i in issues if i.severity == WARNING]
    return {
        "total": len(issues),
        "errors": len(errors),
        "warnings": len(warnings),
        "error_codes": sorted({i.code for i in errors}),
        "warning_codes": sorted({i.code for i in warnings}),
        "issues": [
            {
                "code": i.code,
                "severity": i.severity,
                "field": i.field,
                "message": i.message,
                "recommendation": i.recommendation,
            }
            for i in issues
        ],
    }
