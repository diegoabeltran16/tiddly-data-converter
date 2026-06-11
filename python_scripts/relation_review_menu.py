#!/usr/bin/env python3
"""
relation_review_menu.py — S0127
Módulo auxiliar: Revisión relacional [EXPERIMENTAL].

Responsabilidades:
  - Presentar una sección experimental claramente delimitada en el menú local.
  - Ejecutar validación dry-run de relaciones candidatas ya existentes.
  - Mostrar explícitamente que generación y admisión canónica están BLOQUEADAS.
  - Mostrar el último reporte humano si existe.
  - No generar candidatos nuevos.
  - No invocar --apply.
  - No modificar data/out/local/tiddlers_*.jsonl.

Restricciones S0127:
  - Generación automática de relaciones: BLOQUEADA
  - Admisión canónica relacional: BLOQUEADA
  - --apply: NUNCA invocado
  - Canon: NO modificado
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from relation_admission_gate import (  # noqa: E402
    SCHEMA_HUMAN_DECISIONS,
    VALID_HUMAN_DECISIONS,
    load_canon_index,
    load_s0139_type_policy,
    write_human_review_schema,
)
import relation_batch_review as batch_review  # noqa: E402

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
SCRIPT_DIR: Path = Path(__file__).resolve().parent

RELATIONS_DIR: Path = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relations_candidates"
)
DEFAULT_CANDIDATES_INPUT: Path = (
    RELATIONS_DIR / "relations_candidates.sample.jsonl"
)
DEFAULT_VALIDATION_REPORT: Path = (
    RELATIONS_DIR / "relations_candidates.validation_report.json"
)
DEFAULT_HUMAN_REVIEW: Path = (
    RELATIONS_DIR / "relations_candidates.human_review.md"
)
CANON_ROOT: Path = REPO_ROOT / "data" / "out" / "local"
VALIDATOR_SCRIPT: Path = SCRIPT_DIR / "validate_relation_candidates.py"
ADMISSION_GATE_SCRIPT: Path = SCRIPT_DIR / "relation_admission_gate.py"
DEFAULT_VALID_CANDIDATES_FILE: Path = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline"
    / "relations_candidates" / "s0129" / "valid_candidates.jsonl"
)
S0140_REVIEW_DIR: Path = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_review" / "s0140"
)
S0141_REVIEW_DIR: Path = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_review" / "s0141"
)
S0141_ADMISSION_DIR: Path = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_admission" / "s0141"
)
S0142_REVIEW_DIR: Path = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_review" / "s0142"
)
S0142_ADMISSION_DIR: Path = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_admission" / "s0142"
)
S0143_ADMISSION_DIR: Path = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_admission" / "s0143"
)
S0143_MENU_DIR: Path = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_menu" / "s0143"
)
S0139_TYPE_POLICY_DIR: Path = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_type_governance" / "s0139"
)
S0132_ADMISSIBILITY_REPORT: Path = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_admissibility"
    / "s0132" / "s0132_relation_admissibility_report.json"
)

# ---------------------------------------------------------------------------
# Texto de estado de bloqueo (invariante de sesión S0127)
# ---------------------------------------------------------------------------

BLOCK_STATUS_LINES: list[str] = [
    "[EXPERIMENTAL] Revisión relacional",
    "- Generación automática: BLOQUEADA",
    "- Admisión canónica:     BLOQUEADA",
    "- Modo actual:           dry-run",
    "- Canon modificado:      NO",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _prompt(message: str) -> str:
    try:
        return input(message)
    except EOFError:
        return ""


def _display(path: Path) -> str:
    """Ruta relativa al REPO_ROOT para display."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _review_paths(review_dir: Path = S0141_REVIEW_DIR) -> dict[str, Path]:
    return {
        "queue": review_dir / "human_review_queue.jsonl",
        "decisions": review_dir / "human_review_decisions.json",
        "schema": review_dir / "human_review_decisions.schema.json",
        "audit": review_dir / "human_review_audit_log.jsonl",
        "summary": review_dir / "human_review_summary.md",
    }


def _blank_checks(*, approved: bool = False) -> dict[str, bool]:
    return {
        "source_verified": approved,
        "target_verified": approved,
        "evidence_excerpt_verified": approved,
        "relation_type_checked_against_s0139": approved,
        "not_duplicate_of_existing_relation": approved,
        "no_canonical_write_requested": True,
    }


def _base_decisions_doc() -> dict[str, Any]:
    return {
        "schema": SCHEMA_HUMAN_DECISIONS,
        "session": "S0141",
        "dry_run": True,
        "applied_to_canon": False,
        "reviewer": {
            "reviewer_id": "local-operator",
            "reviewer_role": "human_operator",
        },
        "decisions": [],
    }


def _deferred_decision(candidate_id: str) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "decision": "deferred",
        "reviewed_at": "",
        "rationale": (
            "S0141 deja este candidato pendiente hasta una accion explicita "
            "del operador local."
        ),
        "checks": _blank_checks(),
    }


def _decision_counts(decisions_doc: dict[str, Any]) -> Counter:
    return Counter(d.get("decision") for d in decisions_doc.get("decisions") or [])


def _decisions_by_candidate(decisions_doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(d.get("candidate_id")): d
        for d in decisions_doc.get("decisions") or []
        if d.get("candidate_id")
    }


def _write_summary(review_dir: Path, queue: list[dict[str, Any]], decisions_doc: dict[str, Any]) -> None:
    counts = _decision_counts(decisions_doc)
    paths = _review_paths(review_dir)
    paths["summary"].write_text(
        "\n".join([
            "# S0141 - Human review menu summary",
            "",
            f"- Candidatos en cola: {len(queue)}",
            f"- Decisiones persistidas: {len(decisions_doc.get('decisions') or [])}",
            f"- approved_for_dry_run: {counts.get('approved_for_dry_run', 0)}",
            f"- rejected_by_human: {counts.get('rejected_by_human', 0)}",
            f"- needs_changes: {counts.get('needs_changes', 0)}",
            f"- deferred: {counts.get('deferred', 0)}",
            "- dry_run: true",
            "- applied_to_canon: false",
            "- canon_modified: false",
            "",
            "Las aprobaciones requieren confirmacion explicita del operador local.",
            "",
        ]),
        encoding="utf-8",
    )


