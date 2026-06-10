#!/usr/bin/env python3
"""relation_admission_gate.py — S0137

Compuerta humana mínima de admisión relacional (modo dry-run).

Evalúa relaciones candidatas y determina si podrían avanzar a admisión real,
exigiendo aprobación humana explícita + compatibilidad de tipo relacional.

NUNCA modifica tiddlers_*.jsonl.
NUNCA admite relaciones al canon.
Solo marca candidatos como admission_ready_dry_run o blocked.

Uso
---
  # Evaluar candidatos y generar log + reporte dry-run
  python3 relation_admission_gate.py \\
    --candidates-file data/out/local/pipeline/relations_candidates/s0129/valid_candidates.jsonl \\
    --canon-glob "data/out/local/tiddlers_*.jsonl" \\
    --out-dir data/out/local/pipeline/relation_admission/s0137/

  # Evaluar con fixture de prueba
  python3 relation_admission_gate.py \\
    --candidates-file tests/fixtures/gate_test_candidates.jsonl \\
    --out-dir /tmp/gate_test/

Estados de salida de un candidato:
  admission_ready_dry_run — pasa todos los controles; listo para compuerta real
  blocked                 — no pasa uno o más controles

NO existe modo --apply. Esta compuerta solo genera log y reporte.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_CANON_GLOB = str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl")
DEFAULT_CANDIDATES_FILE = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline"
    / "relations_candidates" / "s0129" / "valid_candidates.jsonl"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_admission" / "s0137"
)

sys.path.insert(0, str(SCRIPT_DIR))

from relation_candidate_contract import (  # noqa: E402
    ALLOWED_RELATION_TYPES,
    CANDIDATE_ID_RE,
    verify_excerpt_in_source,
)

SCHEMA_LOG = "relation-admission-log/v1"
SCHEMA_REPORT = "relation-admission-dry-run-report/v1"

# Types blocked for new candidates (historical types from S0136/S0137 analysis)
HISTORICAL_BLOCKED_TYPES: frozenset[str] = frozenset({
    "usa",
    "parte_de",
    "define",
    "requiere",
    "child_of",
})

ADMISSION_READY = "admission_ready_dry_run"
BLOCKED = "blocked"


# ── Canon loader ──────────────────────────────────────────────────────────────

def load_canon_index(canon_glob: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for fpath in sorted(glob.glob(canon_glob)):
        with open(fpath, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("id"):
                    index[rec["id"]] = rec
    return index


# ── Human review validator ────────────────────────────────────────────────────

def validate_human_review(hr: Any) -> list[str]:
    """Validate the human_review block. Returns list of blocking reasons."""
    reasons: list[str] = []

    if not hr or not isinstance(hr, dict):
        reasons.append("GATE-001: human_review ausente o no es un objeto.")
        return reasons

    status = hr.get("status", "")
    if status != "approved":
        reasons.append(
            f"GATE-002: human_review.status='{status}' — "
            "se requiere 'approved' para avanzar."
        )

    if not hr.get("reviewer", "").strip():
        reasons.append("GATE-003: human_review.reviewer ausente o vacío.")

    if not hr.get("reviewed_at", "").strip():
        reasons.append("GATE-004: human_review.reviewed_at ausente o vacío.")

    if not hr.get("decision_reason", "").strip():
        reasons.append("GATE-005: human_review.decision_reason ausente o vacío.")

    return reasons


# ── Gate evaluator ────────────────────────────────────────────────────────────

def evaluate_gate(
    candidate: dict[str, Any],
    canon: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate a single candidate through the admission gate."""
    reasons_blocked: list[str] = []
    reasons_ok: list[str] = []

    cid = candidate.get("candidate_id", "")
    source = candidate.get("source") or {}
    target = candidate.get("target") or {}
    relation = candidate.get("relation") or {}
    evidence = candidate.get("evidence") or {}
    human_review = candidate.get("human_review")
    provenance = candidate.get("provenance") or {}

    src_id = source.get("tiddler_id", "")
    tgt_id = target.get("tiddler_id", "")
    rel_type = relation.get("type", "")
    ev_kind = evidence.get("kind", "")
    excerpt = evidence.get("excerpt", "")
    resolution_status = target.get("resolution_status", "")

    # ── Criterio 1: candidato_id válido ───────────────────────────────────────
    if not cid or not CANDIDATE_ID_RE.match(cid):
        reasons_blocked.append(f"GATE-000: candidate_id='{cid}' inválido.")
    else:
        reasons_ok.append("candidate_id válido.")

    # ── Criterio 2: human_review ──────────────────────────────────────────────
    hr_issues = validate_human_review(human_review)
    if hr_issues:
        reasons_blocked.extend(hr_issues)
    else:
        reasons_ok.append(
            f"human_review aprobado por '{(human_review or {}).get('reviewer', '')}' "
            f"en {(human_review or {}).get('reviewed_at', '')}."
        )

    # ── Criterio 3: tipo relacional no histórico bloqueado ────────────────────
    if rel_type in HISTORICAL_BLOCKED_TYPES:
        reasons_blocked.append(
            f"GATE-006: relation.type='{rel_type}' es un tipo histórico bloqueado para "
            "nuevos candidatos (S0137). Usar tipo del catálogo DT029/DT031."
        )
    elif rel_type not in ALLOWED_RELATION_TYPES:
        reasons_blocked.append(
            f"GATE-007: relation.type='{rel_type}' no está en el catálogo "
            "DT029/DT031 ni en tipos históricos conocidos."
        )
    else:
        reasons_ok.append(f"Tipo relacional '{rel_type}' del catálogo formal.")

    # ── Criterio 4: source existe en canon ────────────────────────────────────
    src_tiddler = canon.get(src_id)
    if not src_tiddler:
        reasons_blocked.append(
            f"GATE-008: source.tiddler_id='{src_id}' no encontrado en el canon."
        )
    else:
        reasons_ok.append(f"Fuente en canon: '{src_tiddler.get('title','')[:60]}'.")

    # ── Criterio 5: target resuelto en canon ──────────────────────────────────
    tgt_tiddler = canon.get(tgt_id)
    if not tgt_tiddler:
        reasons_blocked.append(
            f"GATE-009: target.tiddler_id='{tgt_id}' no encontrado en el canon "
            f"(resolution_status='{resolution_status}')."
        )
    else:
        reasons_ok.append(f"Destino en canon: '{tgt_tiddler.get('title','')[:60]}'.")

    # ── Criterio 6: excerpt verificable ───────────────────────────────────────
    src_text = (src_tiddler or {}).get("text", "") if src_tiddler else ""
    excerpt_ok = verify_excerpt_in_source(excerpt, src_text)
    if excerpt_ok is False:
        reasons_blocked.append(
            f"GATE-010: excerpt '{excerpt[:60]}...' no verificado en texto fuente."
        )
    elif excerpt_ok is None:
        reasons_blocked.append(
            "GATE-011: texto fuente ausente; excerpt no verificable."
        )
    else:
        reasons_ok.append("Excerpt verificado en texto fuente.")

    # ── Criterio 7: self-relation ─────────────────────────────────────────────
    if src_id and src_id == tgt_id:
        reasons_blocked.append("GATE-012: Auto-relación detectada (source == target).")

    # ── Determinar estado final ───────────────────────────────────────────────
    status = BLOCKED if reasons_blocked else ADMISSION_READY

    # ── Hash de evidencia ─────────────────────────────────────────────────────
    evidence_str = json.dumps(evidence, sort_keys=True, ensure_ascii=False)
    evidence_hash = "sha256:" + hashlib.sha256(evidence_str.encode()).hexdigest()[:16]

    # ── Log ID ────────────────────────────────────────────────────────────────
    log_payload = f"{cid}|{src_id}|{tgt_id}|{rel_type}|{status}"
    log_id = "sha256:" + hashlib.sha256(log_payload.encode()).hexdigest()[:16]

    hr = human_review or {}
    return {
        "candidate_id": cid,
        "gate_status": status,
        "source_tiddler_id": src_id,
        "target_tiddler_id": tgt_id,
        "relation_type": rel_type,
        "blocking_reasons": reasons_blocked,
        "ok_reasons": reasons_ok,
        "human_review_status": hr.get("status", "(absent)"),
        "reviewer": hr.get("reviewer", ""),
        "reviewed_at": hr.get("reviewed_at", ""),
        "decision_reason": hr.get("decision_reason", ""),
        "evidence_hash": evidence_hash,
        "log_id": log_id,
        "source_fields_contract_checked": True,
        "relation_type_compatibility_checked": True,
        "dry_run": True,
    }


