"""S0172 operator-menu boundary tests for the authoritative derivation path."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import operator_menu  # noqa: E402
from tdc_menu_registry import resolve_choice  # noqa: E402
from rag_derivation_profile import build_profile  # noqa: E402


def _answers(*values: str):
    iterator = iter(values)
    return lambda _message: next(iterator)


def _fake_result(args: list[str], cwd: Path) -> operator_menu.CommandResult:
    return operator_menu.CommandResult(args=args, cwd=cwd, returncode=0, stdout="ok", stderr="")


def test_option_5_resolves_to_authoritative_derivation_menu() -> None:
    choice = resolve_choice("5")
    assert choice is not None
    assert choice["action"] == "derivatives"
    assert "derive_layers.py" in choice["label"]


def test_derivation_menu_shows_authoritative_builder(monkeypatch, capsys) -> None:
    monkeypatch.setattr(operator_menu, "prompt", _answers("0"))
    operator_menu.option_derivatives(operator_menu.MenuState())
    assert "Productor autoritativo: derive_layers.py" in capsys.readouterr().out


def test_derivation_menu_shows_policy_versions(monkeypatch, capsys) -> None:
    monkeypatch.setattr(operator_menu, "prompt", _answers("0"))
    operator_menu.option_derivatives(operator_menu.MenuState())
    out = capsys.readouterr().out
    assert "Tag policy: tag-sanitation/v1" in out
    assert "Metadata policy: metadata-promotion/v1" in out


def test_derivation_menu_preview_uses_derive_layers(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(operator_menu, "prompt", _answers("2", "0"))
    monkeypatch.setattr(
        operator_menu,
        "run_command",
        lambda args, cwd=REPO_ROOT: (calls.append(args) or _fake_result(args, cwd)),
    )
    operator_menu.option_derivatives(operator_menu.MenuState())
    assert len(calls) == 1
    assert "src/python_scripts/derive_layers.py" in calls[0]
    assert calls[0][calls[0].index("--mode") + 1] == "preview"
    assert "--dry-run" in calls[0]
    assert "--out-dir" in calls[0]


def test_derivation_menu_gate_uses_authoritative_gate(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    preview = tmp_path / "preview"
    (preview / "semantic_text").mkdir(parents=True)
    (preview / "ai").mkdir(parents=True)
    (preview / "microsoft_copilot").mkdir(parents=True)
    monkeypatch.setattr(operator_menu, "RAG_DERIVATION_PREVIEW_ROOT", preview)
    monkeypatch.setattr(operator_menu, "prompt", _answers("3", "0"))
    monkeypatch.setattr(
        operator_menu,
        "run_command",
        lambda args, cwd=REPO_ROOT: (calls.append(args) or _fake_result(args, cwd)),
    )
    operator_menu.option_derivatives(operator_menu.MenuState())
    assert len(calls) == 1
    assert "src/python_scripts/validate_rag_tag_gate.py" in calls[0]
    assert "--enforce-p1-raw" in calls[0]
    assert "--scan-root" in calls[0]


def test_derivation_menu_productive_regeneration_is_blocked_in_s0172(monkeypatch, capsys) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(operator_menu, "prompt", _answers("6", "0"))
    monkeypatch.setattr(
        operator_menu,
        "run_command",
        lambda args, cwd=REPO_ROOT: (calls.append(args) or _fake_result(args, cwd)),
    )
    operator_menu.option_derivatives(operator_menu.MenuState())
    assert not calls
    assert "Regeneración productiva no habilitada en S0172." in capsys.readouterr().out


def test_derivation_menu_does_not_call_legacy_builder_by_default(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(operator_menu, "prompt", _answers("2", "0"))
    monkeypatch.setattr(
        operator_menu,
        "run_command",
        lambda args, cwd=REPO_ROOT: (calls.append(args) or _fake_result(args, cwd)),
    )
    operator_menu.option_derivatives(operator_menu.MenuState())
    joined = " ".join(calls[0])
    assert "build_rag_safe_semantic_preview.py" not in joined
    assert "build_semantic_text.py" not in joined
    assert "build_semantic_text_authority_aware.py" not in joined
    assert "s45_derive_layers.py" not in joined


def test_derivation_menu_handles_missing_preview_without_traceback(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(operator_menu, "RAG_DERIVATION_PREVIEW_ROOT", tmp_path / "missing-preview")
    monkeypatch.setattr(operator_menu, "prompt", _answers("3", "0"))
    operator_menu.option_derivatives(operator_menu.MenuState())
    out = capsys.readouterr().out
    assert "estado: no disponible" in out
    assert "Traceback" not in out


def test_derivation_menu_handles_missing_plan_without_traceback(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(operator_menu, "RAG_DERIVATION_PLAN", tmp_path / "missing-plan.json")
    monkeypatch.setattr(operator_menu, "prompt", _answers("4", "0"))
    operator_menu.option_derivatives(operator_menu.MenuState())
    out = capsys.readouterr().out
    assert "acción sugerida" in out
    assert "Traceback" not in out


def test_derivation_menu_handles_corrupt_profile_without_traceback(monkeypatch, tmp_path: Path, capsys) -> None:
    profile = tmp_path / "corrupt-profile.json"
    profile.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(operator_menu, "RAG_DERIVATION_PROFILE", profile)
    monkeypatch.setattr(operator_menu, "prompt", _answers("0"))
    operator_menu.option_derivatives(operator_menu.MenuState())
    out = capsys.readouterr().out
    assert "Perfil: no disponible" in out
    assert "Preview: no disponible" in out
    assert "Traceback" not in out


def test_derivation_menu_handles_stale_plan_without_traceback(monkeypatch, tmp_path: Path, capsys) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(build_profile()), encoding="utf-8")
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "schema_version": "rag-derivation-plan/v1",
                "status": "validated_preview",
                "derivation_profile_hash": "stale",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(operator_menu, "RAG_DERIVATION_PROFILE", profile)
    monkeypatch.setattr(operator_menu, "RAG_DERIVATION_PLAN", plan)
    monkeypatch.setattr(operator_menu, "prompt", _answers("0"))
    operator_menu.option_derivatives(operator_menu.MenuState())
    out = capsys.readouterr().out
    assert "Plan: stale" in out
    assert "Traceback" not in out
