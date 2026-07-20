from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "src/python_scripts/relation_admission_state.py"


def test_state_audit_works_without_data_tmp(tmp_path: Path) -> None:
    local = tmp_path / "data/out/local"
    local.mkdir(parents=True)
    (local / "tiddlers_1.jsonl").write_text(
        json.dumps({"id": "fixture", "title": "Fixture", "relations": []}) + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "audit", "--local-root", str(local)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["tmp_dependency"] is False
    assert not (tmp_path / "data/tmp").exists()
    assert (local / "audit/relation_admission/current/relational_operational_state.json").exists()


def test_validate_currentness_returns_two_for_incomplete_fixture(tmp_path: Path) -> None:
    local = tmp_path / "local"
    local.mkdir()
    (local / "tiddlers_1.jsonl").write_text("{}\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "validate-currentness", "--local-root", str(local)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["verdict"] == "NO_CURRENT_RELATION_CANDIDATE_MANIFEST"
