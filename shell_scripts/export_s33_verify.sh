#!/usr/bin/env bash
# export_s33_verify.sh — Verify the S33 functional tiddlers JSONL
#
# Usage:
#   ./shell_scripts/export_s33_verify.sh
#
# Checks:
#   1. data/out/local/export/s33-functional-tiddlers.jsonl exists
#   2. Every line is valid JSON (parseable)
#   3. Every line has required schema v0 fields (schema_version, key, title)
#   4. No duplicate keys
#   5. Line count matches manifest exported count
#   6. SHA-256 matches manifest
#
# Exit codes:
#   0 — all checks pass
#   1 — verification failure
#
# Contract reference: contratos/m01-s33-single-jsonl-functional-tiddlers-from-real-html-v0.md.json

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

JSONL="${REPO_ROOT}/data/out/local/export/s33-functional-tiddlers.jsonl"
MANIFEST="${REPO_ROOT}/data/out/local/export/s33-manifest.json"
FAILURES=0

echo "[s33-verify] ============================================"
echo "[s33-verify] S33 — Verify functional tiddlers JSONL"
echo "[s33-verify] ============================================"

# Check 1: File exists
if [ ! -f "${JSONL}" ]; then
  echo "[s33-verify] FAIL: ${JSONL} does not exist"
  exit 1
fi
echo "[s33-verify] ✓ JSONL file exists"

# Check 2: Every line is valid JSON
LINE_COUNT=$(wc -l < "${JSONL}")
INVALID=$(python3 -c "
import json, sys
count = 0
with open('${JSONL}') as f:
    for i, line in enumerate(f, 1):
        line = line.strip()
        if not line:
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as e:
            print(f'  Line {i}: {e}', file=sys.stderr)
            count += 1
print(count)
")
if [ "${INVALID}" -ne 0 ]; then
  echo "[s33-verify] FAIL: ${INVALID} lines are not valid JSON"
  FAILURES=$((FAILURES + 1))
else
  echo "[s33-verify] ✓ All ${LINE_COUNT} lines are valid JSON"
fi

# Check 3: Required fields (schema_version, key, title)
MISSING_FIELDS=$(python3 -c "
import json, sys
count = 0
with open('${JSONL}') as f:
    for i, line in enumerate(f, 1):
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        for field in ['schema_version', 'key', 'title']:
            if field not in obj or not obj[field]:
                print(f'  Line {i}: missing or empty {field}', file=sys.stderr)
                count += 1
print(count)
")
if [ "${MISSING_FIELDS}" -ne 0 ]; then
  echo "[s33-verify] FAIL: ${MISSING_FIELDS} missing required fields"
  FAILURES=$((FAILURES + 1))
else
  echo "[s33-verify] ✓ All lines have required schema v0 fields"
fi

# Check 4: No duplicate keys
DUPLICATES=$(python3 -c "
import json
keys = []
with open('${JSONL}') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        keys.append(obj.get('key', ''))
dups = len(keys) - len(set(keys))
print(dups)
")
if [ "${DUPLICATES}" -ne 0 ]; then
  echo "[s33-verify] FAIL: ${DUPLICATES} duplicate keys found"
  FAILURES=$((FAILURES + 1))
else
  echo "[s33-verify] ✓ No duplicate keys"
fi

# Check 5: Line count matches manifest
if [ -f "${MANIFEST}" ]; then
  MANIFEST_COUNT=$(python3 -c "import json; m=json.load(open('${MANIFEST}')); print(m.get('exported_count', -1))")
  if [ "${LINE_COUNT}" -ne "${MANIFEST_COUNT}" ]; then
    echo "[s33-verify] FAIL: line count (${LINE_COUNT}) != manifest exported_count (${MANIFEST_COUNT})"
    FAILURES=$((FAILURES + 1))
  else
    echo "[s33-verify] ✓ Line count (${LINE_COUNT}) matches manifest"
  fi

  # Check 6: SHA-256 matches manifest
  MANIFEST_SHA=$(python3 -c "import json; m=json.load(open('${MANIFEST}')); print(m.get('sha256', ''))")
  ACTUAL_SHA="sha256:$(sha256sum "${JSONL}" | cut -d' ' -f1)"
  if [ "${ACTUAL_SHA}" != "${MANIFEST_SHA}" ]; then
    echo "[s33-verify] FAIL: SHA-256 mismatch"
    echo "[s33-verify]   manifest: ${MANIFEST_SHA}"
    echo "[s33-verify]   actual:   ${ACTUAL_SHA}"
    FAILURES=$((FAILURES + 1))
  else
    echo "[s33-verify] ✓ SHA-256 matches manifest"
  fi
else
  echo "[s33-verify] WARN: manifest not found, skipping checks 5-6"
fi

echo ""
if [ "${FAILURES}" -ne 0 ]; then
  echo "[s33-verify] FAILED: ${FAILURES} check(s) failed"
  exit 1
fi

echo "[s33-verify] ============================================"
echo "[s33-verify] All checks passed ✓"
echo "[s33-verify] Lines: ${LINE_COUNT}"
echo "[s33-verify] ============================================"
