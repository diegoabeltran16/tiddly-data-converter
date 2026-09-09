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


def test_cross_batch_reconciliation_uses_closed_semantic_taxonomy() -> None:
    old_equivalent = _candidate("rc_current_" + "1" * 24, "src/source.py", "src/target.py")
    old_modified = _candidate("rc_current_" + "2" * 24, "src/source.py", "src/other.py")
    old_disappeared = _candidate("rc_current_" + "3" * 24, "src/gone.py", "src/target.py")
    old_ambiguous = _candidate("rc_current_" + "4" * 24, "src/ambiguous.py", "src/target.py")
    invalid = {"candidate_id": "invalid"}

    current_equivalent = json.loads(json.dumps(old_equivalent))
    current_equivalent["candidate_id"] = "rc_current_" + "a" * 24
    current_equivalent["evidence"]["line"] = 999
    current_modified = json.loads(json.dumps(old_modified))
    current_modified["candidate_id"] = "rc_current_" + "b" * 24
    current_modified["evidence"]["raw_observation"] = "meaningfully changed evidence"
    current_new = _candidate("rc_current_" + "c" * 24, "src/new.py", "src/target.py")
    ambiguous_one = json.loads(json.dumps(old_ambiguous))
    ambiguous_one["candidate_id"] = "rc_current_" + "d" * 24
    ambiguous_two = json.loads(json.dumps(old_ambiguous))
    ambiguous_two["candidate_id"] = "rc_current_" + "e" * 24

    result = reconcile.build_cross_batch_reconciliation(
        [old_equivalent, old_modified, old_disappeared, old_ambiguous, invalid],
        [current_equivalent, current_modified, current_new, ambiguous_one, ambiguous_two, invalid],
    )
    old_classes = {row["candidate_id"]: row["classification"] for row in result["old_to_current"]}
    current_classes = {row["candidate_id"]: row["classification"] for row in result["current_to_old"]}
    assert old_classes[old_equivalent["candidate_id"]] == "equivalent"
    assert old_classes[old_modified["candidate_id"]] == "modified"
    assert old_classes[old_disappeared["candidate_id"]] == "disappeared"
    assert old_classes[old_ambiguous["candidate_id"]] == "ambiguous"
    assert old_classes["invalid"] == "invalid"
    assert current_classes[current_equivalent["candidate_id"]] == "equivalent"
    assert current_classes[current_modified["candidate_id"]] == "modified"
    assert current_classes[current_new["candidate_id"]] == "new"
    assert current_classes[ambiguous_one["candidate_id"]] == "ambiguous"
    assert current_classes[ambiguous_two["candidate_id"]] == "ambiguous"


def _endpoint(canonical_id: str, *, repo_lifecycle_state=None, artifact_family=None, authority_level=None) -> dict:
    endpoint = {"canonical_id": canonical_id}
    if repo_lifecycle_state is not None:
        endpoint["repo_lifecycle_state"] = repo_lifecycle_state
    if artifact_family is not None:
        endpoint["artifact_family"] = artifact_family
    if authority_level is not None:
        endpoint["authority_level"] = authority_level
    return endpoint


def test_metadata_only_drift_stays_equivalent_exact_production_case() -> None:
    """Real regression: rc_current_0180066b0091a62521673cb7 -- old carries
    artifact_family=artefacto_repositorio, authority_level=current_verified,
    repo_lifecycle_state=current_repo_artifact on both endpoints; current has
    all three nulled out by an unrelated metadata drift. The relation must
    still classify equivalent/decision_reusable, not disappeared/new.
    """
    source_id = "0abe4b56-172f-5deb-baaf-f7aa6acceb05"
    target_id = "2029fa31-d868-56f5-9110-28f9aefe21f1"
    raw_observation = (
        "from relation_admission_gate import aggregate_canon_hash, "
        "count_canon_records  # noqa: E402"
    )
    old = {
        "candidate_id": "rc_current_0180066b0091a62521673cb7",
        "candidate_schema_version": "technical-relation-candidates/v1",
        "session_origin": "CURRENT",
        "relation_type": "depende_de",
        "source": _endpoint(
            source_id, repo_lifecycle_state="current_repo_artifact",
            artifact_family="artefacto_repositorio", authority_level="current_verified",
        ),
        "target": _endpoint(
            target_id, repo_lifecycle_state="current_repo_artifact",
            artifact_family="artefacto_repositorio", authority_level="current_verified",
        ),
        "evidence": {
            "evidence_kind": "content_embedded", "raw_observation": raw_observation,
            "file": "src/python_scripts/some_module.py", "line": 40,
            "parser": "python_ast", "technical_evidence_kind": "ast_import",
        },
    }
    current = json.loads(json.dumps(old))
    current["candidate_id"] = "rc_current_" + "f" * 24
    current["source"]["repo_lifecycle_state"] = None
    current["source"]["artifact_family"] = None
    current["source"]["authority_level"] = None
    current["target"]["repo_lifecycle_state"] = None
    current["target"]["artifact_family"] = None
    current["target"]["authority_level"] = None

    result = reconcile.build_cross_batch_reconciliation([old], [current])
    old_row = result["old_to_current"][0]
    current_row = result["current_to_old"][0]
    assert old_row["classification"] == "equivalent"
    assert old_row["decision_reusable"] is True
    assert current_row["classification"] == "equivalent"
    assert current_row["decision_reusable"] is True


