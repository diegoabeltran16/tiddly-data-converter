#!/usr/bin/env bash
# test_pipeline_smoke.sh — Smoke test mínimo del pipeline Extractor → Doctor → Ingesta
#
# Ejecuta el pipeline completo sobre el fixture mínimo controlado
# (tests/fixtures/minimal_tiddlywiki.html) y valida que cada componente
# produce la evidencia mínima esperada.
#
# Uso:
#   ./tests/smoke/test_pipeline_smoke.sh
#
# Código de salida:
#   0 — todos los checks pasaron
#   1 — uno o más checks fallaron
#
# Ref: contratos/m01-s12-pipeline-costura.md.json

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURE_HTML="${REPO_ROOT}/tests/fixtures/minimal_tiddlywiki.html"
OUT_DIR="$(mktemp -d)"
RAW_JSON="${OUT_DIR}/raw.tiddlers.json"
INGESTA_JSON="${OUT_DIR}/ingesta.tiddlers.json"

PASS=0
FAIL=0

check() {
    local label="$1"
    local result="$2"
    if [ "${result}" = "true" ]; then
        echo "  ✓ ${label}"
        PASS=$((PASS + 1))
    else
        echo "  ✗ ${label}"
        FAIL=$((FAIL + 1))
    fi
}

echo ""
echo "=== Smoke test: pipeline Extractor → Doctor → Ingesta ==="
echo "    Fixture: ${FIXTURE_HTML}"
echo "    Salida:  ${OUT_DIR}"
echo ""

# ─── Paso 1: Extractor ────────────────────────────────────────────────────────
echo "--- Paso 1: Extractor ---"
EXTRACT_LOG="${OUT_DIR}/extract.log"
cargo run \
    --quiet \
    --manifest-path "${REPO_ROOT}/rust/extractor/Cargo.toml" \
    --bin extract \
    -- "${FIXTURE_HTML}" "${RAW_JSON}" \
    2> "${EXTRACT_LOG}" \
    || { echo "FALLO: Extractor terminó con código de error"; cat "${EXTRACT_LOG}"; exit 1; }

cat "${EXTRACT_LOG}"

check "raw.tiddlers.json existe" "$([ -f "${RAW_JSON}" ] && echo true || echo false)"
RAW_COUNT=$(python3 -c "import json; a=json.load(open('${RAW_JSON}')); print(len(a))" 2>/dev/null || echo "0")
check "raw.tiddlers.json contiene tiddlers (got ${RAW_COUNT})" "$([ "${RAW_COUNT}" -gt 0 ] && echo true || echo false)"
check "extractor log menciona status=ok" "$(grep -q 'status=ok' "${EXTRACT_LOG}" && echo true || echo false)"

# ─── Paso 2: Doctor ───────────────────────────────────────────────────────────
echo ""
echo "--- Paso 2: Doctor ---"
AUDIT_LOG="${OUT_DIR}/audit.log"
DOCTOR_EXIT=0
cargo run \
    --quiet \
    --manifest-path "${REPO_ROOT}/rust/doctor/Cargo.toml" \
    --bin audit \
    -- "${RAW_JSON}" \
    2> "${AUDIT_LOG}" \
    || DOCTOR_EXIT=$?

cat "${AUDIT_LOG}"

check "Doctor terminó sin fallo bloqueante (exit=${DOCTOR_EXIT})" "$([ "${DOCTOR_EXIT}" -ne 2 ] && echo true || echo false)"
check "Doctor veredicto no es error" "$([ "${DOCTOR_EXIT}" -ne 10 ] && echo true || echo false)"
check "doctor log menciona veredicto" "$(grep -qE 'verdict=(ok|warning)' "${AUDIT_LOG}" && echo true || echo false)"

# ─── Paso 3: Ingesta ──────────────────────────────────────────────────────────
echo ""
echo "--- Paso 3: Ingesta ---"
INGEST_LOG="${OUT_DIR}/ingest.log"
cd "${REPO_ROOT}/go/ingesta"
go run ./cmd/ingest "${RAW_JSON}" > "${INGESTA_JSON}" 2> "${INGEST_LOG}" \
    || { echo "FALLO: Ingesta terminó con código de error"; cat "${INGEST_LOG}"; exit 1; }

cat "${INGEST_LOG}"

check "ingesta.tiddlers.json existe" "$([ -f "${INGESTA_JSON}" ] && echo true || echo false)"
INGESTA_COUNT=$(python3 -c "import json; a=json.load(open('${INGESTA_JSON}')); print(len(a))" 2>/dev/null || echo "0")
check "ingesta.tiddlers.json contiene tiddlers (got ${INGESTA_COUNT})" "$([ "${INGESTA_COUNT}" -gt 0 ] && echo true || echo false)"
check "ingesta log menciona verdict=ok o verdict=warning" "$(grep -qE 'verdict=(ok|warning)' "${INGEST_LOG}" && echo true || echo false)"
check "conteo raw == conteo ingesta (${RAW_COUNT} == ${INGESTA_COUNT})" "$([ "${RAW_COUNT}" -eq "${INGESTA_COUNT}" ] && echo true || echo false)"

# ─── Resumen ──────────────────────────────────────────────────────────────────
echo ""
echo "=== Resumen smoke test ==="
echo "    Extractor tiddlers raw: ${RAW_COUNT}"
echo "    Ingesta tiddlers:       ${INGESTA_COUNT}"
echo "    Checks pasados: ${PASS}"
echo "    Checks fallidos: ${FAIL}"
echo ""

rm -rf "${OUT_DIR}"

if [ "${FAIL}" -gt 0 ]; then
    echo "SMOKE TEST FALLIDO: ${FAIL} check(s) no pasaron"
    exit 1
fi
echo "SMOKE TEST OK: todos los checks pasaron"
