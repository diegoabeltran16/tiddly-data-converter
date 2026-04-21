#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# baseline_regen.sh — Regenerate golden baseline files from frozen inputs.
#
# This script rebuilds the baseline oracle outputs deterministically.
# The generated files should be reviewed by a human before committing.
#
# Usage:
#   bash scripts/baseline_regen.sh
#
# Prerequisites:
#   - Go 1.24+ installed
#   - Run from the repository root
#
# Ref: S32 — canon-freeze-baseline-oracle-and-first-jsonl-v0
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export GOCACHE="${GOCACHE:-/tmp/tdc-go-build}"
mkdir -p "${GOCACHE}"

# Paths defined in manifest.json
INPUT_DIR="${REPO_ROOT}/tests/fixtures/baseline/v1/input"
GOLDEN_DIR="${REPO_ROOT}/tests/golden/baseline/v1"
SNAPSHOT_OUT="${GOLDEN_DIR}/batch_snapshot.json"
JSONL_OUT="${GOLDEN_DIR}/export.jsonl"

# Deterministic parameters (must match manifest.json)
SNAPSHOT_ID="canon-baseline-v1"
AS_OF="2026-04-14T00:00:00Z"

echo "[baseline_regen] Building accumulate CLI..."
cd "${REPO_ROOT}/go/canon"
go build -o "${REPO_ROOT}/go/canon/accumulate" ./cmd/accumulate

echo "[baseline_regen] Generating golden baseline from ${INPUT_DIR}..."
mkdir -p "${GOLDEN_DIR}"

"${REPO_ROOT}/go/canon/accumulate" \
  --input "${INPUT_DIR}" \
  --out "${SNAPSHOT_OUT}" \
  --export-jsonl "${JSONL_OUT}" \
  --snapshot-id "${SNAPSHOT_ID}" \
  --as-of "${AS_OF}" \
  --verify

echo "[baseline_regen] Golden files regenerated:"
echo "  snapshot: ${SNAPSHOT_OUT}"
echo "  jsonl:    ${JSONL_OUT}"
echo ""
echo "[baseline_regen] Review the diff before committing:"
echo "  git diff tests/golden/baseline/v1/"

# Cleanup build artifact
rm -f "${REPO_ROOT}/go/canon/accumulate"