def ensure_s0141_review_artifacts(review_dir: Path = S0141_REVIEW_DIR) -> dict[str, Path]:
    """Create S0141 queue/decision artifacts without overwriting existing decisions."""
    paths = _review_paths(review_dir)
    review_dir.mkdir(parents=True, exist_ok=True)

    queue = _load_jsonl(paths["queue"])
    if not queue:
        queue = _load_jsonl(S0140_REVIEW_DIR / "human_review_queue.jsonl")
        _write_jsonl(paths["queue"], queue)

    decisions_doc = _load_json(paths["decisions"], None)
    if decisions_doc is None:
        decisions_doc = _base_decisions_doc()
        decisions_doc["decisions"] = [
            _deferred_decision(str(item.get("candidate_id") or ""))
            for item in queue
            if item.get("candidate_id")
        ]
        _write_json(paths["decisions"], decisions_doc)

    if not paths["schema"].exists():
        write_human_review_schema(paths["schema"], session="S0141")
    if not paths["audit"].exists():
        paths["audit"].write_text("", encoding="utf-8")

    _write_summary(review_dir, queue, decisions_doc)
    return paths


def load_human_review_queue(review_dir: Path = S0141_REVIEW_DIR) -> list[dict[str, Any]]:
    paths = ensure_s0141_review_artifacts(review_dir)
    return _load_jsonl(paths["queue"])


def load_human_review_decisions(review_dir: Path = S0141_REVIEW_DIR) -> dict[str, Any]:
    paths = ensure_s0141_review_artifacts(review_dir)
    doc = _load_json(paths["decisions"], _base_decisions_doc())
    if doc.get("session") != "S0141":
        doc["session"] = "S0141"
    return doc


def save_human_review_decisions(
    decisions_doc: dict[str, Any],
    review_dir: Path = S0141_REVIEW_DIR,
) -> None:
    if decisions_doc.get("schema") != SCHEMA_HUMAN_DECISIONS:
        raise ValueError(f"schema invalido: {decisions_doc.get('schema')!r}")
    if decisions_doc.get("session") != "S0141":
        raise ValueError("S0141 menu solo escribe decisiones de session S0141")
    for decision in decisions_doc.get("decisions") or []:
        if decision.get("decision") not in VALID_HUMAN_DECISIONS:
            raise ValueError(f"decision invalida: {decision.get('decision')!r}")
    paths = ensure_s0141_review_artifacts(review_dir)
    _write_json(paths["decisions"], decisions_doc)
    _write_summary(review_dir, _load_jsonl(paths["queue"]), decisions_doc)


def append_human_review_audit(
    action: str,
    *,
    candidate_id: str = "",
    review_dir: Path = S0141_REVIEW_DIR,
) -> None:
    paths = ensure_s0141_review_artifacts(review_dir)
    entry = {
        "timestamp": _utc_now(),
        "session": "S0141",
        "candidate_id": candidate_id,
        "action": action,
        "operator": "local-operator",
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
    }
    with paths["audit"].open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _upsert_decision(
    candidate_id: str,
    decision_value: str,
    *,
    rationale: str,
    checks: dict[str, bool],
    review_dir: Path = S0141_REVIEW_DIR,
) -> dict[str, Any]:
    decisions_doc = load_human_review_decisions(review_dir)
    decisions = decisions_doc.setdefault("decisions", [])
    new_decision = {
        "candidate_id": candidate_id,
        "decision": decision_value,
        "reviewed_at": _utc_now(),
        "rationale": rationale,
        "checks": checks,
    }
    for idx, existing in enumerate(decisions):
        if existing.get("candidate_id") == candidate_id:
            decisions[idx] = new_decision
            break
    else:
        decisions.append(new_decision)
    save_human_review_decisions(decisions_doc, review_dir)
    return new_decision


def _load_type_policy() -> dict[str, Any]:
    path = S0139_TYPE_POLICY_DIR / "s0139_historical_relation_type_decisions.json"
    payload = _load_json(path, {})
    return payload.get("decisions_by_type") or {}


def _batch_paths(review_dir: Path = S0142_REVIEW_DIR) -> dict[str, Path]:
    return {
        "decisions": review_dir / "human_review_batch_decisions.json",
        "audit": review_dir / "human_review_batch_audit_log.jsonl",
        "summary_json": review_dir / "human_review_batch_summary.json",
        "summary_md": review_dir / "human_review_batch_summary.md",
    }


def build_s0142_batch_summary(
    *,
    review_dir: Path = S0142_REVIEW_DIR,
    candidates_file: Path = DEFAULT_VALID_CANDIDATES_FILE,
    canon_glob: str | None = None,
    type_policy_dir: Path = S0139_TYPE_POLICY_DIR,
    admissibility_report: Path = S0132_ADMISSIBILITY_REPORT,
    individual_review_path: Path | None = None,
) -> dict[str, Any]:
    review_dir.mkdir(parents=True, exist_ok=True)
    paths = _batch_paths(review_dir)
    candidates = batch_review.load_candidates(candidates_file)
    canon = load_canon_index(canon_glob or str(CANON_ROOT / "tiddlers_*.jsonl"))
    type_policy = load_s0139_type_policy(type_policy_dir)
    admissibility = batch_review.load_admissibility_results(admissibility_report)
    individual_decisions = batch_review.load_human_review_decisions(individual_review_path)
    classifications = batch_review.classify_batch_candidates(
        candidates,
        canon,
        type_policy=type_policy,
        admissibility=admissibility,
        individual_decisions=individual_decisions,
    )
    summary = batch_review.build_batch_summary(classifications)
    batch_review.write_batch_summary_artifacts(
        summary,
        summary_json=paths["summary_json"],
        summary_md=paths["summary_md"],
    )
    if not paths["decisions"].exists():
        batch_review.write_json(paths["decisions"], batch_review.empty_batch_decisions_doc())
    if not paths["audit"].exists():
        paths["audit"].write_text("", encoding="utf-8")
    return summary


