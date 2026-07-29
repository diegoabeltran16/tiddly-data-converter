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
RELATION_ROLLBACK_SNAPSHOT="${RELATION_ROLLBACK_SNAPSHOT:-}"
RELATION_GATE_G_AUTHORIZATION="${RELATION_GATE_G_AUTHORIZATION:-data/out/local/audit/s0183/gate-g/gate_g_authorization.json}"
RELATION_GATE_G_PLAN="${RELATION_GATE_G_PLAN:-data/out/local/audit/s0183/gate-g/relation_apply_plan.json}"

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
    local -a decision_arg=()
    if [[ -s "$RELATION_HUMAN_REVIEW_DECISIONS" ]]; then
        decision_arg=(--human-review-decisions "$RELATION_HUMAN_REVIEW_DECISIONS")
    fi
    python3 src/python_scripts/relation_admission_gate.py \
        --candidate-file "$candidate_file" \
        --canon-glob "$CANON_DIR/tiddlers_*.jsonl" \
        "${decision_arg[@]}" \
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
        local next_action
        next_action="$(python3 src/python_scripts/relation_admission_state.py next-action --local-root "$CANON_DIR")"
        echo "No existen decisiones humanas vigentes. Acción: $next_action."
    fi
}

tdc_relations_review() {
    python3 src/python_scripts/current_relation_human_review.py \
        --current-dir "$RELATION_OUT_DIR" \
        --canon-root "$CANON_DIR"
}

tdc_relations_preview_review_batches() {
    python3 src/python_scripts/current_relation_human_review.py \
        --current-dir "$RELATION_OUT_DIR" \
        --canon-root "$CANON_DIR" \
        --gate-report "$AUDIT_DIR/admission_gate_dry_run.json" \
        --preview-batches
}

tdc_relations_review_batches() {
    python3 src/python_scripts/current_relation_human_review.py \
        --current-dir "$RELATION_OUT_DIR" \
        --canon-root "$CANON_DIR" \
        --gate-report "$AUDIT_DIR/admission_gate_dry_run.json" \
        --review-batches
}

tdc_relations_review_multiple_batches() {
    python3 src/python_scripts/current_relation_human_review.py \
        --current-dir "$RELATION_OUT_DIR" \
        --canon-root "$CANON_DIR" \
        --gate-report "$AUDIT_DIR/admission_gate_dry_run.json" \
        --review-multiple-batches
}

tdc_relations_supersede_legacy_review() {
    cat <<'EOF'
Esta operación preserva decisiones, auditoría, manifests y dry-run en la ruta
histórica S0181 antes de reinicializar atómicamente la autoridad current.
No ejecuta apply ni modifica el canon.
EOF
    local actor note confirmation
    printf "Identidad del revisor humano: "
    read -r actor || actor=""
    printf "Motivo documentado de supersesión: "
    read -r note || note=""
    printf "Escriba exactamente SUPERSEDE CURRENT HUMAN REVIEW: "
    read -r confirmation || confirmation=""
    python3 src/python_scripts/current_relation_human_review.py \
        --current-dir "$RELATION_OUT_DIR" \
        --canon-root "$CANON_DIR" \
        --reviewer "$actor" \
        --supersede-current \
        --note "$note" \
        --confirmation "$confirmation"
}

