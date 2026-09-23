#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# S0187 Unit D (D17): CANON_DIR resolves from the SAME single workspace/path
# owner Python already uses (path_governance.py), instead of a hardcoded
# REPO_ROOT-relative literal -- so tdc.sh follows a persisted storage
# cutover (.tdc/workspace_storage.json) instead of silently staying pinned
# to repo/data/out/local. Precedence is NOT reimplemented here:
# path_governance.resolve_workspace_root() alone owns
# TDC_WORKSPACE_ROOT > persisted config > default repo/data; this only asks
# it for the current answer, once, at startup, and ONLY when CANON_DIR isn't
# already set (isolated test fixtures set it explicitly and must never
# trigger this python3 call, which some fixtures intercept via PATH to
# assert "no python invoked yet" on early-cancel paths). AUDIT_DIR and
# RELATION_OUT_DIR are then derived from CANON_DIR in bash alone --
# structurally correct because path_governance.DEFAULT_CANON_DIR IS
# DEFAULT_LOCAL_OUT_DIR, the exact same parent DEFAULT_AUDIT_DIR derives
# from, so no second python query is needed and no second precedence
# system is introduced.
if [[ -z "${CANON_DIR:-}" ]]; then
    CANON_DIR="$(python3 - <<'PY'
import sys
sys.path.insert(0, "src/python_scripts")
from path_governance import DEFAULT_CANON_DIR, as_display_path
print(as_display_path(DEFAULT_CANON_DIR))
PY
)"
fi
RELATION_OUT_DIR="${RELATION_OUT_DIR:-$CANON_DIR/pipeline/relation_candidates/current}"
AUDIT_DIR="${AUDIT_DIR:-$CANON_DIR/audit/relation_admission/current}"
# S0186 Unit H8 (second diagnostic pass): decisions written after CURRENT was
# last prepared -- batch confirmations, and now policy_derived materialization
# -- land in effective_human_review_decisions.jsonl when it exists, exactly
# the same "prefer effective, fall back to raw" rule
# current_relation_human_review.decision_authority_path() /
# prepare_current_relational_generation.effective_decisions_path() already
# use. This default MUST mirror that rule; a hardcoded raw-file default here
# silently stranded 97 materialized policy-derived decisions from the
# admission gate dry-run despite the human review record existing correctly.
#
# S0186 Unit H (final intervention, current-authority fragmentation):
# pipeline/current/effective_human_review_decisions.jsonl only mirrors
# governed_relation_admission_policy.materialize_authorized_policy() writes
# -- it never receives batch-review receipts published into a new
# generational review-state bundle (current_relation_human_review.py's own
# persist_current_human_delta_batch()). It is therefore a partial,
# derived/convenience surface, not the authority: it can under-report
# decisions (e.g. 283 of 498 known) relative to the published generational
# bundle the CURRENT pointer names. When a valid current bundle is published,
# resolve decisions from THAT authority (the same one
# current_relational_apply.py already trusts for the productive Apply path)
# instead of the convenience copy, so the admission-gate dry-run this script
# drives sees the same CURRENT every other authority-resolving consumer sees.
# An explicit RELATION_HUMAN_REVIEW_DECISIONS override (as some fixtures/tests
# set) is still respected untouched. Resolved LAZILY (only at point of use,
# not at script startup) so menu paths that never touch relation decisions
# never pay for or depend on this resolution.
resolve_relation_human_review_decisions() {
    if [[ -n "${RELATION_HUMAN_REVIEW_DECISIONS:-}" ]]; then
        return 0
    fi
    RELATION_HUMAN_REVIEW_DECISIONS="$(python3 - "$CANON_DIR" <<'PY'
import sys
sys.path.insert(0, "src/python_scripts")
from pathlib import Path
from current_relational_authority import CurrentRelationalAuthorityError, resolve_current_relational_authority

try:
    authority = resolve_current_relational_authority(Path(sys.argv[1]))
    path = authority["artifacts"].get("effective_decisions")
    print(path if path is not None else "", end="")
except CurrentRelationalAuthorityError:
    print("", end="")
PY
)"
    if [[ -z "$RELATION_HUMAN_REVIEW_DECISIONS" ]]; then
        if [[ -f "$RELATION_OUT_DIR/effective_human_review_decisions.jsonl" ]]; then
            RELATION_HUMAN_REVIEW_DECISIONS="$RELATION_OUT_DIR/effective_human_review_decisions.jsonl"
        else
            RELATION_HUMAN_REVIEW_DECISIONS="$RELATION_OUT_DIR/human_review_decisions.jsonl"
        fi
    fi
}
RELATION_SESSION="${RELATION_SESSION:-current}"
RELATION_RUN_ID="${RELATION_RUN_ID:-current}"
RELATION_ROLLBACK_SNAPSHOT="${RELATION_ROLLBACK_SNAPSHOT:-}"
RELATION_GATE_G_AUTHORIZATION="${RELATION_GATE_G_AUTHORIZATION:-data/out/local/audit/s0183/gate-g/gate_g_authorization.json}"
RELATION_GATE_G_PLAN="${RELATION_GATE_G_PLAN:-data/out/local/audit/s0183/gate-g/relation_apply_plan.json}"
RELATION_MIGRATION_SOURCE_DECISIONS="${RELATION_MIGRATION_SOURCE_DECISIONS:-data/out/local/audit/s0183/entry-20260727T020358Z/pipeline_current/human_review_decisions.jsonl}"
RELATION_MIGRATION_CROSS_BATCH_MANIFEST="${RELATION_MIGRATION_CROSS_BATCH_MANIFEST:-data/out/local/audit/s0183/current/cross_batch_reconciliation_manifest.json}"
RELATION_MIGRATION_AUDIT_DIR="${RELATION_MIGRATION_AUDIT_DIR:-$AUDIT_DIR/human_decision_migration}"

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
        --audit-dir "$CANON_DIR/audit/s0180"
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
    resolve_relation_human_review_decisions
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
    python3 src/python_scripts/relation_admission_state.py \
        state --local-root "$CANON_DIR"
}