# ── Log writer (append-only) ──────────────────────────────────────────────────

def append_to_log(
    result: dict[str, Any],
    candidate: dict[str, Any],
    log_path: Path,
    *,
    session: str = "s0137",
) -> dict[str, str]:
    """Append a gate decision to the admission log. Returns status info."""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    cid = result["candidate_id"]
    existing: list[dict[str, Any]] = []
    conflict = None

    if log_path.exists():
        with log_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    existing.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    # Check for duplicate or conflict
    for prev in existing:
        if prev.get("candidate_id") == cid:
            if prev.get("new_status") == result["gate_status"]:
                return {"outcome": "duplicate_exact", "log_id": prev.get("log_id", "")}
            else:
                conflict = f"Conflicto: mismo candidato {cid}, " \
                           f"estado previo={prev['new_status']} vs nuevo={result['gate_status']}"

    hr = candidate.get("human_review") or {}
    entry = {
        "schema": SCHEMA_LOG,
        "session": session.upper(),
        "log_id": result["log_id"],
        "candidate_id": cid,
        "source_tiddler_id": result["source_tiddler_id"],
        "target_tiddler_id": result["target_tiddler_id"],
        "relation_type": result["relation_type"],
        "previous_status": candidate.get("status", "candidate"),
        "new_status": result["gate_status"],
        "human_review": {
            "status": hr.get("status", "(absent)"),
            "reviewer": hr.get("reviewer", ""),
            "reviewed_at": hr.get("reviewed_at", ""),
            "decision_reason": hr.get("decision_reason", ""),
        },
        "evidence_hash": result["evidence_hash"],
        "source_fields_contract_checked": result["source_fields_contract_checked"],
        "relation_type_compatibility_checked": result["relation_type_compatibility_checked"],
        "blocking_reasons": result["blocking_reasons"],
        "dry_run": True,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "conflict_detected": conflict,
    }

    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {
        "outcome": "conflict" if conflict else "appended",
        "log_id": result["log_id"],
        "conflict_note": conflict or "",
    }


