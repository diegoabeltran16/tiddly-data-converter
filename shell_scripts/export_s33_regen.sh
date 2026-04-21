#!/usr/bin/env bash
# export_s33_regen.sh — Regenerate S33 functional tiddlers JSONL from real HTML
#
# Usage:
#   ./shell_scripts/export_s33_regen.sh [<html_input>]
#
# Parameters:
#   html_input  Path to the TiddlyWiki HTML file
#               (default: data/in/tiddly-data-converter (Saved).html)
#
# Output:
#   data/out/local/export/s33-functional-tiddlers.jsonl  — JSONL with 1 tiddler per line
#   data/out/local/export/s33-export-log.jsonl           — per-tiddler filtering/export log
#   data/out/local/export/s33-manifest.json              — metadata + SHA-256 + conteos
#
# Exit codes:
#   0 — export completed
#   1 — error
#
# Contract reference: contratos/m01-s33-single-jsonl-functional-tiddlers-from-real-html-v0.md.json

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export GOCACHE="${GOCACHE:-/tmp/tdc-go-build}"
mkdir -p "${GOCACHE}"

HTML_INPUT="${1:-${REPO_ROOT}/data/in/tiddly-data-converter (Saved).html}"
EXPORT_DIR="${REPO_ROOT}/data/out/local/export"

mkdir -p "${EXPORT_DIR}"

echo "[s33-regen] ============================================"
echo "[s33-regen] S33 — Regenerate functional tiddlers JSONL"
echo "[s33-regen] Corpus: ${HTML_INPUT}"
echo "[s33-regen] Output: ${EXPORT_DIR}"
echo "[s33-regen] ============================================"

cd "${REPO_ROOT}/go/bridge"

go run ./cmd/export_tiddlers \
  --html "${HTML_INPUT}" \
  --out "${EXPORT_DIR}/s33-functional-tiddlers.jsonl" \
  --log "${EXPORT_DIR}/s33-export-log.jsonl" \
  --manifest "${EXPORT_DIR}/s33-manifest.json" \
  --run-id "s33-regen-$(date -u +%Y%m%dT%H%M%SZ)"

echo ""
echo "[s33-regen] ============================================"
echo "[s33-regen] Output files:"
echo "[s33-regen]   ${EXPORT_DIR}/s33-functional-tiddlers.jsonl"
echo "[s33-regen]   ${EXPORT_DIR}/s33-export-log.jsonl"
echo "[s33-regen]   ${EXPORT_DIR}/s33-manifest.json"
echo "[s33-regen] Lines:  $(wc -l < "${EXPORT_DIR}/s33-functional-tiddlers.jsonl")"
echo "[s33-regen] ============================================"
