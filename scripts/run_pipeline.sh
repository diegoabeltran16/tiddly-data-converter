#!/usr/bin/env bash
# run_pipeline.sh — Runner mínimo del pipeline Extractor → Doctor → Ingesta → Canon
#
# Uso:
#   ./scripts/run_pipeline.sh [<html_input>] [<out_dir>] [--audit] [--audit-apply]
#
# Parámetros:
#   html_input    Ruta al archivo HTML vivo de TiddlyWiki
#                 (por defecto: data/in/tiddly-data-converter (Saved).html)
#   out_dir       Directorio de salida para los artefactos intermedios y finales
#                 (por defecto: data/out/local/pipeline)
#   --audit       Ejecutar auditoría normativa después del pipeline (modo inspect-only)
#   --audit-apply Ejecutar auditoría normativa con aplicación de safe fixes y regeneración
#
# Salida:
#   <out_dir>/raw.tiddlers.json     — artefacto raw del Extractor
#   <out_dir>/ingesta.tiddlers.json — tiddlers pre-canónicos de la Ingesta
#   <out_dir>/canon.entries.json    — entradas canónicas del Bridge
#   <out_dir>/canon.jsonl           — salida canónica mínima JSONL (S16 bootstrap)
#
# Con --audit o --audit-apply:
#   data/out/local/audit/manifest.json         — manifest de ejecución del auditor
#   data/out/local/audit/compliance_report.json
#   data/out/local/audit/compliance_summary.md
#   data/out/local/audit/warnings.jsonl
#   data/out/local/audit/manual_review_queue.jsonl
#   data/out/local/audit/proposed_fixes.json
#   data/out/local/audit/applied_safe_fixes.json
#   data/out/local/audit/pre_post_diff.json
#   data/out/local/audit/audit_log.jsonl
#
# Nota:
#   La auditoría opera sobre el canon local gobernado en data/out/local/.
#   El pipeline bootstrap también escribe por defecto dentro de data/out/local/.
#
# Código de salida:
#   0 — pipeline completo (ok o warning en algún componente)
#   1 — argumento inválido
#   2 — fallo bloqueante en el Extractor
#   3 — fallo bloqueante en el Doctor (incluyendo veredicto Error)
#   4 — fallo bloqueante en la Ingesta
#   5 — fallo bloqueante en el Bridge (admisión Canon)
#   6 — fallo bloqueante en la emisión Canon JSONL
#   7 — fallo bloqueante en la auditoría normativa
#
# Ref: contratos/m01-s12-pipeline-costura.md.json
# Ref: contratos/m01-s14-bridge-ingesta-canon.md.json
# Ref: contratos/m01-s16-canon-jsonl-writer.md.json
# Ref: contratos/m03-s47-normative-self-audit-and-projection-refinement-v0.md.json

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export GOCACHE="${GOCACHE:-/tmp/tdc-go-build}"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-/tmp/tdc-cargo-target}"
mkdir -p "${GOCACHE}" "${CARGO_TARGET_DIR}"

# Parse flags
AUDIT_MODE=""
POSITIONAL=()
for arg in "$@"; do
    case "${arg}" in
        --audit)        AUDIT_MODE="audit" ;;
        --audit-apply)  AUDIT_MODE="apply" ;;
        *)              POSITIONAL+=("${arg}") ;;
    esac
done

HTML_INPUT="${POSITIONAL[0]:-${REPO_ROOT}/data/in/tiddly-data-converter (Saved).html}"
OUT_DIR="${POSITIONAL[1]:-${REPO_ROOT}/data/out/local/pipeline}"
LOCAL_CANON_ROOT="${REPO_ROOT}/data/out/local"
RAW_JSON="${OUT_DIR}/raw.tiddlers.json"
INGESTA_JSON="${OUT_DIR}/ingesta.tiddlers.json"
CANON_JSON="${OUT_DIR}/canon.entries.json"
CANON_JSONL="${OUT_DIR}/canon.jsonl"

mkdir -p "${OUT_DIR}"

echo "[pipeline] ============================================"
echo "[pipeline] Sesión: m01-s12-pipeline-costura"
echo "[pipeline] Corpus: ${HTML_INPUT}"
echo "[pipeline] Salida: ${OUT_DIR}"
echo "[pipeline] ============================================"

