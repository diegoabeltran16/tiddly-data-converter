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
    if [[ -f "$RELATION_OUT_DIR/relation_candidates.jsonl" ]]; then
        printf '%s\n' "$RELATION_OUT_DIR/relation_candidates.jsonl"
        return
    fi
    printf '%s\n' "$RELATION_OUT_DIR/relation_candidates.jsonl"
}

tdc_relation_reviewable_file() {
    if [[ -n "${RELATION_REVIEWABLE_FILE:-}" ]]; then
        printf '%s\n' "$RELATION_REVIEWABLE_FILE"
        return
    fi
    printf '%s\n' "$RELATION_OUT_DIR/ready_for_human_review.jsonl"
}

tdc_relations_generate_candidates() {
    mkdir -p "$RELATION_OUT_DIR"
    cat <<EOF
Generando candidatas relacionales contra canon vigente.
Canon vigente: $CANON_DIR
Salida: $RELATION_OUT_DIR
Los lotes S0161-S0167 permanecen únicamente como historia avanzada.
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
    python3 src/python_scripts/reconcile_current_relation_candidates.py \
        --canon-root "$CANON_DIR" \
        --current-dir "$RELATION_OUT_DIR" \
        --audit-dir data/out/local/audit/s0180
}

tdc_relations_dry_run_gate() {
    mkdir -p "$AUDIT_DIR"
    local candidate_file
    candidate_file="$(tdc_relation_reviewable_file)"
    if [[ ! -f "$candidate_file" ]]; then
        echo "No existe la cola reviewable vigente: $candidate_file."
        echo "Ejecute primero “Validar y reconciliar candidatas vigentes” (opción 2)"
        echo "o defina RELATION_REVIEWABLE_FILE."
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
    python3 src/python_scripts/relation_admission_state.py state
}

tdc_relations_show_ready_queue() {
    python3 - "$RELATION_OUT_DIR/ready_for_human_review.jsonl" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
print(f"Cola técnica vigente: {p}")
print(f"Registros: {sum(1 for line in p.open(encoding='utf-8') if line.strip()) if p.exists() else 0}")
print("Autoridad: candidate; revisión humana no ejecutada; canon no admitido.")
PY
}

tdc_relations_show_blocked() {
    python3 src/python_scripts/relation_admission_state.py validate-currentness || true
}

tdc_relations_show_history() {
    echo "Historia relacional (solo consulta):"
    find data/out/local/pipeline/relation_candidates data/out/local/audit/relation_admission/history -mindepth 1 -maxdepth 1 -type d -printf '%p\n' 2>/dev/null | sort || true
}

tdc_relations_show_decisions() {
    if [[ -s "$RELATION_HUMAN_REVIEW_DECISIONS" ]]; then
        sed -n '1,20p' "$RELATION_HUMAN_REVIEW_DECISIONS"
    else
        echo "No existen decisiones humanas vigentes. Revisión reservada para S0181."
    fi
}

tdc_relations_review() {
    echo "Revisión humana no ejecutada en S0180. Próxima acción gobernada: OPEN_S0181_HUMAN_RELATIONAL_REVIEW."
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
    candidate_file="$(tdc_relation_reviewable_file)"
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
  Relaciones canónicas / preparación técnica
  Canon: PROTEGIDO
  Este módulo no contiene apply
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1) Generar candidatas desde canon vigente
2) Validar y reconciliar candidatas vigentes
3) Ver estado relacional vigente
4) Ver cola lista para revisión humana
5) Ver bloqueos técnicos
9) Historia relacional avanzada
0) Volver
EOF
        printf "> "
        local choice
        read -r choice || choice=""
        case "$choice" in
            1) tdc_relations_generate_candidates; tdc_pause ;;
            2) tdc_relations_validate_candidates; tdc_pause ;;
            3) tdc_relations_show_summary; tdc_pause ;;
            4) tdc_relations_show_ready_queue; tdc_pause ;;
            5) tdc_relations_show_blocked; tdc_pause ;;
            9) tdc_relations_show_history; tdc_pause ;;
            0|"") return 0 ;;
            *) echo "Opción inválida." ;;
        esac
    done
}

tdc_relations_admission_menu() {
    while true; do
        cat <<'EOF'
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Revisión humana / admisión relacional
  Canon: PROTEGIDO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1) Abrir revisión humana (S0181; no ejecutada aquí)
2) Ver decisiones humanas vigentes
3) Ejecutar admission gate dry-run
4) Ver estado de compuerta relacional
5) APPLY RELATIONS protegido
6) Ver reportes relacionales
0) Volver
EOF
        printf "> "
        local choice
        read -r choice || choice=""
        case "$choice" in
            1) tdc_relations_review; tdc_pause ;;
            2) tdc_relations_show_decisions; tdc_pause ;;
            3) tdc_relations_dry_run_gate; tdc_pause ;;
            4) tdc_relations_show_summary; tdc_pause ;;
            5) tdc_relations_apply; tdc_pause ;;
            6) find "$RELATION_OUT_DIR" "$AUDIT_DIR" -maxdepth 1 -type f -printf '%p\n' | sort; tdc_pause ;;
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
    relations-admission)
        tdc_relations_admission_menu
        ;;
    relations-state)
        tdc_relations_show_summary
        ;;
    relations-audit)
        python3 src/python_scripts/relation_admission_state.py audit
        ;;
    relations-rollback-status)
        tdc_relations_show_summary
        ;;
    *)
        python3 src/python_scripts/operator_menu.py
        ;;
esac