def show_block_status(
    report_path: Path | None = None,
    human_review_path: Path | None = None,
) -> None:
    """Imprime el encabezado de estado de bloqueo de S0127."""
    for line in BLOCK_STATUS_LINES:
        print(line)
    rp = report_path or DEFAULT_VALIDATION_REPORT
    hr = human_review_path or DEFAULT_HUMAN_REVIEW
    print(f"- Reporte JSON:        {_display(rp)}")
    print(f"- Reporte humano:      {_display(hr)}")


# ---------------------------------------------------------------------------
# Opción 1: Validar relaciones candidatas existentes (dry-run)
# ---------------------------------------------------------------------------


def option_validate_candidates() -> int:
    """
    Valida relaciones candidatas existentes en modo dry-run.

    Invariantes:
      - Nunca invoca --apply.
      - Nunca genera candidatos nuevos.
      - Nunca modifica tiddlers_*.jsonl.

    Retorna el exit code del validador (0 = OK, != 0 = problema o advertencia).
    """
    print("\n[EXPERIMENTAL] Validar relaciones candidatas existentes (dry-run)")
    print("- Generación automática: BLOQUEADA")
    print("- Admisión canónica:     BLOQUEADA")
    print("- Modo: dry-run (ningún candidato será escrito en el canon)")

    # ── Verificar directorio ────────────────────────────────────────────────
    if not RELATIONS_DIR.exists():
        print(
            f"\nNo existe el directorio de candidatos: {_display(RELATIONS_DIR)}"
        )
        print("No se encontraron relaciones candidatas para revisar.")
        print("Esta opción no genera candidatos nuevos en S0127.")
        print("Crea el directorio y añade candidatos para usar esta opción.")
        return 1

    # ── Verificar archivo de candidatos ────────────────────────────────────
    if not DEFAULT_CANDIDATES_INPUT.exists():
        print(
            "\nNo se encontraron relaciones candidatas para revisar."
        )
        print(f"Ruta esperada: {_display(DEFAULT_CANDIDATES_INPUT)}")
        print("Esta opción no genera candidatos nuevos en S0127.")
        return 1

    # ── Construir comando: --dry-run requerido; --apply NUNCA ───────────────
    cmd: list[str] = [
        sys.executable,
        str(VALIDATOR_SCRIPT),
        "--input",
        str(DEFAULT_CANDIDATES_INPUT),
        "--canon-root",
        str(CANON_ROOT),
        "--report",
        str(DEFAULT_VALIDATION_REPORT),
        "--human-review",
        str(DEFAULT_HUMAN_REVIEW),
        "--dry-run",
        # --apply está EXPLÍCITAMENTE ausente (S0127)
    ]

    print(f"\nEjecutando validador dry-run...")
    print(f"  Input:        {_display(DEFAULT_CANDIDATES_INPUT)}")
    print(f"  Canon root:   {_display(CANON_ROOT)}")
    print(f"  Reporte JSON: {_display(DEFAULT_VALIDATION_REPORT)}")
    print(f"  Reporte human:{_display(DEFAULT_HUMAN_REVIEW)}")

    completed = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if stdout:
        print("\n" + stdout)
    if stderr:
        print("\nstderr:")
        print(stderr[:800])

    if completed.returncode == 0:
        print("\n✅ Validación dry-run completada sin errores fatales.")
    else:
        print(
            f"\n⚠️  Validador terminó con exit code {completed.returncode}. "
            "Revisar salida y reporte."
        )

    print()
    show_block_status()
    return completed.returncode


# ---------------------------------------------------------------------------
# Opción 2: Ver último reporte humano
# ---------------------------------------------------------------------------


def option_view_human_report() -> None:
    """
    Muestra el último reporte humano de revisión relacional.

    Si no existe, instruye al usuario a ejecutar la validación dry-run primero.
    No altera ningún archivo.
    """
    print("\n[EXPERIMENTAL] Último reporte humano de relaciones candidatas")

    if not DEFAULT_HUMAN_REVIEW.exists():
        print("No hay reporte humano disponible todavía.")
        print("Ejecute primero la validación dry-run (opción 1).")
        return

    print(f"Reporte: {_display(DEFAULT_HUMAN_REVIEW)}\n")
    try:
        content = DEFAULT_HUMAN_REVIEW.read_text(encoding="utf-8")
        lines = content.splitlines()
        # Mostrar hasta 120 líneas para no saturar la terminal
        for line in lines[:120]:
            print(line)
        if len(lines) > 120:
            print(
                f"\n... ({len(lines) - 120} líneas adicionales — "
                f"ver archivo completo: {_display(DEFAULT_HUMAN_REVIEW)})"
            )
    except OSError as exc:
        print(f"No se pudo leer el reporte: {exc}")


# ---------------------------------------------------------------------------
# Submenú principal: Revisión relacional [EXPERIMENTAL]
# ---------------------------------------------------------------------------

_MENU_HEADER = """\

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Revisión relacional [EXPERIMENTAL]
  Modo: DRY-RUN
  Canon: PROTEGIDO
  Generación automática de relaciones: BLOQUEADA
  Admisión canónica relacional: BLOQUEADA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1) Revisar lote batch y aprobar para dry-run
2) Ejecutar compuerta dry-run con aprobación existente
3) Ver último resultado dry-run
4) Ver candidatos bloqueados / revisión individual
9) Avanzado / mantenimiento
0) Volver"""

