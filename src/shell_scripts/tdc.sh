#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

CANON_DIR="${CANON_DIR:-data/out/local}"
RELATION_OUT_DIR="${RELATION_OUT_DIR:-data/out/local/pipeline/relation_candidates/current}"
AUDIT_DIR="${AUDIT_DIR:-data/out/local/audit/relation_admission/current}"
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
    if [[ ! -f "$report" ]]; then
        echo "No existe todavía un dry-run relacional persistente."
        echo "Ejecute primero la opción 3."
        return 0
    fi
    python3 - "$report" <<'PY'
import json
import sys
from collections import Counter
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
summary = data.get("summary") or {}
items = data.get("items") or []
decisions = Counter(item.get("decision") for item in items)
all_reasons = Counter()
for item in items:
    for reason in item.get("all_block_reasons") or item.get("blocking_reasons") or []:
        all_reasons[reason.split(":", 1)[0]] += 1

print("Resumen relacional")
print(f"- candidate_count: {summary.get('total_evaluated', len(items))}")
print(f"- review_queue_count: {summary.get('total_evaluated', len(items))}")
print(f"- admission_ready_dry_run_count: {summary.get('admission_ready_dry_run', 0)}")
print(f"- blocked_count: {summary.get('blocked', 0)}")
print(f"- missing_human_review_count: {decisions.get('blocked_missing_human_review', 0)}")
print(f"- stale_path_count: {decisions.get('blocked_repo_path_stale_or_lifecycle', 0)}")
print(f"- missing_lifecycle_state_count: {all_reasons.get('GATE-020', 0)}")
print(f"- build_artifact_blocked_count: {decisions.get('blocked_build_artifact', 0)}")
print(f"- duplicate_count: {decisions.get('blocked_duplicate_existing', 0)}")
print(f"- último reporte generado: {path}")
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
    if [[ ! -f "$report" ]]; then
        echo "APPLY RELATIONS bloqueado."
        echo "Motivo: no existe dry-run relacional persistente en $report."
        echo "No se modificó el canon."
        return 1
    fi

    local apply_block_reason
    if ! apply_block_reason="$(python3 - "$report" 2>&1 <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
summary = data.get("summary") or {}
items = data.get("items") or []
ready = int(summary.get("admission_ready_dry_run") or 0)
blocked = int(summary.get("blocked") or 0)
if ready <= 0:
    raise SystemExit("Motivo: admission_ready_dry_run_count es 0.")
if blocked:
    raise SystemExit(f"Motivo: existen {blocked} candidatas bloqueadas.")
for item in items:
    if item.get("gate_status") != "admission_ready_dry_run":
        continue
    if item.get("human_review_decision") != "approved_for_admission":
        raise SystemExit("Motivo: una candidata lista no tiene human_review_decision=approved_for_admission.")
    reasons = "\n".join(item.get("all_block_reasons") or item.get("blocking_reasons") or [])
    if "GATE-021" in reasons:
        raise SystemExit("Motivo: existe build artifact bloqueado.")
    if "GATE-008" in reasons or "GATE-009" in reasons:
        raise SystemExit("Motivo: existe source/target inexistente.")
    if "GATE-022" in reasons:
        raise SystemExit("Motivo: existe path stale sin lifecycle histórico explícito.")
PY
    )"; then
        echo "APPLY RELATIONS bloqueado."
        echo "$apply_block_reason"
        echo "No se modificó el canon."
        return 1
    fi

    echo "APPLY RELATIONS no disponible todavía."
    echo "Motivo: no existe motor apply seguro validado."
    echo "Siguiente paso: implementar admisión canónica gobernada en S0165."
    echo "No se modificó el canon."
    return 1
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
4) Ver último resumen relacional
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
