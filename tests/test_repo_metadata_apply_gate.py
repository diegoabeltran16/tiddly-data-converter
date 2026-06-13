"""S0149 tests for governed metadata apply and rollback."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

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
                candidate_content_sha256="abc123",
                content_comparison="exact_match",
            ),
            _classification("nar", "#### 🌀 Sesión 0102 = narrative", "session_or_diagnostic_narrative", risk_level="high"),
        ],
    )
    metadata_contract = tmp_path / "s0146" / "contract.md"
    metadata_contract.write_text("# contract\n", encoding="utf-8")
    canon = _write_jsonl(
        tmp_path / "canon" / "tiddlers_1.jsonl",
        [
            {"id": "cur", "title": "python_scripts/current.py", "source_fields": {"artifact_family": "unknown"}, "text": "current"},
            {
                "id": "nar",
                "title": "#### 🌀 Sesión 0102 = narrative",
                "source_fields": {"artifact_family": "detalles_de_sesion"},
                "text": "mentions python_scripts/current.py",
            },
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
        "canon": canon,
        "canon_glob": str(canon.parent / "tiddlers_*.jsonl"),
        "s0147": out_dir,
        "s0149": tmp_path / "s0149",
    }


def _refresh_hashes(fx: dict[str, Path | str]) -> None:
    s0147 = fx["s0147"]
    assert isinstance(s0147, Path)
    rows = gate.read_jsonl(s0147 / "s0147_repo_metadata_patch_preview.jsonl")
    batches_path = s0147 / "s0147_repo_metadata_review_batches.json"
    batches = gate.read_json(batches_path)
    for batch_id, batch in batches["batches"].items():
        batch["patch_sha256"] = gate.subset_sha([row for row in rows if row.get("batch_id") == batch_id])
    gate.write_json(batches_path, batches)
    hashes_path = s0147 / "s0147_repo_metadata_patch_hashes.json"
    hashes = gate.read_json(hashes_path)
    hashes["patch_preview_sha256"] = gate.file_sha256(s0147 / "s0147_repo_metadata_patch_preview.jsonl")
    hashes["review_batches_sha256"] = gate.file_sha256(batches_path)
    hashes["dry_run_report_sha256"] = gate.file_sha256(s0147 / "s0147_repo_metadata_dry_run_report.json")
    classification = fx["classification"]
    assert isinstance(classification, Path)
    hashes["s0146_classification_sha256"] = gate.file_sha256(classification)
    hashes["canon_before_sha256"] = gate.tree_sha256(str(fx["canon_glob"]))
    gate.write_json(hashes_path, hashes)


def _prepare_successful_dry_run(fx: dict[str, Path | str]) -> dict:
    s0147 = fx["s0147"]
    s0149 = fx["s0149"]
    classification = fx["classification"]
    assert isinstance(s0147, Path)
    assert isinstance(s0149, Path)
    assert isinstance(classification, Path)
    gate.select_s0149_batches("1,3", review_batches=s0147 / "s0147_repo_metadata_review_batches.json", out_dir=s0149)
    return gate.run_s0149_dry_run(
        patch_preview=s0147 / "s0147_repo_metadata_patch_preview.jsonl",
        review_batches=s0147 / "s0147_repo_metadata_review_batches.json",
        patch_hashes=s0147 / "s0147_repo_metadata_patch_hashes.json",
        dry_run_report=s0147 / "s0147_repo_metadata_dry_run_report.json",
        selected_batches=gate.s0149_paths(s0149)["selected_batches"],
        canon_glob=str(fx["canon_glob"]),
        s0146_classification=classification,
        out_dir=s0149,
    )


def _apply(fx: dict[str, Path | str], token: str | None) -> dict:
    s0147 = fx["s0147"]
    s0149 = fx["s0149"]
    classification = fx["classification"]
    assert isinstance(s0147, Path)
    assert isinstance(s0149, Path)
    assert isinstance(classification, Path)
    return gate.apply_s0149_metadata(
        patch_preview=s0147 / "s0147_repo_metadata_patch_preview.jsonl",
        review_batches=s0147 / "s0147_repo_metadata_review_batches.json",
        patch_hashes=s0147 / "s0147_repo_metadata_patch_hashes.json",
        s0147_dry_run_report=s0147 / "s0147_repo_metadata_dry_run_report.json",
        dry_run_report_path=gate.s0149_paths(s0149)["dry_run_report"],
        selected_batches=gate.s0149_paths(s0149)["selected_batches"],
        canon_glob=str(fx["canon_glob"]),
        s0146_classification=classification,
        out_dir=s0149,
        apply_token=token,
    )


def _canon_records(canon: Path) -> dict[str, dict]:
    return {row["id"]: row for row in gate.read_jsonl(canon)}


def test_apply_blocks_without_successful_dry_run_or_valid_token(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)

    missing_dry_run = _apply(fx, gate.S0149_APPLY_TOKEN)
    _prepare_successful_dry_run(fx)
    bad_token = _apply(fx, "BAD TOKEN")

    assert missing_dry_run["apply_executed"] is False
    assert "missing_successful_dry_run" in missing_dry_run["block_reasons"]
    assert bad_token["apply_executed"] is False
    assert "invalid_or_missing_apply_token" in bad_token["block_reasons"]


def test_apply_blocks_if_hashes_changed_after_dry_run(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    canon = fx["canon"]
    assert isinstance(canon, Path)
    _prepare_successful_dry_run(fx)
    canon.write_text(canon.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    report = _apply(fx, gate.S0149_APPLY_TOKEN)

    assert report["apply_executed"] is False
    assert "hash_mismatch_before_apply" in report["block_reasons"]


def test_apply_blocks_if_selected_patch_has_critical_risk(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    s0147 = fx["s0147"]
    assert isinstance(s0147, Path)
    patch = s0147 / "s0147_repo_metadata_patch_preview.jsonl"
    rows = gate.read_jsonl(patch)
    rows[0]["source_risk_level"] = "critical"
    gate.write_jsonl(patch, rows)
    _refresh_hashes(fx)
    dry = _prepare_successful_dry_run(fx)

    report = _apply(fx, gate.S0149_APPLY_TOKEN)

    assert dry["blocked"] is True
    assert "critical_risk_in_selected_batches" in dry["block_reasons"]
    assert report["apply_executed"] is False
    assert "dry_run_not_successful" in report["block_reasons"]


def test_apply_uses_only_patch_fields_preserves_session_family_and_generates_no_relations(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    canon = fx["canon"]
    assert isinstance(canon, Path)
    _prepare_successful_dry_run(fx)

    report = _apply(fx, gate.S0149_APPLY_TOKEN)
    records = _canon_records(canon)

    assert report["apply_executed"] is True
    assert report["relations_generated"] is False
    assert report["candidate_relations_generated"] is False
    assert records["cur"]["source_fields"]["artifact_family"] == "artefacto_repositorio"
    assert records["cur"]["source_fields"]["repo_path"] == "python_scripts/current.py"
    assert records["nar"]["source_fields"]["artifact_family"] == "detalles_de_sesion"
    assert records["nar"]["source_fields"]["technical_content_role"] == "session_or_diagnostic_narrative"
    assert "relations" not in records["cur"]["source_fields"]
    assert "candidate_relations" not in records["nar"]["source_fields"]


def test_rollback_restores_canon_before_apply(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    canon = fx["canon"]
    s0149 = fx["s0149"]
    assert isinstance(canon, Path)
    assert isinstance(s0149, Path)
    before = canon.read_text(encoding="utf-8")
    _prepare_successful_dry_run(fx)
    report = _apply(fx, gate.S0149_APPLY_TOKEN)

    rollback = gate.rollback_s0149_metadata(out_dir=s0149)

    assert report["apply_executed"] is True
    assert rollback["rollback_executed"] is True
    assert canon.read_text(encoding="utf-8") == before