# ─── PASO 1: Extractor ────────────────────────────────────────────────────────
echo ""
echo "[pipeline] === Paso 1 · Extractor ==="
cargo run \
    --quiet \
    --manifest-path "${REPO_ROOT}/rust/extractor/Cargo.toml" \
    --bin extract \
    -- "${HTML_INPUT}" "${RAW_JSON}" \
    || { echo "[pipeline] BLOQUEADO: Extractor falló (exit $?)"; exit 2; }
echo "[pipeline] Extractor completado → ${RAW_JSON}"

# ─── PASO 2: Doctor ───────────────────────────────────────────────────────────
echo ""
echo "[pipeline] === Paso 2 · Doctor ==="
cargo run \
    --quiet \
    --manifest-path "${REPO_ROOT}/rust/doctor/Cargo.toml" \
    --bin audit \
    -- "${RAW_JSON}" \
    || {
        EC=$?
        if [ "${EC}" -eq 10 ]; then
            echo "[pipeline] BLOQUEADO: Doctor emitió veredicto Error — pipeline detenido"
        else
            echo "[pipeline] BLOQUEADO: Doctor falló (exit ${EC})"
        fi
        exit 3
    }
echo "[pipeline] Doctor completado"

# ─── PASO 3: Ingesta ──────────────────────────────────────────────────────────
echo ""
echo "[pipeline] === Paso 3 · Ingesta ==="
cd "${REPO_ROOT}/go/ingesta"
go run ./cmd/ingest "${RAW_JSON}" > "${INGESTA_JSON}" \
    || { echo "[pipeline] BLOQUEADO: Ingesta falló (exit $?)"; exit 4; }
echo "[pipeline] Ingesta completada → ${INGESTA_JSON}"


# ─── PASO 4: Bridge → Canon ─────────────────────────────────────────────────────────────
echo ""
echo "[pipeline] === Paso 4 · Bridge → Canon ==="
cd "${REPO_ROOT}/go/bridge"
go run ./cmd/admit "${INGESTA_JSON}" > "${CANON_JSON}" \
    || { echo "[pipeline] BLOQUEADO: Bridge falló (exit $?)"; exit 5; }
echo "[pipeline] Bridge completado → ${CANON_JSON}"

# ─── PASO 5: Canon JSONL ──────────────────────────────────────────────────────
echo ""
echo "[pipeline] === Paso 5 · Canon JSONL (emisión mínima S16) ==="
cd "${REPO_ROOT}/go/canon"
go run ./cmd/emit "${CANON_JSON}" "${CANON_JSONL}" \
    || { echo "[pipeline] BLOQUEADO: Canon JSONL emisión falló (exit $?)"; exit 6; }
echo "[pipeline] Canon JSONL completado → ${CANON_JSONL}"

# ─── PASO 6 (opcional): Auditoría normativa ───────────────────────────────────
if [[ -n "${AUDIT_MODE}" ]]; then
    echo ""
    echo "[pipeline] === Paso 6 · Auditoría normativa (modo: ${AUDIT_MODE}) ==="
    cd "${REPO_ROOT}"
    python3 "${REPO_ROOT}/scripts/audit_normative_projection.py" \
        --mode "${AUDIT_MODE}" \
        --input-root "${LOCAL_CANON_ROOT}" \
        --docs-root "${REPO_ROOT}/docs" \
        || { echo "[pipeline] BLOQUEADO: Auditoría normativa falló (exit $?)"; exit 7; }
    echo "[pipeline] Auditoría normativa completada → ${LOCAL_CANON_ROOT}/audit/"
fi

# ─── RESUMEN ──────────────────────────────────────────────────────────────────
echo ""
echo "[pipeline] ============================================"
echo "[pipeline] Costura completa ✓"
echo "[pipeline] Tiddlers raw:     $(python3 -c "import json,sys; a=json.load(open('${RAW_JSON}')); print(len(a))" 2>/dev/null || echo "?")"
echo "[pipeline] Tiddlers ingesta: $(python3 -c "import json,sys; a=json.load(open('${INGESTA_JSON}')); print(len(a))" 2>/dev/null || echo "?")"
echo "[pipeline] Canon entries:    $(python3 -c "import json,sys; a=json.load(open('${CANON_JSON}')); print(len(a))" 2>/dev/null || echo "?")"
echo "[pipeline] Canon JSONL:      $(wc -l < "${CANON_JSONL}" 2>/dev/null || echo "?")"
echo "[pipeline] ============================================"
