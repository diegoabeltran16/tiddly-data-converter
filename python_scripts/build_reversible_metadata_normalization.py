#!/usr/bin/env python3
"""build_reversible_metadata_normalization.py — S0136

Normalización dry-run de metadata reversible para artefactos de sesión/diagnóstico.

Lee el canon local (solo lectura) y clasifica cada artefacto con artifact_family
en uno de cuatro estados de normalización:

  no_change         — metadata ya gobernada; sin acción requerida
  safe_to_normalize — deuda técnica corregible (ej: ruta legada data/sessions/)
  needs_review      — ambigüedad que requiere decisión humana
  blocked           — incumplimiento de contrato S0133 que bloquea normalización

NO modifica ningún archivo canónico.
Genera patch_preview reversible para records safe_to_normalize.

Uso
---
  python3 build_reversible_metadata_normalization.py \\
    --canon-root data/out/local/ \\
    --out-dir data/out/local/pipeline/reversible_metadata/s0136/ \\
    --session s0136
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_CANON_ROOT = REPO_ROOT / "data" / "out" / "local"
DEFAULT_OUT_DIR = DEFAULT_CANON_ROOT / "pipeline" / "reversible_metadata" / "s0136"

sys.path.insert(0, str(SCRIPT_DIR))

from source_fields_contract import (  # noqa: E402
    ERROR,
    WARNING,
    BASELINE_REQUIRED_FIELDS,
    FORBIDDEN_FIELDS,
    LEGACY_FIELDS,
    KNOWN_ARTIFACT_FAMILIES,
    ALLOWED_SOURCE_PATH_PREFIXES,
    validate_source_fields,
    summarize_issues,
)

SCHEMA = "metadata-normalization-plan/v1"

# Legacy path prefix (pre-S66 governance)
LEGACY_PATH_PREFIX = "data/sessions/"
# Current governed path prefix
GOVERNED_PATH_PREFIX = "data/out/local/sessions/"


# ── Normalization classifier ──────────────────────────────────────────────────

def classify_record(tiddler: dict[str, Any]) -> dict[str, Any]:
    """Classify a single tiddler's normalization status."""
    sf = tiddler.get("source_fields") or {}
    if not isinstance(sf, dict):
        return _make_result("blocked", tiddler, sf,
                            ["source_fields no es un dict."], [], {})

    fam = sf.get("artifact_family", "") or tiddler.get("artifact_family", "")
    if not fam:
        return _make_result("no_change", tiddler, sf, [], [], {})

    # Run source_fields_contract validation
    issues = validate_source_fields(tiddler, level="baseline", strict_forbidden=True,
                                    legacy_as_error=False)
    summary = summarize_issues(issues)
    errors = [i["message"] for i in summary["issues"] if i["severity"] == ERROR]
    warnings = [i["message"] for i in summary["issues"]
                if i["severity"] == WARNING
                and i.get("code") not in ("SF007", "SF009")]  # exclude legacy/path warnings
    # SF007 = TW legacy fields (migration recommendation, not blocking)
    # SF009 for legacy paths = the normalization action itself; not an extra warning

    # Evaluate source_path
    source_path = sf.get("source_path", "") or ""
    patch_preview: dict[str, Any] = {}
    normalization_actions: list[str] = []

    if source_path.startswith(LEGACY_PATH_PREFIX):
        governed_path = GOVERNED_PATH_PREFIX + source_path[len(LEGACY_PATH_PREFIX):]
        patch_preview = {
            "field": "source_fields.source_path",
            "operation": "replace",
            "from": source_path,
            "to": governed_path,
            "reason": "Migrar ruta legada pre-S66 a ruta gobernada.",
            "rollback_hint": f"Restaurar source_path a '{source_path}'.",
        }
        normalization_actions.append(
            f"Migrar source_path '{source_path}' → '{governed_path}'"
        )

    # Also check provenance_ref
    prov_ref = sf.get("provenance_ref", "") or ""
    if prov_ref.startswith(LEGACY_PATH_PREFIX):
        governed_prov = GOVERNED_PATH_PREFIX + prov_ref[len(LEGACY_PATH_PREFIX):]
        patch_preview["provenance_ref_patch"] = {
            "field": "source_fields.provenance_ref",
            "from": prov_ref,
            "to": governed_prov,
        }
        normalization_actions.append(
            f"Migrar provenance_ref '{prov_ref}' → '{governed_prov}'"
        )

    # Also check document_key (legacy pattern)
    doc_key = sf.get("document_key", "") or ""
    if doc_key.startswith(LEGACY_PATH_PREFIX.rstrip("/")):
        normalization_actions.append(
            f"Revisar document_key '{doc_key[:50]}' (referencia legada detectada)"
        )

    # Check for relational fields in source_fields (never allowed)
    relation_fields_in_sf = [k for k in sf if k == "relations" or k.startswith("relation_")]
    if relation_fields_in_sf:
        errors.append(
            f"Campos relacionales en source_fields: {relation_fields_in_sf}. "
            "Las relaciones no deben duplicarse dentro de source_fields."
        )

    # Determine status
    if errors:
        status = "blocked"
    elif normalization_actions:
        if warnings:
            status = "needs_review"
        else:
            status = "safe_to_normalize"
    elif warnings:
        status = "needs_review"
    else:
        status = "no_change"

    return _make_result(status, tiddler, sf, errors, normalization_actions,
                        patch_preview, warnings=warnings)


