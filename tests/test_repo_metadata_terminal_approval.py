"""S0148 tests for terminal metadata batch decisions."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import build_repo_metadata_patch_preview as preview  # noqa: E402
import repo_metadata_admission_gate as gate  # noqa: E402
import repo_metadata_review_menu as menu  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
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


def _fixture(tmp_path: Path) -> dict[str, Path | str]:
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
            )
        ],
    )
    metadata_contract = tmp_path / "s0146" / "contract.md"
    metadata_contract.write_text("# contract\n", encoding="utf-8")
    canon = _write_jsonl(
        tmp_path / "canon" / "tiddlers_1.jsonl",
        [{"id": "cur", "title": "python_scripts/current.py", "source_fields": {"artifact_family": "unknown"}}],
    )
    out_dir = tmp_path / "s0147"
    preview.build_repo_metadata_patch_preview(
        classification=classification,
        metadata_contract=metadata_contract,
        canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
        out_dir=out_dir,
        session="S0147",
        dry_run=True,
    )
    return {
        "classification": classification,
        "canon_glob": str(canon.parent / "tiddlers_*.jsonl"),
        "out_dir": out_dir,
        "decision_dir": tmp_path / "s0148",
    }


def _decision_doc(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_invalid_token_does_not_approve_batch(tmp_path: Path, capsys) -> None:
    fx = _fixture(tmp_path)

    assert (
        menu.main(
            [
                "--out-dir",
                str(fx["out_dir"]),
                "--decision-dir",
                str(fx["decision_dir"]),
                "--approve-batch",
                "batch_current_verified",
                "--decision-token",
                "WRONG",
            ]
        )
        == 2
    )

    assert "invalid_token" in capsys.readouterr().out
    decisions_path = gate.s0148_paths(fx["decision_dir"])["human_decisions"]
    decisions = _decision_doc(decisions_path)
    assert decisions["human_approval_found"] is False
    assert decisions["decisions"] == []


def test_correct_token_approves_current_verified_batch(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)

    assert (
        menu.main(
            [
                "--out-dir",
                str(fx["out_dir"]),
                "--decision-dir",
                str(fx["decision_dir"]),
                "--approve-batch",
                "batch_current_verified",
                "--decision-token",
                "APROBAR_METADATA_BATCH_CURRENT_VERIFIED",
            ]
        )
        == 0
    )

    decisions = _decision_doc(gate.s0148_paths(fx["decision_dir"])["human_decisions"])
    assert decisions["created_by_agent"] is False
    assert decisions["human_approval_found"] is True
    assert decisions["decisions"][0]["decision"] == "approved"
    assert decisions["decisions"][0]["human_approved"] is True
    assert decisions["decisions"][0]["token_verified"] is True


def test_rejected_decision_records_without_approval(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)

    assert (
        menu.main(
            [
                "--out-dir",
                str(fx["out_dir"]),
                "--decision-dir",
                str(fx["decision_dir"]),
                "--reject-batch",
                "batch_current_verified",
                "--decision-token",
                "RECHAZAR_METADATA_BATCH_CURRENT_VERIFIED",
            ]
        )
        == 0
    )

    decision = _decision_doc(gate.s0148_paths(fx["decision_dir"])["human_decisions"])["decisions"][0]
    assert decision["decision"] == "rejected"
    assert decision["human_approved"] is False


def test_deferred_decision_records_without_approval(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)

    assert (
        menu.main(
            [
                "--out-dir",
                str(fx["out_dir"]),
                "--decision-dir",
                str(fx["decision_dir"]),
                "--defer-batch",
                "batch_current_verified",
                "--decision-token",
                "DIFERIR_METADATA_BATCH_CURRENT_VERIFIED",
            ]
        )
        == 0
    )

    decision = _decision_doc(gate.s0148_paths(fx["decision_dir"])["human_decisions"])["decisions"][0]
    assert decision["decision"] == "deferred"
    assert decision["human_approved"] is False


def test_nonexistent_batch_decision_is_blocked(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)

    result = gate.record_terminal_decision(
        batch_id="batch_missing",
        decision="approved",
        token="APROBAR_METADATA_MISSING",
        patch_preview=fx["out_dir"] / "s0147_repo_metadata_patch_preview.jsonl",
        review_batches=fx["out_dir"] / "s0147_repo_metadata_review_batches.json",
        patch_hashes=fx["out_dir"] / "s0147_repo_metadata_patch_hashes.json",
        human_decisions=gate.s0148_paths(fx["decision_dir"])["human_decisions"],
        out_dir=fx["decision_dir"],
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "batch_not_found"


def test_terminal_audit_is_generated_for_decision(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)

    menu.main(
        [
            "--out-dir",
            str(fx["out_dir"]),
            "--decision-dir",
            str(fx["decision_dir"]),
            "--approve-batch",
            "batch_current_verified",
            "--decision-token",
            "APROBAR_METADATA_BATCH_CURRENT_VERIFIED",
        ]
    )

    audit = gate.s0148_paths(fx["decision_dir"])["terminal_audit"].read_text(encoding="utf-8")
    assert "approved_batch" in audit
    assert "recorded" in audit


def test_menu_lists_batches_and_shows_last_gate_report(tmp_path: Path, capsys) -> None:
    fx = _fixture(tmp_path)
    menu.main(["--out-dir", str(fx["out_dir"]), "--list-batches"])
    assert "batch_current_verified" in capsys.readouterr().out

    menu.main(
        [
            "--out-dir",
            str(fx["out_dir"]),
            "--decision-dir",
            str(fx["decision_dir"]),
            "--run-gate-dry-run",
            "--canon-glob",
            str(fx["canon_glob"]),
            "--s0146-classification",
            str(fx["classification"]),
        ]
    )
    assert menu.main(["--decision-dir", str(fx["decision_dir"]), "--show-last-gate-report"]) == 0
    assert "repo-metadata-admission-gate-report" in capsys.readouterr().out
