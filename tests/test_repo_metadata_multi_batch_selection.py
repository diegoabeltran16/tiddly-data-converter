"""S0149 tests for governed multi-batch metadata selection."""

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
            _classification("emb", "#### 🌀 Sesión 0101 = embedded", "embedded_code_block", risk_level="high"),
            _classification("nar", "#### 🌀 Sesión 0102 = narrative", "session_or_diagnostic_narrative", risk_level="high"),
            _classification(
                "hist",
                "README-old",
                "repo_snapshot_drifted",
                candidate_authority_level="historical_snapshot",
                candidate_repo_path="README-old",
                candidate_repo_extension="",
                risk_level="high",
            ),
            _classification("gen", "data/out/local/generated.json", "generated_output"),
            _classification("blocked", "needs review", "review_required", confidence="requires_human_review"),
        ],
    )
    metadata_contract = tmp_path / "s0146" / "contract.md"
    metadata_contract.write_text("# contract\n", encoding="utf-8")
    canon = _write_jsonl(
        tmp_path / "canon" / "tiddlers_1.jsonl",
        [
            {"id": "cur", "title": "python_scripts/current.py", "source_fields": {"artifact_family": "unknown"}},
            {"id": "emb", "title": "#### 🌀 Sesión 0101 = embedded", "source_fields": {"artifact_family": "hipotesis_de_sesion"}},
            {"id": "nar", "title": "#### 🌀 Sesión 0102 = narrative", "source_fields": {"artifact_family": "detalles_de_sesion"}},
            {"id": "hist", "title": "README-old", "source_fields": {"artifact_family": "artefacto_repositorio"}},
            {"id": "gen", "title": "data/out/local/generated.json", "source_fields": {"artifact_family": "artefacto_repositorio"}},
            {"id": "blocked", "title": "needs review", "source_fields": {"artifact_family": "unknown"}},
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


def _run_s0149_dry_run(fx: dict[str, Path | str]) -> dict:
    s0147 = fx["s0147"]
    assert isinstance(s0147, Path)
    s0149 = fx["s0149"]
    assert isinstance(s0149, Path)
    classification = fx["classification"]
    assert isinstance(classification, Path)
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


def test_selects_multiple_recommended_batches_by_menu_number(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    s0147 = fx["s0147"]
    s0149 = fx["s0149"]
    assert isinstance(s0147, Path)
    assert isinstance(s0149, Path)

    doc = gate.select_s0149_batches("1,2,3", review_batches=s0147 / "s0147_repo_metadata_review_batches.json", out_dir=s0149)

    assert doc["valid"] is True
    assert doc["selected_batch_ids"] == [
        "batch_current_verified",
        "batch_embedded_code",
        "batch_narrative_reference",
    ]
    assert doc["selected_operation_count"] == 3
    assert gate.s0149_paths(s0149)["selected_batches"].exists()


def test_rejects_empty_missing_and_excluded_batch_selection(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    s0147 = fx["s0147"]
    s0149 = fx["s0149"]
    assert isinstance(s0147, Path)
    assert isinstance(s0149, Path)
    batches = s0147 / "s0147_repo_metadata_review_batches.json"

    empty = gate.select_s0149_batches("", review_batches=batches, out_dir=s0149 / "empty")
    missing = gate.select_s0149_batches("batch_missing", review_batches=batches, out_dir=s0149 / "missing")
    excluded = gate.select_s0149_batches("6", review_batches=batches, out_dir=s0149 / "excluded")

    assert empty["valid"] is False
    assert empty["empty_selection"] is True
    assert missing["valid"] is False
    assert missing["invalid_batch_ids"] == ["batch_missing"]
    assert excluded["valid"] is False
    assert excluded["blocked_batch_ids"] == ["batch_excluded_review_required"]


def test_dry_run_with_multiple_batches_does_not_modify_canon(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    s0147 = fx["s0147"]
    s0149 = fx["s0149"]
    canon = fx["canon"]
    assert isinstance(s0147, Path)
    assert isinstance(s0149, Path)
    assert isinstance(canon, Path)
    before = canon.read_text(encoding="utf-8")
    gate.select_s0149_batches("1,2,3", review_batches=s0147 / "s0147_repo_metadata_review_batches.json", out_dir=s0149)

    report = _run_s0149_dry_run(fx)

    assert report["blocked"] is False
    assert report["admission_ready"] == 3
    assert report["blocked_records"] == 0
    assert report["canon_modified"] is False
    assert report["relations_generated"] is False
    assert report["candidate_relations_generated"] is False
    assert canon.read_text(encoding="utf-8") == before
