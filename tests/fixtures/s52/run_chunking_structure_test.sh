#!/usr/bin/env bash
# run_chunking_structure_test.sh — Focused S52 regression checks

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

echo "[s52-test] ===== Chunking + structure regression tests ====="
python3 "${REPO_ROOT}/tests/fixtures/s52/test_chunking_structure.py"
