"""S0146 tests for governed repo artifact characterization."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

import characterize_repo_artifacts as cra  # noqa: E402


def _record(
    tid: str,
    title: str,
    *,
    text: str = "",
    role: str = "log",
    tags: list[str] | None = None,
    code: str | None = None,
) -> dict:
    content = {"plain": text}
    if code is not None:
        content["code_blocks"] = [{"language": "text", "text": code}]
    return {
        "id": tid,
        "key": title,
        "title": title,
        "role_primary": role,
        "tags": tags or [],
        "source_tags": tags or [],
        "source_fields": {"canonical_status": "local_admitted"},
        "content": content,
        "text": text,
    }


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _write_lines(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def _repo_file(root: Path, rel: str, content: str = "print('ok')\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run(
    tmp_path: Path,
    monkeypatch,
    records: list[dict],
    *,
    git_files: list[str] | None = None,
    worktree_files: list[str] | None = None,
    s0145_rows: list[dict] | None = None,
    out_name: str = "out",
) -> dict:
    monkeypatch.setattr(cra, "REPO_ROOT", tmp_path)
    canon = _write_jsonl(tmp_path / "canon" / "tiddlers_1.jsonl", records)
    git_path = _write_lines(tmp_path / "git.txt", git_files or [])
    worktree_path = _write_lines(tmp_path / "worktree.txt", worktree_files if worktree_files is not None else (git_files or []))
    s0145_path = tmp_path / "s0145.jsonl"
    if s0145_rows is not None:
        _write_jsonl(s0145_path, s0145_rows)
    return cra.build_repo_artifact_outputs(
        canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
        s0145_candidates=s0145_path if s0145_rows is not None else None,
        git_files=git_path,
        worktree_files=worktree_path,
        out_dir=tmp_path / out_name,
        session="S0146",
        dry_run=True,
    )


def _classifications(result: dict) -> list[dict]:
    path = Path(result["paths"]["classification"])
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_detects_tiddler_tecnico_from_s0145(tmp_path: Path, monkeypatch) -> None:
    result = _run(
        tmp_path,
        monkeypatch,
        [_record("tech", "Entrada tecnica neutra")],
        s0145_rows=[{"id": "tech", "candidate_artifact_family": "tiddler_tecnico", "signals": ["s0145"]}],
    )

    rows = _classifications(result)
    assert len(rows) == 1
    assert rows[0]["s0145_candidate_artifact_family"] == "tiddler_tecnico"


def test_operates_without_s0145_using_only_canon(tmp_path: Path, monkeypatch) -> None:
    result = _run(tmp_path, monkeypatch, [_record("code", "Bloque", code="print('x')")])

    assert _classifications(result)[0]["diagnostic_category"] == "embedded_code_block"


def test_detects_exact_git_path(tmp_path: Path, monkeypatch) -> None:
    _repo_file(tmp_path, "python_scripts/demo.py", "print('ok')\n")
    result = _run(
        tmp_path,
        monkeypatch,
        [_record("demo", "python_scripts/demo.py", role="code", code="print('ok')\n")],
        git_files=["python_scripts/demo.py"],
    )

    row = _classifications(result)[0]
    assert row["repo_path_exists_in_git"] is True
    assert row["diagnostic_category"] == "repo_snapshot_current"


def test_detects_missing_path_as_missing_from_repo(tmp_path: Path, monkeypatch) -> None:
    result = _run(tmp_path, monkeypatch, [_record("missing", "docs/missing.md", role="code", code="old")], git_files=[])

    row = _classifications(result)[0]
    assert row["candidate_repo_lifecycle_state"] == "missing_from_repo"


def test_detects_moved_candidate_by_alternative_path(tmp_path: Path, monkeypatch) -> None:
    _repo_file(tmp_path, "esquemas/old.md", "old\n")
    result = _run(
        tmp_path,
        monkeypatch,
        [_record("old", "docs/old.md", role="code", code="old\n")],
        git_files=["esquemas/old.md"],
    )

    row = _classifications(result)[0]
    assert row["diagnostic_category"] == "moved_candidate"
    assert row["moved_to_candidate"] == "esquemas/old.md"


def test_classifies_py_as_source_code(tmp_path: Path, monkeypatch) -> None:
    _repo_file(tmp_path, "python_scripts/demo.py")
    row = _classifications(_run(tmp_path, monkeypatch, [_record("py", "python_scripts/demo.py", role="code", code="print('ok')\n")], git_files=["python_scripts/demo.py"]))[0]
    assert row["candidate_repo_artifact_kind"] == "source_code"


def test_classifies_test_py_as_test_code(tmp_path: Path, monkeypatch) -> None:
    _repo_file(tmp_path, "tests/test_demo.py")
    row = _classifications(_run(tmp_path, monkeypatch, [_record("test", "tests/test_demo.py", role="code", code="print('ok')\n")], git_files=["tests/test_demo.py"]))[0]
    assert row["candidate_repo_artifact_kind"] == "test_code"


def test_classifies_sh_as_shell_script(tmp_path: Path, monkeypatch) -> None:
    _repo_file(tmp_path, "shell_scripts/run.sh", "#!/usr/bin/env bash\n")
    row = _classifications(_run(tmp_path, monkeypatch, [_record("sh", "shell_scripts/run.sh", role="code", code="#!/usr/bin/env bash\n")], git_files=["shell_scripts/run.sh"]))[0]
    assert row["candidate_repo_artifact_kind"] == "shell_script"


def test_classifies_github_workflow_as_ci_workflow(tmp_path: Path, monkeypatch) -> None:
    _repo_file(tmp_path, ".github/workflows/ci.yml", "name: ci\n")
    row = _classifications(_run(tmp_path, monkeypatch, [_record("ci", ".github/workflows/ci.yml", role="code", code="name: ci\n")], git_files=[".github/workflows/ci.yml"]))[0]
    assert row["candidate_repo_artifact_kind"] == "ci_workflow"


def test_classifies_esquemas_as_schema(tmp_path: Path, monkeypatch) -> None:
    _repo_file(tmp_path, "esquemas/canon/rules.md", "rules\n")
    row = _classifications(_run(tmp_path, monkeypatch, [_record("schema", "esquemas/canon/rules.md", role="code", code="rules\n")], git_files=["esquemas/canon/rules.md"]))[0]
    assert row["candidate_repo_artifact_kind"] == "schema"


def test_classifies_data_out_as_generated_output(tmp_path: Path, monkeypatch) -> None:
    _repo_file(tmp_path, "data/out/local/report.json", "{}\n")
    row = _classifications(_run(tmp_path, monkeypatch, [_record("out", "data/out/local/report.json", role="code", code="{}\n")], git_files=["data/out/local/report.json"]))[0]
    assert row["diagnostic_category"] == "generated_output"
    assert row["candidate_repo_artifact_kind"] == "generated_output"


def test_distinguishes_narrative_code_reference_from_snapshot(tmp_path: Path, monkeypatch) -> None:
    text = "La sesion menciona python_scripts/demo.py como ruta revisada."
    result = _run(tmp_path, monkeypatch, [_record("session", "#### 🌀 Sesión 0146 = demo", text=text)])

    row = _classifications(result)[0]
    assert row["diagnostic_category"] == "session_or_diagnostic_narrative"
    assert row["candidate_repo_path"] == ""


def test_distinguishes_embedded_code_block_from_repo_file(tmp_path: Path, monkeypatch) -> None:
    row = _classifications(_run(tmp_path, monkeypatch, [_record("block", "Ejemplo tecnico", code="x = 1")]))[0]
    assert row["diagnostic_category"] == "embedded_code_block"


def test_does_not_declare_current_verified_for_title_only(tmp_path: Path, monkeypatch) -> None:
    _repo_file(tmp_path, "python_scripts/demo.py", "print('ok')\n")
    row = _classifications(_run(tmp_path, monkeypatch, [_record("title", "python_scripts/demo.py", role="code")], git_files=["python_scripts/demo.py"]))[0]
    assert row["candidate_authority_level"] != "current_verified"
    assert row["content_comparison"] == "no_comparable_code_block"


def test_requires_positive_comparison_for_current_verified(tmp_path: Path, monkeypatch) -> None:
    _repo_file(tmp_path, "python_scripts/demo.py", "print('ok')\n")
    row = _classifications(_run(tmp_path, monkeypatch, [_record("hash", "python_scripts/demo.py", role="code", code="print('ok')\n")], git_files=["python_scripts/demo.py"]))[0]
    assert row["candidate_authority_level"] == "current_verified"
    assert row["content_comparison"] == "exact_match"


def test_declares_applied_to_canon_false(tmp_path: Path, monkeypatch) -> None:
    row = _classifications(_run(tmp_path, monkeypatch, [_record("block", "Ejemplo tecnico", code="x = 1")]))[0]
    assert row["applied_to_canon"] is False


def test_relation_opportunities_are_not_formal_candidates(tmp_path: Path, monkeypatch) -> None:
    _repo_file(tmp_path, "python_scripts/demo.py", "print('ok')\n")
    result = _run(tmp_path, monkeypatch, [_record("demo", "python_scripts/demo.py", role="code", code="print('ok')\n")], git_files=["python_scripts/demo.py"])
    path = Path(result["paths"]["relation_opportunities"])
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows
    assert {row["formal_relation_candidate"] for row in rows} == {False}


def test_classification_jsonl_is_valid(tmp_path: Path, monkeypatch) -> None:
    result = _run(tmp_path, monkeypatch, [_record("block", "Ejemplo tecnico", code="x = 1")])
    rows = _classifications(result)
    assert rows[0]["dry_run"] is True


def test_review_csv_contains_minimum_columns(tmp_path: Path, monkeypatch) -> None:
    result = _run(tmp_path, monkeypatch, [_record("block", "Ejemplo tecnico", code="x = 1")])
    with Path(result["paths"]["review"]).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == cra.REVIEW_COLUMNS


def test_output_is_deterministic(tmp_path: Path, monkeypatch) -> None:
    records = [_record("block", "Ejemplo tecnico", code="x = 1")]
    first = _run(tmp_path, monkeypatch, records, out_name="out1")
    second = _run(tmp_path, monkeypatch, records, out_name="out2")
    first_hash = hashlib.sha256(Path(first["paths"]["classification"]).read_bytes()).hexdigest()
    second_hash = hashlib.sha256(Path(second["paths"]["classification"]).read_bytes()).hexdigest()
    assert first_hash == second_hash


def test_does_not_modify_input_canon_jsonl(tmp_path: Path, monkeypatch) -> None:
    canon = _write_jsonl(tmp_path / "canon" / "tiddlers_1.jsonl", [_record("block", "Ejemplo tecnico", code="x = 1")])
    before = hashlib.sha256(canon.read_bytes()).hexdigest()
    monkeypatch.setattr(cra, "REPO_ROOT", tmp_path)
    cra.build_repo_artifact_outputs(
        canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
        s0145_candidates=None,
        git_files=_write_lines(tmp_path / "git.txt", []),
        worktree_files=_write_lines(tmp_path / "worktree.txt", []),
        out_dir=tmp_path / "out",
        session="S0146",
        dry_run=True,
    )
    assert hashlib.sha256(canon.read_bytes()).hexdigest() == before
