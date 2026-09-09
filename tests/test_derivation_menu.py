"""Operator-menu checks for stable, evidence-derived RAG admission."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import operator_menu  # noqa: E402
from tdc_menu_registry import resolve_choice  # noqa: E402


def _answers(*values: str):
    iterator = iter(values)
    return lambda _message: next(iterator)


def _fake_result(args: list[str], cwd: Path) -> operator_menu.CommandResult:
    return operator_menu.CommandResult(args=args, cwd=cwd, returncode=0, stdout="ok", stderr="")


def test_option_8_resolves_to_authoritative_derivation_menu() -> None:
    # S0186 Unit H (final intervention, top-level UX migration): Derivados /
    # RAG moved from position 5 to 8 (OLD_NAVIGATION_CONTRACT_MIGRATED --
    # the capability is unchanged, only its top-level number moved).
    choice = resolve_choice("8")
    assert choice is not None
    assert choice["action"] == "derivatives"


def test_derivation_menu_uses_stable_capability_names(monkeypatch, capsys) -> None:
    monkeypatch.setattr(operator_menu, "prompt", _answers("0"))
    operator_menu.option_derivatives(operator_menu.MenuState())
    out = capsys.readouterr().out
    assert "Actualizar staging RAG-safe" in out
    assert "Autorizar trial write" in out
    assert "Promover derivados definitivamente" in out
    assert "Generar staging productivo S0173" not in out
    assert "Validar integración y governance S0174" not in out


def test_staging_action_uses_authoritative_producer(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(operator_menu, "prompt", _answers("2", "0"))
    monkeypatch.setattr(operator_menu, "run_command", lambda args, cwd=REPO_ROOT: (calls.append(args) or _fake_result(args, cwd)))
    operator_menu.option_derivatives(operator_menu.MenuState())
    assert len(calls) == 1
    assert "src/python_scripts/derive_layers.py" in calls[0]
    assert calls[0][calls[0].index("--mode") + 1] == "staging"
    assert "--dry-run" in calls[0]


def test_validation_recalculates_equivalence_then_governance(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(operator_menu, "prompt", _answers("3", "0"))
    monkeypatch.setattr(operator_menu, "run_command", lambda args, cwd=REPO_ROOT: (calls.append(args) or _fake_result(args, cwd)))
    operator_menu.option_derivatives(operator_menu.MenuState())
    assert len(calls) == 2
    assert any("validate_productive_equivalence.py" in item for item in calls[0])
    assert calls[1][-1] == "refresh-governance"


def test_trial_authorization_is_guided_and_phrase_bound(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(operator_menu, "prompt", _answers("5", operator_menu.TRIAL_PHRASE, "0"))
    monkeypatch.setattr(operator_menu, "run_command", lambda args, cwd=REPO_ROOT: (calls.append(args) or _fake_result(args, cwd)))
    operator_menu.option_derivatives(operator_menu.MenuState())
    assert calls[0][-3:] == ["authorize-trial", "--phrase", operator_menu.TRIAL_PHRASE]


def test_trial_write_is_delegated_to_governed_capability(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(operator_menu, "prompt", _answers("6", "0"))
    monkeypatch.setattr(operator_menu, "run_command", lambda args, cwd=REPO_ROOT: (calls.append(args) or _fake_result(args, cwd)))
    operator_menu.option_derivatives(operator_menu.MenuState())
    assert calls[0][-1] == "trial-write"


def test_restoration_and_audit_menu_options_have_distinct_read_only_commands(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(operator_menu, "prompt", _answers("9", "12", "0"))
    monkeypatch.setattr(operator_menu, "run_command", lambda args, cwd=REPO_ROOT: (calls.append(args) or _fake_result(args, cwd)))

    operator_menu.option_derivatives(operator_menu.MenuState())

    assert calls[0][-1] == "rollback-status"
    assert calls[1][-1] == "audit"


# --- BLOCKER EN PROMOCION DEFINITIVA: option 11 must fail fast -----------
#
# Option 11 used to chain promote-definitive -> validate-definitive ->
# finalize unconditionally, so a blocked promote-definitive still ran the
# other two commands and produced confusing, unrelated errors. Fixed to
# stop at the first non-zero exit code.


def test_option_11_promote_failure_stops_before_validate_and_finalize(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], cwd: Path = REPO_ROOT) -> operator_menu.CommandResult:
        calls.append(args)
        returncode = 1 if args[-1] == "promote-definitive" else 0
        return operator_menu.CommandResult(args=args, cwd=cwd, returncode=returncode, stdout="", stderr="blocked")

    monkeypatch.setattr(operator_menu, "prompt", _answers("11", "0"))
    monkeypatch.setattr(operator_menu, "run_command", fake_run)

    operator_menu.option_derivatives(operator_menu.MenuState())

    assert [call[-1] for call in calls] == ["promote-definitive"]


def test_option_11_validate_failure_stops_before_finalize(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], cwd: Path = REPO_ROOT) -> operator_menu.CommandResult:
        calls.append(args)
        returncode = 1 if args[-1] == "validate-definitive" else 0
        return operator_menu.CommandResult(args=args, cwd=cwd, returncode=returncode, stdout="", stderr="blocked")

    monkeypatch.setattr(operator_menu, "prompt", _answers("11", "0"))
    monkeypatch.setattr(operator_menu, "run_command", fake_run)

    operator_menu.option_derivatives(operator_menu.MenuState())

    assert [call[-1] for call in calls] == ["promote-definitive", "validate-definitive"]


def test_option_11_successful_sequence_runs_promote_validate_finalize_in_order(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(operator_menu, "prompt", _answers("11", "0"))
    monkeypatch.setattr(operator_menu, "run_command", lambda args, cwd=REPO_ROOT: (calls.append(args) or _fake_result(args, cwd)))

    operator_menu.option_derivatives(operator_menu.MenuState())

    assert [call[-1] for call in calls] == ["promote-definitive", "validate-definitive", "finalize"]


def test_reports_audit_rag_delegates_to_authoritative_derivatives_surface(monkeypatch) -> None:
    calls: list[operator_menu.MenuState] = []
    monkeypatch.setattr(operator_menu, "prompt", _answers("3", "0"))
    monkeypatch.setattr(operator_menu, "option_derivatives", lambda state: calls.append(state))

    operator_menu.option_reports_audit()

    assert len(calls) == 1
    assert isinstance(calls[0], operator_menu.MenuState)


def test_derivation_menu_surfaces_persisted_rollback_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        operator_menu,
        "build_rag_admission_state",
        lambda: {
            "staging": {"current": True},
            "technical_gate": {"status": "pass"},
            "equivalence": {"status": "pass"},
            "governance_gate": {"status": "pass"},
            "authorization": {"trial": "consumed"},
            "trial_write": {"status": "pass"},
            "rollback": {"status": "attempted_failed"},
            "definitive_promotion": {"status": "not_executed"},
            "verdict": "BLOCKED_ROLLBACK_ERROR",
            "next_action": "FIX_AND_RESUME_TRIAL_ROLLBACK",
            "blocking_reasons": [],
        },
    )
    monkeypatch.setattr(operator_menu, "prompt", _answers("0"))
    operator_menu.option_derivatives(operator_menu.MenuState())
    out = capsys.readouterr().out
    assert "Rollback productivo: ATTEMPT_FAILED" in out
    assert "Estado RAG: BLOCKED_ROLLBACK_ERROR" in out
    assert "Siguiente acción segura: FIX_AND_RESUME_TRIAL_ROLLBACK" in out


def test_derivation_menu_explains_expected_canonical_evolution(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        operator_menu,
        "build_rag_admission_state",
        lambda: {
            "staging": {"current": True},
            "technical_gate": {"status": "pass"},
            "equivalence": {
                "status": "equivalent_with_expected_canonical_evolution",
                "evolution": {"additions": 2, "updates": 3, "removals": 0, "regressions": 0},
            },
            "governance_gate": {"status": "pass"},
            "authorization": {"trial": "absent"},
            "trial_write": {"status": "not_executed"},
            "rollback": {"status": "not_executed"},
            "definitive_promotion": {"status": "not_executed"},
            "verdict": "READY_FOR_GOVERNED_WRITE",
            "next_action": "REQUEST_TRIAL_AUTHORIZATION",
            "blocking_reasons": [],
        },
    )
    monkeypatch.setattr(operator_menu, "prompt", _answers("0"))
    operator_menu.option_derivatives(operator_menu.MenuState())
    out = capsys.readouterr().out
    assert "Equivalencia: EVOLUCIÓN CANÓNICA ESPERADA" in out
    assert "Altas: 2" in out
    assert "Actualizaciones: 3" in out
    assert "Pérdidas: 0" in out
    assert "Regresiones: 0" in out
