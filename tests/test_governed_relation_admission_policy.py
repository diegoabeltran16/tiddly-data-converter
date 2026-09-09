from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import governed_relation_admission_policy as gpol  # noqa: E402
import current_relation_human_review as human_review  # noqa: E402


def _candidate(
    candidate_id: str, *, kind: str, predicate: str,
    source_id: str = "src-id", target_id: str | None = "tgt-id",
    source_path: str = "src/python_scripts/a.py",
    target_path: str = "src/python_scripts/b.py",
    technical_evidence_kind: str = "ast_import",
    parser: str = "python_ast",
    raw_observation: str = "import b",
) -> dict:
    return {
        "candidate_id": candidate_id,
        "candidate_schema_version": "technical-relation-candidates/v1",
        "technical_relation_kind": kind,
        "relation_type": predicate,
        "source": {"canonical_id": source_id, "repo_path": source_path},
        "target": {"canonical_id": target_id, "repo_path": target_path},
        "evidence": {
            "evidence_kind": "content_embedded",
            "technical_evidence_kind": technical_evidence_kind,
            "parser": parser,
            "raw_observation": raw_observation,
            "confidence": "high",
        },
    }


def _bindings(salt: str = "a") -> dict[str, str]:
    return {
        "canon_hash": ("1" * 63) + salt[:1],
        "candidate_manifest_hash": ("2" * 63) + salt[:1],
        "reconciliation_manifest_hash": ("3" * 63) + salt[:1],
    }


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_policy_hash_is_deterministic_across_registry_rebuilds() -> None:
    first = {p.policy_id: p.policy_hash for p in gpol.build_policy_registry()}
    second = {p.policy_id: p.policy_hash for p in gpol.build_policy_registry()}
    assert first == second
    assert len(first) == len(gpol.build_policy_registry())


