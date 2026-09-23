"""Focused regression test for build_rag_safe_semantic_preview.py — S0187 D23-A B4-5.

candidate 6 of the B4-5 set: preview-only supporting tool (s0174_governance.py
classifies it functional_status=preview_only_supporting,
authority=none for productive outputs). This test proves only the path
contract fix -- the metadata-promotion-policy fallback used to be a bare
CWD-relative literal string ("data/out/local/pipeline/metadata_promotion/
s0171/metadata_promotion_policy.json"), which resolved against the process's
current working directory, not REPO_ROOT and not WORKSPACE_ROOT. It must now
resolve to an absolute, workspace-governed path regardless of CWD.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "src" / "python_scripts"
sys.path.insert(0, str(SCRIPTS))

import build_rag_safe_semantic_preview as brssp  # noqa: E402
import path_governance as pg  # noqa: E402
from tag_sanitation_policy import write_default_policy as write_tag_policy  # noqa: E402


def test_default_metadata_promotion_policy_path_is_workspace_governed() -> None:
    assert brssp.DEFAULT_OUT_DIR == pg.DEFAULT_LOCAL_OUT_DIR / "pipeline" / "rag_sanitation" / "s0170"
    assert brssp.DEFAULT_PREVIEW_DIR == brssp.DEFAULT_OUT_DIR / "preview"
    assert brssp.DEFAULT_METADATA_PROMOTION_POLICY_PATH == (
        pg.DEFAULT_LOCAL_OUT_DIR / "pipeline" / "metadata_promotion" / "s0171" / "metadata_promotion_policy.json"
    )
    assert brssp.DEFAULT_METADATA_PROMOTION_POLICY_PATH.is_absolute()


def test_metadata_promotion_policy_fallback_resolves_under_workspace_root_regardless_of_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, str] = {}

    def fake_load_metadata_promotion_policy(path):
        captured["path"] = str(path)
        return {"allowed_fields": [], "policy_version": "test"}

    def fake_build_semantic_text_outputs(**kwargs):
        return {"records_written": 0, "dry_run": True, "summary": {}}

    monkeypatch.setattr(brssp, "load_metadata_promotion_policy", fake_load_metadata_promotion_policy)
    monkeypatch.setattr(brssp, "build_semantic_text_outputs", fake_build_semantic_text_outputs)

    canon_dir = tmp_path / "canon"
    canon_dir.mkdir()
    (canon_dir / "tiddlers_1.jsonl").write_text(
        '{"id": "r1", "title": "R1", "tags": []}\n', encoding="utf-8"
    )

    tag_policy_path = tmp_path / "tag_policy.json"
    write_tag_policy(tag_policy_path)

    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text("", encoding="utf-8")

    out_dir = tmp_path / "out"

    # The regression this test exists for: change CWD to somewhere entirely
    # unrelated to REPO_ROOT/WORKSPACE_ROOT before invoking main(). Before
    # this fix, the bare-literal fallback would have resolved relative to
    # THIS directory instead of the governed workspace root.
    unrelated_cwd = tmp_path / "unrelated_cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_rag_safe_semantic_preview.py",
            "--canon-glob",
            str(canon_dir / "tiddlers_*.jsonl"),
            "--tag-policy",
            str(tag_policy_path),
            "--out-dir",
            str(out_dir),
            "--metadata-candidates",
            str(candidates_path),
            # --metadata-promotion-policy intentionally omitted: this is
            # exactly the branch that hits the fallback under test.
        ],
    )

    brssp.main()

    assert captured["path"] == str(brssp.DEFAULT_METADATA_PROMOTION_POLICY_PATH)
    assert Path(captured["path"]).is_absolute()
    # Prove it did NOT resolve against the unrelated CWD we just changed to.
    old_bug_shape = str(
        unrelated_cwd
        / "data"
        / "out"
        / "local"
        / "pipeline"
        / "metadata_promotion"
        / "s0171"
        / "metadata_promotion_policy.json"
    )
    assert captured["path"] != old_bug_shape
    # No productive output was written -- only the isolated tmp_path out_dir.
    assert not out_dir.exists() or all(
        str(p).startswith(str(tmp_path)) for p in out_dir.rglob("*")
    )
