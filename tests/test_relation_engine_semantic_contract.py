"""Conformance tests for the relation engine semantic contract (S0186).

These tests prove the contract declared by
prepare_current_relational_generation.relation_engine_semantic_contract_*()
is the surface the engine actually executes -- not a manual version label --
and that CURRENT's currentness reacts to exactly the right kind of change:
a declared semantic-contract transition, never a cosmetic file edit, and
never the full physical byte hash of the orchestrator/reconciler.

Fixtures/TMP only. Never CURRENT productivo, never a write against real
human decisions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from test_generational_decision_preservation import (
    _degrade_published_bundle,
    _reach_review_complete_two_candidates,
)
from test_prepare_current_relational_generation import _write_canon
from test_reconcile_current_relation_candidates import _candidate, _endpoint

import current_relation_human_review as human_review
import prepare_current_relational_generation as preparation
import reconcile_current_relation_candidates as reconciliation


def _minimal_generation_ids_inputs(tmp_path: Path) -> dict[str, Path]:
    candidate_manifest = tmp_path / "current_candidate_manifest.json"
    candidate_manifest.write_text(
        json.dumps({"candidate_batch": {"hash": "h", "namespace": "n", "record_count": 1}}),
        encoding="utf-8",
    )
    validation_report = tmp_path / "validation_report.json"
    validation_report.write_text(json.dumps({"summary": {"total": 1}}), encoding="utf-8")
    reconciliation_manifest = tmp_path / "reconciliation_manifest.json"
    reconciliation_manifest.write_text(
        json.dumps({"matrix_hash": "m", "total": 1, "unclassified": 0, "dispositions": {}}),
        encoding="utf-8",
    )
    reviewable_manifest = tmp_path / "reviewable_candidate_manifest.json"
    reviewable_manifest.write_text(
        json.dumps({"record_count": 1, "records_hash": "r"}), encoding="utf-8",
    )
    return {
        "candidate_manifest": candidate_manifest,
        "validation_report": validation_report,
        "reconciliation_manifest": reconciliation_manifest,
        "reviewable_manifest": reviewable_manifest,
    }


def _canon_diagnostic_row(identifier: str) -> dict:
    """A thematic-diagnostic-shaped Canon record: forces candidate_generation_
    stale (a technical rebuild) while producing zero new relation candidates,
    exactly like the real thematic diagnostics admitted during S0186."""
    return {
        "id": identifier,
        "title": f"Diagnóstico temático {identifier}",
        "key": f"Diagnóstico temático {identifier}",
        "version_id": f"sha256:{identifier}",
        "text": "Contenido narrativo sin código ni repo_path.",
        "source_fields": {"artifact_family": "thematic_diagnostic"},
        "relations": [],
    }


# --- The contract declaration itself ----------------------------------------

def test_contract_payload_is_deterministic() -> None:
    first = preparation.relation_engine_semantic_contract_payload()
    second = preparation.relation_engine_semantic_contract_payload()
    assert first == second
    assert (
        preparation.relation_engine_semantic_contract_hash()
        == preparation.relation_engine_semantic_contract_hash()
    )


def test_contract_declares_the_real_reconciliation_taxonomy() -> None:
    payload = preparation.relation_engine_semantic_contract_payload()
    assert payload["cross_generation_equivalence_contract"]["reconciliation_classes"] == sorted(
        reconciliation.S0183_RECONCILIATION_CLASSES
    )


def test_contract_declares_the_real_deep_recovery_limits() -> None:
    payload = preparation.relation_engine_semantic_contract_payload()
    policy = payload["decision_preservation_policy"]
    assert policy["deep_historical_recovery_max_hops"] == preparation.DEEP_HISTORICAL_RECOVERY_MAX_HOPS
    assert policy["deep_historical_recovery_allowed_classifications"] == list(
        preparation.DEEP_HISTORICAL_RECOVERY_ALLOWED_CLASSIFICATIONS
    )


def test_record_reports_no_transition_when_previous_manifest_matches() -> None:
    previous_manifest = {
        "engine_semantic_contract": preparation.relation_engine_semantic_contract_record()
    }
    record = preparation.relation_engine_semantic_contract_record(previous_manifest=previous_manifest)
    assert record["contract_transitioned_this_generation"] is False
    assert record["observed_previous_contract_version"] == preparation.RELATION_ENGINE_CONTRACT_VERSION


def test_record_reports_transition_when_previous_manifest_used_older_version() -> None:
    previous_manifest = {
        "engine_semantic_contract": {
            "contract_version": "v0-fixture-only",
            "semantic_contract_hash": "deadbeef",
        }
    }
    record = preparation.relation_engine_semantic_contract_record(previous_manifest=previous_manifest)
    assert record["contract_transitioned_this_generation"] is True
    assert record["observed_previous_contract_version"] == "v0-fixture-only"


# --- Requirement 7 (inverse): cosmetic file drift never moves the id -------

def test_cosmetic_producer_file_drift_does_not_change_relation_generation_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NO aceptar: incluir el sha256 completo del orquestador/reconciliador
    en relation_generation_id. Prove structurally that swapping their
    physical bytes (a stand-in for a pure refactor/comment/rename edit),
    with the declared semantic contract held fixed, never moves the id."""
    canon = {"hash": "canon-hash", "records": 1, "shards": 1}
    inputs = _minimal_generation_ids_inputs(tmp_path)
    gate_report = {"summary": {}, "items": []}
    ids_before = preparation.generation_ids(canon, inputs, "dec-hash", [], gate_report)

    cosmetic_orchestrator = tmp_path / "orchestrator_cosmetic_copy.py"
    cosmetic_orchestrator.write_text("# purely cosmetic edit\n", encoding="utf-8")
    cosmetic_reconciler = tmp_path / "reconciler_cosmetic_copy.py"
    cosmetic_reconciler.write_text("# purely cosmetic edit too\n", encoding="utf-8")
    real_bindings = preparation.producer_bindings()

    def patched_bindings() -> dict[str, Path]:
        bindings = dict(real_bindings)
        bindings["preparation_orchestrator"] = cosmetic_orchestrator
        bindings["cross_generation_reconciler"] = cosmetic_reconciler
        return bindings

    monkeypatch.setattr(preparation, "producer_bindings", patched_bindings)

    ids_after = preparation.generation_ids(canon, inputs, "dec-hash", [], gate_report)
    assert ids_after["relation_generation_id"] == ids_before["relation_generation_id"]