def test_policy_hash_ignores_rationale_wording() -> None:
    policies = list(gpol.build_policy_registry())
    ast_policy = next(p for p in policies if p.policy_id == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    import dataclasses
    reworded = dataclasses.replace(ast_policy, rationale="completely different prose")
    assert reworded.policy_hash == ast_policy.policy_hash


def test_candidate_set_hash_is_deterministic_and_order_independent() -> None:
    ids = ["rc_current_" + f"{n:024x}" for n in range(1, 6)]
    assert gpol.eligible_candidate_set_hash(ids) == gpol.eligible_candidate_set_hash(list(reversed(ids)))
    assert gpol.eligible_candidate_set_hash(ids) != gpol.eligible_candidate_set_hash(ids[:-1])


def test_same_current_input_yields_same_partition() -> None:
    policies = gpol.build_policy_registry()
    candidates = {
        "rc_current_" + "1" * 24: _candidate("rc_current_" + "1" * 24, kind="python_ast_import", predicate="depende_de"),
        "rc_current_" + "2" * 24: _candidate(
            "rc_current_" + "2" * 24, kind="test_imports_subject", predicate="valida",
            source_path="tests/test_foo.py", target_path="src/python_scripts/foo.py",
        ),
    }
    review_reasons = {cid: "new" for cid in candidates}
    first = gpol.partition_pending_candidates(policies, list(candidates), candidates, review_reasons)
    second = gpol.partition_pending_candidates(policies, list(candidates), candidates, review_reasons)
    assert first == second


# ---------------------------------------------------------------------------
# Authorization scope binding / invalidation
# ---------------------------------------------------------------------------

def test_authorization_scope_changes_with_policy_hash() -> None:
    policies = gpol.build_policy_registry()
    ast_policy = next(p for p in policies if p.policy_id == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    ids = ["rc_current_" + "1" * 24]
    bindings = _bindings()
    scope_a = gpol.build_policy_authorization_scope(ast_policy, ids, bindings)

    import dataclasses
    bumped = dataclasses.replace(ast_policy, policy_version="1.0.1")
    scope_b = gpol.build_policy_authorization_scope(bumped, ids, bindings)

    assert scope_a["policy_hash"] != scope_b["policy_hash"]


def test_authorization_scope_changes_with_eligible_set() -> None:
    policies = gpol.build_policy_registry()
    ast_policy = next(p for p in policies if p.policy_id == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    bindings = _bindings()
    scope_a = gpol.build_policy_authorization_scope(ast_policy, ["rc_current_" + "1" * 24], bindings)
    scope_b = gpol.build_policy_authorization_scope(
        ast_policy, ["rc_current_" + "1" * 24, "rc_current_" + "2" * 24], bindings,
    )
    assert scope_a["eligible_candidate_set_hash"] != scope_b["eligible_candidate_set_hash"]
    assert scope_a["eligible_candidate_count"] != scope_b["eligible_candidate_count"]


def test_authorization_scope_changes_with_canon_hash() -> None:
    policies = gpol.build_policy_registry()
    ast_policy = next(p for p in policies if p.policy_id == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    ids = ["rc_current_" + "1" * 24]
    scope_a = gpol.build_policy_authorization_scope(ast_policy, ids, _bindings("a"))
    scope_b = gpol.build_policy_authorization_scope(ast_policy, ids, _bindings("b"))
    assert scope_a["canon_hash"] != scope_b["canon_hash"]


# ---------------------------------------------------------------------------
# Fail-closed exclusions -- never auto-approve
# ---------------------------------------------------------------------------

def test_reconciliation_ambiguous_never_policy_eligible_even_if_kind_matches() -> None:
    policies = gpol.build_policy_registry()
    cid = "rc_current_" + "1" * 24
    candidate = _candidate(cid, kind="python_ast_import", predicate="depende_de")
    partition = gpol.partition_pending_candidates(policies, [cid], {cid: candidate}, {cid: "reconciliation_ambiguous"})
    assert partition["by_policy"]["PYTHON_AST_IMPORT_DEPENDENCY_V1"] == []
    assert partition["exceptions"] == [{"candidate_id": cid, "reason_code": "reconciliation_ambiguous_never_auto"}]


def test_unresolved_endpoint_is_never_eligible() -> None:
    cid = "rc_current_" + "1" * 24
    candidate = _candidate(cid, kind="python_ast_import", predicate="depende_de", target_id=None)
    eligible, reason = gpol._evaluate_python_ast_import(candidate)
    assert eligible is False
    assert reason == "endpoint_not_uniquely_resolved_or_self_reference"


def test_self_reference_is_never_eligible() -> None:
    cid = "rc_current_" + "1" * 24
    candidate = _candidate(cid, kind="python_ast_import", predicate="depende_de", source_id="same", target_id="same")
    eligible, reason = gpol._evaluate_python_ast_import(candidate)
    assert eligible is False
    assert reason == "endpoint_not_uniquely_resolved_or_self_reference"


def test_parser_evidence_mismatch_is_an_exception_not_a_silent_pass() -> None:
    cid = "rc_current_" + "1" * 24
    candidate = _candidate(cid, kind="python_ast_import", predicate="depende_de", technical_evidence_kind="path_literal")
    eligible, reason = gpol._evaluate_python_ast_import(candidate)
    assert eligible is False
    assert reason == "parser_evidence_mismatch"


def test_predicate_mismatch_is_an_exception() -> None:
    cid = "rc_current_" + "1" * 24
    candidate = _candidate(cid, kind="python_ast_import", predicate="references")
    eligible, reason = gpol._evaluate_python_ast_import(candidate)
    assert eligible is False
    assert reason == "predicate_mismatch"


def test_reads_and_writes_are_always_unsupported_regardless_of_evidence_quality() -> None:
    policies = {p.policy_id: p for p in gpol.build_policy_registry()}
    strong_looking = _candidate(
        "rc_current_" + "1" * 24, kind="script_reads_path", predicate="references",
        technical_evidence_kind="path_literal", source_path="src/python_scripts/a.py",
    )
    eligible, reason = policies["SCRIPT_PATH_READ_UNSUPPORTED_V1"].evaluate(strong_looking)
    assert eligible is False
    assert reason == "multi_segment_path_join_misresolution_risk_demonstrated"


# ---------------------------------------------------------------------------
# test_imports_subject basename correspondence
# ---------------------------------------------------------------------------

def test_strict_basename_correspondence_is_eligible() -> None:
    cid = "rc_current_" + "1" * 24
    candidate = _candidate(
        cid, kind="test_imports_subject", predicate="valida",
        source_path="tests/test_foo.py", target_path="src/python_scripts/foo.py",
    )
    eligible, reason = gpol._evaluate_test_imports_subject(candidate)
    assert eligible is True
    assert reason is None


def test_weak_basename_correspondence_is_a_named_exception() -> None:
    cid = "rc_current_" + "1" * 24
    candidate = _candidate(
        cid, kind="test_imports_subject", predicate="valida",
        source_path="tests/test_relation_correspondence_matrix.py",
        target_path="src/python_scripts/build_relation_correspondence_matrix.py",
    )
    eligible, reason = gpol._evaluate_test_imports_subject(candidate)
    assert eligible is False
    assert reason == "subject_basename_correspondence_not_demonstrated"


# ---------------------------------------------------------------------------
# script_references_path source scope + ephemeral-join exclusion
# ---------------------------------------------------------------------------

def test_production_sourced_reference_is_eligible() -> None:
    cid = "rc_current_" + "1" * 24
    candidate = _candidate(
        cid, kind="script_references_path", predicate="references",
        technical_evidence_kind="path_literal",
        source_path="src/python_scripts/operator_menu.py",
        target_path="src/python_scripts/derive_layers.py",
        raw_observation='"src/python_scripts/derive_layers.py",',
    )
    eligible, reason = gpol._evaluate_script_references_path(candidate)
    assert eligible is True
    assert reason is None


def test_test_sourced_reference_is_a_named_exception() -> None:
    cid = "rc_current_" + "1" * 24
    candidate = _candidate(
        cid, kind="script_references_path", predicate="references",
        technical_evidence_kind="path_literal",
        source_path="tests/test_something.py",
        target_path="README.md",
        raw_observation='"README.md"',
    )
    eligible, reason = gpol._evaluate_script_references_path(candidate)
    assert eligible is False
    assert reason == "test_sourced_literal_fixture_noise_risk"


def test_ephemeral_path_join_is_excluded_even_from_production_source() -> None:
    # Defense in depth: even if a production file did this, it must not pass.
    cid = "rc_current_" + "1" * 24
    candidate = _candidate(
        cid, kind="script_references_path", predicate="references",
        technical_evidence_kind="path_literal",
        source_path="src/python_scripts/weird.py",
        target_path="README.md",
        raw_observation='(tmp_path / "README.md")',
    )
    eligible, reason = gpol._evaluate_script_references_path(candidate)
    assert eligible is False
    assert reason == "ephemeral_path_join_misresolution_risk"


# ---------------------------------------------------------------------------
# Partition exhaustiveness / disjointness
# ---------------------------------------------------------------------------

def test_partition_is_exhaustive_disjoint_and_matches_pending_universe() -> None:
    policies = gpol.build_policy_registry()
    candidates = {}
    review_reasons = {}
    specs = [
        ("python_ast_import", "depende_de", "new"),
        ("test_imports_subject", "valida", "new"),
        ("script_references_path", "references", "new"),
        ("script_reads_path", "references", "new"),
        ("script_writes_artifact", "produce_artefacto", "new"),
    ]
    for index, (kind, predicate, reason) in enumerate(specs, start=1):
        cid = "rc_current_" + f"{index:024x}"
        candidates[cid] = _candidate(
            cid, kind=kind, predicate=predicate,
            source_path=f"tests/test_x{index}.py" if kind == "test_imports_subject" else f"src/python_scripts/x{index}.py",
            target_path=f"src/python_scripts/x{index}.py" if kind == "test_imports_subject" else f"src/python_scripts/y{index}.py",
            technical_evidence_kind="path_literal" if kind.startswith("script_") else "ast_import",
        )
        review_reasons[cid] = reason
    ambiguous_id = "rc_current_" + "f" * 24
    candidates[ambiguous_id] = _candidate(ambiguous_id, kind="python_ast_import", predicate="depende_de")
    review_reasons[ambiguous_id] = "reconciliation_ambiguous"

    pending_ids = list(candidates)
    partition = gpol.partition_pending_candidates(policies, pending_ids, candidates, review_reasons)

    all_partitioned_ids = [cid for ids in partition["by_policy"].values() for cid in ids]
    all_partitioned_ids += [item["candidate_id"] for item in partition["exceptions"]]
    assert sorted(all_partitioned_ids) == sorted(pending_ids)
    assert len(all_partitioned_ids) == len(set(all_partitioned_ids))
    assert partition["total_pending"] == len(pending_ids)
    assert ambiguous_id not in [cid for ids in partition["by_policy"].values() for cid in ids]


# ---------------------------------------------------------------------------
# Provenance: policy_derived is distinguishable, never falsified
# ---------------------------------------------------------------------------

def test_policy_derived_decision_carries_distinct_provenance() -> None:
    policies = {p.policy_id: p for p in gpol.build_policy_registry()}
    policy = policies["PYTHON_AST_IMPORT_DEPENDENCY_V1"]
    cid = "rc_current_" + "1" * 24
    candidate = _candidate(cid, kind="python_ast_import", predicate="depende_de")

    record = gpol.materialize_policy_decision(
        policy, candidate, actor="operator", bindings=_bindings(),
        human_authorization_id="auth_" + "a" * 24,
        reviewed_at="2026-09-02T00:00:00+00:00",
    )

    assert record["decision_mode"] == "policy_derived"
    assert record["decision_mode"] not in ("individual", "batch")
    assert record["review_policy_id"] == "PYTHON_AST_IMPORT_DEPENDENCY_V1"
    assert record["policy_version"] == policy.policy_version
    assert record["policy_hash"] == policy.policy_hash
    assert record["human_authorization_id"] == "auth_" + "a" * 24
    assert record["authorization_scope"] == "CURRENT_BATCH"
    assert record["human_review_decision"] == "approved_for_admission"
    assert record["human_review_reason_code"] == "DIRECT_CODE_DEPENDENCY_CONFIRMED"


def test_policy_derived_decision_passes_the_real_admission_validator() -> None:
    import relation_admission_gate as gate

    policies = {p.policy_id: p for p in gpol.build_policy_registry()}
    policy = policies["PYTHON_AST_IMPORT_DEPENDENCY_V1"]
    cid = "rc_current_" + "1" * 24
    candidate = _candidate(cid, kind="python_ast_import", predicate="depende_de")

    record = gpol.materialize_policy_decision(
        policy, candidate, actor="operator", bindings=_bindings(),
        human_authorization_id="auth_" + "a" * 24,
    )

    assert gate.validate_human_review_decision_record(record) == []


def test_policy_derived_decision_missing_governed_fields_fails_closed() -> None:
    import relation_admission_gate as gate

    record = {
        "schema_version": gate.SCHEMA_HUMAN_DECISION_LINE,
        "session_id": "S0181",
        "candidate_id": "rc_current_" + "1" * 24,
        "source_canon_id": "src-id",
        "target_canon_id": "tgt-id",
        "predicate": "depende_de",
        "relation_schema_version": "technical-relation-candidates/v1",
        "evidence": {},
        "human_review_decision": "approved_for_admission",
        "human_review_reason_code": "DIRECT_CODE_DEPENDENCY_CONFIRMED",
        "human_review_note": None,
        "decision_mode": "policy_derived",
        "decision_batch_id": None,
        "review_policy_id": None,
        "multi_review_operation_id": None,
        "supersedes_decision_hash": None,
        "human_review_actor": "operator",
        "human_review_timestamp": "2026-09-02T00:00:00+00:00",
        "approval_scope": "canonical_admission",
        "reviewed_evidence_paths": [],
        **_bindings(),
    }
    errors = gate.validate_human_review_decision_record(record)
    assert any("review_policy_id" in error for error in errors)
    assert any("policy_version" in error for error in errors)
    assert any("policy_hash" in error for error in errors)
    assert any("human_authorization_id" in error for error in errors)
    assert any("authorization_scope" in error for error in errors)


def test_batch_and_individual_decision_modes_still_validate_unchanged() -> None:
    import relation_admission_gate as gate

    base = {
        "schema_version": gate.SCHEMA_HUMAN_DECISION_LINE,
        "session_id": "S0181",
        "candidate_id": "rc_current_" + "1" * 24,
        "source_canon_id": "src-id",
        "target_canon_id": "tgt-id",
        "predicate": "depende_de",
        "relation_schema_version": "technical-relation-candidates/v1",
        "evidence": {},
        "human_review_decision": "approved_for_admission",
        "human_review_reason_code": "DIRECT_CODE_DEPENDENCY_CONFIRMED",
        "human_review_note": None,
        "decision_batch_id": None,
        "review_policy_id": None,
        "multi_review_operation_id": None,
        "supersedes_decision_hash": None,
        "human_review_actor": "operator",
        "human_review_timestamp": "2026-09-02T00:00:00+00:00",
        "approval_scope": "canonical_admission",
        "reviewed_evidence_paths": [],
        **_bindings(),
    }
    individual = {**base, "decision_mode": "individual"}
    assert gate.validate_human_review_decision_record(individual) == []
    batch = {**base, "decision_mode": "batch", "decision_batch_id": "hrb_" + "a" * 24}
    assert gate.validate_human_review_decision_record(batch) == []


def test_materialize_refuses_a_candidate_the_policy_does_not_actually_admit() -> None:
    policies = {p.policy_id: p for p in gpol.build_policy_registry()}
    policy = policies["PYTHON_AST_IMPORT_DEPENDENCY_V1"]
    cid = "rc_current_" + "1" * 24
    non_eligible = _candidate(cid, kind="python_ast_import", predicate="depende_de", target_id=None)
    try:
        gpol.materialize_policy_decision(
            policy, non_eligible, actor="operator", bindings=_bindings(), human_authorization_id="auth_" + "a" * 24,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for a non-eligible candidate")


def test_unsupported_policy_refuses_to_materialize_any_decision() -> None:
    policies = {p.policy_id: p for p in gpol.build_policy_registry()}
    policy = policies["SCRIPT_PATH_READ_UNSUPPORTED_V1"]
    cid = "rc_current_" + "1" * 24
    candidate = _candidate(cid, kind="script_reads_path", predicate="references", technical_evidence_kind="path_literal")
    try:
        gpol.materialize_policy_decision(
            policy, candidate, actor="operator", bindings=_bindings(), human_authorization_id="auth_" + "a" * 24,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError: unsupported policy has no approving decision_effect")


# ---------------------------------------------------------------------------
# Read-only preview against a real (fixture) CURRENT bundle -- writes nothing
# ---------------------------------------------------------------------------

def test_preview_against_fixture_bundle_writes_nothing(tmp_path: Path) -> None:
    local_root = tmp_path / "local"
    current_dir = local_root / "pipeline" / "relation_candidates" / "current"
    current_dir.mkdir(parents=True)
    audit_dir = local_root / "audit" / "relation_admission"
    audit_dir.mkdir(parents=True)

    cid_eligible = "rc_current_" + "1" * 24
    cid_exception = "rc_current_" + "2" * 24
    candidates = [
        _candidate(cid_eligible, kind="python_ast_import", predicate="depende_de"),
        _candidate(
            cid_exception, kind="test_imports_subject", predicate="valida",
            source_path="tests/test_other.py", target_path="src/python_scripts/unrelated.py",
        ),
    ]
    (current_dir / human_review.QUEUE_FILE).write_text(
        "".join(json.dumps(c) + "\n" for c in candidates), encoding="utf-8",
    )
    (current_dir / human_review.DECISIONS_FILE).write_text("", encoding="utf-8")
    (current_dir / "current_candidate_manifest.json").write_text('{"schema":"x"}', encoding="utf-8")
    (current_dir / "reconciliation_manifest.json").write_text('{"schema":"y"}', encoding="utf-8")

    bundle_dir = local_root / "audit" / "relation_admission" / "generations" / "rg_test" / "rv_test" / "human_delta"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "current_human_delta_manifest.json").write_text(json.dumps({
        "review_candidates": [
            {"candidate_id": cid_eligible, "review_reason": "reconciliation_new"},
            {"candidate_id": cid_exception, "review_reason": "reconciliation_new"},
        ],
    }), encoding="utf-8")
    (audit_dir / "current_generation.json").write_text(json.dumps({
        "bundle_path": str(bundle_dir),
    }), encoding="utf-8")

    before_tree = sorted(p.relative_to(local_root) for p in local_root.rglob("*") if p.is_file())
    before_hashes = {p.relative_to(local_root): p.read_bytes() for p in local_root.rglob("*") if p.is_file()}

    preview = gpol.build_current_policy_preview(local_root)

    after_tree = sorted(p.relative_to(local_root) for p in local_root.rglob("*") if p.is_file())
    after_hashes = {p.relative_to(local_root): p.read_bytes() for p in local_root.rglob("*") if p.is_file()}
    assert before_tree == after_tree
    assert before_hashes == after_hashes

    assert preview["current_pending_total"] == 2
    assert preview["policy_eligible_total"] == 1
    assert preview["human_exception_total"] == 1
    ast_summary = next(p for p in preview["policies"] if p["policy_id"] == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    assert ast_summary["eligible_count"] == 1
    assert "authorization_scope" in ast_summary


# ---------------------------------------------------------------------------
# Materialization: authorization -> persisted policy_derived decisions
# ---------------------------------------------------------------------------

def _build_fixture_current(
    tmp_path: Path, *, candidates: list[dict], review_reasons: dict[str, str],
    existing_decisions: list[dict] | None = None, canon_text: str = "canon-v1",
) -> Path:
    local_root = tmp_path / "local"
    current_dir = local_root / "pipeline" / "relation_candidates" / "current"
    current_dir.mkdir(parents=True)
    (local_root / "tiddlers_1.jsonl").write_text(canon_text, encoding="utf-8")

    (current_dir / human_review.QUEUE_FILE).write_text(
        "".join(json.dumps(c) + "\n" for c in candidates), encoding="utf-8",
    )
    (current_dir / human_review.DECISIONS_FILE).write_text(
        "".join(json.dumps(d) + "\n" for d in (existing_decisions or [])), encoding="utf-8",
    )
    (current_dir / "current_candidate_manifest.json").write_text('{"schema":"x"}', encoding="utf-8")
    (current_dir / "reconciliation_manifest.json").write_text('{"schema":"y"}', encoding="utf-8")

    audit_dir = local_root / "audit" / "relation_admission"
    bundle_dir = audit_dir / "generations" / "rg_test" / "rv_test" / "human_delta"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "current_human_delta_manifest.json").write_text(json.dumps({
        "review_candidates": [
            {"candidate_id": cid, "review_reason": reason} for cid, reason in review_reasons.items()
        ],
    }), encoding="utf-8")
    (audit_dir / "current_generation.json").write_text(json.dumps({
        "bundle_path": str(bundle_dir),
    }), encoding="utf-8")
    return local_root


def _authorize_ast_policy(local_root: Path, actor: str = "tester") -> dict:
    policy = next(p for p in gpol.build_policy_registry() if p.policy_id == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    state = gpol.load_current_pending(local_root)
    partition = gpol.partition_pending_candidates(
        gpol.build_policy_registry(), state["pending_ids"], state["by_id"], state["review_reason_by_id"],
    )
    eligible_ids = partition["by_policy"]["PYTHON_AST_IMPORT_DEPENDENCY_V1"]
    return gpol.write_policy_authorization(
        policy, eligible_ids, state["bindings"], actor=actor,
        confirmation=gpol.authorization_confirmation_phrase(policy.policy_id),
        authorizations_dir=local_root / "audit" / "relation_admission" / "current" / "policy_authorizations",
    )


def _two_ast_candidates() -> tuple[str, str, list[dict]]:
    cid_a = "rc_current_" + "1" * 24
    cid_b = "rc_current_" + "2" * 24
    candidates = [
        _candidate(cid_a, kind="python_ast_import", predicate="depende_de", source_path="src/python_scripts/a.py", target_path="src/python_scripts/b.py"),
        _candidate(cid_b, kind="python_ast_import", predicate="depende_de", source_path="src/python_scripts/c.py", target_path="src/python_scripts/d.py"),
    ]
    return cid_a, cid_b, candidates


def test_materialize_valid_authorization_persists_decisions(tmp_path: Path) -> None:
    cid_a, cid_b, candidates = _two_ast_candidates()
    local_root = _build_fixture_current(
        tmp_path, candidates=candidates, review_reasons={cid_a: "reconciliation_new", cid_b: "reconciliation_new"},
    )
    authorization = _authorize_ast_policy(local_root)

    receipt = gpol.materialize_authorized_policy(
        local_root, policy_id="PYTHON_AST_IMPORT_DEPENDENCY_V1", authorization=authorization, actor="tester",
    )

    assert receipt["materialized_count"] == 2
    assert receipt["canon_modified"] is False
    assert receipt["apply_executed"] is False
    decisions_path = local_root / "pipeline" / "relation_candidates" / "current" / human_review.DECISIONS_FILE
    rows = {row["candidate_id"]: row for row in human_review.load_jsonl(decisions_path)}
    assert set(rows) == {cid_a, cid_b}
    for row in rows.values():
        assert row["decision_mode"] == "policy_derived"
        assert row["human_review_decision"] == "approved_for_admission"
        assert row["review_policy_id"] == "PYTHON_AST_IMPORT_DEPENDENCY_V1"
        assert row["human_authorization_id"] == authorization["authorization_id"]
        assert row["authorization_scope"] == "CURRENT_BATCH"
    # The authorization file itself is marked consumed on disk.
    auth_path = (
        local_root / "audit" / "relation_admission" / "current" / "policy_authorizations"
        / f"{authorization['authorization_id']}.json"
    )
    assert json.loads(auth_path.read_text())["consumed"] is True


def test_materialize_does_not_touch_canon_files(tmp_path: Path) -> None:
    cid_a, cid_b, candidates = _two_ast_candidates()
    local_root = _build_fixture_current(
        tmp_path, candidates=candidates, review_reasons={cid_a: "reconciliation_new", cid_b: "reconciliation_new"},
    )
    authorization = _authorize_ast_policy(local_root)
    canon_path = local_root / "tiddlers_1.jsonl"
    before = canon_path.read_bytes()

    gpol.materialize_authorized_policy(
        local_root, policy_id="PYTHON_AST_IMPORT_DEPENDENCY_V1", authorization=authorization, actor="tester",
    )

    assert canon_path.read_bytes() == before


def test_materialize_blocked_when_canon_changes_after_authorization(tmp_path: Path) -> None:
    cid_a, cid_b, candidates = _two_ast_candidates()
    local_root = _build_fixture_current(
        tmp_path, candidates=candidates, review_reasons={cid_a: "reconciliation_new", cid_b: "reconciliation_new"},
    )
    authorization = _authorize_ast_policy(local_root)
    (local_root / "tiddlers_1.jsonl").write_text("canon-v2-grew", encoding="utf-8")

    try:
        gpol.materialize_authorized_policy(
            local_root, policy_id="PYTHON_AST_IMPORT_DEPENDENCY_V1", authorization=authorization, actor="tester",
        )
    except gpol.PolicyMaterializationBlocked as error:
        assert "stale:canon_hash" in error.reasons
    else:
        raise AssertionError("expected PolicyMaterializationBlocked")
    decisions_path = local_root / "pipeline" / "relation_candidates" / "current" / human_review.DECISIONS_FILE
    assert human_review.load_jsonl(decisions_path) == []


def test_materialize_blocked_when_candidate_batch_changes(tmp_path: Path) -> None:
    cid_a, cid_b, candidates = _two_ast_candidates()
    local_root = _build_fixture_current(
        tmp_path, candidates=candidates, review_reasons={cid_a: "reconciliation_new", cid_b: "reconciliation_new"},
    )
    authorization = _authorize_ast_policy(local_root)
    (local_root / "pipeline" / "relation_candidates" / "current" / "current_candidate_manifest.json").write_text(
        '{"schema":"x-changed"}', encoding="utf-8",
    )

    try:
        gpol.materialize_authorized_policy(
            local_root, policy_id="PYTHON_AST_IMPORT_DEPENDENCY_V1", authorization=authorization, actor="tester",
        )
    except gpol.PolicyMaterializationBlocked as error:
        assert "stale:candidate_batch_hash" in error.reasons
    else:
        raise AssertionError("expected PolicyMaterializationBlocked")


def test_materialize_blocked_when_reconciliation_changes(tmp_path: Path) -> None:
    cid_a, cid_b, candidates = _two_ast_candidates()
    local_root = _build_fixture_current(
        tmp_path, candidates=candidates, review_reasons={cid_a: "reconciliation_new", cid_b: "reconciliation_new"},
    )
    authorization = _authorize_ast_policy(local_root)
    (local_root / "pipeline" / "relation_candidates" / "current" / "reconciliation_manifest.json").write_text(
        '{"schema":"y-changed"}', encoding="utf-8",
    )

    try:
        gpol.materialize_authorized_policy(
            local_root, policy_id="PYTHON_AST_IMPORT_DEPENDENCY_V1", authorization=authorization, actor="tester",
        )
    except gpol.PolicyMaterializationBlocked as error:
        assert "stale:reconciliation_hash" in error.reasons
    else:
        raise AssertionError("expected PolicyMaterializationBlocked")


def test_materialize_blocked_when_policy_definition_changes(tmp_path: Path) -> None:
    import dataclasses

    cid_a, cid_b, candidates = _two_ast_candidates()
    local_root = _build_fixture_current(
        tmp_path, candidates=candidates, review_reasons={cid_a: "reconciliation_new", cid_b: "reconciliation_new"},
    )
    authorization = _authorize_ast_policy(local_root)

    original_registry = gpol.build_policy_registry
    bumped = [
        dataclasses.replace(p, policy_version="9.9.9") if p.policy_id == "PYTHON_AST_IMPORT_DEPENDENCY_V1" else p
        for p in original_registry()
    ]
    gpol.build_policy_registry = lambda: tuple(bumped)
    try:
        try:
            gpol.materialize_authorized_policy(
                local_root, policy_id="PYTHON_AST_IMPORT_DEPENDENCY_V1", authorization=authorization, actor="tester",
            )
        except gpol.PolicyMaterializationBlocked as error:
            assert "stale:policy_hash" in error.reasons
        else:
            raise AssertionError("expected PolicyMaterializationBlocked")
    finally:
        gpol.build_policy_registry = original_registry


def test_materialize_blocked_when_eligible_set_shrinks(tmp_path: Path) -> None:
    cid_a, cid_b, candidates = _two_ast_candidates()
    local_root = _build_fixture_current(
        tmp_path, candidates=candidates, review_reasons={cid_a: "reconciliation_new", cid_b: "reconciliation_new"},
    )
    authorization = _authorize_ast_policy(local_root)
    # An individual decision lands on one of the two candidates out of band,
    # exactly as a human using option 1/8/etc could do between authorization
    # and materialization -- the eligible set must shrink and invalidate.
    decisions_path = local_root / "pipeline" / "relation_candidates" / "current" / human_review.DECISIONS_FILE
    state = gpol.load_current_pending(local_root)
    manual = human_review.build_decision_record(
        state["by_id"][cid_a], decision="rejected", reason_code="WRONG_PREDICATE",
        actor="human", bindings=state["bindings"], decision_mode="individual",
    )
    human_review.atomic_write_jsonl(decisions_path, {cid_a: manual})

    try:
        gpol.materialize_authorized_policy(
            local_root, policy_id="PYTHON_AST_IMPORT_DEPENDENCY_V1", authorization=authorization, actor="tester",
        )
    except gpol.PolicyMaterializationBlocked as error:
        assert "stale:eligible_candidate_set_hash" in error.reasons
        assert "stale:eligible_candidate_count" in error.reasons
    else:
        raise AssertionError("expected PolicyMaterializationBlocked")


def test_duplicate_materialization_is_fail_closed_not_a_silent_reapply(tmp_path: Path) -> None:
    cid_a, cid_b, candidates = _two_ast_candidates()
    local_root = _build_fixture_current(
        tmp_path, candidates=candidates, review_reasons={cid_a: "reconciliation_new", cid_b: "reconciliation_new"},
    )
    authorization = _authorize_ast_policy(local_root)

    first = gpol.materialize_authorized_policy(
        local_root, policy_id="PYTHON_AST_IMPORT_DEPENDENCY_V1", authorization=authorization, actor="tester",
    )
    assert first["materialized_count"] == 2

    try:
        gpol.materialize_authorized_policy(
            local_root, policy_id="PYTHON_AST_IMPORT_DEPENDENCY_V1", authorization=authorization, actor="tester",
        )
    except gpol.PolicyMaterializationBlocked as error:
        # Either signal is acceptable -- the eligible set is now empty
        # (everything already decided) AND/OR the authorization itself is
        # marked consumed; both are checked, either is sufficient.
        assert error.reasons
    else:
        raise AssertionError("expected the second materialization to be blocked")

    decisions_path = local_root / "pipeline" / "relation_candidates" / "current" / human_review.DECISIONS_FILE
    rows = human_review.load_jsonl(decisions_path)
    assert len(rows) == 2  # no duplicate rows written


def test_authorization_alone_does_not_affect_admission(tmp_path: Path) -> None:
    # authorization != decision: before materialization, the candidate must
    # still show up as undecided from the decisions-file point of view.
    cid_a, cid_b, candidates = _two_ast_candidates()
    local_root = _build_fixture_current(
        tmp_path, candidates=candidates, review_reasons={cid_a: "reconciliation_new", cid_b: "reconciliation_new"},
    )
    _authorize_ast_policy(local_root)
    decisions_path = local_root / "pipeline" / "relation_candidates" / "current" / human_review.DECISIONS_FILE
    assert human_review.load_jsonl(decisions_path) == []
    state = gpol.load_current_pending(local_root)
    assert set(state["pending_ids"]) == {cid_a, cid_b}


def test_materialize_refuses_unknown_policy_id(tmp_path: Path) -> None:
    cid_a, cid_b, candidates = _two_ast_candidates()
    local_root = _build_fixture_current(
        tmp_path, candidates=candidates, review_reasons={cid_a: "reconciliation_new", cid_b: "reconciliation_new"},
    )
    fake_authorization = {"authorization_id": "auth_" + "f" * 24, "consumed": False}
    try:
        gpol.materialize_authorized_policy(
            local_root, policy_id="NOT_A_REAL_POLICY", authorization=fake_authorization, actor="tester",
        )
    except gpol.PolicyMaterializationBlocked as error:
        assert "unknown_policy:NOT_A_REAL_POLICY" in error.reasons
    else:
        raise AssertionError("expected PolicyMaterializationBlocked")


# ---------------------------------------------------------------------------
# Admission gate consumes policy_derived decisions correctly
# ---------------------------------------------------------------------------

def test_admission_gate_accepts_a_policy_derived_approval() -> None:
    import relation_admission_gate as gate

    policies = {p.policy_id: p for p in gpol.build_policy_registry()}
    policy = policies["PYTHON_AST_IMPORT_DEPENDENCY_V1"]
    cid = "rc_current_" + "1" * 24
    candidate = _candidate(cid, kind="python_ast_import", predicate="depende_de")
    decision = gpol.materialize_policy_decision(
        policy, candidate, actor="tester", bindings=_bindings(),
        human_authorization_id="auth_" + "a" * 24,
    )
    # The gate reads human_review_decision/_reason_code/approval_scope off
    # the (merged) candidate object itself -- exactly what a policy_derived
    # decision provides, regardless of decision_mode.
    merged = {
        **candidate,
        "human_review_decision": decision["human_review_decision"],
        "human_review_reason_code": decision["human_review_reason_code"],
        "approval_scope": decision["approval_scope"],
    }
    decision_issues = gate.validate_candidate_human_review_decision(merged, None)
    assert decision_issues == []


def test_admission_gate_still_blocks_before_any_decision_exists() -> None:
    import relation_admission_gate as gate

    cid = "rc_current_" + "1" * 24
    candidate = _candidate(cid, kind="python_ast_import", predicate="depende_de")
    decision_issues = gate.validate_candidate_human_review_decision(candidate, None)
    assert any("GATE-015" in issue for issue in decision_issues)


def test_compact_summary_does_not_dump_individual_candidates() -> None:
    policies = gpol.build_policy_registry()
    cid = "rc_current_" + "1" * 24
    candidates = {cid: _candidate(cid, kind="python_ast_import", predicate="depende_de")}
    partition = gpol.partition_pending_candidates(policies, [cid], candidates, {cid: "new"})
    preview = {
        "current_pending_total": 1,
        "policies": [
            {"policy_id": p.policy_id, "eligible_count": len(partition["by_policy"][p.policy_id])}
            for p in policies
        ],
        "policy_eligible_total": sum(len(v) for v in partition["by_policy"].values()),
        "human_exception_total": len(partition["exceptions"]),
        "exception_reason_counts": {},
    }
    rendered = gpol.render_compact_summary(preview)
    assert cid not in rendered
    assert "src/python_scripts" not in rendered
    assert len(rendered.splitlines()) < 20


# ---------------------------------------------------------------------------
# Human authorization: phrase-binding, fail-closed, staleness re-verification
# ---------------------------------------------------------------------------

def test_authorization_refuses_without_exact_confirmation_phrase(tmp_path: Path) -> None:
    policy = next(p for p in gpol.build_policy_registry() if p.policy_id == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    ids = ["rc_current_" + "1" * 24]
    try:
        gpol.write_policy_authorization(
            policy, ids, _bindings(), actor="operator", confirmation="yes",
            authorizations_dir=tmp_path,
        )
    except gpol.PolicyAuthorizationRefused:
        pass
    else:
        raise AssertionError("expected refusal for wrong confirmation phrase")
    assert list(tmp_path.iterdir()) == []


def test_authorization_refuses_without_actor(tmp_path: Path) -> None:
    policy = next(p for p in gpol.build_policy_registry() if p.policy_id == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    ids = ["rc_current_" + "1" * 24]
    phrase = gpol.authorization_confirmation_phrase(policy.policy_id)
    try:
        gpol.write_policy_authorization(
            policy, ids, _bindings(), actor="", confirmation=phrase, authorizations_dir=tmp_path,
        )
    except gpol.PolicyAuthorizationRefused:
        pass
    else:
        raise AssertionError("expected refusal for missing actor")
    assert list(tmp_path.iterdir()) == []


def test_authorization_succeeds_with_exact_phrase_and_actor(tmp_path: Path) -> None:
    policy = next(p for p in gpol.build_policy_registry() if p.policy_id == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    ids = ["rc_current_" + "1" * 24]
    bindings = _bindings()
    phrase = gpol.authorization_confirmation_phrase(policy.policy_id)
    record = gpol.write_policy_authorization(
        policy, ids, bindings, actor="operator-1", confirmation=phrase, authorizations_dir=tmp_path,
    )
    assert record["authorized_by"] == "operator-1"
    assert record["consumed"] is False
    written = list(tmp_path.glob("*.json"))
    assert len(written) == 1
    assert json.loads(written[0].read_text())["authorization_id"] == record["authorization_id"]


def test_authorization_is_fresh_when_nothing_drifted(tmp_path: Path) -> None:
    policy = next(p for p in gpol.build_policy_registry() if p.policy_id == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    ids = ["rc_current_" + "1" * 24]
    bindings = _bindings()
    record = gpol.write_policy_authorization(
        policy, ids, bindings, actor="operator-1",
        confirmation=gpol.authorization_confirmation_phrase(policy.policy_id),
        authorizations_dir=tmp_path,
    )
    assert gpol.verify_policy_authorization_current(record, policy, ids, bindings) == []


def test_authorization_is_stale_when_canon_hash_drifts(tmp_path: Path) -> None:
    policy = next(p for p in gpol.build_policy_registry() if p.policy_id == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    ids = ["rc_current_" + "1" * 24]
    record = gpol.write_policy_authorization(
        policy, ids, _bindings("a"), actor="operator-1",
        confirmation=gpol.authorization_confirmation_phrase(policy.policy_id),
        authorizations_dir=tmp_path,
    )
    reasons = gpol.verify_policy_authorization_current(record, policy, ids, _bindings("b"))
    assert "stale:canon_hash" in reasons


def test_authorization_is_stale_when_eligible_set_grows(tmp_path: Path) -> None:
    policy = next(p for p in gpol.build_policy_registry() if p.policy_id == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    bindings = _bindings()
    ids = ["rc_current_" + "1" * 24]
    record = gpol.write_policy_authorization(
        policy, ids, bindings, actor="operator-1",
        confirmation=gpol.authorization_confirmation_phrase(policy.policy_id),
        authorizations_dir=tmp_path,
    )
    grown_ids = ids + ["rc_current_" + "2" * 24]
    reasons = gpol.verify_policy_authorization_current(record, policy, grown_ids, bindings)
    assert "stale:eligible_candidate_set_hash" in reasons
    assert "stale:eligible_candidate_count" in reasons


def test_authorization_is_stale_when_policy_hash_drifts(tmp_path: Path) -> None:
    import dataclasses

    policy = next(p for p in gpol.build_policy_registry() if p.policy_id == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    bindings = _bindings()
    ids = ["rc_current_" + "1" * 24]
    record = gpol.write_policy_authorization(
        policy, ids, bindings, actor="operator-1",
        confirmation=gpol.authorization_confirmation_phrase(policy.policy_id),
        authorizations_dir=tmp_path,
    )
    bumped_policy = dataclasses.replace(policy, policy_version="1.0.1")
    reasons = gpol.verify_policy_authorization_current(record, bumped_policy, ids, bindings)
    assert "stale:policy_version" in reasons
    assert "stale:policy_hash" in reasons


def test_already_consumed_authorization_is_never_fresh(tmp_path: Path) -> None:
    policy = next(p for p in gpol.build_policy_registry() if p.policy_id == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    bindings = _bindings()
    ids = ["rc_current_" + "1" * 24]
    record = gpol.write_policy_authorization(
        policy, ids, bindings, actor="operator-1",
        confirmation=gpol.authorization_confirmation_phrase(policy.policy_id),
        authorizations_dir=tmp_path,
    )
    record["consumed"] = True
    assert "already_consumed" in gpol.verify_policy_authorization_current(record, policy, ids, bindings)


def test_status_categorizes_consumed_authorization_separately_from_stale(tmp_path: Path) -> None:
    # S0186 Unit H8 (second diagnostic pass): a real human materialization
    # showed stale_authorizations=1 for a policy whose ONLY authorization had
    # just been consumed successfully -- consumption was misreported as
    # staleness because verify_policy_authorization_current's
    # "already_consumed" reason got lumped in with genuine binding drift.
    # build_policy_status() must count it as consumed, not stale.
    cid_a, cid_b, candidates = _two_ast_candidates()
    local_root = _build_fixture_current(
        tmp_path, candidates=candidates, review_reasons={cid_a: "reconciliation_new", cid_b: "reconciliation_new"},
    )
    authorization = _authorize_ast_policy(local_root)
    gpol.materialize_authorized_policy(
        local_root, policy_id="PYTHON_AST_IMPORT_DEPENDENCY_V1", authorization=authorization, actor="tester",
    )

    status = gpol.build_policy_status(local_root)
    item = next(p for p in status["policies"] if p["policy_id"] == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    assert item["status"] == "MATERIALIZED"
    assert item["materialized"] == 2
    assert item["effective_for_admission"] is True
    assert item["consumed_authorizations"] == 1
    assert item["stale_authorizations"] == 0
    assert item["active_authorizations"] == 0


def test_status_genuinely_stale_authorization_is_not_miscounted_as_consumed(tmp_path: Path) -> None:
    cid_a, cid_b, candidates = _two_ast_candidates()
    local_root = _build_fixture_current(
        tmp_path, candidates=candidates, review_reasons={cid_a: "reconciliation_new", cid_b: "reconciliation_new"},
    )
    _authorize_ast_policy(local_root)
    # Canon grows after authorization but before anyone materializes --
    # a genuine, never-consumed staleness case.
    (local_root / "tiddlers_1.jsonl").write_text("canon-v2-grew", encoding="utf-8")

    status = gpol.build_policy_status(local_root)
    item = next(p for p in status["policies"] if p["policy_id"] == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    assert item["status"] == "STALE_AUTHORIZATION"
    assert item["stale_authorizations"] == 1
    assert item["consumed_authorizations"] == 0
    assert item["active_authorizations"] == 0


def test_status_reports_freshly_materialized_split_for_in_generation_materialization(
    tmp_path: Path,
) -> None:
    # S0186 Unit H (policy_derived generational preservation fix): the
    # operator panel must distinguish decisions materialized in THIS
    # generation from ones inherited by lineage from a prior one -- a
    # freshly materialized policy never carries generational_preservation.
    cid_a, cid_b, candidates = _two_ast_candidates()
    local_root = _build_fixture_current(
        tmp_path, candidates=candidates, review_reasons={cid_a: "reconciliation_new", cid_b: "reconciliation_new"},
    )
    authorization = _authorize_ast_policy(local_root)
    gpol.materialize_authorized_policy(
        local_root, policy_id="PYTHON_AST_IMPORT_DEPENDENCY_V1", authorization=authorization, actor="tester",
    )

    status = gpol.build_policy_status(local_root)
    item = next(p for p in status["policies"] if p["policy_id"] == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    assert item["status"] == "MATERIALIZED"
    assert item["materialized_freshly_this_generation"] == 2
    assert item["materialized_generationally_preserved"] == 0


def test_status_marks_materialized_preserved_when_all_decisions_carry_lineage(
    tmp_path: Path,
) -> None:
    # Simulates the fixed prepare_current_relational_generation.py output: a
    # policy_derived decision that survived into a new generation carries a
    # generational_preservation marker written by
    # _preserve_equivalent_decisions(), never by materialize_authorized_
    # policy() itself. The operator panel must not read this as
    # "eligible=N, materialized=0" (as if nothing had ever happened) nor as
    # an ordinary fresh materialization -- it is its own, honest state.
    cid_a, cid_b, candidates = _two_ast_candidates()
    local_root = _build_fixture_current(
        tmp_path, candidates=candidates, review_reasons={cid_a: "reconciliation_new", cid_b: "reconciliation_new"},
    )
    authorization = _authorize_ast_policy(local_root)
    gpol.materialize_authorized_policy(
        local_root, policy_id="PYTHON_AST_IMPORT_DEPENDENCY_V1", authorization=authorization, actor="tester",
    )
    current_dir = local_root / "pipeline" / "relation_candidates" / "current"
    decisions_path = human_review.decision_authority_path(current_dir)
    rows = {
        str(row["candidate_id"]): row
        for row in human_review.load_jsonl(decisions_path)
    }
    for row in rows.values():
        row["generational_preservation"] = {
            "classification": "equivalent", "preservation_source": "published_bundle",
        }
    human_review.atomic_write_jsonl(decisions_path, rows)

    status = gpol.build_policy_status(local_root)
    item = next(p for p in status["policies"] if p["policy_id"] == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    assert item["status"] == "MATERIALIZED_PRESERVED"
    assert item["materialized"] == 2
    assert item["materialized_freshly_this_generation"] == 0
    assert item["materialized_generationally_preserved"] == 2
    assert item["effective_for_admission"] is True


def test_individual_and_batch_decisions_still_reach_the_effective_file(tmp_path: Path) -> None:
    # Confirms the tdc.sh path-resolution fix's underlying Python contract
    # (decision_authority_path preferring the effective file) is unaffected
    # for the pre-existing individual/batch write paths -- only the shell
    # wrapper's hardcoded default changed, not this function's behavior.
    cid_a, cid_b, candidates = _two_ast_candidates()
    local_root = _build_fixture_current(
        tmp_path, candidates=candidates, review_reasons={cid_a: "reconciliation_new", cid_b: "reconciliation_new"},
    )
    current_dir = local_root / "pipeline" / "relation_candidates" / "current"
    # Simulate PREPARE having already published an effective snapshot.
    (current_dir / human_review.EFFECTIVE_DECISIONS_FILE).write_text("", encoding="utf-8")
    state = gpol.load_current_pending(local_root)
    individual = human_review.build_decision_record(
        state["by_id"][cid_a], decision="approved_for_admission", reason_code="DIRECT_CODE_DEPENDENCY_CONFIRMED",
        actor="human", bindings=state["bindings"], decision_mode="individual",
    )
    human_review.atomic_write_jsonl(
        human_review.decision_authority_path(current_dir), {cid_a: individual},
    )
    resolved = human_review.decision_authority_path(current_dir)
    assert resolved.name == human_review.EFFECTIVE_DECISIONS_FILE
    rows = human_review.load_jsonl(resolved)
    assert len(rows) == 1
    assert rows[0]["decision_mode"] == "individual"