tdc_relations_show_ready_queue() {
    python3 - "$CANON_DIR" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "src/python_scripts")
from relation_admission_state import build_state

state = build_state(Path(sys.argv[1]))
review = state.get("human_review") or {}
authority = state.get("current_authority") or {}
print(f"Cola técnica reviewable: {review.get('technical_reviewable', 'no resoluble')}")
print(f"Cobertura efectiva de decisiones: {review.get('effective_decision_covered', 'no resoluble')}")
print(f"Delta humano efectivo pendiente: {review.get('effective_pending', 'no resoluble')}")
print(f"Autoridad generacional current: {'VÁLIDA' if authority.get('valid') else 'STALE/AUSENTE'}")
if authority.get("stale_reasons"):
    print("Reason-codes: " + ", ".join(authority["stale_reasons"]))
print(f"Estado operacional: {state.get('verdict')}")
print(f"Siguiente acción: {state.get('next_action')}")
PY
}

tdc_relations_show_blocked() {
    python3 src/python_scripts/relation_admission_state.py validate-currentness || true
}

tdc_relations_show_history() {
    echo "Historia relacional (solo consulta):"
    find "$CANON_DIR/pipeline/relation_candidates" "$CANON_DIR/audit/relation_admission/history" -mindepth 1 -maxdepth 1 -type d -printf '%p\n' 2>/dev/null | sort || true
}

tdc_relations_show_decisions() {
    resolve_relation_human_review_decisions
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
    printf "\n¿Ver detalle completo por candidata? (s/N): "
    local ver_detalle
    read -r ver_detalle || ver_detalle=""
    if [[ "$ver_detalle" =~ ^[sS]$ ]]; then
        python3 src/python_scripts/current_relation_human_review.py \
            --current-dir "$RELATION_OUT_DIR" \
            --canon-root "$CANON_DIR" \
            --gate-report "$AUDIT_DIR/admission_gate_dry_run.json" \
            --preview-batches --detail
    fi
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
    echo "Preflight fail-closed de migración equivalente (dry-run; cero escritura):"
    if ! python3 src/python_scripts/current_relation_human_review.py \
        --migrate-equivalent \
        --historical-decisions "$RELATION_MIGRATION_SOURCE_DECISIONS" \
        --cross-batch-manifest "$RELATION_MIGRATION_CROSS_BATCH_MANIFEST" \
        --migration-audit-dir "$RELATION_MIGRATION_AUDIT_DIR" \
        --current-dir "$RELATION_OUT_DIR" \
        --canon-root "$CANON_DIR"; then
        echo "Supersesión bloqueada por el preflight; no se solicitará confirmación."
        return 1
    fi
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
    resolve_relation_human_review_decisions
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
        "RELATION_APPLY_PREFLIGHT_BLOCKED",
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
    echo "No se modificó el canon."
    return 1
}

