"""S0151 tests for automatic metadata patch refresh."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

import repo_metadata_refresh_patch as refresh  # noqa: E402
from repo_metadata_s0151_helpers import build_s0151_fixture  # noqa: E402


def _copy_source_files(fx: dict[str, Path | str], out_dir: Path, *, session: str) -> None:
    paths = refresh.refreshed_paths(out_dir, session=session)
    for key, source_key in (("patch_preview", "patch"), ("review_batches", "batches"), ("patch_hashes", "hashes")):
        source = fx[source_key]
        assert isinstance(source, Path)
        paths[key].parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, paths[key])


def test_auto_source_prefers_compatible_s0150_refresh(tmp_path: Path) -> None:
    fx = build_s0151_fixture(tmp_path)
    s0150_dir = tmp_path / "s0150_source"
    s0147_dir = tmp_path / "s0147_source"
    _copy_source_files(fx, s0150_dir, session="S0150")
    s0147_dir.mkdir(parents=True)

    source = refresh.resolve_source_patch(
        "auto",
        patch_preview=s0147_dir / "s0147_repo_metadata_patch_preview.jsonl",
        review_batches=s0147_dir / "s0147_repo_metadata_review_batches.json",
        patch_hashes=s0147_dir / "s0147_repo_metadata_patch_hashes.json",
        latest_manifest=Path(str(fx["manifest"])),
        s0150_dir=s0150_dir,
        s0147_dir=s0147_dir,
    )

    assert source["source_session"] == "S0150"
    assert source["source_kind"] == "s0150_refreshed"


def test_refresh_recalculates_canon_hash_and_writes_s0151_outputs(tmp_path: Path) -> None:
    fx = build_s0151_fixture(tmp_path)
    out_dir = tmp_path / "refreshed"
    manifest = tmp_path / "latest.json"

    report = refresh.refresh_metadata_patch(
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
    paths = refresh.refreshed_paths(out_dir, session="S0151")

    assert report["session"] == "S0151"
    assert report["canon_before_sha256_refreshed"] == refresh.tree_sha256(str(fx["canon_glob"]))
    assert paths["patch_preview"].exists()
    assert paths["review_batches"].exists()
    assert paths["patch_hashes"].exists()
    assert paths["blocked"].exists()
    assert paths["review"].exists()
    assert manifest.exists()


def test_refresh_outputs_are_deterministic_for_equivalent_runs(tmp_path: Path) -> None:
    fx = build_s0151_fixture(tmp_path)
    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"

    report_a = refresh.refresh_metadata_patch(
        patch_preview=Path(str(fx["patch"])),
        review_batches=Path(str(fx["batches"])),
        patch_hashes=Path(str(fx["hashes"])),
        canon_glob=str(fx["canon_glob"]),
        out_dir=out_a,
        session="S0151",
        source_session="S0150",
        dry_run=True,
    )
    report_b = refresh.refresh_metadata_patch(
        patch_preview=Path(str(fx["patch"])),
        review_batches=Path(str(fx["batches"])),
        patch_hashes=Path(str(fx["hashes"])),
        canon_glob=str(fx["canon_glob"]),
        out_dir=out_b,
        session="S0151",
        source_session="S0150",
        dry_run=True,
    )

    paths_a = refresh.refreshed_paths(out_a, session="S0151")
    paths_b = refresh.refreshed_paths(out_b, session="S0151")
    assert report_a == report_b
    assert paths_a["patch_preview"].read_text(encoding="utf-8") == paths_b["patch_preview"].read_text(encoding="utf-8")
    assert paths_a["review_batches"].read_text(encoding="utf-8") == paths_b["review_batches"].read_text(encoding="utf-8")