def _make_result(
    status: str,
    tiddler: dict[str, Any],
    sf: dict[str, Any],
    blocking_issues: list[str],
    normalization_actions: list[str],
    patch_preview: dict[str, Any],
    *,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "tiddler_id": tiddler.get("id", ""),
        "title": tiddler.get("title", "")[:120],
        "artifact_family": sf.get("artifact_family", "") or tiddler.get("artifact_family", ""),
        "source_path": sf.get("source_path", ""),
        "normalization_status": status,
        "normalization_actions": normalization_actions,
        "blocking_issues": blocking_issues,
        "warnings": warnings or [],
        "patch_preview": patch_preview,
        "inferred_metadata_note": (
            "La metadata inferida (keywords, headings, referenced_sessions, etc.) "
            "permanece en inferred_metadata y no se normaliza en esta etapa."
        ),
    }


# ── Canon reader ──────────────────────────────────────────────────────────────

def read_session_tiddlers(canon_root: Path) -> list[dict[str, Any]]:
    """Read tiddlers with artifact_family from canon."""
    records = []
    for shard in sorted(canon_root.glob("tiddlers_*.jsonl")):
        with shard.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                sf = rec.get("source_fields") or {}
                if isinstance(sf, dict) and sf.get("artifact_family"):
                    records.append(rec)
    return records


# ── Report builders ───────────────────────────────────────────────────────────

def build_plan(
    results: list[dict[str, Any]],
    *,
    session: str,
    canon_root: Path,
) -> dict[str, Any]:
    counts = {"no_change": 0, "safe_to_normalize": 0, "needs_review": 0, "blocked": 0}
    for r in results:
        s = r["normalization_status"]
        counts[s] = counts.get(s, 0) + 1
    return {
        "schema": SCHEMA,
        "session": session.upper(),
        "mode": "dry-run",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "source": {
            "canon_root": str(canon_root),
            "source_fields_contract": "S0133 (DT035-v1)",
        },
        "summary": {
            "total_records": len(results),
            **counts,
        },
        "records": results,
    }


def build_patch_preview_doc(results: list[dict[str, Any]]) -> dict[str, Any]:
    patches = [
        {
            "tiddler_id": r["tiddler_id"],
            "title": r["title"],
            "artifact_family": r["artifact_family"],
            "normalization_actions": r["normalization_actions"],
            "patches": r["patch_preview"],
        }
        for r in results
        if r["normalization_status"] == "safe_to_normalize" and r.get("patch_preview")
    ]
    return {
        "schema": "metadata-normalization-patch-preview/v1",
        "mode": "dry-run",
        "note": (
            "Previsualización de cambios hipotéticos. "
            "NINGÚN archivo ha sido modificado. "
            "Aplicar solo mediante script gobernado con validación previa."
        ),
        "patches": patches,
    }


