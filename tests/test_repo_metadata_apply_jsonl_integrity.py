"""S0151 tests for JSONL-safe metadata apply and rollback."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import repo_metadata_admission_gate as gate  # noqa: E402
from repo_metadata_s0151_helpers import build_s0151_fixture  # noqa: E402


def _prepare_dry_run(fx: dict[str, Path | str]) -> dict:
    manifest = Path(str(fx["manifest"]))
    out_dir = Path(str(fx["out_dir"]))
    gate.select_s0151_batches("recommended", manifest=manifest, out_dir=out_dir)
    return gate.run_s0151_dry_run(
        manifest=manifest,
        selected_batches=gate.s0151_paths(out_dir)["selected_batches"],
        canon_glob=str(fx["canon_glob"]),
        out_dir=out_dir,
    )


def _apply(fx: dict[str, Path | str], token: str | None) -> dict:
    manifest = Path(str(fx["manifest"]))
    out_dir = Path(str(fx["out_dir"]))
    return gate.apply_s0151_metadata(
        manifest=manifest,
        dry_run_report_path=gate.s0151_paths(out_dir)["dry_run_report"],
        selected_batches=gate.s0151_paths(out_dir)["selected_batches"],
        canon_glob=str(fx["canon_glob"]),
        out_dir=out_dir,
        apply_token=token,
    )


def _canon_rows(canon: Path) -> list[dict]:
    return [json.loads(line) for line in canon.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_apply_blocks_without_successful_dry_run_or_human_token(tmp_path: Path) -> None:
    fx = build_s0151_fixture(tmp_path)

    missing_dry_run = _apply(fx, gate.S0151_APPLY_TOKEN)
    dry = _prepare_dry_run(fx)
    bad_token = _apply(fx, "APPLY METADATA S0149")

    assert dry["blocked"] is False
    assert missing_dry_run["apply_executed"] is False
    assert "missing_successful_dry_run" in missing_dry_run["block_reasons"]
    assert bad_token["apply_executed"] is False
    assert "invalid_or_missing_apply_token" in bad_token["block_reasons"]


def test_apply_updates_existing_jsonl_lines_and_creates_no_per_tiddler_json(tmp_path: Path) -> None:
    fx = build_s0151_fixture(tmp_path)
    canon = Path(str(fx["canon"]))
    out_dir = Path(str(fx["out_dir"]))
    before_line_count = len(canon.read_text(encoding="utf-8").splitlines())
    _prepare_dry_run(fx)

    report = _apply(fx, gate.S0151_APPLY_TOKEN)
    rows = {row["id"]: row for row in _canon_rows(canon)}

    assert report["apply_executed"] is True
    assert report["records_modified"] == 3
    assert report["relations_generated"] is False
    assert report["candidate_relations_generated"] is False
    assert len(canon.read_text(encoding="utf-8").splitlines()) == before_line_count
    assert not list(canon.parent.glob("*.json"))
    assert rows["cur"]["source_fields"]["artifact_family"] == "artefacto_repositorio"
    assert rows["cur"]["source_fields"]["repo_path"] == "python_scripts/current.py"
    assert rows["emb"]["source_fields"]["technical_content_role"] == "embedded_code_block"
    assert rows["nar"]["source_fields"]["authority_level"] == "narrative_reference"
    assert "relations" not in rows["cur"]["source_fields"]
    assert "candidate_relations" not in rows["nar"]["source_fields"]
    assert (gate.s0151_paths(out_dir)["backups"] / "canon_before_apply").exists()
    assert (gate.s0151_paths(out_dir)["backups"] / "rollback_manifest.json").exists()


def test_rollback_restores_jsonl_backup(tmp_path: Path) -> None:
    fx = build_s0151_fixture(tmp_path)
    canon = Path(str(fx["canon"]))
    out_dir = Path(str(fx["out_dir"]))
    before = canon.read_text(encoding="utf-8")
    _prepare_dry_run(fx)
    apply_report = _apply(fx, gate.S0151_APPLY_TOKEN)

    rollback = gate.rollback_s0151_metadata(out_dir=out_dir)

    assert apply_report["apply_executed"] is True
    assert rollback["rollback_executed"] is True
    assert canon.read_text(encoding="utf-8") == before
