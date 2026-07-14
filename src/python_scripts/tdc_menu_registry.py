#!/usr/bin/env python3
"""Declarative local operator menu registry for S0150."""

from __future__ import annotations

from typing import Any


MAIN_MENU_ITEMS: list[dict[str, str]] = [
    {"id": "1", "label": "Preparación / preflight", "action": "preparation"},
    {"id": "2", "label": "Construir o importar canon", "action": "build_or_import_canon"},
    {"id": "3", "label": "Exportar / consultar canon", "action": "export_or_consult_canon"},
    {"id": "4", "label": "Sincronizar sesiones al canon", "action": "session_sync"},
    {"id": "5", "label": "Generar derivados / RAG (derive_layers.py)", "action": "derivatives"},
    {"id": "6", "label": "Relaciones canónicas", "action": "canonical_relations"},
    {"id": "7", "label": "Revisión / admisión gobernada", "action": "governed_admission"},
    {"id": "8", "label": "Reportes / métricas / auditoría", "action": "reports_audit"},
    {"id": "9", "label": "Rollback", "action": "rollback"},
    {"id": "10", "label": "Exportador de repositorio", "action": "repository_exporter"},
    {"id": "11", "label": "Configurar MCP / mirror remoto", "action": "mcp_remote_config"},
    {"id": "12", "label": "Avanzado / mantenimiento", "action": "advanced_maintenance"},
]

COMPATIBILITY_ALIASES: dict[str, dict[str, str]] = {
    "14": {
        "target": "11",
        "action": "mcp_remote_config",
        "message": "Esta opción fue reorganizada. Abriendo Configurar MCP / mirror remoto...",
    },
    "16": {
        "target": "6",
        "action": "canonical_relations",
        "message": "Revisión relacional ahora vive en Relaciones canónicas.",
    },
    "17": {
        "target": "10",
        "action": "repository_exporter",
        "message": "Esta opción fue reorganizada. Abriendo Exportador de repositorio...",
    },
    "18": {
        "target": "7.1",
        "action": "metadata_admission",
        "message": "Metadata técnica ahora vive dentro de Revisión / admisión gobernada → Metadata técnica.",
    },
}


def menu_text() -> str:
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "  Tiddly Data Converter - Operador local",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    lines.extend(f"{item['id']}) {item['label']}" for item in MAIN_MENU_ITEMS)
    lines.append("0) Salir")
    return "\n".join(lines)


def resolve_choice(choice: str) -> dict[str, str] | None:
    for item in MAIN_MENU_ITEMS:
        if item["id"] == choice:
            return dict(item)
    alias = COMPATIBILITY_ALIASES.get(choice)
    if alias:
        return {"id": choice, "label": f"Alias {choice}", **alias}
    return None


def menu_mapping() -> dict[str, Any]:
    return {
        "schema": "tdc-menu-mapping/v1",
        "session": "S0150",
        "main_menu_items": MAIN_MENU_ITEMS,
        "compatibility_aliases": COMPATIBILITY_ALIASES,
        "critical_functions_preserved": {
            "canonical_relations": "6 and alias 16",
            "repository_exporter": "10",
            "mcp_remote_config": "11",
            "metadata_admission": "7.1 and alias 18",
            "rollback": "9",
            "derivatives": "5",
            "session_sync": "4",
        },
        "authoritative_derivation": {
            "menu_option": "5",
            "productive_orchestrator": "src/python_scripts/derive_layers.py",
            "preview_mode": "derive_layers.py --mode preview",
            "staging_mode": "derive_layers.py --mode staging --dry-run",
            "s0174_governance": "src/python_scripts/s0174_governance.py",
            "writer": "src/python_scripts/rag_derivative_writers.py",
            "productive_write_default": False,
        },
    }
