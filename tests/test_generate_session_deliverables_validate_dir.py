from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

from generate_session_deliverables import _cmd_validate_dir  # noqa: E402


def _session_payload(slug: str = "routing-vdir-test") -> dict:
    return {
        "title": "#### 🌀 Contrato de sesión 0186 = routing-vdir-test",
        "type": "text/markdown",
        "created": "20260901000000000",
        "modified": "20260901000000000",
        "session_id": "m04-s0186",
        "module": "m04",
        "session": "S0186",
        "status": "delivered",
        "canonical_slug": f"m04-s0186-{slug}",
        "tags": ["sesion", "contrato", "m04", "s0186"],
        "text": "contenido",
    }


def _thematic_payload(title: str = "diagnostico tematico de prueba") -> dict:
    return {
        "title": title,
        "type": "text/markdown",
        "created": "20260901000000000",
        "modified": "20260901000000000",
        "canonical_slug": "diagnostico-tematico-999-prueba-routing-vdir",
        "tags": ["diagnostico", "tematico"],
        "text": "contenido",
    }


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _run_validate_dir(sessions_dir: Path, capsys) -> tuple[int, str]:
    args = argparse.Namespace(sessions_dir=str(sessions_dir))
    exit_code = _cmd_validate_dir(args)
    return exit_code, capsys.readouterr().out


def test_valid_session_artifact_passes_validate_dir(tmp_path: Path, capsys) -> None:
    sessions = tmp_path / "sessions"
    _write(sessions / "00_contratos" / "m04-s0186-routing-vdir-test.md.json", _session_payload())

    exit_code, out = _run_validate_dir(sessions, capsys)

    assert exit_code == 0
    assert "All 1 file(s) valid." in out


def test_valid_thematic_diagnostic_passes_without_session_schema(tmp_path: Path, capsys) -> None:
    sessions = tmp_path / "sessions"
    _write(
        sessions / "06_diagnoses" / "tema" / "diagnostico-tematico-999-prueba-routing-vdir.md.json",
        _thematic_payload(),
    )

    exit_code, out = _run_validate_dir(sessions, capsys)

    assert exit_code == 0
    assert "All 1 file(s) valid." in out
    # No historical wrong-schema errors — a real thematic diagnostic must never
    # be rejected for missing session_id/module/session/status/tags.
    for field in ("session_id", "module", "session", "status"):
        assert field not in out


def test_invalid_thematic_diagnostic_still_fails_under_its_own_governance(tmp_path: Path, capsys) -> None:
    sessions = tmp_path / "sessions"
    # Filename does not match diagnostic_governance's own tema convention
    # (diagnostico-tematico-<n>-<slug>.md.json) — this is a structural defect
    # under the artifact's OWN contract, not a session-schema mismatch, and
    # routing must not silently pass it.
    _write(
        sessions / "06_diagnoses" / "tema" / "not-a-recognized-thematic-filename.md.json",
        _thematic_payload(),
    )

    exit_code, out = _run_validate_dir(sessions, capsys)

    assert exit_code == 1
    assert "thematic_diagnostic" in out
    assert "unknown_diagnostic_family" in out
    # It must fail for its own-contract reason, not be misreported as a
    # session-deliverable schema failure.
    assert "required field missing" not in out


def test_unsupported_family_fails_closed(tmp_path: Path, capsys) -> None:
    sessions = tmp_path / "sessions"
    _write(sessions / "99_unrouted" / "mystery.md.json", {"title": "mystery, no known family"})

    exit_code, out = _run_validate_dir(sessions, capsys)

    assert exit_code == 1
    assert "other_or_unsupported" in out
    assert "unsupported_family_owner" in out


def test_invalid_json_reports_json_error_not_schema_noise(tmp_path: Path, capsys) -> None:
    sessions = tmp_path / "sessions"
    path = sessions / "00_contratos" / "broken.md.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json", encoding="utf-8")

    exit_code, out = _run_validate_dir(sessions, capsys)

    assert exit_code == 1
    assert "invalid JSON" in out


def test_global_validate_dir_mixed_family_directory(tmp_path: Path, capsys) -> None:
    """Reproduces the historical bug shape: a directory containing both
    session_deliverable and thematic_diagnostic artifacts must classify each
    by its own family, not apply one schema to the whole directory."""
    sessions = tmp_path / "sessions"
    _write(sessions / "00_contratos" / "m04-s0186-routing-vdir-test.md.json", _session_payload())
    _write(
        sessions / "06_diagnoses" / "tema" / "diagnostico-tematico-999-prueba-routing-vdir.md.json",
        _thematic_payload(),
    )
    _write(
        sessions / "06_diagnoses" / "tema" / "not-a-recognized-thematic-filename.md.json",
        _thematic_payload(),
    )
    _write(sessions / "99_unrouted" / "mystery.md.json", {"title": "mystery"})

    exit_code, out = _run_validate_dir(sessions, capsys)

    assert exit_code == 1
    assert "in 2 file(s)." in out
    # exactly the two genuinely-invalid files should be reported ...
    assert "not-a-recognized-thematic-filename.md.json" in out
    assert "mystery.md.json" in out
    # ... and the two genuinely-valid ones (one session, one thematic) must not
    # be mentioned at all — proving family routing, not blanket rejection.
    assert "m04-s0186-routing-vdir-test.md.json" not in out
    assert "diagnostico-tematico-999-prueba-routing-vdir.md.json" not in out


def test_no_nominal_special_case_for_known_dt_numbers(tmp_path: Path, capsys) -> None:
    """A thematic diagnostic whose number is NOT one of the historically-named
    DT065/066/070/087 must pass on exactly the same structural grounds — proving
    there is no filename/number-based allowlist, only family/path routing."""
    sessions = tmp_path / "sessions"
    _write(
        sessions / "06_diagnoses" / "tema" / "diagnostico-tematico-5150-numero-arbitrario-no-listado.md.json",
        _thematic_payload(title="diagnostico numero arbitrario"),
    )

    exit_code, out = _run_validate_dir(sessions, capsys)

    assert exit_code == 0
    assert "All 1 file(s) valid." in out
