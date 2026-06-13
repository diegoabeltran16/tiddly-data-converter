"""S0147 tests for local repo metadata review menu."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

import build_repo_metadata_patch_preview as preview  # noqa: E402
import repo_metadata_review_menu as menu  # noqa: E402


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _classification(tid: str, title: str, category: str, **overrides) -> dict:
    payload = {
        "id": tid,
        "title": title,
        "diagnostic_category": category,
        "candidate_authority_level": "unknown",
        "candidate_is_current_repo_artifact": "false",
        "risk_level": "low",
        "confidence": "high",
        "candidate_repo_path": "",
        "candidate_repo_directory": "",
        "candidate_repo_extension": "",
        "candidate_repo_artifact_kind": "unknown_repo_artifact",
        "candidate_repo_lifecycle_state": "",
        "candidate_artifact_family": "artefacto_repositorio",
        "candidate_content_sha256": f"sha-{tid}",
        "content_comparison": "not_current",
    }
    payload.update(overrides)
    return payload


def _fixture(tmp_path: Path) -> Path:
    classification = _write_jsonl(
        tmp_path / "s0146" / "classification.jsonl",
        [
            _classification(
                "cur",
                "python_scripts/current.py",
                "repo_snapshot_current",
                candidate_authority_level="current_verified",
                candidate_is_current_repo_artifact="true",
                candidate_repo_path="python_scripts/current.py",
                candidate_repo_directory="python_scripts",
                candidate_repo_extension=".py",
                candidate_repo_artifact_kind="source_code",
                candidate_repo_lifecycle_state="current_repo_artifact",
                content_comparison="exact_match",
            ),
            _classification(
                "hist",
                "python_scripts/old.py",
                "repo_snapshot_drifted",
                candidate_authority_level="historical_snapshot",
                candidate_repo_path="python_scripts/old.py",
                candidate_repo_directory="python_scripts",
                candidate_repo_extension=".py",
                candidate_repo_artifact_kind="source_code",
                candidate_repo_lifecycle_state="historical_snapshot",
                risk_level="high",
            ),
            _classification("review", "needs review", "review_required", confidence="requires_human_review"),
        ],
    )
    metadata_contract = tmp_path / "s0146" / "metadata_contract.md"
    metadata_contract.write_text("# contract\n", encoding="utf-8")
    canon = _write_jsonl(
        tmp_path / "canon" / "tiddlers_1.jsonl",
        [
            {"id": "cur", "title": "python_scripts/current.py", "source_fields": {"artifact_family": "unknown"}},
            {"id": "hist", "title": "python_scripts/old.py", "source_fields": {"artifact_family": "tiddler_tecnico"}},
            {"id": "review", "title": "needs review", "source_fields": {"artifact_family": "unknown"}},
        ],
    )
    out_dir = tmp_path / "out"
    preview.build_repo_metadata_patch_preview(
        classification=classification,
        metadata_contract=metadata_contract,
        canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
        out_dir=out_dir,
        session="S0147",
        dry_run=True,
    )
    return out_dir


def test_menu_summary_shows_patch_preview(tmp_path: Path, capsys) -> None:
    out_dir = _fixture(tmp_path)

    assert menu.main(["--out-dir", str(out_dir), "--summary"]) == 0

    out = capsys.readouterr().out
    assert "S0147 repo metadata patch preview" in out
    assert "patch_operations_generated: 2" in out
    assert "lane_a_current_verified" in out


def test_menu_lists_batches(tmp_path: Path, capsys) -> None:
    out_dir = _fixture(tmp_path)

    assert menu.main(["--out-dir", str(out_dir), "--list-batches"]) == 0

    out = capsys.readouterr().out
    assert "batch_current_verified" in out
    assert "approval_disabled=True" in out


def test_menu_shows_specific_batch(tmp_path: Path, capsys) -> None:
    out_dir = _fixture(tmp_path)

    assert menu.main(["--out-dir", str(out_dir), "--show-batch", "batch_current_verified"]) == 0

    out = capsys.readouterr().out
    assert "batch_current_verified" in out
    assert "python_scripts/current.py" in out


def test_menu_shows_excluded_records(tmp_path: Path, capsys) -> None:
    out_dir = _fixture(tmp_path)

    assert menu.main(["--out-dir", str(out_dir), "--show-excluded"]) == 0

    out = capsys.readouterr().out
    assert "excluded records: 1" in out
    assert "needs review" in out


def test_menu_shows_risks(tmp_path: Path, capsys) -> None:
    out_dir = _fixture(tmp_path)

    assert menu.main(["--out-dir", str(out_dir), "--show-risks"]) == 0

    out = capsys.readouterr().out
    assert "S0147 risk report" in out
    assert "high_or_critical_operations: 1" in out


def test_menu_validates_dry_run_contract(tmp_path: Path, capsys) -> None:
    out_dir = _fixture(tmp_path)

    assert menu.main(["--out-dir", str(out_dir), "--validate-dry-run"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert payload["approval_disabled_in_s0147"] is True
    assert payload["human_approved"] is False
    assert payload["applied_to_canon"] is False


def test_menu_requires_valid_token_for_approval(tmp_path: Path, capsys) -> None:
    out_dir = _fixture(tmp_path)
    decision_dir = tmp_path / "s0148"

    assert (
        menu.main(
            [
                "--out-dir",
                str(out_dir),
                "--decision-dir",
                str(decision_dir),
                "--approve-batch",
                "batch_current_verified",
                "--decision-token",
                "BAD_TOKEN",
            ]
        )
        == 2
    )

    assert "invalid_token" in capsys.readouterr().out