_ADVANCED_MENU_HEADER = """\

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Revisión relacional — Avanzado
  Modo: DRY-RUN
  Canon: PROTEGIDO
  MANTENIMIENTO / NO ESCRIBE CANON
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1) Validar relaciones candidatas existentes (dry-run) [MANTENIMIENTO / NO ESCRIBE CANON]
2) Ver último reporte humano [MANTENIMIENTO]
3) Generar plan dry-run S0135 [LEGACY / MANTENIMIENTO / NO ESCRIBE CANON]
4) Ver cola de human_review pendiente [MANTENIMIENTO]
5) Revisar candidato individual [MANTENIMIENTO]
6) Aprobar candidato individual para dry-run [MANTENIMIENTO / NO ESCRIBE CANON]
7) Rechazar candidato individual [MANTENIMIENTO]
8) Diferir candidato individual [MANTENIMIENTO]
9) Ejecutar compuerta individual [DRY-RUN / NO ESCRIBE CANON]
10) Ver reporte individual [MANTENIMIENTO]
11) Generar reporte batch técnico [DRY-RUN]
12) Ver lote batch_ready técnico [MANTENIMIENTO]
0) Volver"""

# Ruta de salida del plan de admisión (S0135)
_ADMISSION_PLAN_DIR: Path = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relations_admission" / "s0135"
)
_ADMISSION_PLAN_SCRIPT: Path = SCRIPT_DIR / "build_relation_admission_plan.py"


def option_generate_admission_plan() -> None:
    """Genera el plan dry-run de admisión relacional (S0135).

    BLOQUEADO: S0135 solo genera plan dry-run. No escribe relaciones en el canon.
    """
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  Generar plan dry-run de admisión relacional (S0135)")
    print("  BLOQUEADO: S0135 solo genera plan dry-run.")
    print("  No escribe relaciones en el canon.")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    if not _ADMISSION_PLAN_SCRIPT.exists():
        print(f"[ERROR] Script no encontrado: {_ADMISSION_PLAN_SCRIPT}")
        return

    cmd = [
        sys.executable,
        str(_ADMISSION_PLAN_SCRIPT),
        "--canon-glob", str(CANON_ROOT / "tiddlers_*.jsonl"),
        "--candidates-dir", str(RELATIONS_DIR),
        "--out-dir", str(_ADMISSION_PLAN_DIR),
        "--dry-run",
    ]
    print(f"Ejecutando plan dry-run de admisión relacional...")
    print(f"Salida: {_display(_ADMISSION_PLAN_DIR)}\n")

    import subprocess
    result = subprocess.run(cmd, capture_output=False)

    if result.returncode == 0:
        plan_path = _ADMISSION_PLAN_DIR / "s0135_relation_admission_plan.json"
        print(f"\n✅ Plan generado. Ver: {_display(plan_path)}")
    elif result.returncode == 1:
        print("\n⚠️  Plan generado con advertencias (ver salida arriba).")
    else:
        print(f"\n[ERROR] Error al generar el plan (código {result.returncode}).")


def show_human_review_queue(review_dir: Path = S0141_REVIEW_DIR) -> None:
    """Show the pending S0141 human-review queue."""
    queue = load_human_review_queue(review_dir)
    decisions_doc = load_human_review_decisions(review_dir)
    decisions = _decisions_by_candidate(decisions_doc)
    counts = _decision_counts(decisions_doc)

    print("\n=== Human Review Queue ===\n")
    print(f"Pendientes: {len([q for q in queue if decisions.get(q.get('candidate_id'), {}).get('decision') in {'deferred', None}])}")
    print(f"Aprobados para dry-run: {counts.get('approved_for_dry_run', 0)}")
    print(f"Rechazados: {counts.get('rejected_by_human', 0)}")
    print(f"Diferidos: {counts.get('deferred', 0)}\n")

    for idx, item in enumerate(queue, start=1):
        cid = str(item.get("candidate_id") or "")
        decision = (decisions.get(cid) or {}).get("decision", "review_required")
        print(
            f"{idx}. {cid} | {item.get('relation_type', '')} | "
            f"{item.get('source_title', '')} -> {item.get('target_title', '')} | "
            f"score {item.get('confidence_score', 0)} | {decision}"
        )
    append_human_review_audit("view_queue", review_dir=review_dir)


def show_candidate_detail(candidate_id: str, review_dir: Path = S0141_REVIEW_DIR) -> dict[str, Any] | None:
    """Show detail for one candidate and return its queue item if found."""
    queue = load_human_review_queue(review_dir)
    decisions_doc = load_human_review_decisions(review_dir)
    decisions = _decisions_by_candidate(decisions_doc)
    item = next((q for q in queue if q.get("candidate_id") == candidate_id), None)
    if item is None:
        print(f"\nCandidato no encontrado: {candidate_id}")
        return None

    type_policy = _load_type_policy().get(str(item.get("relation_type") or ""), {})
    current_decision = (decisions.get(candidate_id) or {}).get("decision", "review_required")
    print("\n=== Candidate Detail ===\n")
    print(f"Candidate ID: {candidate_id}")
    print(f"Source: {item.get('source_id', '')} | {item.get('source_title', '')}")
    print(f"Target: {item.get('target_id', '')} | {item.get('target_title', '')}")
    print(f"Relation type: {item.get('relation_type', '')}")
    print(f"Confidence score: {item.get('confidence_score', 0)}")
    print(f"Evidence kind: {item.get('evidence_kind', '')}")
    print(f"Evidence excerpt: {item.get('evidence_excerpt', '')}")
    print(f"S0139 type policy: {type_policy.get('decision_status', 'not_listed')}")
    print(f"S0131 evidence status: {item.get('evidence_kind', '')} / score {item.get('confidence_score', 0)}")
    print(f"S0132 admissibility: {item.get('current_decision', '')}")
    print(f"Current human_review decision: {current_decision}\n")
    print("1) Aprobar para dry-run")
    print("2) Rechazar")
    print("3) Diferir")
    print("0) Volver")
    append_human_review_audit("view_candidate", candidate_id=candidate_id, review_dir=review_dir)
    return item


