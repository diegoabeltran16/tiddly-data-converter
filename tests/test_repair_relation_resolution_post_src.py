import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "src" / "python_scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import repair_relation_resolution_post_src as repair  # noqa: E402


def test_normalize_post_src_maps_historical_prefixes():
    assert repair.normalize_post_src("go/canon/identity.go") == (
        "src/go/canon/identity.go",
        "old_to_src_prefix",
    )
    assert repair.normalize_post_src("./python_scripts/derive_layers.py") == (
        "src/python_scripts/derive_layers.py",
        "old_to_src_prefix",
    )
    assert repair.normalize_post_src("shell_scripts/tdc.sh") == (
        "src/shell_scripts/tdc.sh",
        "old_to_src_prefix",
    )


def test_normalize_post_src_keeps_current_paths_identity():
    assert repair.normalize_post_src("src/python_scripts/session_sync.py") == (
        "src/python_scripts/session_sync.py",
        "identity",
    )


def test_old_alias_for_src_reverses_only_src_prefixes():
    assert repair.old_alias_for_src("src/rust/doctor/src/main.rs") == "rust/doctor/src/main.rs"
    assert repair.old_alias_for_src("tests/test_text_utils.py") is None


def test_self_relation_is_not_resolved_for_human_review():
    node = repair.CanonNode(
        canonical_id="node-1",
        title="src/python_scripts/self.py",
        key="src/python_scripts/self.py",
        canonical_slug="srcpythonscriptsselfpy",
        version_id="sha256:test",
        repo_path="python_scripts/self.py",
        source_path=None,
        artifact_family="artefacto_repositorio",
        authority_level="current_verified",
        repo_lifecycle_state="current_repo_artifact",
        canonical_status=None,
        shard_path="data/out/local/tiddlers_1.jsonl",
        line_no=1,
    )
    indexes = repair.build_indexes([node])
    candidate = {
        "candidate_id": "rc_s0161_self",
        "relation_type": "references",
        "source": {"repo_path": "src/python_scripts/self.py"},
        "target": {"repo_path": "src/python_scripts/self.py"},
        "evidence": {"raw_observation": '"src/python_scripts/self.py"', "line": 1},
    }

    repaired = repair.classify_candidate(candidate, indexes, set(), {})

    assert repaired["session_resolution"]["classification"] == repair.NEEDS_MANUAL_REVIEW