def write_plan_json(plan: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    compact = dict(plan)
    compact["records_count"] = len(plan.get("records", []))
    compact_records = [
        {k: v for k, v in r.items() if k != "patch_preview"}
        for r in plan.get("records", [])
    ]
    compact["records"] = compact_records
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(compact, fh, indent=2, ensure_ascii=False)
    print(f"[OK] Plan JSON → {out_path}", file=sys.stderr)


def write_patch_preview(doc: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
    print(f"[OK] Patch preview → {out_path}", file=sys.stderr)


def write_review_csv(results: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "tiddler_id", "title", "artifact_family", "source_path",
        "normalization_status", "normalization_actions", "blocking_issues",
        "warnings",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({
                "tiddler_id": r["tiddler_id"],
                "title": r["title"][:100],
                "artifact_family": r["artifact_family"],
                "source_path": r["source_path"][:100],
                "normalization_status": r["normalization_status"],
                "normalization_actions": " | ".join(r["normalization_actions"])[:200],
                "blocking_issues": " | ".join(r["blocking_issues"])[:200],
                "warnings": " | ".join(r["warnings"])[:200],
            })
    print(f"[OK] CSV → {out_path}", file=sys.stderr)


def write_summary_md(plan: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    s = plan["summary"]
    recs = plan.get("records", [])
    blocked = [r for r in recs if r["normalization_status"] == "blocked"]
    safe = [r for r in recs if r["normalization_status"] == "safe_to_normalize"]

    lines = [
        "# S0136 — Plan de normalización de metadata reversible",
        "",
        f"**Modo:** `{plan['mode']}`  ",
        f"**Contrato:** `{plan['source']['source_fields_contract']}`  ",
        f"**Generado:** {plan['generated_at']}",
        "",
        "## Resumen",
        "",
        "| Estado | Registros |",
        "|--------|----------:|",
        f"| `no_change` | {s['no_change']} |",
        f"| `safe_to_normalize` | {s['safe_to_normalize']} |",
        f"| `needs_review` | {s['needs_review']} |",
        f"| `blocked` | {s['blocked']} |",
        f"| **Total** | **{s['total_records']}** |",
        "",
        "## Causa principal de safe_to_normalize",
        "",
        (f"Los {s['safe_to_normalize']} registros con `safe_to_normalize` tienen "
         f"`source_path` en la ruta legada `data/sessions/` (pre-S66). "
         f"El patch_preview propone migrar a `data/out/local/sessions/`."),
        "",
        "## Metadata inferida",
        "",
        "> Toda metadata inferida (headings, referencias S####/DT###, scripts) permanece "
        "en `inferred_metadata` y NO es objeto de normalización en esta etapa.",
        "",
    ]
    if blocked:
        lines += ["## Registros bloqueados", ""]
        for r in blocked[:10]:
            lines.append(f"- `{r['title'][:80]}`: {r['blocking_issues'][:2]}")
        lines.append("")

    lines += [
        "## Qué NO hace este plan",
        "",
        "- No escribe en `tiddlers_*.jsonl`.",
        "- No promueve metadata inferida a metadata reversible.",
        "- No mezcla campos relacionales con `source_fields`.",
        "- No corrige deuda automáticamente.",
        "",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Summary MD → {out_path}", file=sys.stderr)


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Normalización dry-run de metadata reversible (S0136)."
    )
    p.add_argument("--canon-root", type=Path, default=DEFAULT_CANON_ROOT)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--session", default="s0136")
    p.add_argument("--verbose", "-v", action="store_true", default=False)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    session_tag = args.session.lower()
    out = args.out_dir

    tiddlers = read_session_tiddlers(args.canon_root)
    if args.verbose:
        print(f"  Tiddlers con artifact_family: {len(tiddlers)}", file=sys.stderr)

    results = [classify_record(t) for t in tiddlers]
    plan = build_plan(results, session=session_tag, canon_root=args.canon_root)
    patch_doc = build_patch_preview_doc(results)

    write_plan_json(plan, out / f"{session_tag}_metadata_normalization_plan.json")
    write_patch_preview(patch_doc, out / f"{session_tag}_metadata_normalization_patch_preview.json")
    write_review_csv(results, out / f"{session_tag}_metadata_normalization_review.csv")
    write_summary_md(plan, out / f"{session_tag}_metadata_normalization_summary.md")

    s = plan["summary"]
    print(
        f"\n=== Metadata Normalization Plan ({session_tag.upper()}) ===\n"
        f"  Total      : {s['total_records']}\n"
        f"  no_change  : {s['no_change']}\n"
        f"  safe_norm  : {s['safe_to_normalize']}\n"
        f"  needs_rev  : {s['needs_review']}\n"
        f"  blocked    : {s['blocked']}\n"
    )
    return 1 if s["blocked"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