def approve_candidate_for_dry_run(
    candidate_id: str,
    *,
    rationale: str | None = None,
    confirmation: str | None = None,
    review_dir: Path = S0141_REVIEW_DIR,
) -> bool:
    """Persist explicit operator approval for dry-run only."""
    load_human_review_queue(review_dir)
    answer = confirmation
    if answer is None:
        answer = _prompt("¿Apruebas este candidato SOLO PARA DRY-RUN?\nEsto NO escribirá el canon. [y/N] ")
    if answer.strip().lower() not in {"y", "yes"}:
        print("Aprobación cancelada. El candidato no fue aprobado.")
        return False
    _upsert_decision(
        candidate_id,
        "approved_for_dry_run",
        rationale=rationale or "Aprobado explicitamente por operador local solo para dry-run.",
        checks=_blank_checks(approved=True),
        review_dir=review_dir,
    )
    append_human_review_audit("approved_for_dry_run", candidate_id=candidate_id, review_dir=review_dir)
    print(f"Candidato aprobado solo para dry-run: {candidate_id}")
    return True


def reject_candidate_by_human(
    candidate_id: str,
    *,
    rationale: str | None = None,
    review_dir: Path = S0141_REVIEW_DIR,
) -> dict[str, Any]:
    decision = _upsert_decision(
        candidate_id,
        "rejected_by_human",
        rationale=rationale or "Rechazado explicitamente por operador local.",
        checks=_blank_checks(),
        review_dir=review_dir,
    )
    append_human_review_audit("rejected_by_human", candidate_id=candidate_id, review_dir=review_dir)
    print(f"Candidato rechazado por operador: {candidate_id}")
    return decision


def defer_candidate(
    candidate_id: str,
    *,
    rationale: str | None = None,
    review_dir: Path = S0141_REVIEW_DIR,
) -> dict[str, Any]:
    decision = _upsert_decision(
        candidate_id,
        "deferred",
        rationale=rationale or "Diferido por operador local para revision posterior.",
        checks=_blank_checks(),
        review_dir=review_dir,
    )
    append_human_review_audit("deferred", candidate_id=candidate_id, review_dir=review_dir)
    print(f"Candidato diferido: {candidate_id}")
    return decision


def run_relation_admission_gate_dry_run(
    *,
    review_dir: Path = S0141_REVIEW_DIR,
    admission_dir: Path = S0141_ADMISSION_DIR,
    candidates_file: Path = DEFAULT_VALID_CANDIDATES_FILE,
    canon_glob: str | None = None,
    type_policy_dir: Path = S0139_TYPE_POLICY_DIR,
    admissibility_report: Path | None = None,
) -> int:
    """Run relation_admission_gate.py for S0141 in dry-run mode only."""
    paths = ensure_s0141_review_artifacts(review_dir)
    admission_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(ADMISSION_GATE_SCRIPT),
        "--candidates-file",
        str(candidates_file),
        "--canon-glob",
        canon_glob or str(CANON_ROOT / "tiddlers_*.jsonl"),
        "--human-review",
        str(paths["decisions"]),
        "--type-policy-dir",
        str(type_policy_dir),
        "--review-dir",
        str(review_dir),
        "--admissibility-report",
        str(admissibility_report or (REPO_ROOT / "data" / "out" / "local" / "pipeline"
                                     / "relation_admissibility" / "s0132"
                                     / "s0132_relation_admissibility_report.json")),
        "--out-dir",
        str(admission_dir),
        "--session",
        "s0141",
        "--dry-run",
    ]
    print("\nEjecutando compuerta relacional con human_review [DRY-RUN]...")
    print(f"Decisiones: {_display(paths['decisions'])}")
    print(f"Salida: {_display(admission_dir)}")
    append_human_review_audit("run_gate_dry_run", review_dir=review_dir)
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    return result.returncode


def show_admission_gate_report(
    admission_dir: Path = S0141_ADMISSION_DIR,
    *,
    review_dir: Path = S0141_REVIEW_DIR,
) -> None:
    """Render the S0141 dry-run gate report in a compact operator view."""
    ready_path = admission_dir / "admission_ready_dry_run.json"
    blocked_path = admission_dir / "admission_blocked.json"
    preview_path = admission_dir / "admission_patch_preview.json"
    if not ready_path.exists() or not blocked_path.exists() or not preview_path.exists():
        print("\nNo existe reporte de compuerta S0141. Ejecuta primero la opción 9.")
        return
    ready = _load_json(ready_path, {})
    blocked = _load_json(blocked_path, {})
    preview = _load_json(preview_path, {})
    by_decision = (blocked.get("summary") or {}).get("by_decision") or {}

    print("\n=== Relation Admission Gate — DRY-RUN ===\n")
    print(f"admission_ready_dry_run: {(ready.get('summary') or {}).get('total', 0)}")
    print(f"blocked: {(blocked.get('summary') or {}).get('total', 0)}")
    print(f"blocked_missing_human_review: {by_decision.get('blocked_missing_human_review', 0)}")
    print(f"blocked_legacy_alias_policy: {by_decision.get('blocked_legacy_alias_policy', 0)}")
    print(f"blocked_unresolved_target: {by_decision.get('blocked_unresolved_target', 0)}")
    print(f"blocked_unverified_evidence: {by_decision.get('blocked_unverified_evidence', 0)}")
    print(f"blocked_duplicate_existing: {by_decision.get('blocked_duplicate_existing', 0)}")
    print(f"rejected_by_human: {by_decision.get('rejected_by_human', 0)}\n")
    print(f"patch_preview_operations: {preview.get('total_operations_previewed', 0)}")
    print(f"applied_to_canon: {str(preview.get('applied_to_canon')).lower()}")
    print(f"canon_modified: {str(preview.get('canon_modified')).lower()}")
    append_human_review_audit("view_gate_report", review_dir=review_dir)


