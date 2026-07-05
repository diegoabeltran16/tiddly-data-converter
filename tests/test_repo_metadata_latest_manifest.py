"""S0151 tests for latest metadata patch manifest consumption."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import repo_metadata_admission_gate as gate  # noqa: E402
import repo_metadata_refresh_patch as refresh  # noqa: E402
from repo_metadata_s0151_helpers import build_s0151_fixture  # noqa: E402


def test_refresh_generates_latest_manifest_with_required_fields(tmp_path: Path) -> None:
    fx = build_s0151_fixture(tmp_path)
    manifest = tmp_path / "latest.json"
    out_dir = tmp_path / "refreshed"

    refresh.refresh_metadata_patch(
        patch_preview=Path(str(fx["patch"])),
        review_batches=Path(str(fx["batches"])),
        patch_hashes=Path(str(fx["hashes"])),
        canon_glob=str(fx["canon_glob"]),
        out_dir=out_dir,
        session="S0151",
        source_session="S0150",
        manifest_path=manifest,
        dry_run=True,
    )
    doc = json.loads(manifest.read_text(encoding="utf-8"))

    assert doc["schema"] == "latest-metadata-patch-manifest/v1"
    assert doc["session"] == "S0151"
    assert doc["status"] == "ready_for_dry_run"
    assert doc["canon_before_sha256"] == refresh.tree_sha256(str(fx["canon_glob"]))
    assert doc["dry_run"] is True
    assert doc["applied_to_canon"] is False
    for key in ("patch_preview", "review_batches", "patch_hashes", "refresh_report", "created_at"):
        assert doc[key]
    for key in ("patch_preview", "review_batches", "patch_hashes", "refresh_report"):
        assert (REPO_ROOT / doc[key]).exists()


def test_dry_run_uses_latest_manifest_and_writes_required_outputs(tmp_path: Path) -> None:
    fx = build_s0151_fixture(tmp_path)
    manifest = Path(str(fx["manifest"]))
    out_dir = Path(str(fx["out_dir"]))
    gate.select_s0151_batches("recommended", manifest=manifest, out_dir=out_dir)

    report = gate.run_s0151_dry_run(
        manifest=manifest,
        selected_batches=gate.s0151_paths(out_dir)["selected_batches"],
        canon_glob=str(fx["canon_glob"]),
        out_dir=out_dir,
    )
    paths = gate.s0151_paths(out_dir)

    assert report["blocked"] is False
    assert report["manifest"] == str(manifest)
    assert report["selected_operation_count"] == 3
    assert report["admission_ready"] == 3
    assert paths["dry_run_report"].exists()
    assert paths["ready"].exists()
    assert paths["blocked"].exists()
    assert paths["patch_preview"].exists()
    assert paths["review"].exists()
    assert paths["summary"].exists()
    assert paths["audit"].exists()
    assert paths["operator_ux_report"].exists()


def test_dry_run_blocks_when_manifest_canon_hash_is_stale(tmp_path: Path) -> None:
    fx = build_s0151_fixture(tmp_path)
    manifest = Path(str(fx["manifest"]))
    out_dir = Path(str(fx["out_dir"]))
    canon = Path(str(fx["canon"]))
    gate.select_s0151_batches("recommended", manifest=manifest, out_dir=out_dir)
    canon.write_text(canon.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    report = gate.run_s0151_dry_run(
        manifest=manifest,
        selected_batches=gate.s0151_paths(out_dir)["selected_batches"],
        canon_glob=str(fx["canon_glob"]),
        out_dir=out_dir,
    )

    assert report["blocked"] is True
    assert "hash_mismatch:manifest_canon_before_sha256" in report["block_reasons"]
    assert "hash_mismatch:patch_hashes_canon_before_sha256" in report["block_reasons"]
    assert report["admission_ready"] == 0
    assert report["relations_generated"] is False
    assert report["candidate_relations_generated"] is False
