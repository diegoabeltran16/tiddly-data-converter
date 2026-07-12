#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

CANON_DIR="${CANON_DIR:-data/out/local}"
RELATION_OUT_DIR="${RELATION_OUT_DIR:-data/out/local/pipeline/relation_candidates/current}"
AUDIT_DIR="${AUDIT_DIR:-data/out/local/audit/relation_admission/current}"
RELATION_HUMAN_REVIEW_DECISIONS="${RELATION_HUMAN_REVIEW_DECISIONS:-$RELATION_OUT_DIR/human_review_decisions.jsonl}"
RELATION_SESSION="${RELATION_SESSION:-current}"
RELATION_RUN_ID="${RELATION_RUN_ID:-current}"

tdc_pause() {
    if [[ -t 0 ]]; then
        printf "\nEnter para volver al menú..."
        read -r _ || true
    fi
}

tdc_relation_candidate_file() {
    if [[ -n "${RELATION_CANDIDATE_FILE:-}" ]]; then
        printf '%s\n' "$RELATION_CANDIDATE_FILE"
        return
    fi
    if [[ -f "$RELATION_OUT_DIR/review_queue.jsonl" ]]; then
        printf '%s\n' "$RELATION_OUT_DIR/review_queue.jsonl"
        return
    fi
    if [[ -f "$RELATION_OUT_DIR/relation_candidates.jsonl" ]]; then
        printf '%s\n' "$RELATION_OUT_DIR/relation_candidates.jsonl"
        return
    fi
    if [[ -f "$RELATION_OUT_DIR/candidates.jsonl" ]]; then
        printf '%s\n' "$RELATION_OUT_DIR/candidates.jsonl"
        return
    fi
    if [[ -f "data/out/local/pipeline/relation_candidates/s0162/review_queue.jsonl" ]]; then
        printf '%s\n' "data/out/local/pipeline/relation_candidates/s0162/review_queue.jsonl"
        return
    fi
    printf '%s\n' "$RELATION_OUT_DIR/review_queue.jsonl"
}

tdc_relations_generate_candidates() {
    mkdir -p "$RELATION_OUT_DIR"
    cat <<EOF
Generando candidatas relacionales contra canon vigente.
Canon vigente: $CANON_DIR
Salida: $RELATION_OUT_DIR
Nota: S0162 review_queue, si se usa después, es evidencia histórica; no autoridad actual.
EOF
    python3 src/python_scripts/generate_technical_relation_candidates.py \
        --canon-root "$CANON_DIR" \
        --out-dir "$RELATION_OUT_DIR" \
        --session "$RELATION_SESSION" \
        --run-id "$RELATION_RUN_ID" \
        --dry-run
}

tdc_relations_validate_candidates() {
    mkdir -p "$RELATION_OUT_DIR"
    local candidate_file
    candidate_file="$(tdc_relation_candidate_file)"
    if [[ "$candidate_file" == *"/s0162/"* ]]; then
        echo "Usando S0162 review_queue como evidencia histórica: $candidate_file"
    fi
    if [[ ! -f "$candidate_file" ]]; then
        echo "No existe archivo de candidatas: $candidate_file"
        echo "Ejecute primero la opción 1 o defina RELATION_CANDIDATE_FILE."
        return 1
    fi
    python3 src/python_scripts/validate_relation_candidates.py \
        --candidate-file "$candidate_file" \
        --canon-glob "$CANON_DIR/tiddlers_*.jsonl" \
        --report "$RELATION_OUT_DIR/validation_report.json" \
        --human-review "$RELATION_OUT_DIR/human_review.md" \
        --output-dir "$RELATION_OUT_DIR" \
        --session-tag "$RELATION_SESSION" \
        --dry-run
}

tdc_relations_dry_run_gate() {
    mkdir -p "$AUDIT_DIR"
    local candidate_file
    candidate_file="$(tdc_relation_candidate_file)"
    if [[ "$candidate_file" == *"/s0162/"* ]]; then
        echo "Usando S0162 review_queue como evidencia histórica: $candidate_file"
    fi
    if [[ ! -f "$candidate_file" ]]; then
        echo "No existe archivo de candidatas: $candidate_file"
        echo "Ejecute primero la opción 1 o defina RELATION_CANDIDATE_FILE."
        return 1
    fi
    python3 src/python_scripts/relation_admission_gate.py \
        --candidate-file "$candidate_file" \
        --canon-glob "$CANON_DIR/tiddlers_*.jsonl" \
        --dry-run \
        --session "$RELATION_SESSION" \
        --output "$AUDIT_DIR/admission_gate_dry_run.json" \
        --out-dir "$AUDIT_DIR"
}