def test_metadata_only_drift_general_case_stays_equivalent() -> None:
    """7a: endpoint/predicate/evidence unchanged, only lifecycle metadata
    drifts (populated -> null) -- must remain equivalent."""
    old = _candidate("rc_current_" + "1" * 24, "src/source.py", "src/target.py")
    old["source"]["repo_lifecycle_state"] = "current_repo_artifact"
    old["target"]["repo_lifecycle_state"] = "current_repo_artifact"
    current = json.loads(json.dumps(old))
    current["candidate_id"] = "rc_current_" + "2" * 24
    current["source"]["repo_lifecycle_state"] = None
    current["target"]["repo_lifecycle_state"] = None

    result = reconcile.build_cross_batch_reconciliation([old], [current])
    assert result["old_to_current"][0]["classification"] == "equivalent"
    assert result["old_to_current"][0]["decision_reusable"] is True
    assert result["current_to_old"][0]["classification"] == "equivalent"


def test_same_candidate_id_reused_for_different_endpoint_is_not_equivalent() -> None:
    """7b: identical candidate_id, but the target endpoint genuinely changed
    -- must NOT be treated as equivalent (candidate_id alone is never
    sufficient proof of equivalence)."""
    old = _candidate("rc_current_" + "3" * 24, "src/source.py", "src/target.py")
    current = _candidate("rc_current_" + "3" * 24, "src/source.py", "src/different-target.py")

    result = reconcile.build_cross_batch_reconciliation([old], [current])
    assert result["old_to_current"][0]["classification"] != "equivalent"
    assert result["old_to_current"][0]["decision_reusable"] is False
    assert result["current_to_old"][0]["classification"] != "equivalent"


def test_different_predicate_is_not_equivalent() -> None:
    """7c: same endpoints, different relation_type -- must NOT be equivalent,
    even though endpoint identity alone matches."""
    old = _candidate("rc_current_" + "4" * 24, "src/source.py", "src/target.py", predicate="depende_de")
    current = _candidate("rc_current_" + "5" * 24, "src/source.py", "src/target.py", predicate="references")

    result = reconcile.build_cross_batch_reconciliation([old], [current])
    assert result["old_to_current"][0]["classification"] != "equivalent"
    assert result["current_to_old"][0]["classification"] != "equivalent"


def test_endpoint_stable_metadata_rehydrated_stays_equivalent() -> None:
    """7d: inverse direction of drift -- lifecycle metadata goes from absent
    (null) to rehydrated/populated while the endpoint identity and evidence
    stay stable -- must remain equivalent."""
    old = _candidate("rc_current_" + "6" * 24, "src/source.py", "src/target.py")
    current = json.loads(json.dumps(old))
    current["candidate_id"] = "rc_current_" + "7" * 24
    current["source"]["repo_lifecycle_state"] = "current_repo_artifact"
    current["source"]["artifact_family"] = "artefacto_repositorio"
    current["target"]["authority_level"] = "current_verified"

    result = reconcile.build_cross_batch_reconciliation([old], [current])
    assert result["old_to_current"][0]["classification"] == "equivalent"
    assert result["old_to_current"][0]["decision_reusable"] is True


def test_unrelated_inventory_growth_preserves_decision() -> None:
    """7e: the inventory growing with unrelated new candidates must not
    disturb the equivalence/reusability of an existing, unrelated relation
    (no O(N) re-review forced by growth alone)."""
    old_target = _candidate("rc_current_" + "8" * 24, "src/source.py", "src/target.py")
    old_target["source"]["repo_lifecycle_state"] = "current_repo_artifact"
    current_target = json.loads(json.dumps(old_target))
    current_target["candidate_id"] = "rc_current_" + "9" * 24
    current_target["source"]["repo_lifecycle_state"] = None

    old_unrelated = _candidate("rc_current_" + "a" * 24, "src/alpha.py", "src/beta.py")
    new_unrelated_1 = _candidate("rc_current_" + "b" * 24, "src/gamma.py", "src/delta.py")
    new_unrelated_2 = _candidate("rc_current_" + "c" * 24, "src/epsilon.py", "src/zeta.py")

    result = reconcile.build_cross_batch_reconciliation(
        [old_target, old_unrelated],
        [current_target, old_unrelated, new_unrelated_1, new_unrelated_2],
    )
    by_id = {row["candidate_id"]: row for row in result["old_to_current"]}
    assert by_id[old_target["candidate_id"]]["classification"] == "equivalent"
    assert by_id[old_target["candidate_id"]]["decision_reusable"] is True


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
