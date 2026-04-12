#!/usr/bin/env bash
# run_pipeline.sh — Runner mínimo del pipeline Extractor → Doctor → Ingesta → Canon
#
# Uso:
#   ./scripts/run_pipeline.sh [<html_input>] [<out_dir>]
#
# Parámetros:
#   html_input  Ruta al archivo HTML vivo de TiddlyWiki
#               (por defecto: data/tiddly-data-converter (Saved).html)
#   out_dir     Directorio de salida para los artefactos intermedios y finales
#               (por defecto: /tmp/tdc-pipeline-run)
#
# Salida:
#   <out_dir>/raw.tiddlers.json     — artefacto raw del Extractor
#   <out_dir>/ingesta.tiddlers.json — tiddlers pre-canónicos de la Ingesta
#   <out_dir>/canon.entries.json    — entradas canónicas del Bridge
#   <out_dir>/canon.jsonl           — salida canónica mínima JSONL (S16 bootstrap)
#
# Código de salida:
#   0 — pipeline completo (ok o warning en algún componente)
#   1 — argumento inválido
#   2 — fallo bloqueante en el Extractor
#   3 — fallo bloqueante en el Doctor (incluyendo veredicto Error)
#   4 — fallo bloqueante en la Ingesta
#   5 — fallo bloqueante en el Bridge (admisión Canon)
#   6 — fallo bloqueante en la emisión Canon JSONL
#
# Ref: contratos/m01-s12-pipeline-costura.md.json
# Ref: contratos/m01-s14-bridge-ingesta-canon.md.json
# Ref: contratos/m01-s16-canon-jsonl-writer.md.json

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

HTML_INPUT="${1:-${REPO_ROOT}/data/tiddly-data-converter (Saved).html}"
OUT_DIR="${2:-/tmp/tdc-pipeline-run}"
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

# ─── RESUMEN ──────────────────────────────────────────────────────────────────
echo ""
echo "[pipeline] ============================================"
echo "[pipeline] Costura completa ✓"
echo "[pipeline] Tiddlers raw:     $(python3 -c "import json,sys; a=json.load(open('${RAW_JSON}')); print(len(a))" 2>/dev/null || echo "?")"
echo "[pipeline] Tiddlers ingesta: $(python3 -c "import json,sys; a=json.load(open('${INGESTA_JSON}')); print(len(a))" 2>/dev/null || echo "?")"
echo "[pipeline] Canon entries:    $(python3 -c "import json,sys; a=json.load(open('${CANON_JSON}')); print(len(a))" 2>/dev/null || echo "?")"
echo "[pipeline] Canon JSONL:      $(wc -l < "${CANON_JSONL}" 2>/dev/null || echo "?")"
echo "[pipeline] ============================================"
