#!/usr/bin/env python3
"""Declarative local operator menu registry for S0150."""

from __future__ import annotations

from typing import Any


MAIN_MENU_ITEMS: list[dict[str, str]] = [
    {"id": "1", "label": "Preparación / preflight", "action": "preparation"},
    {"id": "2", "label": "Construir o importar canon", "action": "build_or_import_canon"},
    {"id": "3", "label": "Exportar / consultar canon", "action": "export_or_consult_canon"},
    {"id": "4", "label": "Sincronizar sesiones al canon", "action": "session_sync"},
    {"id": "5", "label": "Generar derivados", "action": "derivatives"},
    {"id": "6", "label": "Revisión / admisión gobernada", "action": "governed_admission"},
    {"id": "7", "label": "Reportes / métricas / auditoría", "action": "reports_audit"},
    {"id": "8", "label": "Rollback", "action": "rollback"},
    {"id": "9", "label": "Exportador de repositorio", "action": "repository_exporter"},
    {"id": "10", "label": "Configurar MCP / mirror remoto", "action": "mcp_remote_config"},
    {"id": "11", "label": "Avanzado / mantenimiento", "action": "advanced_maintenance"},
]

COMPATIBILITY_ALIASES: dict[str, dict[str, str]] = {
    "14": {
        "target": "10",
        "action": "mcp_remote_config",
        "message": "Esta opción fue reorganizada. Abriendo Configurar MCP / mirror remoto...",
    },
    "16": {
        "target": "6.2",
        "action": "relation_review",
        "message": "Revisión relacional ahora vive dentro de Revisión / admisión gobernada → Relaciones candidatas.",
    },
    "17": {
        "target": "9",
        "action": "repository_exporter",
        "message": "Esta opción fue reorganizada. Abriendo Exportador de repositorio...",
    },
    "18": {
        "target": "6.1",
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
            "repository_exporter": "9",
            "mcp_remote_config": "10",
            "relation_review": "6.2 and alias 16",
            "metadata_admission": "6.1 and alias 18",
            "rollback": "8",
            "derivatives": "5",
            "session_sync": "4",
        },
    }
