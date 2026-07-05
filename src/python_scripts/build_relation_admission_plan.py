#!/usr/bin/env python3
"""build_relation_admission_plan.py — S0135

Planificador dry-run de promoción relacional con parche canónico reversible
y evidencia source_fields.

Este script opera EXCLUSIVAMENTE en modo dry-run.
NO modifica data/out/local/tiddlers_*.jsonl.
NO escribe relaciones admitidas.
NO tiene modo --apply.

Uso
---
  python3 build_relation_admission_plan.py \\
    --canon-glob "data/out/local/tiddlers_*.jsonl" \\
    --candidates-dir data/out/local/pipeline/relations_candidates \\
    --out-dir data/out/local/pipeline/relations_admission/s0135 \\
    --dry-run

  # --dry-run es el comportamiento por defecto y SIEMPRE está activo.

Bases normativas
----------------
  - S0133: contrato operativo de source_fields (DT035 v1)
  - S0134: metadata mínima reversible
  - DT036: política de promoción de relaciones candidatas a relaciones admitidas
  - DT031: contrato de salida para relaciones candidatas generadas por IA
  - S0131: circuito de admisión relacional gobernada
  - S0132: evaluador dry-run de admisibilidad relacional

Criterios de decisión (S0135 §6):
  promotable       — cumple todos los 10 criterios
  review_required  — potencial, pero requiere revisión humana
  blocked          — incumplimiento claro de criterios
  duplicate        — relación ya existe en canon
  unresolved_target— destino no resuelto
  invalid_contract — candidato no cumple contrato estructural
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_CANON_GLOB = str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl")
DEFAULT_CANDIDATES_DIR = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relations_candidates"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relations_admission" / "s0135"
)

sys.path.insert(0, str(SCRIPT_DIR))

from relation_candidate_contract import (  # noqa: E402
    ALLOWED_RELATION_TYPES,
    ALLOWED_EVIDENCE_KINDS,
    CANDIDATE_ID_RE,
    WEAK_EVIDENCE_THRESHOLD,
    verify_excerpt_in_source,
    is_self_relation,
)

SCHEMA_PLAN = "relation-admission-plan/v1"
SCHEMA_PATCH = "relation-admission-patch-preview/v1"

# Evidence kinds that are strong (promotable without extra review)
STRONG_EVIDENCE_KINDS: frozenset[str] = frozenset({
    "explicit_reference",
    "wikilink",
})

# Evidence kinds that need human review
MEDIUM_EVIDENCE_KINDS: frozenset[str] = frozenset({
    "content_embedded",
    "heading_reference",
    "title_mention",
})

# Evidence kinds that are weak / AI-only
WEAK_EVIDENCE_KINDS: frozenset[str] = frozenset({
    "ai_inference",
    "structural_tag",
})

# Confidence threshold per DT036
MIN_CONFIDENCE_P0 = 0.70
MIN_CONFIDENCE_P1 = 0.50

# Relations in P1/P2 tier (always require human review per DT036)
P1_P2_RELATION_TYPES: frozenset[str] = frozenset({
    "depende_de",
    "corrige",
    "contradice",
    "afecta_pipeline",
})

# NEVER: attempts to use an apply/write mode
_FORBIDDEN_FLAGS: frozenset[str] = frozenset({
    "--apply",
    "--write-canon",
    "--write",
    "--write-relations",
    "--force-admit",
    "--admit",
})


# ── Canon loader ──────────────────────────────────────────────────────────────

def load_canon_index(canon_glob: str) -> dict[str, dict[str, Any]]:
    """Build index of all canon tiddlers keyed by tiddler_id."""
    index: dict[str, dict[str, Any]] = {}
    for fpath in sorted(glob.glob(canon_glob)):
        with open(fpath, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                tid = rec.get("id", "")
                if tid:
                    index[tid] = rec
    return index


def build_canon_relation_set(canon: dict[str, dict[str, Any]]) -> set[tuple[str, str, str]]:
    """Build set of (source_id, target_id, type) for existing canonical relations."""
    existing: set[tuple[str, str, str]] = set()
    for tid, rec in canon.items():
        for rel in (rec.get("relations") or []):
            if isinstance(rel, dict):
                existing.add((tid, rel.get("target_id", ""), rel.get("type", "")))
    return existing


# ── Candidate loader ──────────────────────────────────────────────────────────

def load_candidates(candidates_dir: Path) -> list[dict[str, Any]]:
    """Load all candidates from the candidates directory, deduplicated by candidate_id."""
    seen: dict[str, dict[str, Any]] = {}

    # Prefer s0129 processed files over sample
    priority_paths: list[Path] = []
    sample_paths: list[Path] = []
    for fpath in sorted(candidates_dir.rglob("*.jsonl")):
        if "validation_report" in fpath.name or "human_review" in fpath.name:
            continue
        if "sample" in fpath.name:
            sample_paths.append(fpath)
        else:
            priority_paths.append(fpath)

    for fpath in priority_paths + sample_paths:
        with fpath.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    cid = rec.get("candidate_id", "")
                    if cid and cid not in seen:
                        seen[cid] = rec
                except json.JSONDecodeError:
                    pass

    return list(seen.values())


# ── Decision engine ───────────────────────────────────────────────────────────

def evaluate_candidate(
    candidate: dict[str, Any],
    canon: dict[str, dict[str, Any]],
    canon_relations: set[tuple[str, str, str]],
) -> dict[str, Any]:
    """Evaluate a single candidate against the 10 DT036 criteria.

    Returns a decision dict with: decision, admission_reasons, blocking_reasons,
    risk_level, metadata_patch_preview, reverse_preview.
    """
    admission_reasons: list[str] = []
    blocking_reasons: list[str] = []

    cid = candidate.get("candidate_id", "")
    source = candidate.get("source") or {}
    target = candidate.get("target") or {}
    relation = candidate.get("relation") or {}
    evidence = candidate.get("evidence") or {}
    confidence = candidate.get("confidence") or {}
    provenance = candidate.get("provenance") or {}

    src_id = source.get("tiddler_id", "")
    tgt_id = target.get("tiddler_id", "")
    rel_type = relation.get("type", "")
    ev_kind = evidence.get("kind", "")
    excerpt = evidence.get("excerpt", "")
    conf_score = confidence.get("score", 0.0)
    risk_flags = confidence.get("risk_flags") or []
    resolution_status = target.get("resolution_status", "")

    # ── Criterion 0: Schema / contract validity ────────────────────────────────
    schema_ok = True
    if not cid or not CANDIDATE_ID_RE.match(cid):
        blocking_reasons.append(f"candidate_id='{cid}' no cumple el patrón rc1_<hex>.")
        schema_ok = False
    if not src_id:
        blocking_reasons.append("source.tiddler_id ausente.")
        schema_ok = False
    if not rel_type:
        blocking_reasons.append("relation.type ausente.")
        schema_ok = False

    if not schema_ok:
        return _make_decision("invalid_contract", blocking_reasons, [], "high",
                              candidate, None, None)

    # ── Criterion 1: source exists in canon ────────────────────────────────────
    src_tiddler = canon.get(src_id)
    if not src_tiddler:
        blocking_reasons.append(f"source.tiddler_id='{src_id}' no encontrado en el canon.")
    else:
        admission_reasons.append(f"Fuente verificada en canon: '{src_tiddler.get('title','')[:60]}'.")

    # ── Criterion 2: target exists or is resolved ──────────────────────────────
    tgt_tiddler = canon.get(tgt_id)
    if not tgt_tiddler:
        if resolution_status == "resolved":
            blocking_reasons.append(
                f"target.tiddler_id='{tgt_id}' marcado como resolved "
                "pero no encontrado en canon."
            )
        else:
            return _make_decision("unresolved_target",
                                  [f"target.tiddler_id='{tgt_id}' no resuelto (status='{resolution_status}')."],
                                  admission_reasons, "medium", candidate, None, None)
    else:
        admission_reasons.append(f"Destino verificado en canon: '{tgt_tiddler.get('title','')[:60]}'.")

    # ── Self-relation check ────────────────────────────────────────────────────
    if is_self_relation(src_id, tgt_id):
        blocking_reasons.append("Auto-relación detectada (source == target).")

    # ── Criterion 3: relation type in catalog ──────────────────────────────────
    if rel_type not in ALLOWED_RELATION_TYPES:
        blocking_reasons.append(
            f"relation.type='{rel_type}' no pertenece al catálogo permitido (DT029/DT031)."
        )
    else:
        admission_reasons.append(f"Tipo de relación permitido: '{rel_type}'.")

    # ── Criterion 4: evidence excerpt verifiable in source ─────────────────────
    src_text = (src_tiddler or {}).get("text", "") if src_tiddler else ""
    excerpt_verified = verify_excerpt_in_source(excerpt, src_text)
    if excerpt_verified is False:
        blocking_reasons.append(
            f"El excerpt '{excerpt[:60]}...' no se encontró en el texto fuente."
        )
    elif excerpt_verified is None:
        blocking_reasons.append(
            "El texto fuente está ausente; no se puede verificar el excerpt."
        )
    else:
        admission_reasons.append("Excerpt verificado en texto fuente.")

    # ── Criterion 5: evidence declares source_fields origin ───────────────────
    prov_source_path = provenance.get("source_path", "") or ""
    prov_generated_by = provenance.get("generated_by", "") or ""
    if not prov_source_path and not prov_generated_by:
        blocking_reasons.append(
            "La evidencia no declara origen mediante provenance.source_path "
            "ni provenance.generated_by."
        )
    else:
        admission_reasons.append(
            f"Procedencia declarada: generated_by='{prov_generated_by}'."
        )

    # ── Criterion 6: not duplicate of existing canonical relation ──────────────
    if (src_id, tgt_id, rel_type) in canon_relations:
        return _make_decision("duplicate",
                              [f"La relación ({rel_type}: {src_id}→{tgt_id}) ya existe en el canon."],
                              admission_reasons, "low", candidate, None, None)

    # ── Criterion 7: not solely weak AI inference ──────────────────────────────
    is_weak_ai = (
        ev_kind == "ai_inference"
        or any(f in {"weak_semantic_inference", "ai_inference_unverifiable"} for f in risk_flags)
    )
    if is_weak_ai:
        if conf_score < MIN_CONFIDENCE_P0:
            blocking_reasons.append(
                f"Evidencia débil (ai_inference, score={conf_score:.2f} < {MIN_CONFIDENCE_P0}). "
                f"risk_flags={risk_flags}. DT036: no promocionable sin revisión reforzada."
            )
        else:
            blocking_reasons.append(
                f"Evidencia ai_inference (score={conf_score:.2f}). "
                "DT036: requiere revisión humana reforzada."
            )

    # ── Confidence threshold ───────────────────────────────────────────────────
    min_conf = MIN_CONFIDENCE_P1 if rel_type in P1_P2_RELATION_TYPES else MIN_CONFIDENCE_P0
    if conf_score < min_conf:
        blocking_reasons.append(
            f"confidence.score={conf_score:.2f} por debajo del umbral mínimo "
            f"{min_conf:.2f} para '{rel_type}' (DT036)."
        )
    else:
        admission_reasons.append(
            f"Confianza suficiente: score={conf_score:.2f} ≥ {min_conf:.2f}."
        )

    # ── Criterion 8: representable as reversible metadata ─────────────────────
    # Always true in dry-run: we can always construct the patch_preview
    admission_reasons.append("Metadata reversible: patch_preview generado.")

    # ── Build patch preview ────────────────────────────────────────────────────
    patch_preview = None
    reverse_preview = None
    if src_tiddler and tgt_tiddler:
        patch_preview = _build_patch_preview(candidate, src_tiddler, tgt_tiddler)
        reverse_preview = _build_reverse_preview(src_tiddler, rel_type, tgt_id)

    # ── Final decision ─────────────────────────────────────────────────────────
    if blocking_reasons:
        # Check if the only issue is needing human review (not a hard block)
        hard_blocks = [
            r for r in blocking_reasons
            if not any(
                phrase in r.lower()
                for phrase in ["revisión humana", "review", "ai_inference (score"]
            )
        ]
        if hard_blocks:
            decision = "blocked"
            risk = "high"
        else:
            decision = "review_required"
            risk = "medium"
    else:
        # P1/P2 types always need human review
        if rel_type in P1_P2_RELATION_TYPES:
            decision = "review_required"
            risk = "medium"
            admission_reasons.append(
                f"Tipo '{rel_type}' (P1/P2) requiere revisión humana obligatoria per DT036."
            )
        elif ev_kind in WEAK_EVIDENCE_KINDS:
            decision = "review_required"
            risk = "medium"
        elif ev_kind in MEDIUM_EVIDENCE_KINDS:
            decision = "review_required"
            risk = "low"
        else:
            decision = "promotable"
            risk = "low"
            admission_reasons.append(
                "Cumple todos los criterios DT036. "
                "Requiere compuerta humana (human_approved) antes de admisión real."
            )

    return _make_decision(decision, blocking_reasons, admission_reasons, risk,
                          candidate, patch_preview, reverse_preview)


def _make_decision(
    decision: str,
    blocking_reasons: list[str],
    admission_reasons: list[str],
    risk: str,
    candidate: dict[str, Any],
    patch_preview: dict | None,
    reverse_preview: dict | None,
) -> dict[str, Any]:
    source = candidate.get("source") or {}
    target = candidate.get("target") or {}
    relation = candidate.get("relation") or {}
    evidence = candidate.get("evidence") or {}
    provenance = candidate.get("provenance") or {}

    return {
        "candidate_id": candidate.get("candidate_id", ""),
        "decision": decision,
        "source": {
            "tiddler_id": source.get("tiddler_id", ""),
            "title": source.get("title", ""),
        },
        "target": {
            "tiddler_id": target.get("tiddler_id", ""),
            "title": target.get("title", ""),
            "resolution_status": target.get("resolution_status", "unresolved"),
        },
        "relation": {
            "type": relation.get("type", ""),
            "direction": relation.get("direction", "source_to_target"),
        },
        "evidence": {
            "kind": evidence.get("kind", ""),
            "excerpt": (evidence.get("excerpt", "") or "")[:200],
            "source_fields": [
                provenance.get("source_path", ""),
                provenance.get("generated_by", ""),
            ],
            "verified_in_source": evidence.get("kind", "") in STRONG_EVIDENCE_KINDS,
        },
        "admission_reasons": admission_reasons,
        "blocking_reasons": blocking_reasons,
        "risk_level": risk,
        "metadata_patch_preview": patch_preview or {},
        "reverse_preview": reverse_preview or {},
    }


def _build_patch_preview(
    candidate: dict[str, Any],
    src_tiddler: dict[str, Any],
    tgt_tiddler: dict[str, Any],
) -> dict[str, Any]:
    """Build the hypothetical change if this relation were admitted."""
    relation = candidate.get("relation") or {}
    evidence = candidate.get("evidence") or {}
    provenance = candidate.get("provenance") or {}
    src_id = src_tiddler.get("id", "")
    tgt_id = tgt_tiddler.get("id", "")
    rel_type = relation.get("type", "")

    existing_relations = src_tiddler.get("relations") or []
    proposed_relation = {
        "type": rel_type,
        "target_id": tgt_id,
        "evidence": evidence.get("kind", ""),
        "status": "admitted",
        "provenance": {
            "candidate_id": candidate.get("candidate_id", ""),
            "generated_by": provenance.get("generated_by", ""),
            "admitted_by": "PENDING_HUMAN_APPROVAL",
            "admitted_at": "PENDING",
        },
    }

    after_relations = list(existing_relations) + [proposed_relation]

    return {
        "tiddler_id": src_id,
        "target_file": _guess_shard_path(src_id, provenance),
        "operation": "append_relation",
        "path": "relations",
        "before_summary": {
            "relation_count": len(existing_relations),
            "relation_types": sorted({r.get("type", "") for r in existing_relations if isinstance(r, dict)}),
        },
        "after_preview": {
            "relation_count": len(after_relations),
            "appended_relation": proposed_relation,
        },
        "rollback_hint": (
            f"Eliminar de 'relations' del tiddler {src_id} la entrada con "
            f"type='{rel_type}' y target_id='{tgt_id}'. "
            "El candidato original permanece en staging con status='superseded'."
        ),
    }


def _build_reverse_preview(
    src_tiddler: dict[str, Any],
    rel_type: str,
    tgt_id: str,
) -> dict[str, Any]:
    """Show what TW reverse would see for this relation."""
    return {
        "note": (
            "Las relaciones canónicas se almacenan en el campo 'relations' del tiddler, "
            "no como campo nativo TiddlyWiki. El reverse_tiddlers exporta 'relations' "
            "como campo custom (JSON). TiddlyWiki no renderiza relaciones automáticamente."
        ),
        "tiddler_title": src_tiddler.get("title", "")[:80],
        "relation_visible_in_tw": False,
        "reverse_field_hint": {
            "field_name": "relations",
            "field_value_preview": f"[{{\"type\":\"{rel_type}\",\"target_id\":\"{tgt_id}\",\"status\":\"admitted\"}}]",
        },
    }


def _guess_shard_path(tiddler_id: str, provenance: dict[str, Any]) -> str:
    """Guess the canon shard path from provenance."""
    sp = provenance.get("source_path", "")
    if sp and "tiddlers_" in sp:
        return sp
    return "data/out/local/tiddlers_*.jsonl (shard indeterminado)"


# ── Report builders ───────────────────────────────────────────────────────────

def build_plan(
    items: list[dict[str, Any]],
    *,
    session: str,
    canon_glob: str,
    candidates_dir: Path,
) -> dict[str, Any]:
    counts: dict[str, int] = {
        "promotable": 0, "review_required": 0, "blocked": 0,
        "duplicate": 0, "unresolved_target": 0, "invalid_contract": 0,
    }
    for item in items:
        d = item["decision"]
        counts[d] = counts.get(d, 0) + 1

    return {
        "schema": SCHEMA_PLAN,
        "session": session.upper(),
        "mode": "dry-run",
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "inputs": {
            "canon_glob": canon_glob,
            "candidates_dir": str(candidates_dir),
            "source_fields_policy": "S0133 (DT035-v1)",
            "metadata_reversibility_policy": "S0134 (minimal-reversible-metadata/v1)",
        },
        "summary": {
            "total_candidates": len(items),
            **counts,
        },
        "items": items,
    }


def build_patch_preview_doc(items: list[dict[str, Any]]) -> dict[str, Any]:
    patches = [
        {
            "candidate_id": item["candidate_id"],
            "target_file": item.get("metadata_patch_preview", {}).get("target_file", "?"),
            "tiddler_id": item.get("metadata_patch_preview", {}).get("tiddler_id", ""),
            "operation": item.get("metadata_patch_preview", {}).get("operation", ""),
            "path": item.get("metadata_patch_preview", {}).get("path", ""),
            "before_summary": item.get("metadata_patch_preview", {}).get("before_summary", {}),
            "after_preview": item.get("metadata_patch_preview", {}).get("after_preview", {}),
            "rollback_hint": item.get("metadata_patch_preview", {}).get("rollback_hint", ""),
        }
        for item in items
        if item["decision"] == "promotable" and item.get("metadata_patch_preview")
    ]
    return {
        "schema": SCHEMA_PATCH,
        "mode": "dry-run",
        "note": (
            "Este documento es una PREVISUALIZACIÓN de los cambios hipotéticos "
            "que se realizarían al canon si las relaciones promotable fueran admitidas. "
            "NINGÚN archivo ha sido modificado."
        ),
        "patches": patches,
    }


def write_plan_json(plan: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2, ensure_ascii=False)
    print(f"[OK] Plan JSON → {out_path}", file=sys.stderr)


def write_patch_preview(doc: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
    print(f"[OK] Patch preview → {out_path}", file=sys.stderr)


def write_review_csv(items: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "candidate_id", "decision", "source_title", "target_title",
        "relation_type", "evidence_kind", "verified_in_source",
        "risk_level", "blocking_reasons", "review_notes",
    ]
    rows = []
    for item in items:
        rows.append({
            "candidate_id": item["candidate_id"],
            "decision": item["decision"],
            "source_title": item.get("source", {}).get("title", "")[:100],
            "target_title": item.get("target", {}).get("title", "")[:100],
            "relation_type": item.get("relation", {}).get("type", ""),
            "evidence_kind": item.get("evidence", {}).get("kind", ""),
            "verified_in_source": item.get("evidence", {}).get("verified_in_source", False),
            "risk_level": item.get("risk_level", ""),
            "blocking_reasons": " | ".join(item.get("blocking_reasons", []))[:200],
            "review_notes": " | ".join(item.get("admission_reasons", []))[:200],
        })
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[OK] CSV de revisión → {out_path}", file=sys.stderr)


def write_summary_md(plan: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    s = plan["summary"]
    items = plan.get("items", [])

    lines = [
        "# S0135 — Plan de admisión relacional dry-run",
        "",
        f"**Modo:** `{plan['mode']}`  ",
        f"**Sesión:** `{plan['session']}`  ",
        f"**Generado:** {plan['created_at']}",
        "",
        "## Fuente",
        "",
        f"- Canon: `{plan['inputs']['canon_glob']}`",
        f"- Candidatos: `{plan['inputs']['candidates_dir']}`",
        f"- Política source_fields: `{plan['inputs']['source_fields_policy']}`",
        f"- Política metadata reversible: `{plan['inputs']['metadata_reversibility_policy']}`",
        "",
        "## Resultados",
        "",
        "| Decisión | Candidatos |",
        "|----------|----------:|",
    ]
    for k in ("promotable", "review_required", "blocked", "duplicate",
               "unresolved_target", "invalid_contract"):
        lines.append(f"| `{k}` | {s.get(k, 0)} |")
    lines += [
        f"| **Total** | **{s['total_candidates']}** |",
        "",
    ]

    # Promotable details
    promotable = [i for i in items if i["decision"] == "promotable"]
    if promotable:
        lines += [
            "## Candidatos promotables",
            "",
            "| candidate_id | Relación | Fuente | Destino |",
            "|--------------|----------|--------|---------|",
        ]
        for i in promotable:
            lines.append(
                f"| `{i['candidate_id'][:20]}` "
                f"| `{i['relation']['type']}` "
                f"| {i['source']['title'][:50]} "
                f"| {i['target']['title'][:50]} |"
            )
        lines.append("")

    # Blocked details
    blocked = [i for i in items if i["decision"] == "blocked"]
    if blocked:
        lines += ["## Candidatos bloqueados", ""]
        for i in blocked:
            lines.append(f"- **{i['candidate_id'][:20]}**: {' | '.join(i['blocking_reasons'][:2])}")
        lines.append("")

    # Unresolved
    unresolved = [i for i in items if i["decision"] == "unresolved_target"]
    if unresolved:
        lines += ["## Targets no resueltos", ""]
        for i in unresolved:
            lines.append(f"- `{i['candidate_id'][:20]}`: {' | '.join(i['blocking_reasons'][:1])}")
        lines.append("")

    lines += [
        "## Dependencias con S0133 y S0134",
        "",
        "- **S0133 (source_fields_contract)**: usado para validar presencia de `provenance.source_path`.",
        "- **S0134 (metadata reversible)**: los patch_previews respetan la estructura reversible.",
        "",
        "## Qué falta antes de admisión real al canon",
        "",
        "1. Compuerta humana operativa (`human_approved=True` con operador y timestamp).",
        "2. Implementación de `relation_admission_log` para auditoría.",
        "3. Extensión de `admit_session_candidates.py` para soportar admisión relacional.",
        "4. Procedimiento de reversión documentado y testeado.",
        "5. Al menos 3 candidatos que pasen todo el circuito en dry-run (hoy: "
        f"{s.get('promotable', 0)} promotable{'s' if s.get('promotable',0)!=1 else ''}).",
        "",
        f"> **Nota:** Este plan es SOLO dry-run. El canon NO ha sido modificado.",
        "",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Resumen Markdown → {out_path}", file=sys.stderr)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _check_forbidden_flags(argv: list[str]) -> None:
    """Abort immediately if any forbidden flag is present."""
    for arg in argv:
        if arg.lower() in _FORBIDDEN_FLAGS or any(arg.lower().startswith(f) for f in _FORBIDDEN_FLAGS):
            print(
                f"\nBLOQUEADO: S0135 solo genera plan dry-run. "
                f"No escribe relaciones en el canon.\n"
                f"  El flag '{arg}' está explícitamente prohibido.\n",
                file=sys.stderr,
            )
            sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Planificador dry-run de promoción relacional (S0135). "
            "SOLO genera plan. NO escribe al canon. NO tiene modo --apply."
        ),
    )
    p.add_argument(
        "--canon-glob",
        default=DEFAULT_CANON_GLOB,
        help=f"Glob de shards canónicos. Default: {DEFAULT_CANON_GLOB}",
    )
    p.add_argument(
        "--candidates-dir",
        type=Path,
        default=DEFAULT_CANDIDATES_DIR,
        help=f"Directorio de candidatos relacionales. Default: {DEFAULT_CANDIDATES_DIR}",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Directorio de salida. Default: {DEFAULT_OUT_DIR}",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Modo dry-run (por defecto y siempre activo).",
    )
    p.add_argument(
        "--session",
        default="s0135",
        help="ID de la sesión. Default: s0135",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
    )
    return p


def main(argv: list[str] | None = None) -> int:
    raw_argv = argv if argv is not None else sys.argv[1:]
    _check_forbidden_flags(raw_argv)

    parser = build_parser()
    args = parser.parse_args(raw_argv)

    session_tag = args.session.lower()
    out = args.out_dir

    if args.verbose:
        print(f"[build_relation_admission_plan] session={session_tag}", file=sys.stderr)
        print(f"  canon_glob={args.canon_glob}", file=sys.stderr)
        print(f"  candidates_dir={args.candidates_dir}", file=sys.stderr)

    # 1. Load canon
    if args.verbose:
        print("  Cargando índice del canon...", file=sys.stderr)
    canon = load_canon_index(args.canon_glob)
    canon_relations = build_canon_relation_set(canon)

    if args.verbose:
        print(f"  Canon: {len(canon)} tiddlers, {len(canon_relations)} relaciones existentes.",
              file=sys.stderr)

    # 2. Load candidates
    if not args.candidates_dir.exists():
        print(f"[ERROR] candidates_dir no existe: {args.candidates_dir}", file=sys.stderr)
        return 2
    candidates = load_candidates(args.candidates_dir)
    if args.verbose:
        print(f"  Candidatos cargados: {len(candidates)}", file=sys.stderr)

    # 3. Evaluate each candidate
    items = [evaluate_candidate(c, canon, canon_relations) for c in candidates]

    # 4. Build documents
    plan = build_plan(items, session=session_tag, canon_glob=args.canon_glob,
                      candidates_dir=args.candidates_dir)
    patch_doc = build_patch_preview_doc(items)

    # 5. Write reports
    write_plan_json(plan, out / f"{session_tag}_relation_admission_plan.json")
    write_patch_preview(patch_doc, out / f"{session_tag}_relation_admission_patch_preview.json")
    write_review_csv(items, out / f"{session_tag}_relation_admission_review.csv")
    write_summary_md(plan, out / f"{session_tag}_relation_admission_summary.md")

    # 6. Print summary
    s = plan["summary"]
    print(
        f"\n=== Relation Admission Plan ({session_tag.upper()}) — DRY-RUN ===\n"
        f"  Total candidatos  : {s['total_candidates']}\n"
        f"  promotable        : {s['promotable']}\n"
        f"  review_required   : {s['review_required']}\n"
        f"  blocked           : {s['blocked']}\n"
        f"  duplicate         : {s['duplicate']}\n"
        f"  unresolved_target : {s['unresolved_target']}\n"
        f"  invalid_contract  : {s['invalid_contract']}\n"
    )
    print("[OK] Plan dry-run generado. El canon NO fue modificado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
