from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "src" / "python_scripts"
sys.path.insert(0, str(SCRIPTS))

import reconcile_current_relation_candidates as reconcile  # noqa: E402


def _record(identifier: str, repo_path: str, relations: list[dict] | None = None) -> dict:
    return {
        "id": identifier,
        "title": repo_path,
        "key": repo_path,
        "version_id": f"sha256:{identifier}",
        "source_fields": {"repo_path": repo_path},
        "relations": relations or [],
    }


def _candidate(identifier: str, source: str, target: str, predicate: str = "references", *, evidence: bool = True) -> dict:
    return {
        "candidate_id": identifier,
        "candidate_schema_version": "technical-relation-candidates/v1",
        "session_origin": "CURRENT",
        "relation_type": predicate,
        "source": {"repo_path": source},
        "target": {"repo_path": target},
        "evidence": {"evidence_kind": "content_embedded", "raw_observation": f"{identifier} evidence", "file": source, "line": 1} if evidence else {},
        "policy": {"canonical_admission_allowed": False, "derivation_allowed": False, "human_review_required": True},
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _setup(tmp_path: Path, rows: list[dict], canon_rows: list[dict] | None = None) -> tuple[Path, Path, Path]:
    local = tmp_path / "data" / "out" / "local"
    canon = local
    _write_jsonl(canon / "tiddlers_1.jsonl", canon_rows or [
        _record("source", "src/source.py"),
        _record("target", "src/target.py"),
    ])
    current = local / "pipeline" / "relation_candidates" / "current"
    _write_jsonl(current / "relation_candidates.jsonl", rows)
    productive = local / "audit" / "rag_admission" / "productive_rag_manifest.json"
    productive.parent.mkdir(parents=True, exist_ok=True)
    productive.write_text(json.dumps({"technical_gate": "PASS", "governance_gate": "PASS"}), encoding="utf-8")
    return canon, current, productive


def _run(canon: Path, current: Path, productive: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    baseline = out / "pre_relational_rag_baseline_manifest.json"
    if not baseline.exists():
        baseline.write_text(json.dumps({"schema_version": "pre-relational-rag-baseline/v1", "fixture": True}) + "\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS / "reconcile_current_relation_candidates.py"), "--canon-root", str(canon), "--current-dir", str(current), "--out-dir", str(out), "--productive-manifest", str(productive)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_reconciles_allowed_dispositions_and_preserves_input(tmp_path: Path) -> None:
    rows = [
        _candidate("ready", "src/source.py", "src/target.py"),
        _candidate("exact", "src/source.py", "src/target.py"),
        _candidate("different-evidence", "src/source.py", "src/target.py"),
        _candidate("unknown-target", "src/source.py", "urn:placeholder"),
        _candidate("unsupported", "src/source.py", "src/target.py", "invented"),
        _candidate("self", "src/source.py", "src/source.py"),
        _candidate("no-evidence", "src/source.py", "src/target.py", evidence=False),
    ]
    rows[1]["evidence"]["raw_observation"] = rows[0]["evidence"]["raw_observation"]
    rows[2]["evidence"]["raw_observation"] = "different provenance"
    canon, current, productive = _setup(tmp_path, rows)
    original = hashlib.sha256((current / "relation_candidates.jsonl").read_bytes()).hexdigest()
    result = _run(canon, current, productive, tmp_path / "audit")
    matrix = [json.loads(line) for line in (tmp_path / "audit" / "candidate_reconciliation_matrix.jsonl").read_text().splitlines()]
    dispositions = {row["candidate_id"]: row["disposition"] for row in matrix}
    assert result["unclassified"] == 0
    assert dispositions == {
        "ready": "ready_for_review",
        "exact": "exact_duplicate",
        "different-evidence": "ready_for_review",
        "unknown-target": "unresolved_target",
        "unsupported": "unsupported_predicate",
        "self": "self_reference",
        "no-evidence": "insufficient_evidence",
    }
    assert hashlib.sha256((current / "relation_candidates.jsonl").read_bytes()).hexdigest() == original


def test_legacy_equivalence_and_ambiguous_mapping_are_not_promoted(tmp_path: Path) -> None:
    canon_rows = [
        _record("source", "src/source.py", [{"type": "references", "target_id": "target"}]),
        _record("target", "src/target.py"),
        _record("one", "src/ambiguous.py"),
        _record("two", "src/ambiguous.py"),
    ]
    rows = [_candidate("legacy", "src/source.py", "src/target.py"), _candidate("ambiguous", "src/ambiguous.py", "src/target.py")]
    canon, current, productive = _setup(tmp_path, rows, canon_rows)
    _run(canon, current, productive, tmp_path / "audit")
    matrix = [json.loads(line) for line in (tmp_path / "audit" / "candidate_reconciliation_matrix.jsonl").read_text().splitlines()]
    values = {row["candidate_id"]: row for row in matrix}
    assert values["legacy"]["disposition"] == "ready_for_review"
    assert values["legacy"]["canon_admitted"] is False
    assert values["ambiguous"]["disposition"] == "not_canonicalizable"
    assert all(row["candidate_authority"] == "candidate" for row in matrix)
    assert all(row["canonical_authority_granted"] is False for row in matrix)


def test_reviewable_manifest_tracks_staleness_inputs_and_canon_binding(tmp_path: Path) -> None:
    canon, current, productive = _setup(tmp_path, [_candidate("ready", "src/source.py", "src/target.py")])
    out_one = tmp_path / "audit-one"
    baseline_hash = hashlib.sha256(b'{"schema_version": "pre-relational-rag-baseline/v1", "fixture": true}\n').hexdigest()
    _run(canon, current, productive, out_one)
    manifest_one = json.loads((current / "reviewable_candidate_manifest.json").read_text())
    assert manifest_one["authority"] == "technical_review_queue"
    assert manifest_one["human_reviewed"] is False
    assert manifest_one["canon_admitted"] is False
    assert manifest_one["canon_hash"]
    assert hashlib.sha256((out_one / "pre_relational_rag_baseline_manifest.json").read_bytes()).hexdigest() == baseline_hash
    with (canon / "tiddlers_1.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_record("other", "src/other.py")) + "\n")
    _run(canon, current, productive, out_one)
    manifest_two = json.loads((current / "reviewable_candidate_manifest.json").read_text())
    assert manifest_one["canon_hash"] != manifest_two["canon_hash"]
    assert hashlib.sha256((out_one / "pre_relational_rag_baseline_manifest.json").read_bytes()).hexdigest() == baseline_hash


def test_outputs_never_emit_canonical_or_admission_authority(tmp_path: Path) -> None:
    canon, current, productive = _setup(tmp_path, [_candidate("ready", "src/source.py", "src/target.py")])
    _run(canon, current, productive, tmp_path / "audit")
    matrix = [json.loads(line) for line in (tmp_path / "audit" / "candidate_reconciliation_matrix.jsonl").read_text().splitlines()]
    assert all(row.get("relation_schema") != "canonical-relation/v1" for row in matrix)
    emitted = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "audit").iterdir() if path.is_file())
    assert "approved_for_admission" not in emitted