tdc_relations_apply() {
    local preflight readiness authorization_present reviewer confirmation authorization_id apply_result
    if ! preflight="$(python3 src/python_scripts/current_relational_apply.py preflight --local-root "$CANON_DIR")"; then
        printf '%s\n' "$preflight"
        echo "RELATION_APPLY_PREFLIGHT_BLOCKED"
        return 1
    fi
    printf '%s\n' "$preflight"
    readiness="$(printf '%s' "$preflight" | python3 -c 'import json,sys; print(json.load(sys.stdin)["readiness_id"])')"
    authorization_present="$(printf '%s' "$preflight" | python3 -c 'import json,sys; print(str(json.load(sys.stdin)["authorization_present"]).lower())')"
    if [[ "$authorization_present" != "true" ]]; then
        printf 'Identidad del autorizador: '
        read -r reviewer || reviewer=""
        printf 'Escriba exactamente AUTHORIZE CURRENT RELATIONAL APPLY %s: ' "$readiness"
        read -r confirmation || confirmation=""
        if ! python3 src/python_scripts/current_relational_apply.py authorize \
            --local-root "$CANON_DIR" --reviewer "$reviewer" --confirmation "$confirmation"; then
            echo "CURRENT_RELATIONAL_APPLY_AUTHORIZATION_CANCELLED"
            echo "No se modificó el canon."
            return 1
        fi
        echo "CURRENT_RELATIONAL_APPLY_AUTHORIZED"
        echo "Apply no ejecutado. Vuelva a seleccionar la opción 6 para ejecutar."
        return 0
    fi
    authorization_id="$(printf '%s' "$preflight" | python3 -c 'import json,sys; print(json.load(sys.stdin)["authorization"]["authorization_id"])')"
    printf 'Escriba exactamente CONFIRM APPLY CURRENT RELATIONS %s: ' "$authorization_id"
    read -r confirmation || confirmation=""
    if [[ "$confirmation" != "CONFIRM APPLY CURRENT RELATIONS $authorization_id" ]]; then
        echo "CURRENT_RELATIONAL_APPLY_CANCELLED"
        echo "No se modificó el canon."
        return 1
    fi
    if ! apply_result="$(python3 src/python_scripts/current_relational_apply.py apply \
        --local-root "$CANON_DIR" --authorization-id "$authorization_id" --confirmation "$confirmation")"; then
        printf '%s\n' "$apply_result"
        echo "CURRENT_RELATIONAL_APPLY_BLOCKED"
        return 1
    fi
    printf '%s\n' "$apply_result"
    echo "CURRENT_RELATIONAL_APPLY_COMPLETED"
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

tdc_relations_prepare_current_generation() {
    local status preflight result
    echo "Estado current antes de preparar:"
    if ! status="$(python3 src/python_scripts/prepare_current_relational_generation.py \
        --status --local-root "$CANON_DIR")"; then
        printf '%s\n' "$status"
    else
        printf '%s\n' "$status"
    fi
    echo "Preflight de recomposición current:"
    if ! preflight="$(python3 src/python_scripts/prepare_current_relational_generation.py \
        --dry-run --local-root "$CANON_DIR" --compact)"; then
        printf '%s\n' "$preflight"
        echo "CURRENT_RECOMPOSITION_PREFLIGHT_BLOCKED"
        return 0
    fi
    printf '%s\n' "$preflight"
    echo "Ejecutando recomposición current en staging:"
    if ! result="$(python3 src/python_scripts/prepare_current_relational_generation.py \
        --execute --local-root "$CANON_DIR" --compact)"; then
        printf '%s\n' "$result"
        echo "CURRENT_RECOMPOSITION_BLOCKED"
        return 0
    fi
    printf '%s\n' "$result"
}

tdc_relations_policy_preview() {
    python3 src/python_scripts/governed_relation_admission_policy.py \
        --local-root "$CANON_DIR" --compact
}

tdc_relations_policy_detail() {
    local policy_id
    printf "policy_id (ver el resumen compacto para la lista exacta): "
    read -r policy_id || policy_id=""
    if [[ -z "$policy_id" ]]; then
        echo "policy_id vacío; cancelado."
        return 0
    fi
    python3 src/python_scripts/governed_relation_admission_policy.py \
        --local-root "$CANON_DIR" --policy "$policy_id"
}

tdc_relations_policy_exceptions() {
    python3 src/python_scripts/governed_relation_admission_policy.py \
        --local-root "$CANON_DIR" --exceptions
}

tdc_relations_policy_authorize() {
    local policy_id actor confirmation
    cat <<'EOF'
Autorizar política para lote CURRENT
Esto NO aprueba ninguna relación. Solo registra que un humano autorizó esta
política, exactamente para el conjunto elegible y los hashes CURRENT vigentes
en este momento. Cualquier cambio posterior de Canon, del lote de candidatas,
de la reconciliación o de la propia política invalida esta autorización.
No ejecuta admisión, no ejecuta Apply, no modifica Canon.
EOF
    printf "policy_id a autorizar (ver el resumen compacto): "
    read -r policy_id || policy_id=""
    if [[ -z "$policy_id" ]]; then
        echo "policy_id vacío; cancelado."
        return 0
    fi
    python3 src/python_scripts/governed_relation_admission_policy.py \
        --local-root "$CANON_DIR" --policy "$policy_id"
    printf "Identidad del humano que autoriza: "
    read -r actor || actor=""
    printf "Escriba exactamente la frase de confirmación mostrada arriba: "
    read -r confirmation || confirmation=""
    python3 src/python_scripts/governed_relation_admission_policy.py \
        --local-root "$CANON_DIR" \
        --authorize "$policy_id" --actor "$actor" --confirmation "$confirmation"
}

tdc_relations_policy_materialize() {
    local policy_id actor
    cat <<'EOF'
Materializar decisiones de políticas autorizadas
Esto SI escribe decisiones (human_review_decisions.jsonl), una por cada
candidata del conjunto autorizado, con decision_mode=policy_derived y
provenance explícita (no se etiquetan como revisión humana individual).
Antes de escribir, se recalcula el conjunto elegible y se compara byte a
byte contra la autorización: canon_hash, candidate_batch_hash,
reconciliation_hash, policy_hash y el propio conjunto elegible. Cualquier
diferencia bloquea la operación sin escribir nada.
No modifica Canon. No ejecuta admisión ni Apply.
EOF
    printf "policy_id a materializar (debe tener una autorización vigente y no consumida): "
    read -r policy_id || policy_id=""
    if [[ -z "$policy_id" ]]; then
        echo "policy_id vacío; cancelado."
        return 0
    fi
    printf "Identidad del humano que ejecuta la materialización: "
    read -r actor || actor=""
    python3 src/python_scripts/governed_relation_admission_policy.py \
        --local-root "$CANON_DIR" \
        --materialize "$policy_id" --actor "$actor"
}

tdc_relations_policy_status() {
    python3 src/python_scripts/governed_relation_admission_policy.py \
        --local-root "$CANON_DIR" --status
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
6) Revisión / admisión / Apply protegido
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
            # S0186 Unit H (operator relational human-lifecycle unification):
            # bridges to the review/admission/Apply menu without leaving this
            # screen -- preparación técnica and revisión/admisión/Apply are
            # separate BACKEND contracts, but the operator should not need to
            # know that to reach one from the other.
            6) tdc_relations_admission_menu ;;
            9) tdc_relations_show_history; tdc_pause ;;
            0|"") return 0 ;;
            *) echo "Opción inválida." ;;
        esac
    done
}

