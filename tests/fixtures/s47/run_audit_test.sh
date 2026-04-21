#!/usr/bin/env bash
# run_audit_test.sh — Local validation for audit_normative_projection.py against S47 fixtures
#
# Usage:
#   bash tests/fixtures/s47/run_audit_test.sh
#
# Verifies:
#   1. Help flag works
#   2. Audit mode runs without errors on minimal fixture
#   3. Safe autofix for missing normalized_tags and invalid role_primary
#   4. Output JSON is parseable
#
# Exit code: 0 = all tests passed, 1 = at least one test failed

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
FIXTURES="${REPO_ROOT}/tests/fixtures/s47"
TMP_DIR=$(mktemp -d)
trap "rm -rf ${TMP_DIR}" EXIT

PASS=0
FAIL=0

check() {
    local desc="$1"
    local result="$2"
    if [[ "${result}" == "0" ]]; then
        echo "  ✓ ${desc}"
        PASS=$((PASS + 1))
    else
        echo "  ✗ ${desc}"
        FAIL=$((FAIL + 1))
    fi
}

echo "[s47-test] ===== Audit fixture tests ====="
echo ""

# Test 1: Help flag
echo "[s47-test] Test 1: --help flag"
python3 "${REPO_ROOT}/python_scripts/audit_normative_projection.py" --help > /dev/null 2>&1
check "--help exits 0" "$?"

# Test 2: Audit mode on fixture (no writes)
echo "[s47-test] Test 2: --mode audit on fixture"
python3 "${REPO_ROOT}/python_scripts/audit_normative_projection.py" \
    --mode audit \
    --input-root "${FIXTURES}" \
    --enriched-dir "${TMP_DIR}/enriched" \
    --ai-dir "${TMP_DIR}/ai" \
    --reports-dir "${TMP_DIR}/reports" \
    --audit-dir "${TMP_DIR}/audit" \
    --no-regenerate \
    > "${TMP_DIR}/audit_stdout.txt" 2>&1 || true
check "audit mode completed" "$([[ -f "${TMP_DIR}/audit/compliance_report.json" ]] && echo 0 || echo 1)"
check "compliance_report.json is valid JSON" "$(python3 -c "import json; json.load(open('${TMP_DIR}/audit/compliance_report.json'))" > /dev/null 2>&1 && echo 0 || echo 1)"
check "manifest.json is valid JSON" "$(python3 -c "import json; json.load(open('${TMP_DIR}/audit/manifest.json'))" > /dev/null 2>&1 && echo 0 || echo 1)"
check "proposed_fixes.json is valid JSON" "$(python3 -c "import json; json.load(open('${TMP_DIR}/audit/proposed_fixes.json'))" > /dev/null 2>&1 && echo 0 || echo 1)"

# Test 3: Apply mode on fixture (with safe fixes)
echo "[s47-test] Test 3: --mode apply on fixture"
cp "${FIXTURES}/canon_minimal.jsonl" "${TMP_DIR}/tiddlers_1.jsonl"
python3 "${REPO_ROOT}/python_scripts/audit_normative_projection.py" \
    --mode apply \
    --input-root "${TMP_DIR}" \
    --enriched-dir "${TMP_DIR}/enriched" \
    --ai-dir "${TMP_DIR}/ai" \
    --reports-dir "${TMP_DIR}/reports" \
    --audit-dir "${TMP_DIR}/audit_apply" \
    --no-regenerate \
    > "${TMP_DIR}/apply_stdout.txt" 2>&1 || true
check "apply mode completed" "$([[ -f "${TMP_DIR}/audit_apply/applied_safe_fixes.json" ]] && echo 0 || echo 1)"
check "applied_safe_fixes.json is valid JSON" "$(python3 -c "import json; json.load(open('${TMP_DIR}/audit_apply/applied_safe_fixes.json'))" > /dev/null 2>&1 && echo 0 || echo 1)"
check "pre_post_diff.json is valid JSON" "$(python3 -c "import json; json.load(open('${TMP_DIR}/audit_apply/pre_post_diff.json'))" > /dev/null 2>&1 && echo 0 || echo 1)"

# Test 4: Verify safe fixes were applied
echo "[s47-test] Test 4: Safe fix correctness"
FIXES_APPLIED=$(python3 -c "import json; d=json.load(open('${TMP_DIR}/audit_apply/applied_safe_fixes.json')); print(d['total_applied'])")
check "At least 1 safe fix applied (missing normalized_tags or invalid role)" "$([[ ${FIXES_APPLIED} -ge 1 ]] && echo 0 || echo 1)"

# Test 5: Rewritten shard is valid JSONL
echo "[s47-test] Test 5: Rewritten shard is valid JSONL"
check "tiddlers_1.jsonl still valid JSONL after fix" "$(python3 -c "
import json
count = 0
with open('${TMP_DIR}/tiddlers_1.jsonl') as f:
    for line in f:
        line = line.strip()
        if line:
            json.loads(line)
            count += 1
assert count >= 3, f'Expected >= 3 lines, got {count}'
" > /dev/null 2>&1 && echo 0 || echo 1)"

# Test 6: warnings.jsonl lines are parseable
echo "[s47-test] Test 6: warnings.jsonl parseable"
check "warnings.jsonl lines are valid JSON" "$(python3 -c "
import json
with open('${TMP_DIR}/audit_apply/warnings.jsonl') as f:
    for line in f:
        line = line.strip()
        if line:
            json.loads(line)
" > /dev/null 2>&1 && echo 0 || echo 1)"

echo ""
echo "[s47-test] ===== Results: ${PASS} passed, ${FAIL} failed ====="

if [[ "${FAIL}" -gt 0 ]]; then
    exit 1
fi
exit 0
