#!/usr/bin/env bash
# run_canon_proposal_test.sh — Local validation for session proposal JSONL files

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
FIXTURES="${REPO_ROOT}/tests/fixtures/s49"
S40_FIXTURES="${REPO_ROOT}/tests/fixtures/s40"
TMP_DIR=$(mktemp -d)
trap "rm -rf ${TMP_DIR}" EXIT

PASS=0
FAIL=0

check() {
    local desc="$1"
    local result="$2"
    if [[ "${result}" == "0" ]]; then
        echo "  [OK] ${desc}"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] ${desc}"
        FAIL=$((FAIL + 1))
    fi
}

echo "[s49-test] ===== Session proposal fixture tests ====="
echo ""

cp "${S40_FIXTURES}/base_canon.jsonl" "${TMP_DIR}/tiddlers_1.jsonl"

echo "[s49-test] Test 1: create proposal file with a new canon line"
python3 "${REPO_ROOT}/scripts/canon_proposal.py" create \
    --session "m03-s49-mcp-onedrive-canon-proposals-v0" \
    --payload-file "${FIXTURES}/candidate_line.json" \
    --canon-dir "${TMP_DIR}" \
    --output "${TMP_DIR}/session_lines.jsonl" \
    > "${TMP_DIR}/create_new_stdout.txt" 2>&1
check "proposal JSONL file created" "$([[ -f "${TMP_DIR}/session_lines.jsonl" ]] && echo 0 || echo 1)"
check "proposal JSONL has exactly one line" "$([[ $(wc -l < "${TMP_DIR}/session_lines.jsonl") -eq 1 ]] && echo 0 || echo 1)"

echo "[s49-test] Test 2: validate proposal file with a new canon line"
python3 "${REPO_ROOT}/scripts/canon_proposal.py" validate \
    --proposal-file "${TMP_DIR}/session_lines.jsonl" \
    --canon-dir "${TMP_DIR}" \
    > "${TMP_DIR}/validate_new_stdout.txt" 2>&1
check "proposal file validates against fixture canon" "$?"

cat "${TMP_DIR}/session_lines.jsonl" >> "${TMP_DIR}/tiddlers_2.jsonl"

echo "[s49-test] Test 3: create proposal file that includes an existing canon line"
python3 "${REPO_ROOT}/scripts/canon_proposal.py" create \
    --session "m03-s49-mcp-onedrive-canon-proposals-v0" \
    --payload-file "${TMP_DIR}/session_lines.jsonl" \
    --canon-dir "${TMP_DIR}" \
    --allow-existing \
    --output "${TMP_DIR}/session_lines_existing.jsonl" \
    > "${TMP_DIR}/create_replace_stdout.txt" 2>&1
check "existing-line proposal JSONL file created" "$([[ -f "${TMP_DIR}/session_lines_existing.jsonl" ]] && echo 0 || echo 1)"
check "existing-line proposal JSONL has one line" "$([[ $(wc -l < "${TMP_DIR}/session_lines_existing.jsonl") -eq 1 ]] && echo 0 || echo 1)"

echo "[s49-test] Test 4: validate proposal file with allow-existing"
python3 "${REPO_ROOT}/scripts/canon_proposal.py" validate \
    --proposal-file "${TMP_DIR}/session_lines_existing.jsonl" \
    --canon-dir "${TMP_DIR}" \
    --allow-existing \
    > "${TMP_DIR}/validate_replace_stdout.txt" 2>&1
check "existing-line proposal file validates when existing lines are allowed" "$?"

echo ""
echo "[s49-test] ===== Results: ${PASS} passed, ${FAIL} failed ====="

if [[ "${FAIL}" -gt 0 ]]; then
    exit 1
fi
exit 0