def show_batch_terminal_report(
    *,
    review_dir: Path = S0142_REVIEW_DIR,
    prompt_for_sample: bool = True,
) -> dict[str, Any]:
    summary = build_s0142_batch_summary(review_dir=review_dir)
    print()
    print(batch_review.render_terminal_batch_report(summary, sample_size=0))
    batch_review.append_batch_audit(_batch_paths(review_dir)["audit"], action="view_batch_report", summary=summary)
    if prompt_for_sample:
        answer = _prompt("¿Quieres ver muestra auditada del lote batch_ready? [y/N] ")
        if answer.strip().lower() in {"y", "yes", "s", "si", "sí"}:
            report = batch_review.render_terminal_batch_report(summary, sample_size=5)
            sample_section = report.split("Muestra auditada batch_ready:", 1)
            if len(sample_section) == 2:
                print("\nMuestra auditada batch_ready:" + sample_section[1])
    return summary


def review_batch_and_approve_for_dry_run(
    *,
    review_dir: Path = S0142_REVIEW_DIR,
    confirmation: str | None = None,
    candidates_file: Path = DEFAULT_VALID_CANDIDATES_FILE,
    canon_glob: str | None = None,
    type_policy_dir: Path = S0139_TYPE_POLICY_DIR,
    admissibility_report: Path = S0132_ADMISSIBILITY_REPORT,
    individual_review_path: Path | None = None,
) -> bool:
    """Operator shortcut: render the batch report and persist approval only with the strong token."""
    summary = build_s0142_batch_summary(
        review_dir=review_dir,
        candidates_file=candidates_file,
        canon_glob=canon_glob,
        type_policy_dir=type_policy_dir,
        admissibility_report=admissibility_report,
        individual_review_path=individual_review_path,
    )
    print()
    print(batch_review.render_terminal_batch_report(summary, sample_size=3))
    batch_review.append_batch_audit(
        _batch_paths(review_dir)["audit"],
        action="view_batch_report",
        summary=summary,
    )

    ready_count = len(summary.get("batch_ready_candidate_ids") or [])
    blocked_count = (summary.get("summary") or {}).get("blocked", 0)
    print("\nResumen para aprobación dry-run:")
    print(f"batch_id: {summary.get('batch_id')}")
    print(f"batch_sha256: {summary.get('batch_sha256')}")
    print(f"batch_ready: {ready_count}")
    print(f"blocked: {blocked_count}")

    if ready_count == 0:
        print("\nNo hay candidatos batch_ready para aprobar.")
        return False

    token = batch_review.CONFIRMATION_TOKEN
    print("\nVas a aprobar SOLO PARA DRY-RUN el lote batch_ready.")
    print("Esto NO escribirá el canon.")
    print("Esto NO aplicará aliases.")
    print("Esto NO modificará data/out/local/tiddlers_*.jsonl.")
    print("\nPara confirmar, escribe exactamente:")
    print(token)

    answer = confirmation if confirmation is not None else _prompt("> ")
    paths = _batch_paths(review_dir)
    approved = batch_review.persist_batch_decision(
        summary,
        decisions_path=paths["decisions"],
        audit_path=paths["audit"],
        confirmation=answer.strip(),
    )
    if not approved:
        print("Aprobación cancelada. No se escribió decisión batch.")
        return False
    print("Decisión batch persistida para dry-run.")
    return True


def show_batch_ready_lot(review_dir: Path = S0142_REVIEW_DIR) -> dict[str, Any]:
    summary = build_s0142_batch_summary(review_dir=review_dir)
    ready = [
        item for item in summary.get("classifications") or []
        if item.get("category") == batch_review.BATCH_READY
    ]
    print("\n=== Lote batch_ready ===\n")
    print(f"Batch ID: {summary.get('batch_id')}")
    print(f"Batch SHA256: {summary.get('batch_sha256')}")
    print(f"Candidatos: {len(ready)}\n")
    for idx, item in enumerate(sorted(ready, key=lambda x: x["candidate_id"]), start=1):
        print(
            f"{idx}. {item['candidate_id']} | {item['relation_type']} | "
            f"{item['source_id']} -> {item['target_id']} | score {item['confidence_score']}"
        )
    batch_review.append_batch_audit(_batch_paths(review_dir)["audit"], action="view_batch_ready", summary=summary)
    return summary


def approve_batch_ready_for_dry_run(
    *,
    review_dir: Path = S0142_REVIEW_DIR,
    confirmation: str | None = None,
) -> bool:
    summary = show_batch_ready_lot(review_dir)
    token = batch_review.CONFIRMATION_TOKEN
    print("\nVas a aprobar SOLO PARA DRY-RUN el lote:\n")
    print(f"Batch ID: {summary.get('batch_id')}")
    print(f"Batch SHA256: {summary.get('batch_sha256')}")
    print(f"Candidatos: {len(summary.get('batch_ready_candidate_ids') or [])}\n")
    print("Esto NO escribirá el canon.")
    print("Esto NO aplicará aliases.")
    print("Esto NO modificará data/out/local/tiddlers_*.jsonl.\n")
    print("Para confirmar, escribe exactamente:")
    print(token)
    answer = confirmation if confirmation is not None else _prompt("> ")
    paths = _batch_paths(review_dir)
    approved = batch_review.persist_batch_decision(
        summary,
        decisions_path=paths["decisions"],
        audit_path=paths["audit"],
        confirmation=answer.strip(),
    )
    if not approved:
        print("Aprobación cancelada. No se escribió decisión batch.")
        return False
    print("Decisión batch persistida para dry-run.")
    return True