tdc_relations_show_summary() {
    local report="$AUDIT_DIR/admission_gate_dry_run.json"
    python3 - "$report" <<'PY'
import json
import sys
from collections import Counter
from pathlib import Path

path = Path(sys.argv[1])
repo_root = Path.cwd()
current_dir = repo_root / "data/out/local/pipeline/relation_candidates/current"
s0167_dir = repo_root / "data/out/local/pipeline/relation_candidates/s0167"
s0167_audit = repo_root / "data/out/local/audit/relation_admission/s0167/s0167_admission_gate_dry_run.json"


def load_json(json_path):
    if not json_path.exists():
        return {}
    return json.loads(json_path.read_text(encoding="utf-8"))


def count_jsonl(jsonl_path):
    if not jsonl_path.exists():
        return 0
    with jsonl_path.open(encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def count_human_decisions(jsonl_path):
    counts = Counter()
    if not jsonl_path.exists():
        return counts
    with jsonl_path.open(encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            row = json.loads(raw)
            counts[row.get("human_review_decision") or row.get("decision") or "(unknown)"] += 1
    return counts

print("Resumen relacional")

current_report = load_json(current_dir / "relation_candidates_report.json")
current_validation = load_json(current_dir / "validation_report.json")
current_candidate_count = 0
if current_report:
    current_candidate_count = int(current_report.get("candidate_count") or 0)
    print("Current generation:")
    print(f"- candidatas generadas: {current_candidate_count}")
    print(f"- listas directas para review: {current_report.get('ready_for_review_count', 0)}")
    print(f"- bloqueadas: {current_report.get('blocked_count', 0)}")
    status_counts = current_report.get("status_counts") or {}
    if status_counts:
        print("- bloqueos:")
        for status, count in sorted(status_counts.items()):
            print(f"  - {status}: {count}")
elif (current_dir / "relation_candidates.jsonl").exists():
    print("Current generation:")
    print(f"- candidatas generadas: {count_jsonl(current_dir / 'relation_candidates.jsonl')}")
    print("- listas directas para review: no calculado")
    print("- bloqueadas: no calculado")
else:
    print("Current generation:")
    print("- no hay candidatas current generadas")

validation_summary = current_validation.get("summary") or {}
if validation_summary:
    validation_total = int(validation_summary.get("total") or 0)
    validation_label = "validación current"
    if current_candidate_count and validation_total != current_candidate_count:
        validation_label += " (desfasada frente a la generación actual)"
    print(
        f"- {validation_label}: total={validation_total} "
        f"valid={validation_summary.get('valid', 0)} invalid={validation_summary.get('invalid', 0)}"
    )

repair_report = load_json(s0167_dir / "repair_report.json")
ready_path = s0167_dir / "relation_candidates_ready_for_review.jsonl"
ready_count = count_jsonl(ready_path)
if repair_report or ready_path.exists():
    residual = repair_report.get("residual_breakdown_for_s0168") or {}
    summary = repair_report.get("summary") or {}
    decisions = count_human_decisions(s0167_dir / "human_review_decisions.jsonl")
    approved = decisions.get("approved_for_admission", 0)
    print("S0167 repaired queue:")
    print(f"- cola S0167: {ready_count} candidatas válidas para revisión humana")
    print("- estado: no admitidas")
    print(f"- decisiones humanas persistentes: {sum(decisions.values())}")
    print(f"- aprobadas para admisión: {approved}")
    print(f"- bloqueadas por mapping restantes: {residual.get('blocked_mapping_remaining', summary.get('blocked_mapping_remaining', 0))}")
    print(f"- bloqueadas por target restantes: {residual.get('blocked_target_remaining', summary.get('blocked_target_remaining', 0))}")
    print(f"- inválidas por contrato restantes: {residual.get('invalid_contract_remaining', summary.get('invalid_contract_remaining', 0))}")
    print(f"- duplicados excluidos: {residual.get('duplicate_excluded', summary.get('duplicate_excluded', 0))}")
    print("- siguiente paso: revisión humana persistente")
else:
    print("S0167 repaired queue:")
    print("- no disponible")

print("Apply:")
print("- protegido: requiere human_review_decisions persistente y confirmación explícita")

if path.exists():
    data = json.loads(path.read_text(encoding="utf-8"))
    summary = data.get("summary") or {}
    items = data.get("items") or []
    decisions = Counter(item.get("decision") for item in items)
    all_reasons = Counter()
    for item in items:
        for reason in item.get("all_block_reasons") or item.get("blocking_reasons") or []:
            all_reasons[reason.split(":", 1)[0]] += 1
    print("Último dry-run current:")
    print(f"- evaluadas: {summary.get('total_evaluated', len(items))}")
    print(f"- admission_ready_dry_run: {summary.get('admission_ready_dry_run', 0)}")
    print(f"- bloqueadas: {summary.get('blocked', 0)}")
    print(f"- missing_human_review: {decisions.get('blocked_missing_human_review', 0)}")
    print(f"- stale_path: {decisions.get('blocked_repo_path_stale_or_lifecycle', 0)}")
    print(f"- missing_lifecycle_state: {all_reasons.get('GATE-020', 0)}")
    print(f"- build_artifact_blocked: {decisions.get('blocked_build_artifact', 0)}")
    print(f"- duplicate_existing: {decisions.get('blocked_duplicate_existing', 0)}")
    print(f"- reporte: {path}")
elif s0167_audit.exists():
    gate = load_json(s0167_audit)
    gate_summary = gate.get("summary") or {}
    print("Último dry-run S0167:")
    print(f"- evaluadas: {gate_summary.get('total_evaluated', 0)}")
    print(f"- admission_ready_dry_run: {gate_summary.get('admission_ready_dry_run', 0)}")
    print(f"- bloqueadas: {gate_summary.get('blocked', 0)}")
    print("- estado: bloqueado correctamente hasta decisiones humanas persistentes")
    print(f"- reporte: {s0167_audit}")
else:
    print("Último dry-run:")
    print("- no existe todavía un dry-run relacional persistente")
    print("- ejecute primero la opción 3")
PY
}

tdc_relations_apply() {
    cat <<'EOF'
ATENCIÓN:
Esta operación puede modificar el canon local agregando relaciones admitidas.

Solo debe ejecutarse si:
- el dry-run pasó;
- existe human_review_decision=approved_for_admission;
- las candidatas fueron revalidadas contra el canon vigente;
- el operador acepta la mutación canónica.

Escribe exactamente:
APPLY RELATIONS
para continuar.
EOF
    local confirmation
    read -r confirmation || confirmation=""
    if [[ "$confirmation" != "APPLY RELATIONS" ]]; then
        echo "Operación cancelada. No se modificó el canon."
        return 0
    fi

    local report="$AUDIT_DIR/admission_gate_dry_run.json"
    local candidate_file
    candidate_file="$(tdc_relation_candidate_file)"
    mkdir -p "$AUDIT_DIR"
    python3 src/python_scripts/relation_admission_gate.py \
        --candidate-file "$candidate_file" \
        --canon-glob "$CANON_DIR/tiddlers_*.jsonl" \
        --human-review-decisions "$RELATION_HUMAN_REVIEW_DECISIONS" \
        --dry-run-report "$report" \
        --out-dir "$AUDIT_DIR" \
        --session "$RELATION_SESSION" \
        --terminal-confirmation "$confirmation" \
        --apply 2>&1
}

tdc_relations_menu() {
    while true; do
        cat <<'EOF'
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Relaciones canónicas
  Canon: PROTEGIDO
  Apply: requiere confirmación humana explícita
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1) Generar candidatas desde canon vigente
2) Validar candidatas / review queue
3) Dry-run admission gate
4) Ver estado relacional y cola S0167
5) APPLY RELATIONS al canon
0) Volver
EOF
        printf "> "
        local choice
        read -r choice || choice=""
        case "$choice" in
            1) tdc_relations_generate_candidates; tdc_pause ;;
            2) tdc_relations_validate_candidates; tdc_pause ;;
            3) tdc_relations_dry_run_gate; tdc_pause ;;
            4) tdc_relations_show_summary; tdc_pause ;;
            5) tdc_relations_apply; tdc_pause ;;
            0|"") return 0 ;;
            *) echo "Opción inválida." ;;
        esac
    done
}

# tdc.sh mcp  → gestor de configuracion MCP / mirror remoto
# tdc.sh relations → submenú relacional gobernado
# tdc.sh      → menu principal del operador
case "${1:-}" in
    mcp)
        python3 src/python_scripts/mcp_env_manager.py
        ;;
    relations)
        tdc_relations_menu
        ;;
    *)
        python3 src/python_scripts/operator_menu.py
        ;;
esac
