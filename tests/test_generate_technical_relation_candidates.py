from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

from generate_technical_relation_candidates import (  # noqa: E402
    BLOCKED_DUPLICATE,
    BLOCKED_UNRESOLVED,
    READY,
    build_candidates,
    validate_candidates,
    write_outputs,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _canon_record(tid: str, repo_path: str, relations: list[dict] | None = None) -> dict:
    return {
        "id": tid,
        "title": repo_path,
        "text": f"## {repo_path}",
        "relations": relations or [],
        "source_fields": {
            "artifact_family": "artefacto_repositorio",
            "authority_level": "current_verified",
            "repo_lifecycle_state": "current_repo_artifact",
            "repo_path": repo_path,
            "content_sha256": f"sha-{tid}",
        },
    }


def _write_canon(canon_root: Path, records: list[dict]) -> None:
    canon_root.mkdir(parents=True, exist_ok=True)
    shard = canon_root / "tiddlers_1.jsonl"
    shard.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def test_generates_ready_test_import_candidate(tmp_path: Path) -> None:
    _write(tmp_path / "python_scripts" / "subject.py", "VALUE = 1\n")
    _write(tmp_path / "tests" / "test_subject.py", "from python_scripts import subject\n")
    canon_root = tmp_path / "data" / "out" / "local"
    _write_canon(canon_root, [
        _canon_record("src-test", "tests/test_subject.py"),
        _canon_record("target-script", "python_scripts/subject.py"),
    ])

    candidates = build_candidates(tmp_path, canon_root)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["status"] == READY
    assert candidate["technical_relation_kind"] == "test_imports_subject"
    assert candidate["relation_type"] == "valida"
    assert candidate["source"]["canonical_id"] == "src-test"
    assert candidate["target"]["canonical_id"] == "target-script"
    assert candidate["policy"]["canonical_admission_allowed"] is False
    assert candidate["policy"]["derivation_allowed"] is False
    assert validate_candidates(candidates) == []


def test_marks_existing_canonical_relation_as_possible_duplicate(tmp_path: Path) -> None:
    _write(tmp_path / "python_scripts" / "subject.py", "VALUE = 1\n")
    _write(tmp_path / "tests" / "test_subject.py", "from python_scripts import subject\n")
    canon_root = tmp_path / "data" / "out" / "local"
    _write_canon(canon_root, [
        _canon_record("src-test", "tests/test_subject.py", [{"type": "valida", "target_id": "target-script"}]),
        _canon_record("target-script", "python_scripts/subject.py"),
    ])

    candidates = build_candidates(tmp_path, canon_root)

    assert candidates[0]["status"] == BLOCKED_DUPLICATE
    assert candidates[0]["duplicate_of"] == "canonical_relation"


def test_blocks_path_literal_when_target_has_no_canonical_mapping(tmp_path: Path) -> None:
    _write(tmp_path / "python_scripts" / "reader.py", "PATH = 'README.md'\n")
    _write(tmp_path / "README.md", "# readme\n")
    canon_root = tmp_path / "data" / "out" / "local"
    _write_canon(canon_root, [_canon_record("src-reader", "python_scripts/reader.py")])

    candidates = build_candidates(tmp_path, canon_root)

    assert len(candidates) == 1
    assert candidates[0]["status"] == BLOCKED_UNRESOLVED
    assert candidates[0]["target"]["repo_path"] == "README.md"
    assert candidates[0]["target"]["canonical_id"] is None


def test_writes_required_review_outputs(tmp_path: Path) -> None:
    _write(tmp_path / "python_scripts" / "subject.py", "VALUE = 1\n")
    _write(tmp_path / "tests" / "test_subject.py", "from python_scripts import subject\n")
    canon_root = tmp_path / "data" / "out" / "local"
    _write_canon(canon_root, [
        _canon_record("src-test", "tests/test_subject.py"),
        _canon_record("target-script", "python_scripts/subject.py"),
    ])
    candidates = build_candidates(tmp_path, canon_root)
    out_dir = tmp_path / "out"

    report = write_outputs(candidates, out_dir, canon_root)

    assert report["candidate_count"] == 1
    assert report["ready_for_review_count"] == 1
    for name in [
        "relation_candidates.jsonl",
        "relation_candidates_report.json",
        "relation_candidates_summary.md",
        "relation_candidates_review.csv",
        "relation_candidates_blocked.json",
        "relation_candidates_ready_for_review.json",
        "relation_candidates_audit_log.jsonl",
    ]:
        assert (out_dir / name).exists()