def test_semantic_contract_change_does_change_relation_generation_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact opposite of the above: holding physical bytes fixed, only
    changing the DECLARED semantic contract must change the id."""
    canon = {"hash": "canon-hash", "records": 1, "shards": 1}
    inputs = _minimal_generation_ids_inputs(tmp_path)
    gate_report = {"summary": {}, "items": []}
    ids_before = preparation.generation_ids(canon, inputs, "dec-hash", [], gate_report)

    real_payload = preparation.relation_engine_semantic_contract_payload

    def bumped_payload() -> dict:
        payload = real_payload()
        payload["conformance_test_marker"] = "v2"
        return payload

    monkeypatch.setattr(preparation, "relation_engine_semantic_contract_payload", bumped_payload)

    ids_after = preparation.generation_ids(canon, inputs, "dec-hash", [], gate_report)
    assert ids_after["relation_generation_id"] != ids_before["relation_generation_id"]


# --- Requirement 5: conformance of the declared invariants -----------------

def test_conformance_metadata_only_endpoint_drift_stays_equivalent() -> None:
    """(a) The contract excludes governed/mutable endpoint metadata from
    identity; prove the reconciler actually honors it."""
    old = _candidate("rc_current_" + "1" * 24, "src/source.py", "src/target.py")
    old["source"] = _endpoint("src/source.py", repo_lifecycle_state="active")
    old["target"] = _endpoint("src/target.py", artifact_family="repo_module")
    current = json.loads(json.dumps(old))
    current["candidate_id"] = "rc_current_" + "a" * 24
    current["source"].pop("repo_lifecycle_state")
    current["target"]["artifact_family"] = None
    cross = reconciliation.build_cross_batch_reconciliation([old], [current])
    assert cross["current_to_old"][0]["classification"] == "equivalent"


def test_conformance_different_predicate_is_not_equivalent() -> None:
    """(b) Endpoint identity alone is never sufficient; the predicate must
    also match."""
    old = _candidate("rc_current_" + "2" * 24, "src/source.py", "src/target.py", predicate="references")
    current = _candidate("rc_current_" + "b" * 24, "src/source.py", "src/target.py", predicate="depende_de")
    cross = reconciliation.build_cross_batch_reconciliation([old], [current])
    assert cross["old_to_current"][0]["classification"] != "equivalent"


def test_conformance_different_evidence_produces_modified() -> None:
    """(c) Same endpoints/predicate, different observed evidence text ->
    the contract's base-fingerprint tier ("modified"), never "equivalent"."""
    old = _candidate("rc_current_" + "3" * 24, "src/source.py", "src/target.py")
    current = json.loads(json.dumps(old))
    current["candidate_id"] = "rc_current_" + "c" * 24
    current["evidence"]["raw_observation"] = "meaningfully different observed evidence"
    cross = reconciliation.build_cross_batch_reconciliation([old], [current])
    assert cross["old_to_current"][0]["classification"] == "modified"


