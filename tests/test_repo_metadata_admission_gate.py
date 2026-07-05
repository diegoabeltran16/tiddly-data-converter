"""S0148 tests for repo metadata dry-run admission gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import build_repo_metadata_patch_preview as preview  # noqa: E402
import repo_metadata_admission_gate as gate  # noqa: E402


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
            ),
            _classification("review", "needs review", "review_required", confidence="requires_human_review"),
        ],
    )
    metadata_contract = tmp_path / "s0146" / "contract.md"
    metadata_contract.write_text("# contract\n", encoding="utf-8")
    canon = _write_jsonl(
        tmp_path / "canon" / "tiddlers_1.jsonl",
        [
            {"id": "cur", "title": "python_scripts/current.py", "source_fields": {"artifact_family": "unknown"}},
            {"id": "review", "title": "needs review", "source_fields": {"artifact_family": "unknown"}},
        ],
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
        "canon_file": canon,
        "canon_glob": str(canon.parent / "tiddlers_*.jsonl"),
        "s0147": out_dir,
        "s0148": tmp_path / "s0148",
    }


def _paths(fx: dict[str, Path | str]) -> dict[str, Path]:
    s0147 = fx["s0147"]
    assert isinstance(s0147, Path)
    s0148 = fx["s0148"]
    assert isinstance(s0148, Path)
    return {
        "patch": s0147 / "s0147_repo_metadata_patch_preview.jsonl",
        "batches": s0147 / "s0147_repo_metadata_review_batches.json",
        "hashes": s0147 / "s0147_repo_metadata_patch_hashes.json",
        "dry": s0147 / "s0147_repo_metadata_dry_run_report.json",
        "decisions": gate.s0148_paths(s0148)["human_decisions"],
        "out": s0148,
    }


def _approve(fx: dict[str, Path | str]) -> None:
    p = _paths(fx)
    result = gate.record_terminal_decision(
        batch_id="batch_current_verified",
        decision="approved",
        token="APROBAR_METADATA_BATCH_CURRENT_VERIFIED",
        patch_preview=p["patch"],
        review_batches=p["batches"],
        patch_hashes=p["hashes"],
        human_decisions=p["decisions"],
        out_dir=p["out"],
        timestamp="2026-06-12T00:00:00Z",
    )
    assert result["status"] == "ok"


def _run_gate(fx: dict[str, Path | str]) -> dict:
    p = _paths(fx)
    classification = fx["classification"]
    assert isinstance(classification, Path)
    return gate.run_gate(
        patch_preview=p["patch"],
        review_batches=p["batches"],
        patch_hashes=p["hashes"],
        dry_run_report=p["dry"],
        human_decisions=p["decisions"],
        canon_glob=str(fx["canon_glob"]),
        s0146_classification=classification,
        out_dir=p["out"],
        session="S0148",
        dry_run=True,
    )


def _refresh_hashes(fx: dict[str, Path | str]) -> None:
    p = _paths(fx)
    patch_rows = gate.read_jsonl(p["patch"])
    batches = gate.read_json(p["batches"])
    for batch_id, batch in batches["batches"].items():
        rows = [row for row in patch_rows if row.get("batch_id") == batch_id]
        if batch_id != "batch_excluded_review_required":
            batch["patch_sha256"] = gate.subset_sha(rows)
    gate.write_json(p["batches"], batches)
    hashes = gate.read_json(p["hashes"])
    hashes["patch_preview_sha256"] = gate.file_sha256(p["patch"])
    hashes["review_batches_sha256"] = gate.file_sha256(p["batches"])
    hashes["dry_run_report_sha256"] = gate.file_sha256(p["dry"])
    classification = fx["classification"]
    assert isinstance(classification, Path)
    hashes["s0146_classification_sha256"] = gate.file_sha256(classification)
    hashes["canon_before_sha256"] = gate.tree_sha256(str(fx["canon_glob"]))
    gate.write_json(p["hashes"], hashes)


def test_gate_blocks_without_human_approval_and_writes_reports(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)

    report = _run_gate(fx)

    assert report["blocked"] is True
    assert report["admission_ready_dry_run"] == 0
    assert "no_human_approval" in report["block_reasons"]
    paths = gate.s0148_paths(fx["s0148"])
    for key in [
        "human_decisions",
        "batch_approvals",
        "gate_report",
        "admission_ready",
        "blocked_records",
        "rejected_or_deferred",
        "terminal_audit",
        "hash_verification",
        "risk_verification",
        "operator_summary",
        "next_apply_plan",
    ]:
        assert paths[key].exists()


def test_approved_current_verified_batch_produces_admission_ready_dry_run(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    _approve(fx)

    report = _run_gate(fx)
    ready_rows = gate.read_jsonl(gate.s0148_paths(fx["s0148"])["admission_ready"])

    assert report["blocked"] is False
    assert report["approved_batches"] == ["batch_current_verified"]
    assert report["admission_ready_dry_run"] == 1
    assert ready_rows[0]["human_approved"] is True
    assert ready_rows[0]["dry_run"] is True
    assert ready_rows[0]["applied_to_canon"] is False
    assert "relations" not in ready_rows[0]
    assert "candidate_relations" not in ready_rows[0]
    assert report["relations_generated"] is False
    assert report["candidate_relations_generated"] is False
    assert report["semantic_text_modified"] is False


def test_rejected_and_deferred_decisions_block_admission(tmp_path: Path) -> None:
    for decision, token, expected_key in [
        ("rejected", "RECHAZAR_METADATA_BATCH_CURRENT_VERIFIED", "rejected_batches"),
        ("deferred", "DIFERIR_METADATA_BATCH_CURRENT_VERIFIED", "deferred_batches"),
    ]:
        fx = _fixture(tmp_path / decision)
        p = _paths(fx)
        gate.record_terminal_decision(
            batch_id="batch_current_verified",
            decision=decision,
            token=token,
            patch_preview=p["patch"],
            review_batches=p["batches"],
            patch_hashes=p["hashes"],
            human_decisions=p["decisions"],
            out_dir=p["out"],
            timestamp="2026-06-12T00:00:00Z",
        )
        report = _run_gate(fx)
        assert report["blocked"] is True
        assert report["admission_ready_dry_run"] == 0
        assert report[expected_key] == ["batch_current_verified"]


def test_patch_hash_mismatch_blocks_admission(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    _approve(fx)
    p = _paths(fx)
    rows = gate.read_jsonl(p["patch"])
    rows[0]["target_title"] = "changed.py"
    gate.write_jsonl(p["patch"], rows)

    report = _run_gate(fx)

    assert report["blocked"] is True
    assert "hash_mismatch:patch_preview_sha256" in report["block_reasons"]


def test_canon_hash_mismatch_blocks_admission_and_canon_is_not_modified_by_gate(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    _approve(fx)
    canon_file = fx["canon_file"]
    assert isinstance(canon_file, Path)
    before_gate = canon_file.read_text(encoding="utf-8")
    canon_file.write_text(before_gate + "\n", encoding="utf-8")
    changed_before_gate = canon_file.read_text(encoding="utf-8")

    report = _run_gate(fx)

    assert report["blocked"] is True
    assert "hash_mismatch:canon_before_sha256" in report["block_reasons"]
    assert canon_file.read_text(encoding="utf-8") == changed_before_gate


def test_s0146_classification_hash_mismatch_blocks_admission(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    _approve(fx)
    classification = fx["classification"]
    assert isinstance(classification, Path)
    classification.write_text(classification.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    report = _run_gate(fx)

    assert report["blocked"] is True
    assert "hash_mismatch:s0146_classification_sha256" in report["block_reasons"]


def test_critical_risk_in_approved_batch_blocks_admission(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    p = _paths(fx)
    rows = gate.read_jsonl(p["patch"])
    rows[0]["source_risk_level"] = "critical"
    gate.write_jsonl(p["patch"], rows)
    _refresh_hashes(fx)
    _approve(fx)

    report = _run_gate(fx)

    assert report["blocked"] is True
    assert "critical_risk_in_approved_batch" in report["block_reasons"]


def test_lane_f_batch_blocks_admission(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    p = _paths(fx)
    batches = gate.read_json(p["batches"])["batches"]
    hashes = gate.read_json(p["hashes"])
    decisions = gate.empty_decisions_doc()
    decisions["human_approval_found"] = True
    decisions["decisions"] = [
        {
            "batch_id": "batch_excluded_review_required",
            "decision": "approved",
            "human_approved": True,
            "token_verified": True,
            "token_name": "APROBAR_METADATA_EXCLUDED_REVIEW_REQUIRED",
            "decision_timestamp": "2026-06-12T00:00:00Z",
            "patch_sha256": hashes["patch_preview_sha256"],
            "batch_sha256": batches["batch_excluded_review_required"]["patch_sha256"],
            "canon_before_sha256": hashes["canon_before_sha256"],
            "s0146_classification_sha256": hashes["s0146_classification_sha256"],
            "source_session": "S0147",
            "decision_source": "terminal",
        }
    ]
    gate.write_json(p["decisions"], decisions)

    report = _run_gate(fx)

    assert report["blocked"] is True
    assert "excluded_batch_not_approvable" in report["block_reasons"]


def test_hash_and_risk_verification_files_are_generated(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    _approve(fx)

    report = _run_gate(fx)
    paths = gate.s0148_paths(fx["s0148"])

    assert report["hash_verification"]["all_hashes_match"] is True
    assert paths["hash_verification"].exists()
    assert paths["risk_verification"].exists()


def test_gate_report_is_deterministic_for_equivalent_runs(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    _approve(fx)

    first = _run_gate(fx)
    first_text = gate.s0148_paths(fx["s0148"])["gate_report"].read_text(encoding="utf-8")
    second = _run_gate(fx)
    second_text = gate.s0148_paths(fx["s0148"])["gate_report"].read_text(encoding="utf-8")

    assert first == second
    assert first_text == second_text
