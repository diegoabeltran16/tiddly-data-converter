#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# tdc.sh mcp  → gestor de configuracion MCP / mirror remoto
# tdc.sh      → menu principal del operador
case "${1:-}" in
    mcp)
        python3 python_scripts/mcp_env_manager.py
        ;;
    *)
        python3 python_scripts/operator_menu.py
        ;;
esac