def test_conformance_ambiguity_fails_closed(tmp_path: Path) -> None:
    """(f) Two CURRENT candidates sharing one semantic fingerprint must
    never be silently resolved by the deep-recovery walk -- neither is
    told apart from the other, so neither may borrow a historical decision."""
    paths, _source_root, _canon_rows, candidate_id, _anchor_id = (
        _reach_review_complete_two_candidates(tmp_path)
    )
    queue = preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")
    target_row = next(row for row in queue if row["candidate_id"] == candidate_id)
    duplicate = dict(target_row)
    duplicate["candidate_id"] = "rc_current_" + "f" * 12
    predecessor = preparation._analysis_review_predecessor(paths)
    recovered, manifest = preparation._recover_certified_lineage_decisions(
        paths,
        pending_candidates=[target_row, duplicate],
        current_batch_candidates=queue + [duplicate],
        immediate_predecessor=predecessor,
        bindings=human_review.current_bindings(paths.current_dir, paths.local_root),
    )
    assert recovered == []
    assert set(manifest["not_recoverable_candidate_ids"]) == {
        candidate_id, duplicate["candidate_id"],
    }


def test_conformance_deep_recovery_recovers_equivalent_authority(tmp_path: Path) -> None:
    """(d) Deep recovery is real, not declarative: reuse the established
    rich-G1 / degraded-G2 / rebuilt-G3 fixture shape."""
    paths, source_root, canon_rows, candidate_id, _anchor_id = (
        _reach_review_complete_two_candidates(tmp_path)
    )
    canon_rows.append(_canon_diagnostic_row("diagnostic-conformance-d-g2"))
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    g2 = preparation.execute(paths, source_root=source_root)
    assert g2["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    _degrade_published_bundle(paths, Path(g2["bundle_path"]), candidate_id)

    canon_rows.append(_canon_diagnostic_row("diagnostic-conformance-d-g3"))
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    g3 = preparation.execute(paths, source_root=source_root)
    assert g3["decision_preservation"]["preserved_from_deep_historical_lineage_recovery"] == 1


def test_conformance_later_governed_decision_prevails_over_deep_recovery(tmp_path: Path) -> None:
    """(e) Newest authority always wins over anything deep recovery could
    offer -- deep recovery is only ever consulted for candidates nothing
    newer already resolved."""
    paths, source_root, canon_rows, candidate_id, _anchor_id = (
        _reach_review_complete_two_candidates(tmp_path)
    )
    canon_rows.append(_canon_diagnostic_row("diagnostic-conformance-e-g2"))
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    g2 = preparation.execute(paths, source_root=source_root)
    _degrade_published_bundle(paths, Path(g2["bundle_path"]), candidate_id)

    human_review.record_individual_decision(
        paths.current_dir, paths.local_root, candidate_id=candidate_id,
        decision="deferred", reason_code="INSUFFICIENT_CONTEXT",
        note="Later governed re-decision (conformance).", actor="Naveen",
        confirmation=human_review.DECISION_INITIAL_CONFIRMATION,
    )
    # A live decision changing after a predecessor already reached
    # AUTHORIZATION requires an explicit, governed recomposition pass to be
    # absorbed before any further technical rebuild -- the ordinary path,
    # not a workaround (see test_deep_recovery_never_overrides_a_later_
    # governed_supersession for the same, already-established shape).
    preparation.execute(paths, source_root=source_root)

    canon_rows.append(_canon_diagnostic_row("diagnostic-conformance-e-g3"))
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    g3 = preparation.execute(paths, source_root=source_root)
    g3_decisions = {
        row["candidate_id"]: row
        for row in preparation.read_jsonl(human_review.decision_authority_path(paths.current_dir))
    }
    assert g3_decisions[candidate_id]["human_review_decision"] == "deferred"
    generational = g3_decisions[candidate_id]["generational_preservation"]
    assert generational["preservation_source"] != "deep_historical_lineage_recovery"


# --- Requirement 6: currentness reacts to a declared contract change -------

def test_engine_semantic_contract_change_forces_recomposition_without_data_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S0186 Unit H, Alternative D end-to-end: a declared engine semantic-
    contract change must reopen CURRENT for recomposition even when Canon
    and candidates are byte-identical (criterion B), and must let deep
    historical recovery reach decisions the degraded immediate predecessor
    alone could not certify (criterion C) -- driven by the contract alone,
    with no further canon/candidate change.
    """
    paths, source_root, canon_rows, candidate_id, _anchor_id = (
        _reach_review_complete_two_candidates(tmp_path)
    )
    g1_relation_generation_id = preparation.read_json(paths.pointer)["relation_generation_id"]

    canon_rows.append(_canon_diagnostic_row("diagnostic-currentness-g2"))
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    g2 = preparation.execute(paths, source_root=source_root)
    assert g2["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    g2_relation_generation_id = g2["ids"]["relation_generation_id"]
    _degrade_published_bundle(paths, Path(g2["bundle_path"]), candidate_id)
    assert candidate_id not in {
        row["candidate_id"]
        for row in preparation.read_jsonl(human_review.decision_authority_path(paths.current_dir))
    }

    canon_before = preparation.canon_snapshot(paths.local_root)["hash"]
    candidates_before = preparation.sha256_file(paths.current_dir / "relation_candidates.jsonl")

    real_payload = preparation.relation_engine_semantic_contract_payload

    def bumped_payload() -> dict:
        payload = real_payload()
        payload["conformance_test_contract_marker"] = "v2"
        return payload

    monkeypatch.setattr(preparation, "relation_engine_semantic_contract_payload", bumped_payload)
    monkeypatch.setattr(preparation, "RELATION_ENGINE_CONTRACT_VERSION", "v2-conformance-test")

    g3 = preparation.execute(paths, source_root=source_root)

    # A: only the contract moved -- Canon and candidates did not.
    assert preparation.canon_snapshot(paths.local_root)["hash"] == canon_before
    assert preparation.sha256_file(paths.current_dir / "relation_candidates.jsonl") == candidates_before
    # B: no idempotent noop, and a new relation_generation_id.
    assert g3.get("idempotent_noop") is not True
    assert g3["ids"]["relation_generation_id"] != g2_relation_generation_id
    # C: deep recovery reached past the degraded immediate predecessor to
    # the older, richer, certified generation 1.
    assert g3["decision_preservation"]["preserved_from_deep_historical_lineage_recovery"] == 1
    g3_decisions = {
        row["candidate_id"]: row
        for row in preparation.read_jsonl(human_review.decision_authority_path(paths.current_dir))
    }
    assert candidate_id in g3_decisions
    generational = g3_decisions[candidate_id]["generational_preservation"]
    assert generational["preservation_source"] == "deep_historical_lineage_recovery"
    assert generational["source_generation_id"] == g1_relation_generation_id

    manifest = preparation.read_json(Path(g3["bundle_path"]) / "bundle_manifest.json")
    assert manifest["engine_semantic_contract"]["contract_version"] == "v2-conformance-test"
    assert manifest["engine_semantic_contract"]["contract_transitioned_this_generation"] is True


def test_missing_previously_recorded_engine_semantic_contract_triggers_recomposition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PRODUCTION INCIDENT (post-Alternative-D live validation): an
    authority produced before the engine semantic contract existed at all
    -- paths.current_dir's generational_decision_preservation.json has NO
    engine_semantic_contract key whatsoever, not merely an older declared
    version -- must ALSO be treated as a transition, exactly like a
    declared version change. Before the fix,
    _engine_semantic_contract_transition_reasons()'s guard
    (`declared_hash is not None and declared_hash != current_hash`)
    treated "nothing recorded" as "nothing to compare": analyze() never
    raised, execute() dispatched straight through _execute_human_delta's
    own "initial_current_review_basis" fallback (analysis["effective_
    decisions"] taken as-is, zero cross-generation reconciliation), and
    real production's degraded rg_0bab168df2c4fb612fd07e3e authority
    (123 decisions / 401 pending) stayed frozen instead of recomposing --
    confirmed by inspecting the actual published bundle_manifest.json,
    whose engine_semantic_contract showed contract_transitioned_this_
    generation=false / observed_previous_contract_version=null, the
    signature of relation_engine_semantic_contract_record() falling back
    to previous_manifest=None rather than reading a real predecessor.

    Generation 2 (the one that gets degraded) is deliberately built while
    relation_engine_semantic_contract_hash() is monkeypatched to a fixed
    "pre-feature" sentinel -- reproducing, faithfully, that a REAL
    pre-Alternative-D authority was never just missing a bookkeeping
    field: its relation_generation_id was computed by a formula that
    never had this hash term at all, so it structurally cannot collide
    with what current (real) code computes for the same inputs. Building
    generation 2 with today's real formula instead (differing from
    generation 1 only by a stripped-after-the-fact field) is a strictly
    weaker, self-contradictory fixture: a "healed" recomposition would
    then legitimately recompute the exact same (relation_generation_id,
    review_state_id, readiness_id) coordinate degradation had mutated in
    place, tripping the unrelated republish-collision guard instead of
    reproducing this bug.
    """
    paths, source_root, canon_rows, candidate_id, _anchor_id = (
        _reach_review_complete_two_candidates(tmp_path)
    )
    g1_relation_generation_id = preparation.read_json(paths.pointer)["relation_generation_id"]

    canon_rows.append(_canon_diagnostic_row("diagnostic-bootstrap-gap-g2"))
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    real_contract_hash = preparation.relation_engine_semantic_contract_hash
    monkeypatch.setattr(
        preparation, "relation_engine_semantic_contract_hash",
        lambda: "__pre_alternative_d_no_contract_tracking__",
    )
    g2 = preparation.execute(paths, source_root=source_root)
    assert g2["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    g2_relation_generation_id = g2["ids"]["relation_generation_id"]
    _degrade_published_bundle(paths, Path(g2["bundle_path"]), candidate_id)
    assert candidate_id not in {
        row["candidate_id"]
        for row in preparation.read_jsonl(human_review.decision_authority_path(paths.current_dir))
    }

    # Simulate the exact real-production condition: the live mirror's own
    # preservation report predates the engine semantic contract's
    # existence -- not an older declared version, no declaration at all,
    # exactly like every authority produced before this feature shipped.
    report_path = paths.current_dir / "generational_decision_preservation.json"
    report = preparation.read_json(report_path)
    assert "engine_semantic_contract" in report  # sanity: it WAS recorded (sentinel value)
    del report["engine_semantic_contract"]
    preparation.write_json(report_path, report)

    # Restore the REAL, deployed contract before generation 3 -- exactly
    # like running today's already-fixed code against a pre-existing,
    # untouched-since authority. No further monkeypatching from here on.
    monkeypatch.setattr(preparation, "relation_engine_semantic_contract_hash", real_contract_hash)

    canon_before = preparation.canon_snapshot(paths.local_root)["hash"]
    candidates_before = preparation.sha256_file(paths.current_dir / "relation_candidates.jsonl")

    g3 = preparation.execute(paths, source_root=source_root)

    # Canon/candidates never changed -- only the missing-record condition
    # (plus the pre-existing-authority's structurally different id) is
    # being exercised, matching the real production case exactly.
    assert preparation.canon_snapshot(paths.local_root)["hash"] == canon_before
    assert preparation.sha256_file(paths.current_dir / "relation_candidates.jsonl") == candidates_before

    assert g3.get("idempotent_noop") is not True
    assert g3["ids"]["relation_generation_id"] != g2_relation_generation_id
    assert g3["decision_preservation"]["preserved_from_deep_historical_lineage_recovery"] == 1
    g3_decisions = {
        row["candidate_id"]: row
        for row in preparation.read_jsonl(human_review.decision_authority_path(paths.current_dir))
    }
    assert candidate_id in g3_decisions
    generational = g3_decisions[candidate_id]["generational_preservation"]
    assert generational["preservation_source"] == "deep_historical_lineage_recovery"
    assert generational["source_generation_id"] == g1_relation_generation_id


def test_no_contract_change_stays_idempotent_noop(tmp_path: Path) -> None:
    """Requirement 7's direct counterpart at the pipeline level: with
    nothing changed at all (not even a cosmetic edit), a second execute()
    call must remain the ordinary idempotent noop, never a forced rebuild."""
    paths, source_root, _canon_rows, _candidate_id, _anchor_id = (
        _reach_review_complete_two_candidates(tmp_path)
    )
    first = preparation.execute(paths, source_root=source_root)
    second = preparation.execute(paths, source_root=source_root)
    assert second.get("idempotent_noop") is True
    assert second["ids"]["relation_generation_id"] == first["ids"]["relation_generation_id"]
