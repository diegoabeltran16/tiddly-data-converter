#!/usr/bin/env python3
"""Declarative local operator menu registry for S0150."""

from __future__ import annotations

from typing import Any


MAIN_MENU_ITEMS: list[dict[str, str]] = [
    {"id": "1", "label": "Preparación / preflight", "action": "preparation"},
    {"id": "2", "label": "Construir o importar canon", "action": "build_or_import_canon"},
    {"id": "3", "label": "Exportador de repositorio", "action": "repository_exporter"},
    {"id": "4", "label": "Sincronizar artefactos al canon", "action": "session_sync"},
    {"id": "5", "label": "Exportar / consultar canon", "action": "export_or_consult_canon"},
    {"id": "6", "label": "Relaciones canónicas", "action": "canonical_relations"},
    {"id": "7", "label": "Reportes / métricas / auditoría", "action": "reports_audit"},
    {"id": "8", "label": "Derivados / RAG", "action": "derivatives"},
    {"id": "9", "label": "Configurar MCP / mirror remoto", "action": "mcp_remote_config"},
    {"id": "10", "label": "Rollback", "action": "rollback"},
    {"id": "11", "label": "Temporales / quiescencia", "action": "tmp_quiescence"},
    {"id": "12", "label": "Avanzado / mantenimiento", "action": "advanced_maintenance"},
]

# S0186 Unit H (final intervention, top-level UX migration): "Revisión /
# admisión gobernada" is retired as an independent top-level entry. Its
# capabilities are relocated, not deleted: relations governance (technical
# preparation + review/admission/Apply) already lives inside "6) Relaciones
# canónicas" (bridged from within tdc.sh's own relations menu); metadata
# técnica, "Estado de compuertas" and session governance now live inside
# "4) Sincronizar artefactos al canon". "Ver reportes de admisión" and
# "Avanzado" were always the same handlers as top-level 7 and 12
# respectively -- no relocation needed, just no longer duplicated here.
COMPATIBILITY_ALIASES: dict[str, dict[str, str]] = {
    "13": {
        "target": "11",
        "action": "tmp_quiescence",
        "message": "La numeración del menú principal fue reorganizada (S0186 Unit H). Abriendo Temporales / quiescencia...",
    },
    "14": {
        "target": "9",
        "action": "mcp_remote_config",
        "message": "La numeración del menú principal fue reorganizada (S0186 Unit H). Abriendo Configurar MCP / mirror remoto...",
    },
    "16": {
        "target": "6",
        "action": "canonical_relations",
        "message": "Preparación relacional y revisión/admisión/Apply viven juntas en Relaciones canónicas.",
    },
    "17": {
        "target": "3",
        "action": "repository_exporter",
        "message": "La numeración del menú principal fue reorganizada (S0186 Unit H). Abriendo Exportador de repositorio...",
    },
    "18": {
        "target": "4",
        "action": "metadata_admission",
        "message": "Metadata técnica ahora vive dentro de Sincronizar artefactos al canon → Metadata técnica.",
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
            "repository_exporter": "3 and alias 17",
            "mcp_remote_config": "9 and alias 14",
            "metadata_admission": "4.2 and alias 18",
            "rollback": "10",
            "derivatives": "8",
            "session_sync": "4.1",
            "tmp_quiescence": "11 and alias 13",
        },
        "authoritative_derivation": {
            "menu_option": "8",
            "capability": "rag_admission",
            "state_engine": "src/python_scripts/rag_admission_state.py",
            "productive_orchestrator": "src/python_scripts/derive_layers.py",
            "preview_mode": "derive_layers.py --mode preview",
            "staging_mode": "derive_layers.py --mode staging --dry-run",
            "historical_governance_compatibility": "src/python_scripts/s0174_governance.py",
            "writer": "src/python_scripts/rag_derivative_writers.py",
            "productive_write_default": False,
        },
        "relational_operation": {
            "preparation_menu": "6 and alias 16",
            "human_review_and_admission_menu": "6 (bridged: tdc.sh relations menu item 6)",
            "state_engine": "src/python_scripts/relation_admission_state.py",
            "audit_menu": "7.2",
            "rollback_status_menu": "10.3",
            "legacy_batches": "advanced_history_only",
            "productive_write_default": False,
        },
    }
