#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# baseline_verify.sh — Verify committed golden files match regenerated output.
#
# This script regenerates the baseline from frozen inputs and performs a
# strict byte-for-byte comparison against the committed golden files.
# Any difference causes a non-zero exit (regression detected).
#
# Usage:
#   bash scripts/baseline_verify.sh
#
# Exit codes:
#   0 — golden files match regenerated output
#   1 — regression detected (diff found)
#   2 — build or generation error
#
# Ref: S32 — canon-freeze-baseline-oracle-and-first-jsonl-v0
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Paths
INPUT_DIR="${REPO_ROOT}/tests/fixtures/baseline/v1/input"
GOLDEN_DIR="${REPO_ROOT}/tests/golden/baseline/v1"
EXPECTED_SNAPSHOT="${GOLDEN_DIR}/batch_snapshot.json"
EXPECTED_JSONL="${GOLDEN_DIR}/export.jsonl"

# Deterministic parameters (must match manifest.json)
SNAPSHOT_ID="canon-baseline-v1"
AS_OF="2026-04-14T00:00:00Z"

# Temp dir for regenerated outputs
REGEN_DIR="$(mktemp -d)"
trap 'rm -rf "${REGEN_DIR}"' EXIT

REGEN_SNAPSHOT="${REGEN_DIR}/batch_snapshot.json"
REGEN_JSONL="${REGEN_DIR}/export.jsonl"

echo "[baseline_verify] Building accumulate CLI..."
cd "${REPO_ROOT}/go/canon"
go build -o "${REGEN_DIR}/accumulate" ./cmd/accumulate || { echo "[baseline_verify] ERROR: build failed"; exit 2; }

echo "[baseline_verify] Regenerating baseline from frozen inputs..."
"${REGEN_DIR}/accumulate" \
  --input "${INPUT_DIR}" \
  --out "${REGEN_SNAPSHOT}" \
  --export-jsonl "${REGEN_JSONL}" \
  --snapshot-id "${SNAPSHOT_ID}" \
  --as-of "${AS_OF}" || { echo "[baseline_verify] ERROR: generation failed"; exit 2; }

echo "[baseline_verify] Comparing batch_snapshot.json..."
if ! diff -u "${EXPECTED_SNAPSHOT}" "${REGEN_SNAPSHOT}"; then
  echo "[baseline_verify] FAIL: batch_snapshot.json differs from golden"
  exit 1
fi

echo "[baseline_verify] Comparing export.jsonl..."
if ! diff -u "${EXPECTED_JSONL}" "${REGEN_JSONL}"; then
  echo "[baseline_verify] FAIL: export.jsonl differs from golden"
  exit 1
fi

echo "[baseline_verify] Verifying snapshot by replay..."
"${REGEN_DIR}/accumulate" \
  --verify \
  --snapshot "${EXPECTED_SNAPSHOT}" \
  --input "${INPUT_DIR}" || { echo "[baseline_verify] FAIL: replay verification failed"; exit 1; }

echo "[baseline_verify] PASS — all golden files match regenerated output"