# ── Report builder ────────────────────────────────────────────────────────────

def build_dry_run_report(
    results: list[dict[str, Any]],
    *,
    session: str,
    candidates_file: Path,
    canon_glob: str,
) -> dict[str, Any]:
    ready = [r for r in results if r["gate_status"] == ADMISSION_READY]
    blocked = [r for r in results if r["gate_status"] == BLOCKED]
    return {
        "schema": SCHEMA_REPORT,
        "session": session.upper(),
        "mode": "dry-run",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "inputs": {
            "candidates_file": str(candidates_file),
            "canon_glob": canon_glob,
        },
        "summary": {
            "total_evaluated": len(results),
            "admission_ready_dry_run": len(ready),
            "blocked": len(blocked),
        },
        "items": [
            {
                "candidate_id": r["candidate_id"],
                "gate_status": r["gate_status"],
                "relation_type": r["relation_type"],
                "blocking_reasons": r["blocking_reasons"],
                "ok_reasons": r["ok_reasons"],
                "human_review_status": r["human_review_status"],
                "dry_run": True,
            }
            for r in results
        ],
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Compuerta humana mínima de admisión relacional (S0137). "
            "Modo dry-run obligatorio. NO escribe al canon."
        )
    )
    p.add_argument("--candidates-file", type=Path, default=DEFAULT_CANDIDATES_FILE)
    p.add_argument("--canon-glob", default=DEFAULT_CANON_GLOB)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--session", default="s0137")
    p.add_argument("--verbose", "-v", action="store_true", default=False)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    session_tag = args.session.lower()
    out = args.out_dir

    # Forbid any apply-like flags
    raw = argv if argv is not None else sys.argv[1:]
    for arg in raw:
        if any(arg.lower().startswith(f) for f in ("--apply", "--write", "--admit", "--force")):
            print(
                f"\nBLOQUEADO: relation_admission_gate.py solo opera en dry-run. "
                f"El flag '{arg}' está prohibido.\n",
                file=sys.stderr,
            )
            return 1

    # Load canon
    canon = load_canon_index(args.canon_glob)
    if args.verbose:
        print(f"  Canon: {len(canon)} tiddlers", file=sys.stderr)

    # Load candidates
    if not args.candidates_file.exists():
        print(f"[ERROR] candidates_file no existe: {args.candidates_file}", file=sys.stderr)
        return 2
    candidates: list[dict[str, Any]] = []
    with args.candidates_file.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    candidates.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    if args.verbose:
        print(f"  Candidatos cargados: {len(candidates)}", file=sys.stderr)

    # Evaluate each candidate through the gate
    results = [evaluate_gate(c, canon) for c in candidates]

    # Append to log
    log_path = out / f"{session_tag}_relation_admission_log.jsonl"
    log_outcomes: list[dict[str, str]] = []
    for result, candidate in zip(results, candidates):
        outcome = append_to_log(result, candidate, log_path, session=session_tag)
        log_outcomes.append(outcome)

    # Build and write report
    report = build_dry_run_report(
        results,
        session=session_tag,
        candidates_file=args.candidates_file,
        canon_glob=args.canon_glob,
    )
    report_path = out / f"{session_tag}_relation_admission_dry_run_report.json"
    out.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"[OK] Reporte → {report_path}", file=sys.stderr)
    print(f"[OK] Log → {log_path}", file=sys.stderr)

    s = report["summary"]
    print(
        f"\n=== Relation Admission Gate ({session_tag.upper()}) — DRY-RUN ===\n"
        f"  Total evaluados          : {s['total_evaluated']}\n"
        f"  admission_ready_dry_run  : {s['admission_ready_dry_run']}\n"
        f"  blocked                  : {s['blocked']}\n"
    )
    print("[OK] Compuerta dry-run completada. El canon NO fue modificado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