tdc_relations_pending_review_menu() {
    while true; do
        cat <<'EOF'
Revisar relaciones pendientes (S0181; sin apply)
1) Revisión individual
2) Ver decisiones humanas vigentes
3) Previsualizar lotes homogéneos (no escribe)
4) Revisar y confirmar un lote
5) Revisar múltiples lotes homogéneos
0) Volver
EOF
        printf "> "
        local choice
        read -r choice || choice=""
        case "$choice" in
            1) tdc_relations_review; tdc_pause ;;
            2) tdc_relations_show_decisions; tdc_pause ;;
            3) tdc_relations_preview_review_batches; tdc_pause ;;
            4) tdc_relations_review_batches; tdc_pause ;;
            5) tdc_relations_review_multiple_batches; tdc_pause ;;
            0|"") return 0 ;;
            *) echo "Opción inválida." ;;
        esac
    done
}

tdc_relations_policy_menu() {
    while true; do
        cat <<'EOF'
Gobernanza por políticas
1) Resumen de políticas
2) Ver detalle / muestra
3) Ver excepciones
4) Autorizar política CURRENT
5) Materializar decisiones autorizadas
6) Ver autorizaciones / decisiones (estado detallado)
0) Volver
EOF
        printf "> "
        local choice
        read -r choice || choice=""
        case "$choice" in
            1) tdc_relations_policy_preview; tdc_pause ;;
            2) tdc_relations_policy_detail; tdc_pause ;;
            3) tdc_relations_policy_exceptions; tdc_pause ;;
            4) tdc_relations_policy_authorize; tdc_pause ;;
            5) tdc_relations_policy_materialize; tdc_pause ;;
            6) tdc_relations_policy_status; tdc_pause ;;
            0|"") return 0 ;;
            *) echo "Opción inválida." ;;
        esac
    done
}