def run_relation_admission_gate_batch_dry_run(
    *,
    review_dir: Path = S0142_REVIEW_DIR,
    admission_dir: Path = S0142_ADMISSION_DIR,
    session_tag: str = "s0142",
    candidates_file: Path = DEFAULT_VALID_CANDIDATES_FILE,
    canon_glob: str | None = None,
    type_policy_dir: Path = S0139_TYPE_POLICY_DIR,
    admissibility_report: Path = S0132_ADMISSIBILITY_REPORT,
) -> int:
    summary = build_s0142_batch_summary(review_dir=review_dir)
    paths = _batch_paths(review_dir)
    admission_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(ADMISSION_GATE_SCRIPT),
        "--candidates-file",
        str(candidates_file),
        "--canon-glob",
        canon_glob or str(CANON_ROOT / "tiddlers_*.jsonl"),
        "--human-review-batch",
        str(paths["decisions"]),
        "--type-policy-dir",
        str(type_policy_dir),
        "--admissibility-report",
        str(admissibility_report),
        "--out-dir",
        str(admission_dir),
        "--session",
        session_tag,
        "--dry-run",
    ]
    print("\nEjecutando compuerta batch [DRY-RUN]...")
    print(f"Batch ID: {summary.get('batch_id')}")
    print(f"Batch SHA256: {summary.get('batch_sha256')}")
    print(f"Decisiones batch: {_display(paths['decisions'])}")
    batch_review.append_batch_audit(paths["audit"], action="run_batch_gate_dry_run", summary=summary)
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    return result.returncode


def run_s0143_batch_admission_gate_dry_run(
    *,
    review_dir: Path = S0142_REVIEW_DIR,
    admission_dir: Path = S0143_ADMISSION_DIR,
    candidates_file: Path = DEFAULT_VALID_CANDIDATES_FILE,
    canon_glob: str | None = None,
    type_policy_dir: Path = S0139_TYPE_POLICY_DIR,
    admissibility_report: Path = S0132_ADMISSIBILITY_REPORT,
) -> int:
    """Run the batch admission gate as S0143 while reusing the governed S0142 batch decision store."""
    return run_relation_admission_gate_batch_dry_run(
        review_dir=review_dir,
        admission_dir=admission_dir,
        session_tag="s0143",
        candidates_file=candidates_file,
        canon_glob=canon_glob,
        type_policy_dir=type_policy_dir,
        admissibility_report=admissibility_report,
    )


def show_batch_gate_report(
    admission_dir: Path = S0142_ADMISSION_DIR,
    *,
    review_dir: Path = S0142_REVIEW_DIR,
) -> None:
    summary = build_s0142_batch_summary(review_dir=review_dir)
    ready_path = admission_dir / "admission_ready_dry_run.json"
    blocked_path = admission_dir / "admission_blocked.json"
    preview_path = admission_dir / "admission_patch_preview.json"
    if not ready_path.exists() or not blocked_path.exists() or not preview_path.exists():
        print("\nNo existe resultado batch S0142. Ejecuta primero la opción 14.")
        return
    ready = _load_json(ready_path, {})
    blocked = _load_json(blocked_path, {})
    preview = _load_json(preview_path, {})
    decisions = _load_json(_batch_paths(review_dir)["decisions"], batch_review.empty_batch_decisions_doc())
    batch_approved = batch_review.approved_batch_decision(decisions) is not None
    by_decision = (blocked.get("summary") or {}).get("by_decision") or {}
    print("\n=== Relation Admission Gate — BATCH DRY-RUN ===\n")
    print(f"batch_id: {summary.get('batch_id')}")
    print(f"batch_sha256: {summary.get('batch_sha256')}")
    print(f"batch_approved: {str(batch_approved).lower()}\n")
    print(f"admission_ready_dry_run: {(ready.get('summary') or {}).get('total', 0)}")
    print(f"blocked: {(blocked.get('summary') or {}).get('total', 0)}")
    print(f"rejected_by_human: {by_decision.get('rejected_by_human', 0)}")
    print(f"deferred: {by_decision.get('deferred', 0)}")
    print(f"blocked_batch_hash_mismatch: {by_decision.get('blocked_batch_hash_mismatch', 0)}")
    print(f"blocked_missing_human_review: {by_decision.get('blocked_missing_human_review', 0)}")
    print(f"blocked_legacy_alias_policy: {by_decision.get('blocked_legacy_alias_policy', 0)}")
    print(f"blocked_unresolved_target: {by_decision.get('blocked_unresolved_target', 0)}")
    print(f"blocked_unverified_evidence: {by_decision.get('blocked_unverified_evidence', 0)}")
    print(f"blocked_duplicate_existing: {by_decision.get('blocked_duplicate_existing', 0)}\n")
    print(f"patch_preview_operations: {preview.get('total_operations_previewed', 0)}")
    print(f"applied_to_canon: {str(preview.get('applied_to_canon')).lower()}")
    print(f"canon_modified: {str(preview.get('canon_modified')).lower()}")
    batch_review.append_batch_audit(_batch_paths(review_dir)["audit"], action="view_batch_gate_report", summary=summary)


def show_latest_dry_run_result(
    admission_dir: Path = S0143_ADMISSION_DIR,
    *,
    review_dir: Path = S0142_REVIEW_DIR,
) -> None:
    """Render the latest S0143 dry-run result without dumping large files."""
    ready_path = admission_dir / "admission_ready_dry_run.json"
    blocked_path = admission_dir / "admission_blocked.json"
    preview_path = admission_dir / "admission_patch_preview.json"
    if not ready_path.exists() or not blocked_path.exists() or not preview_path.exists():
        print("\nNo existe resultado dry-run S0143. Ejecuta primero la opción 2.")
        return

    ready = _load_json(ready_path, {})
    blocked = _load_json(blocked_path, {})
    preview = _load_json(preview_path, {})
    by_decision = (blocked.get("summary") or {}).get("by_decision") or {}

    print("\n=== Último resultado dry-run ===\n")
    print(f"admission_ready_dry_run: {(ready.get('summary') or {}).get('total', 0)}")
    print(f"blocked: {(blocked.get('summary') or {}).get('total', 0)}")
    print(f"rejected_by_human: {by_decision.get('rejected_by_human', 0)}")
    print(f"blocked_missing_human_review: {by_decision.get('blocked_missing_human_review', 0)}")
    print(f"blocked_batch_hash_mismatch: {by_decision.get('blocked_batch_hash_mismatch', 0)}")
    print(f"blocked_unverified_evidence: {by_decision.get('blocked_unverified_evidence', 0)}")
    print(f"patch_preview_operations: {preview.get('total_operations_previewed', 0)}\n")
    print(f"applied_to_canon: {str(preview.get('applied_to_canon')).lower()}")
    print(f"canon_modified: {str(preview.get('canon_modified')).lower()}\n")
    print("Archivos:")
    print("- admission_ready_dry_run.json")
    print("- admission_blocked.json")
    print("- admission_patch_preview.json")
    batch_review.append_batch_audit(
        _batch_paths(review_dir)["audit"],
        action="view_s0143_dry_run_result",
        summary=build_s0142_batch_summary(review_dir=review_dir),
    )