tdc_relations_apply_cli_guard() {
    local report="$AUDIT_DIR/admission_gate_dry_run.json"
    local guard_output
    if guard_output="$(python3 - "$report" "$RELATION_HUMAN_REVIEW_DECISIONS" <<'PY'
import json
import sys
from pathlib import Path


report_path = Path(sys.argv[1])
decisions_path = Path(sys.argv[2])


def block(reason_code, *messages):
    print(reason_code)
    for message in messages:
        print(message)
    raise SystemExit(1)


try:
    report = json.loads(report_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    block(
        "RELATION_APPLY_PREFLIGHT_BLOCKED",
        "Apply bloqueado: el reporte dry-run current no es válido para preparar admisión.",
    )

summary = report.get("summary") if isinstance(report, dict) else None
items = report.get("items") if isinstance(report, dict) else None
if not isinstance(summary, dict) or not isinstance(items, list):
    block(
        "RELATION_APPLY_PREFLIGHT_BLOCKED",
        "Apply bloqueado: el reporte dry-run current no es válido para preparar admisión.",
    )
if summary.get("dry_run") is not True or summary.get("canon_modified") is not False:
    block(
        "RELATION_APPLY_PREFLIGHT_BLOCKED",
        "Apply bloqueado: el reporte no representa un dry-run inmutable.",
    )

try:
    evaluated = int(summary.get("evaluated", summary.get("total_evaluated", len(items))) or 0)
    admission_ready = int(
        summary.get("admission_ready", summary.get("admission_ready_dry_run", 0)) or 0
    )
    awaiting = int(summary.get("awaiting_human_review") or 0)
except (TypeError, ValueError):
    block(
        "RELATION_APPLY_PREFLIGHT_BLOCKED",
        "Apply bloqueado: los conteos del dry-run current no son válidos.",
    )

if awaiting > 0 or (evaluated > 0 and not decisions_path.is_file()):
    block(
        "HUMAN_REVIEW_INCOMPLETE",
        "Apply bloqueado: la revisión humana del lote current está incompleta.",
        "Resuelva las candidatas awaiting antes de preparar una admisión.",
    )
if admission_ready <= 0:
    block(
        "NO_ADMISSION_READY_CANDIDATES",
        "Apply bloqueado: no existen candidatas admission-ready.",
    )
PY
)"; then
        return 0
    fi
    printf '%s\n' "$guard_output"
    echo "No se solicitará confirmación y no se modificó el canon."
    return 1
}

tdc_relations_apply() {
    if ! python3 src/python_scripts/relation_admission_state.py \
        apply-preflight --local-root "$CANON_DIR"; then
        echo "RELATION_APPLY_PREFLIGHT_BLOCKED"
        echo "APPLY RELATIONS bloqueado antes de solicitar confirmación."
        echo "No se modificó el canon."
        return 1
    fi
    if ! tdc_relations_apply_cli_guard; then
        return 1
    fi
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
        echo "RELATION_APPLY_CANCELLED"
        echo "Apply cancelado: no se recibió la confirmación exacta requerida."
        echo "No se modificó el canon."
        return 1
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
        --authorization-file "$RELATION_GATE_G_AUTHORIZATION" \
        --authorized-plan "$RELATION_GATE_G_PLAN" \
        --out-dir "$AUDIT_DIR" \
        --session "$RELATION_SESSION" \
        --terminal-confirmation "$confirmation" \
        --apply 2>&1
}

tdc_relations_rollback() {
    if [[ -z "$RELATION_ROLLBACK_SNAPSHOT" || ! -f "$RELATION_ROLLBACK_SNAPSHOT" ]]; then
        echo "ROLLBACK RELATIONS bloqueado: defina RELATION_ROLLBACK_SNAPSHOT con un snapshot verificable."
        return 1
    fi
    cat <<'EOF'
Esta operación restaura exactamente los shards vinculados al snapshot.
Escriba exactamente:
ROLLBACK RELATIONS
para continuar.
EOF
    local confirmation
    read -r confirmation || confirmation=""
    if [[ "$confirmation" != "ROLLBACK RELATIONS" ]]; then
        echo "Rollback cancelado. No se modificó el canon."
        return 0
    fi
    python3 src/python_scripts/relation_admission_gate.py \
        --rollback-snapshot "$RELATION_ROLLBACK_SNAPSHOT" \
        --rollback-confirmation "$confirmation" \
        --out-dir "$AUDIT_DIR"
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

1) Abrir revisión individual v2 (S0181; sin apply)
2) Ver decisiones humanas vigentes
3) Ejecutar admission gate dry-run
4) Ver estado de compuerta relacional
5) APPLY RELATIONS protegido
6) Ver reportes relacionales
7) Previsualizar lotes homogéneos v2 (no escribe)
8) Revisar y confirmar un lote v2
9) Superseder revisión legacy con respaldo histórico
10) Revisar múltiples lotes homogéneos v2
11) ROLLBACK RELATIONS protegido
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
            7) tdc_relations_preview_review_batches; tdc_pause ;;
            8) tdc_relations_review_batches; tdc_pause ;;
            9) tdc_relations_supersede_legacy_review; tdc_pause ;;
            10) tdc_relations_review_multiple_batches; tdc_pause ;;
            11) tdc_relations_rollback; tdc_pause ;;
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
