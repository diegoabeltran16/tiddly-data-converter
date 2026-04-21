#!/usr/bin/env bash
# run_semantic_microchunk_test.sh — Focused S54 regression checks

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

echo "[s54-test] ===== Semantic + microchunk regression tests ====="
python3 "${REPO_ROOT}/tests/fixtures/s54/test_semantic_microchunk.py"
