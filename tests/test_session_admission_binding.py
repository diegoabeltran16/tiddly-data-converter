from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "src" / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import admit_session_candidates as asc  # noqa: E402


def _args(report: Path | None, **changes: object) -> argparse.Namespace:
    values = {
        "dry_run_report": str(report) if report else None,
        "allow_replacements": False,
        "all_contracts": False,
        "scope": "missing",
        "session_filter_type": "session_id",
        "session_filter_value": "m04-s0183",
    }
    values.update(changes)
    return argparse.Namespace(**values)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    canon_dir = tmp_path / "canon"
    canon_dir.mkdir()
    (canon_dir / "tiddlers_1.jsonl").write_text('{"id":"base"}\n', encoding="utf-8")
    candidate = tmp_path / "missing-m04-s0183.canon-candidates.jsonl"
    candidate.write_text('{"id":"candidate"}\n', encoding="utf-8")
    report = tmp_path / "dry-run.json"
    binding = asc._binding_from_args(_args(report), candidate, canon_dir, report, "ok")
    report.write_text(
        json.dumps({"mode": "dry-run", "status": "ok", "admission_binding": binding}),
        encoding="utf-8",
    )
    return canon_dir, candidate, report


def test_exact_binding_is_accepted(tmp_path: Path) -> None:
    canon_dir, candidate, report = _fixture(tmp_path)
    _, errors = asc._validate_dry_run_binding(_args(report), candidate, canon_dir)
    assert errors == []


def test_missing_or_failed_dry_run_is_rejected(tmp_path: Path) -> None:
    canon_dir, candidate, report = _fixture(tmp_path)
    _, missing_errors = asc._validate_dry_run_binding(_args(None), candidate, canon_dir)
    assert any("requires --dry-run-report" in error for error in missing_errors)
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["status"] = "fail"
    report.write_text(json.dumps(payload), encoding="utf-8")
    _, failed_errors = asc._validate_dry_run_binding(_args(report), candidate, canon_dir)
    assert "dry-run status" in failed_errors


def test_candidate_or_canon_hash_change_is_rejected(tmp_path: Path) -> None:
    canon_dir, candidate, report = _fixture(tmp_path)
    candidate.write_text(candidate.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    _, candidate_errors = asc._validate_dry_run_binding(_args(report), candidate, canon_dir)
    assert "candidate hash" in candidate_errors
    candidate.write_text('{"id":"candidate"}\n', encoding="utf-8")
    (canon_dir / "tiddlers_1.jsonl").write_text('{"id":"changed"}\n', encoding="utf-8")
    _, canon_errors = asc._validate_dry_run_binding(_args(report), candidate, canon_dir)
    assert "canon hash" in canon_errors


def test_scope_filter_or_replacement_policy_change_is_rejected(tmp_path: Path) -> None:
    canon_dir, candidate, report = _fixture(tmp_path)
    _, scope_errors = asc._validate_dry_run_binding(_args(report, scope="combined"), candidate, canon_dir)
    assert "scope" in scope_errors
    _, filter_errors = asc._validate_dry_run_binding(
        _args(report, session_filter_value="m04-s0184"), candidate, canon_dir
    )
    assert "session filter" in filter_errors
    _, policy_errors = asc._validate_dry_run_binding(
        _args(report, allow_replacements=True), candidate, canon_dir
    )
    assert "replacement policy" in policy_errors


def test_candidate_count_or_receipt_identity_change_is_rejected(tmp_path: Path) -> None:
    canon_dir, candidate, report = _fixture(tmp_path)
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["admission_binding"]["candidate_count"] = 99
    payload["admission_binding"]["dry_run_report"] = "another-report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")
    _, errors = asc._validate_dry_run_binding(_args(report), candidate, canon_dir)
    assert "candidate count" in errors
    assert "dry-run report" in errors
