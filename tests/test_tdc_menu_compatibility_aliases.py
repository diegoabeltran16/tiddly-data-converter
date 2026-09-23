"""S0150 tests for historical menu alias compatibility."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import operator_menu  # noqa: E402
import tdc_menu_registry as registry  # noqa: E402


def test_aliases_resolve_to_critical_new_locations() -> None:
    assert registry.resolve_choice("14")["action"] == "mcp_remote_config"
    assert registry.resolve_choice("16")["action"] == "canonical_relations"
    assert registry.resolve_choice("17")["action"] == "repository_exporter"
    assert registry.resolve_choice("18")["action"] == "metadata_admission"


def test_dispatch_alias_16_opens_canonical_relations(monkeypatch, capsys) -> None:
    called: list[str] = []
    monkeypatch.setattr(operator_menu, "option_canonical_relations_menu", lambda: called.append("relation"))

    assert operator_menu.dispatch_main_choice("16", operator_menu.MenuState()) is True

    assert called == ["relation"]
    assert "Relaciones canónicas" in capsys.readouterr().out


def test_dispatch_alias_17_opens_material_inventory(monkeypatch, capsys) -> None:
    # S0187 Unit C: alias 17 still targets action "repository_exporter", but
    # that action now dispatches to the reoriented material-inventory
    # submenu (option_material_inventory), not the retired exporter label.
    called: list[str] = []
    monkeypatch.setattr(operator_menu, "option_material_inventory", lambda: called.append("inventory"))

    assert operator_menu.dispatch_main_choice("17", operator_menu.MenuState()) is True

    assert called == ["inventory"]
    assert "Inventario material / repositorio" in capsys.readouterr().out


def test_dispatch_alias_14_opens_mcp(monkeypatch, capsys) -> None:
    called: list[str] = []
    monkeypatch.setattr(operator_menu, "option_mcp_manager", lambda: called.append("mcp"))

    assert operator_menu.dispatch_main_choice("14", operator_menu.MenuState()) is True

    assert called == ["mcp"]
    assert "Configurar MCP / mirror remoto" in capsys.readouterr().out
