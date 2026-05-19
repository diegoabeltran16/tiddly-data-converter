#!/usr/bin/env bash
# export_s33_verify.sh — Verify the S33 functional tiddlers JSONL
#
# Usage:
#   ./shell_scripts/export_s33_verify.sh
#
# Checks (delegated to python_scripts/verify_export_counts.py):
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

echo "[s33-verify] ============================================"
echo "[s33-verify] S33 — Verify functional tiddlers JSONL"
echo "[s33-verify] ============================================"

# Check 1: File exists
if [ ! -f "${JSONL}" ]; then
  echo "[s33-verify] FAIL: ${JSONL} does not exist"
  exit 1
fi
echo "[s33-verify] ✓ JSONL file exists"

# Delegate checks 2-6 to Python utility
python3 "${REPO_ROOT}/python_scripts/verify_export_counts.py" \
  --jsonl "${JSONL}" \
  --manifest "${MANIFEST}"