tdc_relations_repo_lifecycle_authority() {
    python3 src/python_scripts/audit_repo_lifecycle_authority.py \
        --local-root "$CANON_DIR" --compact
}

tdc_relations_reports_menu() {
    while true; do
        cat <<'EOF'
Reportes
1) Listado de archivos (candidatas / auditoría)
2) Auditoría de autoridad de repo_lifecycle_state (solo lectura)
0) Volver
EOF
        printf "> "
        local choice
        read -r choice || choice=""
        case "$choice" in
            1) find "$RELATION_OUT_DIR" "$AUDIT_DIR" -maxdepth 1 -type f -printf '%p\n' | sort; tdc_pause ;;
            2) tdc_relations_repo_lifecycle_authority; tdc_pause ;;
            0|"") return 0 ;;
            *) echo "Opción inválida." ;;
        esac
    done
}

tdc_relations_advanced_menu() {
    while true; do
        cat <<'EOF'
Avanzado / especializado
1) Superseder revisión legacy con respaldo histórico
2) ROLLBACK RELATIONS protegido
0) Volver
EOF
        printf "> "
        local choice
        read -r choice || choice=""
        case "$choice" in
            1) tdc_relations_supersede_legacy_review; tdc_pause ;;
            2) tdc_relations_rollback; tdc_pause ;;
            0|"") return 0 ;;
            *) echo "Opción inválida." ;;
        esac
    done
}

tdc_relations_admission_menu() {
    while true; do
        cat <<'EOF'
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Relaciones canónicas — revisión/admisión
  Canon: PROTEGIDO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1) Estado actual
2) Generar / reconciliar CURRENT
3) Revisar relaciones pendientes
4) Gobernanza por políticas
5) Preparar admisión (dry-run gate)
6) APPLY RELATIONS protegido
7) Reportes
8) Revisar aprobadas con bloqueo técnico
9) Avanzado
0) Volver
EOF
        printf "> "
        local choice
        read -r choice || choice=""
        case "$choice" in
            1) tdc_relations_show_summary; tdc_pause ;;
            2) tdc_relations_prepare_current_generation; tdc_pause ;;
            3) tdc_relations_pending_review_menu ;;
            4) tdc_relations_policy_menu ;;
            5) tdc_relations_dry_run_gate; tdc_pause ;;
            6) tdc_relations_apply; tdc_pause ;;
            7) tdc_relations_reports_menu ;;
            8) tdc_relations_review_technically_invalid; tdc_pause ;;
            9) tdc_relations_advanced_menu ;;
            0|"") return 0 ;;
            *) echo "Opción inválida." ;;
        esac
    done
}

tdc_relations_review_technically_invalid() {
    # S0186 Unit H (final closure blocker): scope exactly CURRENT AND
    # human_review_decision == approved_for_admission AND
    # technically_invalid == true. Preview performs zero decision writes;
    # the final write, if the human explicitly chooses one, reuses the
    # already-governed supersede_individual_decision() primitive.
    python3 src/python_scripts/current_relation_human_review.py \
        --current-dir "$RELATION_OUT_DIR" \
        --canon-root "$CANON_DIR" \
        --gate-report "$AUDIT_DIR/admission_gate_dry_run.json" \
        --review-technically-invalid
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