def show_blocked_or_individual_review_candidates(
    *,
    review_dir: Path = S0142_REVIEW_DIR,
    candidates_file: Path = DEFAULT_VALID_CANDIDATES_FILE,
    canon_glob: str | None = None,
    type_policy_dir: Path = S0139_TYPE_POLICY_DIR,
    admissibility_report: Path = S0132_ADMISSIBILITY_REPORT,
    individual_review_path: Path | None = None,
) -> dict[str, Any]:
    """Show candidates outside the main approvable batch without mixing them into approval."""
    summary = build_s0142_batch_summary(
        review_dir=review_dir,
        candidates_file=candidates_file,
        canon_glob=canon_glob,
        type_policy_dir=type_policy_dir,
        admissibility_report=admissibility_report,
        individual_review_path=individual_review_path,
    )
    classifications = summary.get("classifications") or []
    outside_batch = [
        item for item in classifications
        if item.get("category") != batch_review.BATCH_READY
    ]
    reason_counts = Counter(
        reason
        for item in outside_batch
        for reason in item.get("reasons") or []
    )
    category_counts = Counter(item.get("category") for item in outside_batch)

    print("\n=== Candidatos bloqueados / revisión individual ===\n")
    print("Los candidatos batch_ready no se muestran aquí.")
    print(f"blocked: {category_counts.get(batch_review.BLOCKED, 0)}")
    print(f"individual_review_required: {category_counts.get(batch_review.INDIVIDUAL_REVIEW_REQUIRED, 0)}")
    print(f"unverified_evidence: {reason_counts.get('unverified_evidence', 0)}")
    print(f"unresolved_target: {reason_counts.get('unresolved_target', 0)}")
    print(f"legacy_alias_policy: {reason_counts.get('legacy_alias_policy', 0)}")
    print(f"possible_duplicate: {reason_counts.get('possible_duplicate', 0)}")
    print(f"rejected_by_human: {category_counts.get(batch_review.REJECTED_BY_HUMAN, 0)}")
    print(f"deferred: {(summary.get('summary') or {}).get('deferred', 0)}\n")

    for idx, item in enumerate(sorted(outside_batch, key=lambda x: x["candidate_id"]), start=1):
        reasons = ", ".join(item.get("reasons") or [])
        print(
            f"{idx}. {item['candidate_id']} | {item.get('category', '')} | "
            f"{item.get('relation_type', '')} | razones: {reasons}"
        )
    if not outside_batch:
        print("No hay candidatos bloqueados ni de revisión individual fuera del batch.")
    print("\nPara revisar candidatos individuales, usa 9) Avanzado / mantenimiento.")
    batch_review.append_batch_audit(
        _batch_paths(review_dir)["audit"],
        action="view_blocked_or_individual_review",
        summary=summary,
    )
    return summary


def _prompt_candidate_id() -> str:
    return _prompt("Candidate ID: ").strip()


def show_relation_review_menu() -> None:
    option_relation_review_menu()


def option_relation_review_advanced_menu() -> None:
    """Technical/legacy actions kept out of the main operator path."""
    while True:
        print(_ADVANCED_MENU_HEADER)
        choice = _prompt("> ").strip()

        if choice == "0" or choice == "":
            return

        if choice == "1":
            option_validate_candidates()
        elif choice == "2":
            option_view_human_report()
        elif choice == "3":
            option_generate_admission_plan()
        elif choice == "4":
            show_human_review_queue()
        elif choice == "5":
            cid = _prompt_candidate_id()
            if cid:
                item = show_candidate_detail(cid)
                if item:
                    subchoice = _prompt("> ").strip()
                    if subchoice == "1":
                        approve_candidate_for_dry_run(cid)
                    elif subchoice == "2":
                        reject_candidate_by_human(cid)
                    elif subchoice == "3":
                        defer_candidate(cid)
        elif choice == "6":
            cid = _prompt_candidate_id()
            if cid:
                approve_candidate_for_dry_run(cid)
        elif choice == "7":
            cid = _prompt_candidate_id()
            if cid:
                reject_candidate_by_human(cid)
        elif choice == "8":
            cid = _prompt_candidate_id()
            if cid:
                defer_candidate(cid)
        elif choice == "9":
            run_relation_admission_gate_dry_run()
        elif choice == "10":
            show_admission_gate_report()
        elif choice == "11":
            show_batch_terminal_report()
        elif choice == "12":
            show_batch_ready_lot()
        else:
            print("Opción inválida.")


def option_relation_review_menu() -> None:
    """
    Submenú experimental de revisión relacional.

    Contrato S0127/S0135:
      - Generación: BLOQUEADA
      - Admisión canónica: BLOQUEADA
      - --apply: NUNCA ejecutado
      - tiddlers_*.jsonl: NO modificados
    """
    while True:
        print(_MENU_HEADER)
        choice = _prompt("> ").strip()

        if choice == "0" or choice == "":
            return

        if choice == "1":
            review_batch_and_approve_for_dry_run()
        elif choice == "2":
            run_s0143_batch_admission_gate_dry_run()
        elif choice == "3":
            show_latest_dry_run_result()
        elif choice == "4":
            show_blocked_or_individual_review_candidates()
        elif choice == "9":
            option_relation_review_advanced_menu()
        else:
            print("Opción inválida.")


# ---------------------------------------------------------------------------
# Punto de entrada directo (útil para prueba manual)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    option_relation_review_menu()
