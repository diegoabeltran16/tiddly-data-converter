#!/usr/bin/env bash
# test_pipeline_smoke.sh — Smoke test mínimo del pipeline Extractor → Doctor → Ingesta → Canon
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
# Ref: contratos/m01-s14-bridge-ingesta-canon.md.json
# Ref: contratos/m01-s16-canon-jsonl-writer.md.json

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURE_HTML="${REPO_ROOT}/tests/fixtures/minimal_tiddlywiki.html"
OUT_DIR="$(mktemp -d)"
RAW_JSON="${OUT_DIR}/raw.tiddlers.json"
INGESTA_JSON="${OUT_DIR}/ingesta.tiddlers.json"
CANON_JSON="${OUT_DIR}/canon.entries.json"
CANON_JSONL="${OUT_DIR}/canon.jsonl"

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
echo "=== Smoke test: pipeline Extractor → Doctor → Ingesta → Canon → JSONL ==="
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

# ─── Paso 4: Bridge → Canon ────────────────────────────────────────────────────────────
echo ""
echo "--- Paso 4: Bridge → Canon ---"
BRIDGE_LOG="${OUT_DIR}/bridge.log"
cd "${REPO_ROOT}/go/bridge"
go run ./cmd/admit "${INGESTA_JSON}" > "${CANON_JSON}" 2> "${BRIDGE_LOG}" \
    || { echo "FALLO: Bridge terminó con código de error"; cat "${BRIDGE_LOG}"; exit 1; }

cat "${BRIDGE_LOG}"

check "canon.entries.json existe" "$([ -f "${CANON_JSON}" ] && echo true || echo false)"
CANON_COUNT=$(python3 -c "import json; a=json.load(open('${CANON_JSON}')); print(len(a))" 2>/dev/null || echo "0")
check "canon.entries.json contiene entries (got ${CANON_COUNT})" "$([ "${CANON_COUNT}" -gt 0 ] && echo true || echo false)"
check "bridge log menciona input=" "$(grep -q 'input=' "${BRIDGE_LOG}" && echo true || echo false)"
check "conteo ingesta == conteo canon (${INGESTA_COUNT} == ${CANON_COUNT})" "$([ "${INGESTA_COUNT}" -eq "${CANON_COUNT}" ] && echo true || echo false)"

# ─── Paso 5: Canon JSONL ──────────────────────────────────────────────────────
echo ""
echo "--- Paso 5: Canon JSONL (emisión mínima S16) ---"
EMIT_LOG="${OUT_DIR}/emit.log"
cd "${REPO_ROOT}/go/canon"
go run ./cmd/emit "${CANON_JSON}" "${CANON_JSONL}" 2> "${EMIT_LOG}" \
    || { echo "FALLO: Canon JSONL emisión terminó con código de error"; cat "${EMIT_LOG}"; exit 1; }

cat "${EMIT_LOG}"

check "canon.jsonl existe" "$([ -f "${CANON_JSONL}" ] && echo true || echo false)"
JSONL_LINES=$(wc -l < "${CANON_JSONL}" 2>/dev/null || echo "0")
check "canon.jsonl contiene líneas (got ${JSONL_LINES})" "$([ "${JSONL_LINES}" -gt 0 ] && echo true || echo false)"
check "emit log menciona written=" "$(grep -q 'written=' "${EMIT_LOG}" && echo true || echo false)"
check "conteo canon entries == líneas JSONL (${CANON_COUNT} == ${JSONL_LINES})" "$([ "${CANON_COUNT}" -eq "${JSONL_LINES}" ] && echo true || echo false)"
# Validate each JSONL line is valid JSON with 'schema_version', 'key' and 'title' fields.
JSONL_VALID="true"
while IFS= read -r line; do
    if ! python3 -c "import json,sys; d=json.loads(sys.argv[1]); assert d.get('schema_version')=='v0'; assert 'key' in d; assert 'title' in d" "$line" 2>/dev/null; then
        JSONL_VALID="false"
        break
    fi
done < "${CANON_JSONL}"
check "cada línea JSONL es JSON válido con schema_version=v0, key y title" "${JSONL_VALID}"

# ─── Resumen ──────────────────────────────────────────────────────────────────
echo ""
echo "=== Resumen smoke test ==="
echo "    Extractor tiddlers raw: ${RAW_COUNT}"
echo "    Ingesta tiddlers:       ${INGESTA_COUNT}"
echo "    Canon entries:          ${CANON_COUNT}"
echo "    Canon JSONL líneas:     ${JSONL_LINES}"
echo "    Checks pasados: ${PASS}"
echo "    Checks fallidos: ${FAIL}"
echo ""

rm -rf "${OUT_DIR}"

if [ "${FAIL}" -gt 0 ]; then
    echo "SMOKE TEST FALLIDO: ${FAIL} check(s) no pasaron"
    exit 1
fi
echo "SMOKE TEST OK: todos los checks pasaron"
