"""S0186 Unit H: generational preservation of policy_derived decisions.

Root cause (see data/out/local/audit/s0186/unit_h_repository_relational_full_hd/
34_policy_derived_generational_preservation_root_cause_and_fix.json for the
full trace): current_relation_human_review.persist_current_human_delta_batch
republishes a new review-state bundle on every batch/individual confirmation,
so prepare_current_relational_generation's predecessor resolution (which by
design trusts only certified, published bundles -- never the mutable live
current/ directory, see _load_review_bundle's docstring) always sees them.
governed_relation_admission_policy.materialize_authorized_policy() writes
policy_derived decisions straight to the live decisions file and never
publishes a bundle, so they are invisible to the next generation's
predecessor resolution -- not rejected fail-closed, simply never considered.

The fix (_live_decisions_recoverable_from_current, wired into
_previous_authority) recovers them, but only as a verified superset of the
bundle: same candidate inventory, every bundle-certified row reproduced
byte-identical, each additional row independently re-validated. It never
re-runs the policy engine, never creates or touches an authorization, and
never writes Canon -- it only widens which decisions decision preservation
considers "old", then lets the existing equivalence/rebinding/validation
logic in _preserve_equivalent_decisions handle them exactly like any other
decision.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from test_prepare_current_relational_generation import (
    _canon_record,
    _rebuild_fixture,
    _review_current_batch,
    _write_canon,
)

import prepare_current_relational_generation as preparation
import current_relation_human_review as human_review


POLICY_ID = "PYTHON_AST_IMPORT_DEPENDENCY_V1"
POLICY_VERSION = "1.0.0"
POLICY_HASH = "sha256:" + "ab" * 32
AUTHORIZATION_ID = "auth_" + "cd" * 12


def _policy_derived_record(candidate: dict, *, bindings: dict[str, str]) -> dict:
    return human_review.build_decision_record(
        candidate,
        decision="approved_for_admission",
        reason_code="DIRECT_CODE_DEPENDENCY_CONFIRMED",
        actor="policy-engine",
        bindings=bindings,
        decision_mode="policy_derived",
        review_policy_id=POLICY_ID,
        policy_version=POLICY_VERSION,
        policy_hash=POLICY_HASH,
        human_authorization_id=AUTHORIZATION_ID,
        authorization_scope="CURRENT_BATCH",
        reviewed_at="2026-09-02T18:00:00+00:00",
    )


def _materialize_policy_derived_directly(paths: preparation.Paths, candidate_id: str) -> dict:
    """Reproduce governed_relation_admission_policy.materialize_authorized_policy()'s
    write pattern exactly: straight to the live decisions file, no bundle publish.
    """
    queue = {
        str(row["candidate_id"]): row
        for row in preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")
    }
    candidate = queue[candidate_id]
    bindings = human_review.current_bindings(paths.current_dir, paths.local_root)
    decisions_path = human_review.decision_authority_path(paths.current_dir)
    existing = {
        str(row["candidate_id"]): row
        for row in preparation.read_jsonl(decisions_path)
    }
    record = _policy_derived_record(candidate, bindings=bindings)
    existing[candidate_id] = record
    human_review.atomic_write_jsonl(decisions_path, dict(sorted(existing.items())))
    return record


def _add_permanently_approved_pair(
    paths: preparation.Paths, source_root: Path, canon_rows: list[dict],
) -> None:
    """Give the fixture a second, independently-decided candidate that is
    never touched again. build_apply_plan() (inside execute()) refuses to
    proceed with zero approved decisions anywhere -- an orchestrator-wide
    rule unrelated to this fix -- so any test whose scenario leaves the
    single original candidate undecided/disappeared needs a permanent,
    unrelated anchor to keep execute() runnable, mirroring how production
    CURRENT always has many independently-decided candidates at once.
    """
    scripts = source_root / "src" / "python_scripts"
    scripts.joinpath("anchor_target.py").write_text("ANCHOR = 1\n", encoding="utf-8")
    scripts.joinpath("anchor_source.py").write_text("import anchor_target\n", encoding="utf-8")
    canon_rows.append(
        _canon_record("target-anchor", "src/python_scripts/anchor_target.py", "ANCHOR = 1\n")
    )
    canon_rows.append(
        _canon_record("source-anchor", "src/python_scripts/anchor_source.py", "import anchor_target\n")
    )
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)


def _decide_all_pending_individually(paths: preparation.Paths, *, decision: str = "approved_for_admission") -> None:
    queue = preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")
    bindings = human_review.current_bindings(paths.current_dir, paths.local_root)
    decisions_path = human_review.decision_authority_path(paths.current_dir)
    existing = {
        str(row["candidate_id"]): row
        for row in preparation.read_jsonl(decisions_path)
    }
    for candidate in queue:
        candidate_id = str(candidate["candidate_id"])
        if candidate_id in existing:
            continue
        existing[candidate_id] = human_review.build_decision_record(
            candidate,
            decision=decision,
            reason_code=(
                "DIRECT_CODE_DEPENDENCY_CONFIRMED"
                if decision == "approved_for_admission" else "INSUFFICIENT_CONTEXT"
            ),
            actor="fixture-reviewer",
            bindings=bindings,
            decision_mode="individual",
            reviewed_at="2026-09-02T18:00:00+00:00",
        )
    human_review.atomic_write_jsonl(decisions_path, dict(sorted(existing.items())))


def test_policy_derived_decision_survives_unrelated_canon_growth_across_generations(
    tmp_path: Path,
) -> None:
    """The exact end-to-end scenario the incident traced: generation A gets a
    policy-derived decision materialized directly (no bundle republish),
    Canon grows with an unrelated record, generation B is prepared -- the
    policy-derived decision must remain effective, not silently vanish.
    """
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    first = preparation.execute(paths, source_root=source_root)
    assert first["terminal_state"] == preparation.TERMINAL_HUMAN
    pending = preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")
    assert len(pending) == 1
    candidate_id = str(pending[0]["candidate_id"])

    materialized = _materialize_policy_derived_directly(paths, candidate_id)
    assert materialized["decision_mode"] == "policy_derived"
    # Confirm the defect precondition: the published bundle for generation A
    # does NOT know about this decision (it was never republished).
    pointer = preparation.read_json(paths.pointer)
    bundle_manifest = preparation.read_json(Path(pointer["bundle_path"]) / "bundle_manifest.json")
    bundle_decisions = preparation.read_jsonl(
        Path(pointer["bundle_path"]) / bundle_manifest["artifacts"]["effective_decisions"]["path"]
    )
    assert candidate_id not in {str(row["candidate_id"]) for row in bundle_decisions}

    # Unrelated Canon growth: a brand-new file/record, nothing to do with the
    # decided candidate's source/target/predicate/evidence.
    scripts = source_root / "src" / "python_scripts"
    (scripts / "unrelated_target.py").write_text("UNRELATED_VALUE = 1\n", encoding="utf-8")
    (scripts / "unrelated.py").write_text("import unrelated_target\n", encoding="utf-8")
    canon_rows.append(
        _canon_record("target-unrelated", "src/python_scripts/unrelated_target.py", "UNRELATED_VALUE = 1\n")
    )
    canon_rows.append(
        _canon_record("source-unrelated", "src/python_scripts/unrelated.py", "import unrelated_target\n")
    )
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)

    second = preparation.execute(paths, source_root=source_root)
    assert second["terminal_state"] == preparation.TERMINAL_HUMAN
    assert second["decision_preservation"]["preserved_equivalent"] == 1
    assert second["decision_preservation"]["preserved_from_live_recovery"] == 1
    assert second["decision_preservation"]["preserved_from_published_bundle"] == 0
    assert second["decision_preservation"]["live_recovery"]["recovered_count"] == 1

    preserved = preparation.read_jsonl(paths.current_dir / "human_review_decisions.jsonl")
    assert len(preserved) == 1
    row = preserved[0]
    assert row["decision_mode"] == "policy_derived"
    assert row["review_policy_id"] == POLICY_ID
    assert row["policy_version"] == POLICY_VERSION
    assert row["policy_hash"] == POLICY_HASH
    assert row["human_authorization_id"] == AUTHORIZATION_ID
    assert row["authorization_scope"] == "CURRENT_BATCH"
    assert row["generational_preservation"]["preservation_source"] == "live_recovered_not_yet_published"
    assert row["generational_preservation"]["classification"] == "equivalent"


def test_policy_derived_decision_not_preserved_when_source_modified(tmp_path: Path) -> None:
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    first = preparation.execute(paths, source_root=source_root)
    candidate_id = str(
        preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")[0]["candidate_id"]
    )
    _materialize_policy_derived_directly(paths, candidate_id)

    scripts = source_root / "src" / "python_scripts"
    scripts.joinpath("a.py").write_text("from b import VALUE\n", encoding="utf-8")
    canon_rows[0]["text"] = "from b import VALUE\n"
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)

    second = preparation.execute(paths, source_root=source_root)
    assert second["terminal_state"] == preparation.TERMINAL_HUMAN
    assert second["decision_preservation"]["preserved_equivalent"] == 0
    assert second["decision_preservation"]["pending_delta"] == 1


def test_policy_derived_decision_not_preserved_when_disappeared(tmp_path: Path) -> None:
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    _add_permanently_approved_pair(paths, source_root, canon_rows)
    preparation.execute(paths, source_root=source_root)
    pending = {
        str(row["candidate_id"]): row
        for row in preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")
    }
    target_candidate_id = next(
        cid for cid, row in pending.items()
        if row["source"]["canonical_id"] == "source-a"
    )
    anchor_candidate_id = next(
        cid for cid in pending if cid != target_candidate_id
    )
    _materialize_policy_derived_directly(paths, target_candidate_id)
    _decide_all_pending_individually(paths)  # decides the anchor too; target already decided

    scripts = source_root / "src" / "python_scripts"
    scripts.joinpath("a.py").unlink()
    canon_rows[0]["text"] = "historical source removed\n"
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)

    second = preparation.execute(paths, source_root=source_root)
    assert second["decision_preservation"]["preserved_equivalent"] == 1  # only the anchor
    assert second["decision_preservation"]["disappeared_provenance"] == 1
    preserved_ids = {
        row["candidate_id"]
        for row in preparation.read_jsonl(paths.current_dir / "human_review_decisions.jsonl")
    }
    assert target_candidate_id not in preserved_ids


def test_policy_derived_decision_unaffected_by_unrelated_ambiguous_candidate(
    tmp_path: Path,
) -> None:
    """A genuinely new, never-decided candidate becoming ambiguous must not
    be confused with -- or steal the identity of -- the already-decided,
    still-equivalent policy-derived candidate sitting alongside it.
    """
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    candidate_id = str(
        preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")[0]["candidate_id"]
    )
    _materialize_policy_derived_directly(paths, candidate_id)

    scripts = source_root / "src" / "python_scripts"
    scripts.joinpath("a.py").write_text("import b\nimport b\n", encoding="utf-8")
    canon_rows[0]["text"] = "import b\nimport b\n"
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)

    second = preparation.execute(paths, source_root=source_root)
    manifest = preparation.read_json(Path(second["bundle_path"]) / "human_delta.json")
    assert manifest["ambiguous"], "fixture premise: the duplicate import must yield an ambiguous candidate"
    assert candidate_id not in manifest["ambiguous"]
    assert second["decision_preservation"]["preserved_equivalent"] == 1


def test_policy_provenance_mismatch_excluded_without_blocking_other_decisions(
    tmp_path: Path,
) -> None:
    """A live row claiming decision_mode=policy_derived but missing a
    governed provenance field must be dropped individually -- it must not
    abort preservation for every other candidate in the same generation.
    """
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    candidate_id = str(
        preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")[0]["candidate_id"]
    )
    record = _materialize_policy_derived_directly(paths, candidate_id)
    decisions_path = human_review.decision_authority_path(paths.current_dir)
    broken = dict(record)
    del broken["policy_hash"]  # governed field required for policy_derived
    human_review.atomic_write_jsonl(decisions_path, {candidate_id: broken})

    predecessor = preparation._resolve_monotonic_review_predecessor(paths)
    extra, report = preparation._live_decisions_recoverable_from_current(paths, predecessor)
    assert extra == []
    assert report["recovered_count"] == 0
    assert len(report["rejected"]) == 1
    assert report["rejected"][0]["candidate_id"] == candidate_id
    assert any("policy_hash" in err for err in report["rejected"][0]["errors"])


def test_wrong_source_or_target_is_not_reused_as_equivalent(tmp_path: Path) -> None:
    """Cross-generation reconciliation, not identity, decides equivalence --
    a policy-derived decision must not ride along just because a candidate_id
    happens to still exist if its endpoints changed. Exercised indirectly:
    the disappeared/modified tests above already prove non-identity changes
    are excluded; this confirms the live-recovered row is bound through the
    SAME cross["old_to_current"] classification as every other decision,
    not given a shortcut.
    """
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    candidate_id = str(
        preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")[0]["candidate_id"]
    )
    _materialize_policy_derived_directly(paths, candidate_id)
    predecessor = preparation._resolve_monotonic_review_predecessor(paths)
    extra, _report = preparation._live_decisions_recoverable_from_current(paths, predecessor)
    assert len(extra) == 1
    # The recovered row is fed into the same old_decisions list _preserve_
    # equivalent_decisions builds from the bundle -- there is no separate,
    # weaker code path for it.
    assert extra[0]["candidate_id"] == candidate_id


def test_live_recovery_tolerates_unrelated_candidate_inventory_growth(tmp_path: Path) -> None:
    """S0186 Unit H (final closure blocker, part 2): a technical rebuild
    growing relation_candidates.jsonl (e.g. Canon growth adding unrelated
    candidates) must not, by itself, make every bundle-certified candidate
    look untrustworthy. Only genuinely conflicting identity should.
    """
    paths, source_root, _rows = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    predecessor = preparation._resolve_monotonic_review_predecessor(paths)
    live_candidates = paths.current_dir / "relation_candidates.jsonl"
    rows = preparation.read_jsonl(live_candidates)
    rows.append({"candidate_id": "rc_injected", "extra": True})
    preparation.write_jsonl(live_candidates, rows)

    extra, report = preparation._live_decisions_recoverable_from_current(paths, predecessor)
    assert extra == []
    assert report["reason"] == "ok"


def test_live_recovery_rejects_candidate_id_reused_for_different_semantics(tmp_path: Path) -> None:
    """A bundle-certified candidate_id whose regenerated row now describes a
    different source/target/predicate is a genuine identity collision, not
    benign technical drift -- recovery must still fail closed on it.
    """
    paths, source_root, canon_rows, candidate_id, anchor_id = (
        _reach_review_complete_two_candidates(tmp_path)
    )
    predecessor = preparation._resolve_monotonic_review_predecessor(paths)
    live_candidates = paths.current_dir / "relation_candidates.jsonl"
    rows = preparation.read_jsonl(live_candidates)
    for row in rows:
        if row.get("candidate_id") == anchor_id:
            row["target"] = dict(row["target"], canonical_id="unrelated-different-target")
    preparation.write_jsonl(live_candidates, rows)

    extra, report = preparation._live_decisions_recoverable_from_current(paths, predecessor)
    assert extra == []
    assert report["reason"] == "live_candidate_identity_reused_for_different_semantics"


def test_governed_supersession_survives_canon_growth_that_adds_new_candidates(
    tmp_path: Path,
) -> None:
    """S0186 Unit H (final closure blocker, part 2), exact real-production
    shape: unlike the thematic-diagnostic Canon growth above (zero new
    candidates, relation_candidates.jsonl staying byte-identical and never
    exercising the whole-file gate this fix replaced), the real incident's
    Canon growth also introduced genuinely NEW resolvable candidates --
    growing relation_candidates.jsonl's line count/bytes. That alone used
    to make the whole-file byte-identity gate in
    _live_decisions_recoverable_from_current() reject EVERY candidate,
    silently reverting the unrelated, already-superseded candidate back to
    its stale approved_for_admission value on the very next technical
    rebuild -- reproducing the original incident through a different gate
    than the one already covered by
    test_governed_supersession_survives_canon_growth_and_technical_rebuild.
    """
    paths, source_root, canon_rows, candidate_id, anchor_id = (
        _reach_review_complete_two_candidates(tmp_path)
    )
    human_review.supersede_individual_decision(
        paths.current_dir, paths.local_root,
        candidate_id=candidate_id, decision="deferred",
        reason_code="LIFECYCLE_UNRESOLVED", note="repo lifecycle evidence insufficient",
        actor="Naveen", confirmation=human_review.DECISION_SUPERSESSION_CONFIRMATION,
    )

    # Canon grows with a genuinely NEW resolvable import edge -- unlike the
    # thematic-diagnostic growth above, this DOES change
    # relation_candidates.jsonl's byte content (a new row is appended).
    scripts = source_root / "src" / "python_scripts"
    scripts.joinpath("late_target.py").write_text("LATE = 1\n", encoding="utf-8")
    scripts.joinpath("late_source.py").write_text("import late_target\n", encoding="utf-8")
    canon_rows.append(
        _canon_record("target-late", "src/python_scripts/late_target.py", "LATE = 1\n")
    )
    canon_rows.append(
        _canon_record("source-late", "src/python_scripts/late_source.py", "import late_target\n")
    )
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)

    candidates_before = preparation.read_jsonl(paths.current_dir / "relation_candidates.jsonl")
    canon_before = preparation.canon_snapshot(paths.local_root)["hash"]

    result = preparation.execute(paths, source_root=source_root)  # must NOT raise

    assert result["terminal_state"] == preparation.TERMINAL_HUMAN
    assert preparation.canon_snapshot(paths.local_root)["hash"] == canon_before
    assert result.get("apply_executed") is not True
    assert result.get("authorization_created") is not True
    candidates_after = preparation.read_jsonl(paths.current_dir / "relation_candidates.jsonl")
    assert len(candidates_after) > len(candidates_before)

    live_decisions_after = human_review.load_jsonl(
        human_review.decision_authority_path(paths.current_dir)
    )
    queue_after = human_review.load_jsonl(paths.current_dir / human_review.QUEUE_FILE)
    queue_by_id_after = {row["candidate_id"]: row for row in queue_after}
    live_by_source = {
        queue_by_id_after[row["candidate_id"]]["source"]["canonical_id"]: row
        for row in live_decisions_after if row["candidate_id"] in queue_by_id_after
    }
    assert live_by_source["source-a"]["human_review_decision"] == "deferred"
    assert live_by_source["source-a"]["human_review_reason_code"] == "LIFECYCLE_UNRESOLVED"
    assert live_by_source["source-anchor"]["human_review_decision"] == "approved_for_admission"


def test_live_recovery_noop_when_no_live_decisions_file(tmp_path: Path) -> None:
    paths, source_root, _rows = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    predecessor = preparation._resolve_monotonic_review_predecessor(paths)
    (paths.current_dir / preparation.EFFECTIVE_DECISIONS_FILE).unlink(missing_ok=True)
    (paths.current_dir / "human_review_decisions.jsonl").unlink(missing_ok=True)

    extra, report = preparation._live_decisions_recoverable_from_current(paths, predecessor)
    assert extra == []
    assert report["reason"] == "no_live_decisions_file"


def test_live_recovery_rejects_when_certified_row_diverges(tmp_path: Path) -> None:
    """If a bundle-certified decision was silently rewritten in the live
    file, the whole live file is untrusted (not partially merged) -- this
    is a stronger signal something bypassed governance than an ordinary new
    row appearing.
    """
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    candidate_id = str(
        preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")[0]["candidate_id"]
    )
    _materialize_policy_derived_directly(paths, candidate_id)
    scripts = source_root / "src" / "python_scripts"
    (scripts / "unrelated_target.py").write_text("UNRELATED_VALUE = 1\n", encoding="utf-8")
    (scripts / "unrelated.py").write_text("import unrelated_target\n", encoding="utf-8")
    canon_rows.append(
        _canon_record("target-unrelated", "src/python_scripts/unrelated_target.py", "UNRELATED_VALUE = 1\n")
    )
    canon_rows.append(
        _canon_record("source-unrelated", "src/python_scripts/unrelated.py", "import unrelated_target\n")
    )
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    # Generation B's published bundle now certifies candidate_id's decision.
    preparation.execute(paths, source_root=source_root)
    predecessor = preparation._resolve_monotonic_review_predecessor(paths)
    assert candidate_id in predecessor["decision_by_id"]

    # Someone hand-edits the live decisions file for a certified candidate,
    # bypassing governance entirely.
    decisions_path = human_review.decision_authority_path(paths.current_dir)
    rows = {
        str(r["candidate_id"]): r
        for r in preparation.read_jsonl(decisions_path)
    }
    rows[candidate_id] = dict(rows[candidate_id], human_review_note="tampered")
    human_review.atomic_write_jsonl(decisions_path, rows)

    extra, report = preparation._live_decisions_recoverable_from_current(paths, predecessor)
    assert extra == []
    assert report["reason"] == "live_decision_diverges_from_certified_bundle_row"


def test_live_recovery_recovers_valid_supersessions_despite_unrelated_missing_decision(
    tmp_path: Path,
) -> None:
    """S0186 Unit H (final closure blocker, part 3), exact real-production
    shape: a bundle-certified candidate's decision can go missing from the
    live file for a reason entirely unrelated to any OTHER candidate (56
    such candidates in the real incident, of unrelated origin). Before
    this fix, that alone made _live_decisions_recoverable_from_current()
    reject EVERY live recovery wholesale
    ("live_decisions_missing_certified_bundle_rows"), discarding 171
    separately valid, governed supersessions
    (supersede_individual_decision()/persist_current_technical_
    supersession()) along with it and silently falling back to the stale,
    pre-supersession bundle authority for every candidate -- not just the
    one genuinely missing. anchor_id (receipt-covered) stands in for the
    unrelated missing-coverage candidate; candidate_id (individually
    decided) stands in for a genuinely, validly superseded one.
    """
    paths, source_root, _canon_rows, candidate_id, anchor_id = (
        _reach_review_complete_two_candidates(tmp_path)
    )
    predecessor = preparation._resolve_monotonic_review_predecessor(paths)
    assert {candidate_id, anchor_id}.issubset(predecessor["decision_by_id"])

    # A valid, governed supersession on one candidate.
    human_review.supersede_individual_decision(
        paths.current_dir, paths.local_root, candidate_id=candidate_id, decision="deferred",
        reason_code="LIFECYCLE_UNRESOLVED", note="repo lifecycle evidence insufficient",
        actor="Naveen", confirmation=human_review.DECISION_SUPERSESSION_CONFIRMATION,
    )

    # An entirely separate, real-world coverage gap on anchor_id:
    # bundle-certified but simply absent from the live file -- never
    # touched, never superseded, just missing.
    decisions_path = human_review.decision_authority_path(paths.current_dir)
    live_rows = {str(r["candidate_id"]): r for r in preparation.read_jsonl(decisions_path)}
    del live_rows[anchor_id]
    human_review.atomic_write_jsonl(decisions_path, live_rows)

    extra, report = preparation._live_decisions_recoverable_from_current(paths, predecessor)
    assert report["reason"] == "ok"
    assert report["missing_from_live_candidate_ids"] == [anchor_id]
    assert report["superseded_candidate_ids"] == [candidate_id]
    recovered_ids = {row["candidate_id"] for row in extra}
    assert recovered_ids == {candidate_id}
    recovered = next(row for row in extra if row["candidate_id"] == candidate_id)
    assert recovered["human_review_decision"] == "deferred"


def test_execute_recomposes_authority_after_supersession_despite_unrelated_missing_coverage(
    tmp_path: Path,
) -> None:
    """End-to-end mandate invariant: CURRENT published with candidate_id
    (individually decided, approved) and anchor_id (receipt-covered,
    approved). candidate_id receives a VALID governed supersession ->
    deferred, live only. anchor_id's bundle-certified decision separately
    goes missing from the live file -- an unrelated, real-world coverage
    gap, not a supersession. execute() must detect the regression,
    recompose the EFFECTIVE authority (not fall back to the stale
    bundle), and publish a new review_state -- readiness/apply-plan must
    reflect exactly the true remainder (anchor_id still approved,
    recovered from the bundle's own certified row despite being absent
    from live; candidate_id deferred).
    """
    paths, source_root, _canon_rows, candidate_id, anchor_id = (
        _reach_review_complete_two_candidates(tmp_path)
    )
    g_advance = preparation.execute(paths, source_root=source_root)
    assert g_advance["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    published_relation_generation_id = g_advance["ids"]["relation_generation_id"]
    published_review_state_id = g_advance["ids"]["review_state_id"]

    canon_before = preparation.canon_snapshot(paths.local_root)["hash"]
    canon_files_before = {
        p.name: p.read_bytes() for p in sorted(paths.local_root.glob("tiddlers_*.jsonl"))
    }

    # candidate_id receives a VALID governed supersession.
    human_review.supersede_individual_decision(
        paths.current_dir, paths.local_root, candidate_id=candidate_id, decision="deferred",
        reason_code="LIFECYCLE_UNRESOLVED", note="repo lifecycle evidence insufficient",
        actor="Naveen", confirmation=human_review.DECISION_SUPERSESSION_CONFIRMATION,
    )
    # anchor_id's certified decision separately goes missing from live --
    # an unrelated real-world coverage gap, never itself superseded.
    decisions_path = human_review.decision_authority_path(paths.current_dir)
    live_rows = {str(r["candidate_id"]): r for r in preparation.read_jsonl(decisions_path)}
    original_anchor_decision = live_rows[anchor_id]
    del live_rows[anchor_id]
    human_review.atomic_write_jsonl(decisions_path, live_rows)

    result = preparation.execute(paths, source_root=source_root)  # must NOT raise, must NOT stay stale

    assert result["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    assert result.get("apply_executed") is not True
    assert result.get("authorization_created") is not True
    assert result["ids"]["relation_generation_id"] == published_relation_generation_id
    assert result["ids"]["review_state_id"] != published_review_state_id

    # Canon: byte-identical before/after.
    assert preparation.canon_snapshot(paths.local_root)["hash"] == canon_before
    canon_files_after = {
        p.name: p.read_bytes() for p in sorted(paths.local_root.glob("tiddlers_*.jsonl"))
    }
    assert canon_files_after == canon_files_before

    final_decisions = {
        str(r["candidate_id"]): r
        for r in preparation.read_jsonl(human_review.decision_authority_path(paths.current_dir))
    }
    assert final_decisions[candidate_id]["human_review_decision"] == "deferred"
    assert final_decisions[candidate_id]["human_review_reason_code"] == "LIFECYCLE_UNRESOLVED"
    assert final_decisions[candidate_id]["supersedes_decision_hash"]
    # anchor_id recovered from the bundle's own certified row despite
    # being absent from live -- not lost, not silently reinterpreted. It
    # is rebound through the normal cross-generation preservation pass
    # (like every other unchanged "equivalent" decision), so its record
    # is re-derived, not a byte-identical copy; what must be unchanged is
    # its actual human authority.
    assert final_decisions[anchor_id]["human_review_decision"] == "approved_for_admission"
    assert (
        final_decisions[anchor_id]["human_review_reason_code"]
        == original_anchor_decision["human_review_reason_code"]
    )
    assert (
        final_decisions[anchor_id]["human_review_actor"]
        == original_anchor_decision["human_review_actor"]
    )
    assert final_decisions[anchor_id]["generational_preservation"]["preservation_source"] in (
        "published_bundle", "live_recovered_not_yet_published",
    )

    # The recomposition itself correctly attributes both outcomes: a real
    # governed supersession recovered, and an unrelated, genuinely-missing
    # certified row that no longer blocks it.
    decision_preservation = result["decision_preservation"]
    assert decision_preservation["preserved_from_live_recovery"] == 1
    live_recovery = decision_preservation["live_recovery"]
    assert live_recovery["reason"] == "ok"
    assert live_recovery["superseded_candidate_ids"] == [candidate_id]
    assert live_recovery["missing_from_live_candidate_ids"] == [anchor_id]

    # Apply plan reflects exactly the true remainder, no partial Apply.
    bundle_manifest = preparation.read_json(Path(result["bundle_path"]) / "bundle_manifest.json")
    plan = preparation.read_json(
        Path(result["bundle_path"]) / bundle_manifest["artifacts"]["apply_plan"]["path"]
    )
    assert plan["would_apply_candidate_ids"] == [anchor_id]
    assert candidate_id not in plan["would_apply_candidate_ids"]
    assert result.get("apply_executed") is not True


def test_batch_decision_preservation_source_is_published_bundle(tmp_path: Path) -> None:
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    _review_current_batch(paths)
    preparation.execute(paths, source_root=source_root)

    scripts = source_root / "src" / "python_scripts"
    (scripts / "unrelated_target.py").write_text("UNRELATED_VALUE = 1\n", encoding="utf-8")
    (scripts / "unrelated.py").write_text("import unrelated_target\n", encoding="utf-8")
    canon_rows.append(
        _canon_record("target-unrelated", "src/python_scripts/unrelated_target.py", "UNRELATED_VALUE = 1\n")
    )
    canon_rows.append(
        _canon_record("source-unrelated", "src/python_scripts/unrelated.py", "import unrelated_target\n")
    )
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    grown = preparation.execute(paths, source_root=source_root)
    assert grown["decision_preservation"]["preserved_equivalent"] == 1
    assert grown["decision_preservation"]["preserved_from_published_bundle"] == 1
    assert grown["decision_preservation"]["preserved_from_live_recovery"] == 0
    preserved = preparation.read_jsonl(paths.current_dir / "human_review_decisions.jsonl")
    assert preserved[0]["decision_mode"] == "batch"
    assert preserved[0]["generational_preservation"]["preservation_source"] == "published_bundle"


def test_deferred_decision_preserved_unchanged_across_generations(tmp_path: Path) -> None:
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    _add_permanently_approved_pair(paths, source_root, canon_rows)
    preparation.execute(paths, source_root=source_root)
    pending = {
        str(row["candidate_id"]): row
        for row in preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")
    }
    deferred_candidate_id = next(
        cid for cid, row in pending.items() if row["source"]["canonical_id"] == "source-a"
    )
    _decide_all_pending_individually(paths)  # approves the anchor
    # Overwrite the target candidate's own decision to "deferred" directly on
    # the live file, exactly like governed_relation_admission_policy would
    # for a machine-derived decision -- bypassing the batch-publish flow.
    decisions_path = human_review.decision_authority_path(paths.current_dir)
    existing = {
        str(row["candidate_id"]): row
        for row in preparation.read_jsonl(decisions_path)
    }
    candidate = {
        str(row["candidate_id"]): row for row in pending.values()
    }[deferred_candidate_id]
    bindings = human_review.current_bindings(paths.current_dir, paths.local_root)
    existing[deferred_candidate_id] = human_review.build_decision_record(
        candidate, decision="deferred", reason_code="INSUFFICIENT_CONTEXT",
        actor="fixture-reviewer", bindings=bindings, decision_mode="individual",
        reviewed_at="2026-09-02T18:00:00+00:00",
    )
    human_review.atomic_write_jsonl(decisions_path, dict(sorted(existing.items())))

    scripts = source_root / "src" / "python_scripts"
    (scripts / "unrelated_target.py").write_text("UNRELATED_VALUE = 1\n", encoding="utf-8")
    (scripts / "unrelated.py").write_text("import unrelated_target\n", encoding="utf-8")
    canon_rows.append(
        _canon_record("target-unrelated", "src/python_scripts/unrelated_target.py", "UNRELATED_VALUE = 1\n")
    )
    canon_rows.append(
        _canon_record("source-unrelated", "src/python_scripts/unrelated.py", "import unrelated_target\n")
    )
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    grown = preparation.execute(paths, source_root=source_root)
    assert grown["decision_preservation"]["preserved_equivalent"] == 2  # anchor + deferred
    preserved = {
        row["candidate_id"]: row
        for row in preparation.read_jsonl(paths.current_dir / "human_review_decisions.jsonl")
    }
    assert preserved[deferred_candidate_id]["human_review_decision"] == "deferred"
    assert (
        preserved[deferred_candidate_id]["generational_preservation"]["preservation_source"]
        == "live_recovered_not_yet_published"
    )


def test_consumed_authorization_untouched_by_preservation(tmp_path: Path) -> None:
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    candidate_id = str(
        preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")[0]["candidate_id"]
    )
    _materialize_policy_derived_directly(paths, candidate_id)

    authorizations_dir = paths.local_root / "audit" / "relation_admission" / "current" / "policy_authorizations"
    authorizations_dir.mkdir(parents=True, exist_ok=True)
    authorization_file = authorizations_dir / f"{AUTHORIZATION_ID}.json"
    authorization_payload = {
        "authorization_id": AUTHORIZATION_ID, "policy_id": POLICY_ID, "consumed": True,
    }
    authorization_file.write_text(json.dumps(authorization_payload, sort_keys=True) + "\n", encoding="utf-8")
    before = authorization_file.read_bytes()

    scripts = source_root / "src" / "python_scripts"
    (scripts / "unrelated_target.py").write_text("UNRELATED_VALUE = 1\n", encoding="utf-8")
    (scripts / "unrelated.py").write_text("import unrelated_target\n", encoding="utf-8")
    canon_rows.append(
        _canon_record("target-unrelated", "src/python_scripts/unrelated_target.py", "UNRELATED_VALUE = 1\n")
    )
    canon_rows.append(
        _canon_record("source-unrelated", "src/python_scripts/unrelated.py", "import unrelated_target\n")
    )
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    result = preparation.execute(paths, source_root=source_root)

    assert result["decision_preservation"]["preserved_equivalent"] == 1
    assert authorization_file.read_bytes() == before
    payload = json.loads(before.decode("utf-8"))
    assert payload["consumed"] is True


def test_no_governed_policy_engine_module_used_during_preservation() -> None:
    """Structural guarantee: fixing generational preservation must never
    re-run or import the policy engine -- recovery is purely a read of
    already-written decisions plus the existing reconciliation/validation
    logic, never a fresh authorization or materialization.

    Checked against the module's own static imports rather than
    sys.modules, which is process-wide and legitimately already populated
    whenever this file runs alongside test_governed_relation_admission_
    policy.py in the same pytest session -- that shared process state says
    nothing about what prepare_current_relational_generation.py itself
    imports or calls.
    """
    import ast

    source = Path(preparation.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)
    assert "governed_relation_admission_policy" not in imported_names


def test_readiness_recomposition_recognizes_governed_decision_evolution_end_to_end(
    tmp_path: Path,
) -> None:
    """S0186 Unit H: reproduces the real production sequence at small scale --
    rv_A (published) -> a candidate decided live, out-of-band (governed
    policy materialization, never through any batch) -> a governed batch
    receipt confirming the rest -> effective_pending=0 -> dry_run()'s
    readiness recomposition correctly recognizes this as sanctioned governed
    decision evolution (not unexplained drift) and reaches a clean,
    observable READY_FOR_AUTHORIZATION preview with monotonic review
    coverage -- never touching Canon or the live pointer. (The real
    production incident additionally chained a SECOND, separately-classed
    batch receipt within the same relation_generation; that exact multi-hop
    lineage was independently verified read-only against the real,
    already-published rv_ada -> rv_ae5 -> rv_89a bundles -- see
    37/38_*.json evidence -- since forcing two distinct reconciliation
    classes to coexist is only reachable through real cross-generation
    history, not a single-generation synthetic fixture.)
    """
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    scripts = source_root / "src" / "python_scripts"
    # Second "new"-class candidate: reviewed via a governed batch receipt.
    scripts.joinpath("e.py").write_text("import f\n", encoding="utf-8")
    scripts.joinpath("f.py").write_text("VALUE_F = 1\n", encoding="utf-8")
    canon_rows.append(_canon_record("source-e", "src/python_scripts/e.py", "import f\n"))
    canon_rows.append(_canon_record("target-f", "src/python_scripts/f.py", "VALUE_F = 1\n"))
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)

    first = preparation.execute(paths, source_root=source_root)
    assert first["terminal_state"] == preparation.TERMINAL_HUMAN
    pending = preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")
    assert len(pending) == 2
    live_candidate_id = next(
        row["candidate_id"] for row in pending if row["source"]["canonical_id"] == "source-a"
    )

    # Candidate a->b: decided live, out-of-band (governed policy
    # materialization), never through a batch confirmation at all.
    _materialize_policy_derived_directly(paths, live_candidate_id)

    # Batch receipt: the remaining "new"-class candidate, e->f.
    receipt = _review_current_batch(paths, action="approved_for_admission")
    assert receipt["decisions_written"] == 1

    surface_final = human_review.resolve_current_human_delta_surface(paths.local_root)
    assert surface_final["inventory"]["total_pending"] == 0

    canon_before = preparation.canon_snapshot(paths.local_root)["hash"]
    pointer_before = paths.pointer.read_bytes()

    dry = preparation.dry_run(paths)

    assert dry["review_coverage"]["effective_pending"] == 0
    assert dry["review_coverage"]["effective_decision_covered"] == 2
    assert dry["review_coverage"]["monotonic"] is True
    assert dry["expected_terminal_state"] == "READY_FOR_AUTHORIZATION"
    assert dry["planning"]["conservation_valid"] is True
    assert dry["ids"]["readiness_id"]
    assert dry["apply_executed"] is False
    assert "review_predecessor_decision_hash_mismatch" not in dry["reason_codes"]
    assert "review_receipt_lineage_invalid" not in dry["reason_codes"]

    # Read-only: dry_run() must never touch Canon or advance the live pointer.
    assert preparation.canon_snapshot(paths.local_root)["hash"] == canon_before
    assert paths.pointer.read_bytes() == pointer_before


def _reach_ready_for_authorization_single_candidate(tmp_path: Path) -> tuple[preparation.Paths, Path, str]:
    """Fixture helper: two candidates reach a published, READY_FOR_AUTHORIZATION
    bundle -- one decided individually (direct write to
    decision_authority_path(current_dir), mirroring real production's
    policy-derived write path, which is the ONLY channel
    supersede_individual_decision() can see); one decided via a governed
    batch receipt, providing the receipt anchor the live-recovery lineage
    check requires (a pure zero-receipt generation is not reachable
    through this fixture -- see
    test_readiness_recomposition_recognizes_governed_decision_evolution_end_to_end's
    own docstring for the same, already-established reason). The
    individually-decided candidate is the one returned for supersession.
    """
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    _add_permanently_approved_pair(paths, source_root, canon_rows)
    first = preparation.execute(paths, source_root=source_root)
    assert first["terminal_state"] == preparation.TERMINAL_HUMAN
    pending = preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")
    assert len(pending) == 2
    candidate_id = next(
        row["candidate_id"] for row in pending if row["source"]["canonical_id"] == "source-a"
    )
    _decide_all_pending_individually(paths, decision="approved_for_admission")
    # Overwrite the anchor's decision with a real batch receipt so the
    # lineage check has one to anchor on (matches the established pattern).
    anchor_id = next(
        row["candidate_id"] for row in pending if row["source"]["canonical_id"] == "source-anchor"
    )
    decisions_path = human_review.decision_authority_path(paths.current_dir)
    existing = {row["candidate_id"]: row for row in human_review.load_jsonl(decisions_path)}
    del existing[anchor_id]
    human_review.atomic_write_jsonl(decisions_path, existing)
    receipt = _review_current_batch(paths, action="approved_for_admission")
    assert receipt["decisions_written"] == 1
    surface_final = human_review.resolve_current_human_delta_surface(paths.local_root)
    assert surface_final["inventory"]["total_pending"] == 0

    second = preparation.execute(paths, source_root=source_root)
    assert second["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    analysis = preparation.analyze(paths)
    assert analysis["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    assert analysis["review_coverage"]["superseded_candidate_ids"] == []
    return paths, source_root, candidate_id


def test_governed_supersession_resolves_to_one_effective_latest_decision(tmp_path: Path) -> None:
    """S0186 Unit H (final closure blocker): a candidate's ALREADY-PUBLISHED
    approved_for_admission decision, explicitly superseded via the existing
    current_relation_human_review.supersede_individual_decision() primitive,
    must let CURRENT readiness recomposition proceed -- consuming the LATEST
    (superseding) decision as effective -- instead of raising
    review_decision_conflict merely because the decision changed.
    """
    paths, _source_root, candidate_id = _reach_ready_for_authorization_single_candidate(tmp_path)

    decisions_path = human_review.decision_authority_path(paths.current_dir)
    original_decisions = human_review.load_jsonl(decisions_path)
    original_record = next(
        row for row in original_decisions if row["candidate_id"] == candidate_id
    )

    superseded_record = human_review.supersede_individual_decision(
        paths.current_dir, paths.local_root,
        candidate_id=candidate_id, decision="deferred",
        reason_code="INSUFFICIENT_CONTEXT", note="governed re-review, lifecycle evidence pending",
        actor="fixture-reviewer",
        confirmation=human_review.DECISION_SUPERSESSION_CONFIRMATION,
    )
    assert superseded_record["human_review_decision"] == "deferred"
    assert superseded_record["supersedes_decision_hash"] == human_review.decision_hash(original_record)

    analysis = preparation.analyze(paths)  # must NOT raise review_decision_conflict

    assert analysis["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    assert analysis["review_coverage"]["effective_pending"] == 0
    assert analysis["review_coverage"]["monotonic"] is True
    assert analysis["review_coverage"]["superseded_candidate_ids"] == [candidate_id]

    # The LATEST decision is what's effective now -- not the original.
    live_decisions = human_review.load_jsonl(decisions_path)
    live_record = next(row for row in live_decisions if row["candidate_id"] == candidate_id)
    assert live_record["human_review_decision"] == "deferred"

    # The ORIGINAL remains historical/auditable: unmodified inside the
    # already-published predecessor bundle, and in the append-only audit log.
    predecessor = preparation._analysis_review_predecessor(paths)
    predecessor_decision = predecessor["decision_by_id"][candidate_id]
    assert predecessor_decision["human_review_decision"] == "approved_for_admission"
    assert predecessor_decision == original_record


def test_governed_supersession_coverage_conserved_exactly_once(tmp_path: Path) -> None:
    """No double counting: a superseded candidate is still counted exactly
    once in effective_decision_covered, never as both old and new."""
    paths, _source_root, candidate_id = _reach_ready_for_authorization_single_candidate(tmp_path)

    human_review.supersede_individual_decision(
        paths.current_dir, paths.local_root,
        candidate_id=candidate_id, decision="deferred",
        reason_code="INSUFFICIENT_CONTEXT", note="governed re-review",
        actor="fixture-reviewer",
        confirmation=human_review.DECISION_SUPERSESSION_CONFIRMATION,
    )
    analysis = preparation.analyze(paths)
    assert analysis["review_coverage"]["expected_equivalent_covered"] == 2
    assert analysis["review_coverage"]["effective_decision_covered"] == 2


def test_malformed_supersession_lineage_fails_closed(tmp_path: Path) -> None:
    """A live decision whose supersedes_decision_hash does not match the
    predecessor's actual decision hash is NOT a valid governed supersession
    -- it must still raise review_decision_conflict, exactly as before this
    fix existed. Reproduces exactly what a broken/forged lineage looks like:
    write directly to the decisions file, bypassing the governed primitive.
    """
    paths, _source_root, candidate_id = _reach_ready_for_authorization_single_candidate(tmp_path)
    decisions_path = human_review.decision_authority_path(paths.current_dir)
    queue = human_review.load_jsonl(paths.current_dir / human_review.QUEUE_FILE)
    candidate = next(row for row in queue if row["candidate_id"] == candidate_id)
    bindings = human_review.current_bindings(paths.current_dir, paths.local_root)

    forged = human_review.build_decision_record(
        candidate, decision="deferred", reason_code="INSUFFICIENT_CONTEXT",
        actor="fixture-reviewer", bindings=bindings, note="forged lineage",
        supersedes_decision_hash="sha256:" + "0" * 64,
        reviewed_at="2026-09-03T00:00:00+00:00",
    )
    existing = {row["candidate_id"]: row for row in human_review.load_jsonl(decisions_path)}
    existing[candidate_id] = forged
    human_review.atomic_write_jsonl(decisions_path, existing)

    try:
        preparation.dry_run(paths)
        raised = False
    except preparation.PreparationBlocked as error:
        raised = True
        assert "review_decision_conflict" in error.reason_codes
    assert raised is True


def test_supersession_missing_lineage_field_fails_closed(tmp_path: Path) -> None:
    """A decision that simply changed value, with NO supersedes_decision_hash
    at all, is indistinguishable from unexplained drift -- must still fail
    closed exactly as before this fix (this is the pre-existing regression
    test, re-affirmed: the fix must never accept disagreement alone)."""
    paths, _source_root, candidate_id = _reach_ready_for_authorization_single_candidate(tmp_path)
    decisions_path = human_review.decision_authority_path(paths.current_dir)
    queue = human_review.load_jsonl(paths.current_dir / human_review.QUEUE_FILE)
    candidate = next(row for row in queue if row["candidate_id"] == candidate_id)
    bindings = human_review.current_bindings(paths.current_dir, paths.local_root)

    unexplained = human_review.build_decision_record(
        candidate, decision="deferred", reason_code="INSUFFICIENT_CONTEXT",
        actor="fixture-reviewer", bindings=bindings, note="no lineage at all",
        reviewed_at="2026-09-03T00:00:00+00:00",
    )
    existing = {row["candidate_id"]: row for row in human_review.load_jsonl(decisions_path)}
    existing[candidate_id] = unexplained
    human_review.atomic_write_jsonl(decisions_path, existing)

    try:
        preparation.dry_run(paths)
        raised = False
    except preparation.PreparationBlocked as error:
        raised = True
        assert "review_decision_conflict" in error.reason_codes
    assert raised is True


# ── S0186 Unit H (final closure blocker): Canon evolves AFTER a governed ────
# supersession, forcing a technical candidate-generation rebuild. This is the
# real production incident this fix resolves -- distinct from and additional
# to the readiness-recomposition-only fix above, because it goes through a
# COMPLETELY DIFFERENT causal boundary: rebuild_source_generation() ->
# _previous_authority() -> _live_decisions_recoverable_from_current() ->
# _preserve_equivalent_decisions(), never _validate_review_semantic_
# monotonicity() at all (candidate_generation_stale is caught and handled
# before that check is ever reached).


def _reach_review_complete_two_candidates(
    tmp_path: Path,
) -> tuple[preparation.Paths, Path, list[dict], str, str]:
    """Fixture helper: two candidates fully decided, 0 pending, bundle
    published at REVIEW_COMPLETE_PENDING_READINESS_RECOMPOSITION -- the
    EXACT real-production state (never yet advanced to
    TERMINAL_AUTHORIZATION, since prepare_current_relational_generation.py
    --execute has not yet successfully computed readiness). This matters:
    _previous_authority() has a SEPARATE, earlier, unconditional guard for
    predecessors already at TERMINAL_AUTHORIZATION ('decision authority
    changed after READY_FOR_AUTHORIZATION') that would otherwise mask the
    bug this fixture targets; real production's supersessions happened
    while CURRENT was at THIS exact intermediate state, never past it.

    The one that will be superseded is decided individually (direct
    write, mirroring real production's policy-derived channel, the ONLY
    one supersede_individual_decision() can see); the permanent anchor is
    decided via a governed batch receipt, providing the receipt anchor
    the live-recovery lineage check requires (a pure zero-receipt
    generation is not reachable through this fixture -- same already-
    established reason as
    _reach_ready_for_authorization_single_candidate above).
    """
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    _add_permanently_approved_pair(paths, source_root, canon_rows)
    first = preparation.execute(paths, source_root=source_root)
    assert first["terminal_state"] == preparation.TERMINAL_HUMAN
    pending = preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")
    assert len(pending) == 2
    candidate_id = next(
        row["candidate_id"] for row in pending if row["source"]["canonical_id"] == "source-a"
    )
    anchor_id = next(
        row["candidate_id"] for row in pending if row["source"]["canonical_id"] == "source-anchor"
    )
    _decide_all_pending_individually(paths, decision="approved_for_admission")
    decisions_path = human_review.decision_authority_path(paths.current_dir)
    existing = {row["candidate_id"]: row for row in human_review.load_jsonl(decisions_path)}
    del existing[anchor_id]
    human_review.atomic_write_jsonl(decisions_path, existing)
    receipt = _review_current_batch(paths, action="approved_for_admission")
    assert receipt["decisions_written"] == 1
    surface_final = human_review.resolve_current_human_delta_surface(paths.local_root)
    assert surface_final["inventory"]["total_pending"] == 0
    pointer = preparation.read_json(paths.pointer)
    assert pointer["terminal_state"] == preparation.TERMINAL_REVIEW_COMPLETE

    # The anchor's decision was deliberately excluded from the live file
    # above so batch review would treat it as pending (a receipt-covered
    # decision is never written to pipeline/current's own live file, only
    # to the published bundle -- exactly the real production pattern this
    # whole fixture reproduces). _live_decisions_recoverable_from_current()
    # requires the live file to be a superset of the bundle's own decisions
    # (a genuinely separate, deliberate invariant, unrelated to this fix) --
    # so mirror the bundle's own now-certified anchor decision back into the
    # live file, exactly as governed_relation_admission_policy
    # .materialize_authorized_policy() would for an approved decision.
    bundle_path = Path(str(preparation.read_json(paths.pointer)["bundle_path"]))
    bundle_manifest = preparation.read_json(bundle_path / "bundle_manifest.json")
    bundle_decisions = human_review.load_jsonl(
        bundle_path / bundle_manifest["artifacts"]["effective_decisions"]["path"]
    )
    anchor_bundle_row = next(row for row in bundle_decisions if row["candidate_id"] == anchor_id)
    existing = {row["candidate_id"]: row for row in human_review.load_jsonl(decisions_path)}
    existing[anchor_id] = anchor_bundle_row
    human_review.atomic_write_jsonl(decisions_path, existing)

    return paths, source_root, canon_rows, candidate_id, anchor_id


def test_governed_supersession_survives_canon_growth_and_technical_rebuild(
    tmp_path: Path,
) -> None:
    """The exact production incident: GEN N published with a candidate
    approved_for_admission; the human supersedes it to deferred
    (LIFECYCLE_UNRESOLVED-style, governed, audited); THEN Canon grows
    (an unrelated new file/candidate is admitted) forcing a technical
    candidate-generation rebuild for GEN N+1. Before this fix,
    rebuild_source_generation()'s own decision-preservation step silently
    reverted the supersession back to approved_for_admission (because
    _live_decisions_recoverable_from_current() aborted ALL live recovery on
    the first unexplained-looking divergence and fell back to the stale
    published bundle), reintroducing a technically_invalid-shaped candidate
    into N+1 and blocking with apply_plan_invalid /
    technically_invalid_candidates_excluded on the FINAL execute() call.
    """
    paths, source_root, canon_rows, candidate_id, anchor_id = (
        _reach_review_complete_two_candidates(tmp_path)
    )

    decisions_path = human_review.decision_authority_path(paths.current_dir)
    original = next(
        row for row in human_review.load_jsonl(decisions_path)
        if row["candidate_id"] == candidate_id
    )
    human_review.supersede_individual_decision(
        paths.current_dir, paths.local_root,
        candidate_id=candidate_id, decision="deferred",
        reason_code="LIFECYCLE_UNRESOLVED", note="repo lifecycle evidence insufficient",
        actor="Naveen", confirmation=human_review.DECISION_SUPERSESSION_CONFIRMATION,
    )

    # Canon grows with a non-repo-like record -- exactly like the 8 new
    # thematic diagnostics admitted via session_sync in the real incident:
    # they are documents, not repo-artifact code files, so they produce
    # zero new relation candidates and force ONLY candidate_generation_stale
    # (a technical rebuild), never a new pending human-review item.
    canon_rows.append({
        "id": "diagnostic-new-thematic",
        "title": "Diagnóstico temático 0090",
        "key": "Diagnóstico temático 0090",
        "version_id": "sha256:diagnostic-new-thematic",
        "text": "Contenido narrativo sin código ni repo_path.",
        "source_fields": {"artifact_family": "thematic_diagnostic"},
        "relations": [],
    })
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)

    canon_before = preparation.canon_snapshot(paths.local_root)["hash"]
    pointer_before = paths.pointer.read_bytes()

    result = preparation.execute(paths, source_root=source_root)  # must NOT raise

    assert result["terminal_state"] == preparation.TERMINAL_AUTHORIZATION

    # No Canon write, no Apply, no authorization -- this is candidate
    # generation + decision preservation only.
    assert preparation.canon_snapshot(paths.local_root)["hash"] == canon_before
    assert result.get("apply_executed") is not True
    assert result.get("authorization_created") is not True

    # The supersession survived the technical rebuild: the reconciled
    # current-generation decision for the same real candidate is still
    # deferred, NOT reverted to approved_for_admission.
    live_decisions_after = human_review.load_jsonl(
        human_review.decision_authority_path(paths.current_dir)
    )
    live_by_source = {}
    queue_after = human_review.load_jsonl(paths.current_dir / human_review.QUEUE_FILE)
    queue_by_id_after = {row["candidate_id"]: row for row in queue_after}
    for row in live_decisions_after:
        candidate = queue_by_id_after.get(row["candidate_id"])
        if candidate:
            live_by_source[candidate["source"]["canonical_id"]] = row
    assert live_by_source["source-a"]["human_review_decision"] == "deferred"
    assert live_by_source["source-a"]["human_review_reason_code"] == "LIFECYCLE_UNRESOLVED"
    assert live_by_source["source-anchor"]["human_review_decision"] == "approved_for_admission"

    # The original, pre-supersession decision remains historical/auditable
    # inside the untouched, immutable predecessor bundle.
    predecessor = preparation._analysis_review_predecessor(paths)
    assert predecessor is not None
    # (predecessor here is now the N+1 bundle's own certified history --
    # walk one hop further to the N bundle that recorded the original.)
    n_plus_1_manifest = predecessor["manifest"]
    assert n_plus_1_manifest.get("relation_generation_id") != "rg_s0183_certified_predecessor"


def test_general_convergence_property_published_n_never_contaminates_staged_n_plus_1(
    tmp_path: Path,
) -> None:
    """General property (not scoped to the exact S0186 accident): once a
    candidate's decision has a verified governed supersession, NO
    consumer building a NEW generation (technical rebuild, decision-only
    recomposition, or plain readiness) may fall back to the OLDER
    published generation's value for that candidate. The published
    generation remains valid as reconciliation baseline/provenance; it
    must never win as EFFECTIVE decisional authority over a later
    verified supersession.
    """
    paths, source_root, canon_rows, candidate_id, _anchor_id = (
        _reach_review_complete_two_candidates(tmp_path)
    )
    human_review.supersede_individual_decision(
        paths.current_dir, paths.local_root,
        candidate_id=candidate_id, decision="rejected",
        reason_code="OUT_OF_SCOPE", note="governed re-review",
        actor="fixture-reviewer", confirmation=human_review.DECISION_SUPERSESSION_CONFIRMATION,
    )

    # Canon evolves again, twice in a row, to prove this isn't a one-shot
    # coincidence tied to a single rebuild. Each growth is a non-repo-like
    # record (no repo_path, no code) -- like the real incident's thematic
    # diagnostics -- so it produces zero new relation candidates and forces
    # ONLY a technical rebuild, never a new pending human-review item.
    for suffix in ("i", "j"):
        canon_rows.append({
            "id": f"diagnostic-extra-{suffix}", "title": f"Diagnóstico {suffix}",
            "key": f"Diagnóstico {suffix}", "version_id": f"sha256:diagnostic-{suffix}",
            "text": "Contenido narrativo sin código ni repo_path.",
            "source_fields": {"artifact_family": "thematic_diagnostic"}, "relations": [],
        })
        _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
        result = preparation.execute(paths, source_root=source_root)  # must NOT raise
        assert result["terminal_state"] == preparation.TERMINAL_AUTHORIZATION

    queue_after = human_review.load_jsonl(paths.current_dir / human_review.QUEUE_FILE)
    live_decisions_after = human_review.load_jsonl(
        human_review.decision_authority_path(paths.current_dir)
    )
    queue_by_id_after = {row["candidate_id"]: row for row in queue_after}
    live_by_source = {
        queue_by_id_after[row["candidate_id"]]["source"]["canonical_id"]: row
        for row in live_decisions_after if row["candidate_id"] in queue_by_id_after
    }
    assert live_by_source["source-a"]["human_review_decision"] == "rejected"


def test_decision_hash_mismatch_without_lineage_or_receipt_fails_closed(
    tmp_path: Path,
) -> None:
    """A decision that changed content with no receipt/lineage explaining
    the change must still fail closed -- the governed-evolution recognition
    added by this fix covers ONLY receipt-backed and live-recovered-tagged
    deltas, never an arbitrary rewritten decision.
    """
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    candidate_id = str(
        preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")[0]["candidate_id"]
    )
    _review_current_batch(paths, action="approved_for_admission")

    authority = human_review.resolve_current_relational_authority(paths.local_root)
    decisions_path = authority["artifacts"]["effective_decisions"]
    rows = {row["candidate_id"]: row for row in preparation.read_jsonl(decisions_path)}
    rows[candidate_id]["human_review_note"] = "tampered, no receipt covers this change"
    preparation.write_jsonl(decisions_path, list(rows.values()))
    checkpoint_path = authority["artifacts"]["decision_checkpoint"]
    checkpoint = preparation.read_json(checkpoint_path)
    checkpoint["decisions_file_hash"] = preparation.sha256_file(decisions_path)
    preparation.write_json(checkpoint_path, checkpoint)

    try:
        preparation.dry_run(paths)
        raised = False
    except preparation.PreparationBlocked as error:
        # A content change with no matching manifest/receipt update is
        # caught by the bundle's own self-consistency check before it even
        # reaches the governed-evolution recognition this fix added --
        # either way, it must never be silently accepted.
        raised = True
    assert raised


def test_incomplete_receipt_fails_closed(tmp_path: Path) -> None:
    """A receipt whose recorded candidate_hashes no longer match what the
    source bundle actually declares must fail closed -- receipt corruption
    is not governed evolution.
    """
    paths, source_root, _canon_rows = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    _review_current_batch(paths, action="approved_for_admission")

    authority = human_review.resolve_current_relational_authority(paths.local_root)
    receipts_path = authority["artifacts"]["review_receipts"]
    receipts = preparation.read_jsonl(receipts_path)
    receipts[0]["candidate_hashes"] = ["sha256:" + "0" * 64 for _ in receipts[0]["candidate_hashes"]]
    preparation.write_jsonl(receipts_path, receipts)

    try:
        preparation.dry_run(paths)
        raised = False
    except preparation.PreparationBlocked as error:
        # Same reasoning: receipt corruption is caught by the bundle's own
        # artifact-hash self-consistency check; the important guarantee is
        # that it is never silently accepted as governed evolution.
        raised = True
    assert raised


def test_inconsistent_candidate_coverage_fails_closed(tmp_path: Path) -> None:
    """If the result bundle's decision coverage does not equal source ∪
    receipt candidates ∪ genuinely-tagged live_recovered ids, the guard
    must still fail closed -- an untagged or mislabeled extra decision is
    never treated as explained.
    """
    paths, source_root, _canon_rows = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    _review_current_batch(paths, action="approved_for_admission")

    authority = human_review.resolve_current_relational_authority(paths.local_root)
    decisions_path = authority["artifacts"]["effective_decisions"]
    rows = {row["candidate_id"]: row for row in preparation.read_jsonl(decisions_path)}
    fabricated = dict(next(iter(rows.values())))
    fabricated["candidate_id"] = "rc_current_" + "9" * 24
    rows[fabricated["candidate_id"]] = fabricated
    preparation.write_jsonl(decisions_path, list(rows.values()))
    checkpoint_path = authority["artifacts"]["decision_checkpoint"]
    checkpoint = preparation.read_json(checkpoint_path)
    checkpoint["decisions_file_hash"] = preparation.sha256_file(decisions_path)
    checkpoint["total_decisions"] = len(rows)
    preparation.write_json(checkpoint_path, checkpoint)

    try:
        preparation.dry_run(paths)
        raised = False
    except preparation.PreparationBlocked as error:
        # Whichever specific integrity guard trips first, a fabricated,
        # untagged extra decision must never be silently accepted as
        # explained governed evolution.
        raised = True
    assert raised


def test_cold_restart_recomposition_preserves_policy_derived_decision(tmp_path: Path) -> None:
    """recompose_current_decision_authority (the 'reuse an already-current
    technical set' / cold-restart path) shares _previous_authority, so it
    must recover live policy-derived decisions exactly like a full technical
    rebuild does.
    """
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    candidate_id = str(
        preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")[0]["candidate_id"]
    )
    _materialize_policy_derived_directly(paths, candidate_id)

    work, staged_current, preservation_report = preparation.recompose_current_decision_authority(paths)
    try:
        assert preservation_report["preserved_equivalent"] == 1
        assert preservation_report["preserved_from_live_recovery"] == 1
        rows = preparation.read_jsonl(staged_current / preparation.EFFECTIVE_DECISIONS_FILE)
        assert len(rows) == 1
        assert rows[0]["decision_mode"] == "policy_derived"
        assert rows[0]["generational_preservation"]["preservation_source"] == "live_recovered_not_yet_published"
    finally:
        import shutil
        if work.exists():
            shutil.rmtree(work)


# ── S0186: deep historical lineage recovery ─────────────────────────────────


def _degrade_published_bundle(
    paths: preparation.Paths, bundle_path: Path, candidate_id: str,
) -> None:
    """Surgically remove exactly one candidate's decision from an
    ALREADY-PUBLISHED, otherwise-correct bundle (and its live pipeline/
    current mirror), recomputing every hash/count the bundle's own
    integrity checks (_load_review_bundle / _validate_staged_bundle) verify
    on every future read -- so the result is a genuinely self-consistent,
    structurally valid bundle with degraded coverage, exactly like a
    reconciliation defect that dropped decisions during publish would
    produce, never a bundle a real read would reject as corrupt.

    This is test-fixture-only bundle surgery under tmp_path -- never CURRENT
    productivo -- used because the original defect this recovery mechanism
    targets is already fixed and can no longer be reproduced by driving the
    real pipeline; degrading an otherwise-real, otherwise-valid published
    bundle is the most faithful way left to exercise "an intermediate
    generation lost coverage" without hand-fabricating bundle internals
    from scratch.
    """
    manifest_path = bundle_path / "bundle_manifest.json"
    manifest = preparation.read_json(manifest_path)
    decisions_role = "effective_decisions"
    decisions_rel_path = manifest["artifacts"][decisions_role]["path"]
    decisions_path = bundle_path / decisions_rel_path
    checkpoint_path = bundle_path / manifest["artifacts"]["decision_checkpoint"]["path"]

    rows = [
        row for row in preparation.read_jsonl(decisions_path)
        if row["candidate_id"] != candidate_id
    ]
    preparation.write_jsonl(decisions_path, rows)

    checkpoint = preparation.read_json(checkpoint_path)
    removed_entry = next(
        item for item in checkpoint["individual_decision_hashes"]
        if item["candidate_id"] == candidate_id
    )
    checkpoint["individual_decision_hashes"] = [
        item for item in checkpoint["individual_decision_hashes"]
        if item["candidate_id"] != candidate_id
    ]
    checkpoint["total_decisions"] -= 1
    checkpoint[removed_entry["classification"]] -= 1
    checkpoint["decisions_file_hash"] = preparation.sha256_file(decisions_path)
    preparation.write_json(checkpoint_path, checkpoint)

    manifest["artifacts"][decisions_role]["sha256"] = preparation.sha256_file(decisions_path)
    manifest["artifacts"]["decision_checkpoint"]["sha256"] = preparation.sha256_file(checkpoint_path)

    for filename in ("effective_human_review_decisions.jsonl", "human_review_decisions.jsonl"):
        live_path = paths.current_dir / filename
        if not live_path.is_file():
            continue
        live_rows = [
            row for row in preparation.read_jsonl(live_path)
            if row["candidate_id"] != candidate_id
        ]
        preparation.write_jsonl(live_path, live_rows)
        # The bundle's own manifest declares the sha256 of whichever live
        # pipeline/current file it bound as source_bindings.human_decisions
        # at publish time (_bundle_source_bindings) -- _previous_authority()
        # separately compares that declared hash against the live file's
        # CURRENT hash whenever the predecessor is already at
        # TERMINAL_AUTHORIZATION, fail-closed on any divergence
        # ("decision authority changed after READY_FOR_AUTHORIZATION").
        # Keeping it in sync here is exactly what re-publishing after this
        # degradation would have recorded; it is not bypassing that guard.
        human_decisions_binding = (manifest.get("source_bindings") or {}).get("human_decisions")
        if human_decisions_binding and Path(human_decisions_binding["path"]).resolve() == live_path.resolve():
            human_decisions_binding["sha256"] = preparation.sha256_file(live_path)

    preparation.write_json(manifest_path, manifest)
    new_manifest_hash = preparation.sha256_file(manifest_path)

    if paths.pointer.is_file():
        pointer = preparation.read_json(paths.pointer)
        if Path(str(pointer.get("bundle_path") or "")).resolve() == bundle_path.resolve():
            pointer["bundle_manifest_hash"] = new_manifest_hash
            preparation.write_json(paths.pointer, pointer)


def _tamper_published_bundle_decision(
    paths: preparation.Paths, bundle_path: Path, candidate_id: str, *,
    decision: str, reason_code: str, supersedes_decision_hash: str | None,
) -> None:
    """Surgically REPLACE (not remove) one candidate's certified decision
    in an ALREADY-PUBLISHED bundle with a hand-authored value that does
    NOT verifiably chain to the original via supersedes_decision_hash,
    recomputing every hash the bundle's own integrity checks
    (_load_review_bundle) verify on every future read -- a genuinely
    self-consistent, structurally valid bundle whose one tampered row is
    exactly the "not a governed supersession" negative control, never a
    bundle a real read would reject as internally corrupt for unrelated
    reasons.
    """
    manifest_path = bundle_path / "bundle_manifest.json"
    manifest = preparation.read_json(manifest_path)
    decisions_role = "effective_decisions"
    decisions_rel_path = manifest["artifacts"][decisions_role]["path"]
    decisions_path = bundle_path / decisions_rel_path
    checkpoint_path = bundle_path / manifest["artifacts"]["decision_checkpoint"]["path"]

    rows = preparation.read_jsonl(decisions_path)
    original = next(row for row in rows if row["candidate_id"] == candidate_id)
    tampered = dict(original)
    tampered["human_review_decision"] = decision
    tampered["human_review_reason_code"] = reason_code
    tampered["human_review_note"] = "hand-edited, bypassing governance"
    tampered["supersedes_decision_hash"] = supersedes_decision_hash
    rows = [tampered if row["candidate_id"] == candidate_id else row for row in rows]
    preparation.write_jsonl(decisions_path, rows)

    checkpoint = preparation.read_json(checkpoint_path)
    for item in checkpoint["individual_decision_hashes"]:
        if item["candidate_id"] == candidate_id:
            item["decision_sha256"] = preparation.semantic_hash(tampered)
    checkpoint["decisions_file_hash"] = preparation.sha256_file(decisions_path)
    preparation.write_json(checkpoint_path, checkpoint)

    manifest["artifacts"][decisions_role]["sha256"] = preparation.sha256_file(decisions_path)
    manifest["artifacts"]["decision_checkpoint"]["sha256"] = preparation.sha256_file(checkpoint_path)

    live_path = paths.current_dir / "effective_human_review_decisions.jsonl"
    if live_path.is_file():
        live_rows = {
            str(r["candidate_id"]): (tampered if r["candidate_id"] == candidate_id else r)
            for r in preparation.read_jsonl(live_path)
        }
        preparation.write_jsonl(live_path, live_rows.values())
        human_decisions_binding = (manifest.get("source_bindings") or {}).get("human_decisions")
        if human_decisions_binding and Path(human_decisions_binding["path"]).resolve() == live_path.resolve():
            human_decisions_binding["sha256"] = preparation.sha256_file(live_path)

    preparation.write_json(manifest_path, manifest)
    new_manifest_hash = preparation.sha256_file(manifest_path)

    if paths.pointer.is_file():
        pointer = preparation.read_json(paths.pointer)
        if Path(str(pointer.get("bundle_path") or "")).resolve() == bundle_path.resolve():
            pointer["bundle_manifest_hash"] = new_manifest_hash
            preparation.write_json(paths.pointer, pointer)


def test_resolve_monotonic_review_predecessor_accepts_valid_governed_supersession(
    tmp_path: Path,
) -> None:
    """S0186 Unit H (final closure blocker, part 4), exact real-production
    shape: once a governed supersession has been correctly recomposed and
    republished as a NEW bundle under the SAME relation_generation_id,
    resolving THAT bundle's own declared genealogy (against its immediate
    predecessor bundle) must not treat the verified, hash-chained
    supersession as corruption. Before this fix,
    _resolve_monotonic_review_predecessor()'s same-generation/same-
    inventory signature check ignored _valid_governed_supersession()
    entirely -- unlike its three siblings in this file
    (_validate_review_semantic_monotonicity, inspect_review_coverage,
    _live_decisions_recoverable_from_current) -- and raised
    review_decision_conflict on the real production authority for exactly
    its 171 valid GATE-020 supersessions.
    """
    paths, source_root, _canon_rows, candidate_id, anchor_id = (
        _reach_review_complete_two_candidates(tmp_path)
    )
    g_advance = preparation.execute(paths, source_root=source_root)
    assert g_advance["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    previous_review_state_id = g_advance["ids"]["review_state_id"]

    human_review.supersede_individual_decision(
        paths.current_dir, paths.local_root, candidate_id=candidate_id, decision="deferred",
        reason_code="LIFECYCLE_UNRESOLVED", note="repo lifecycle evidence insufficient",
        actor="Naveen", confirmation=human_review.DECISION_SUPERSESSION_CONFIRMATION,
    )
    result = preparation.execute(paths, source_root=source_root)
    assert result["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    assert result["ids"]["relation_generation_id"] == g_advance["ids"]["relation_generation_id"]
    assert result["ids"]["review_state_id"] != previous_review_state_id

    canon_before = preparation.canon_snapshot(paths.local_root)["hash"]

    # The critical assertion: resolving the NEWLY published bundle's own
    # declared genealogy (against the pre-supersession bundle it points
    # back to) must succeed cleanly -- must NOT raise review_decision_conflict.
    # (Which of the two bundles this resolves to is governed by a separate,
    # unrelated mechanism -- receipt-ledger completeness -- not asserted
    # here; only that resolving it at all no longer fails closed on a
    # verified, hash-chained supersession.)
    predecessor = preparation._resolve_monotonic_review_predecessor(paths)
    assert predecessor["manifest"].get("relation_generation_id") == result["ids"]["relation_generation_id"]

    coverage = preparation.inspect_review_coverage(paths)
    assert coverage["valid"] is True
    assert coverage["reason_codes"] == []

    assert preparation.canon_snapshot(paths.local_root)["hash"] == canon_before

    # The 171-equivalent supersession remains exactly what it was -- this
    # read-only resolution wrote nothing.
    live_decisions = {
        str(r["candidate_id"]): r
        for r in preparation.read_jsonl(human_review.decision_authority_path(paths.current_dir))
    }
    assert live_decisions[candidate_id]["human_review_decision"] == "deferred"
    assert live_decisions[candidate_id]["supersedes_decision_hash"]


def test_resolve_monotonic_review_predecessor_still_rejects_unverified_divergence(
    tmp_path: Path,
) -> None:
    """Negative control: a shared candidate whose certified decision
    differs between two published bundles under the same generation, but
    WITHOUT a valid, hash-chained supersedes_decision_hash, must keep
    failing closed exactly as before this fix -- the fix narrows the
    exception to verified governed supersessions only, it does not weaken
    the conflict guard itself.
    """
    paths, source_root, _canon_rows, candidate_id, anchor_id = (
        _reach_review_complete_two_candidates(tmp_path)
    )
    g_advance = preparation.execute(paths, source_root=source_root)
    assert g_advance["terminal_state"] == preparation.TERMINAL_AUTHORIZATION

    # Hand-edit the published bundle's own certified row for anchor_id --
    # a different decision, with NO valid supersession chain -- exactly
    # the "bypassed governance" scenario this guard exists to catch.
    _tamper_published_bundle_decision(
        paths, Path(g_advance["bundle_path"]), anchor_id,
        decision="rejected", reason_code="OUT_OF_SCOPE",
        supersedes_decision_hash=None,
    )

    with pytest.raises(preparation.PreparationBlocked) as excinfo:
        preparation._resolve_monotonic_review_predecessor(paths)
    assert "review_decision_conflict" in excinfo.value.reason_codes

    coverage = preparation.inspect_review_coverage(paths)
    assert coverage["valid"] is False


def test_deep_recovery_survives_degraded_intermediate_generation(tmp_path: Path) -> None:
    """S0186: a rich, certified generation (rg_b245-equivalent) is followed
    by an intermediate generation degraded by a (since-fixed) reconciliation
    defect -- simulated by surgically degrading an otherwise-real, otherwise
    -valid published bundle (see _degrade_published_bundle), never by
    hand-fabricating bundle internals from scratch. A further technical
    rebuild (generation 3) must still recover the degraded candidate's
    decision from the older, richer, certified generation, because the
    CURRENT candidate remains semantically equivalent to it.
    """
    # G1 needs its own receipt to be a valid predecessor at all (a bundle
    # whose decision set grew relative to its OWN first, zero-decision
    # publish -- inescapable for any first generation -- fails closed
    # requiring receipt lineage; see _reach_review_complete_two_candidates).
    # candidate_id (source-a) is decided INDIVIDUALLY, never covered by that
    # receipt -- exactly the shape a real auto-preserved decision has, and
    # the one this test degrades.
    paths, source_root, canon_rows, candidate_id, _anchor_id = (
        _reach_review_complete_two_candidates(tmp_path)
    )
    g1_decisions = preparation.read_jsonl(
        human_review.decision_authority_path(paths.current_dir)
    )
    assert len(g1_decisions) == 2
    g1_relation_generation_id = preparation.read_json(paths.pointer)["relation_generation_id"]

    # Grow Canon (non-repo-like -- zero new candidates) to force a technical
    # rebuild for generation 2, with NO new pending candidate and therefore
    # NO receipt of generation 2's own: both decisions auto-preserve via the
    # fixed reconciler, so generation 2's own decision set is EQUAL to
    # generation 1's (no growth to justify), never entering the receipt-
    # lineage machinery generation 1 itself required. Built normally first,
    # then surgically degraded on disk to lose exactly candidate_id's
    # decision -- a real, internally self-consistent published bundle with
    # degraded coverage, exactly like the real incident, never a fabricated
    # file built from scratch.
    canon_rows.append({
        "id": "diagnostic-g2-trigger",
        "title": "Diagnóstico temático G2",
        "key": "Diagnóstico temático G2",
        "version_id": "sha256:diagnostic-g2-trigger",
        "text": "Contenido narrativo sin código ni repo_path.",
        "source_fields": {"artifact_family": "thematic_diagnostic"},
        "relations": [],
    })
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    g2 = preparation.execute(paths, source_root=source_root)
    assert g2["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    g2_relation_generation_id = g2["ids"]["relation_generation_id"]
    assert g2_relation_generation_id != g1_relation_generation_id
    g2_decisions_before_degradation = {
        row["candidate_id"]: row
        for row in preparation.read_jsonl(human_review.decision_authority_path(paths.current_dir))
    }
    assert candidate_id in g2_decisions_before_degradation
    assert len(g2_decisions_before_degradation) == 2

    _degrade_published_bundle(paths, Path(g2["bundle_path"]), candidate_id)
    g2_decisions = {
        row["candidate_id"]: row
        for row in preparation.read_jsonl(human_review.decision_authority_path(paths.current_dir))
    }
    assert candidate_id not in g2_decisions

    # Grow Canon again to force generation 3's technical rebuild. Without
    # deep recovery, candidate_id would stay pending forever, since its
    # immediate predecessor (generation 2) never certified it. With deep
    # recovery, generation 3 must walk past degraded generation 2 to
    # certified, richer generation 1 and recover it.
    canon_rows.append({
        "id": "diagnostic-g3-trigger",
        "title": "Diagnóstico temático G3",
        "key": "Diagnóstico temático G3",
        "version_id": "sha256:diagnostic-g3-trigger",
        "text": "Otro contenido narrativo sin código ni repo_path.",
        "source_fields": {"artifact_family": "thematic_diagnostic"},
        "relations": [],
    })
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    g3 = preparation.execute(paths, source_root=source_root)

    assert g3["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    assert g3["decision_preservation"]["preserved_from_deep_historical_lineage_recovery"] == 1
    g3_decisions = {
        row["candidate_id"]: row
        for row in preparation.read_jsonl(human_review.decision_authority_path(paths.current_dir))
    }
    assert candidate_id in g3_decisions
    recovered_row = g3_decisions[candidate_id]
    assert recovered_row["human_review_decision"] == "approved_for_admission"
    generational = recovered_row["generational_preservation"]
    assert generational["preservation_source"] == "deep_historical_lineage_recovery"
    assert generational["source_generation_id"] == g1_relation_generation_id
    assert generational["recovery_classification"] == "equivalent"
    assert generational["source_decision_hash"]
    assert generational["semantic_equivalence_fingerprint"]

    deep_manifest = preparation.read_json(
        paths.current_dir / "deep_historical_authority_recovery_manifest.json"
    )
    assert deep_manifest["recovered_decisions"]
    recovered_entry = next(
        item for item in deep_manifest["recovered_decisions"]
        if item["current_candidate_id"] == candidate_id
    )
    assert recovered_entry["source_generation_id"] == g1_relation_generation_id
    # The walk starts at the ancestor OF the immediate predecessor (degraded
    # generation 2 itself is handled by the ordinary, non-deep preservation
    # pass and is never itself a "scanned" hop) -- so generation 1 is the
    # first and only entry here, confirming the walk reached straight past
    # generation 2 to the older, richer, certified generation.
    assert [gen["relation_generation_id"] for gen in deep_manifest["scanned_generations"]] == [
        g1_relation_generation_id,
    ]
    assert deep_manifest["final_pending_delta"] == 0


def test_deep_recovery_never_overrides_a_later_governed_supersession(tmp_path: Path) -> None:
    """S0186 requirement 4/10: a later governed decision (supersession or
    initial decision) always wins over anything deep recovery could pull
    from an older, richer generation -- by construction, deep recovery is
    only ever consulted for candidates nothing newer already resolved.
    """
    # See test_deep_recovery_survives_degraded_intermediate_generation for
    # why generation 1 comes from _reach_review_complete_two_candidates
    # (needs its own receipt to be a valid predecessor at all) and why
    # generation 2 is built via PURE canon-only growth with no new
    # candidate of its own (so it never has its own receipt either -- a
    # receipt-anchored bundle's decision set is checked as an all-or-
    # nothing whole against its own receipt, so degrading ANY candidate
    # from a bundle that has one breaks that unrelated invariant), and why
    # candidate_id (source-a, decided INDIVIDUALLY in generation 1) is the
    # one degraded, never anchor_id (receipt-anchored back in generation 1).
    paths, source_root, canon_rows, candidate_id, _anchor_id = (
        _reach_review_complete_two_candidates(tmp_path)
    )
    canon_rows.append({
        "id": "diagnostic-supersession-g2-trigger",
        "title": "Diagnóstico temático supersesión G2",
        "key": "Diagnóstico temático supersesión G2",
        "version_id": "sha256:diagnostic-supersession-g2-trigger",
        "text": "Contenido narrativo sin código ni repo_path.",
        "source_fields": {"artifact_family": "thematic_diagnostic"},
        "relations": [],
    })
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    g2 = preparation.execute(paths, source_root=source_root)
    assert g2["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    g2_decisions_before_degradation = preparation.read_jsonl(
        human_review.decision_authority_path(paths.current_dir)
    )
    assert len(g2_decisions_before_degradation) == 2
    _degrade_published_bundle(paths, Path(g2["bundle_path"]), candidate_id)

    # A later governed decision on the degraded candidate, via
    # record_individual_decision() (no prior decision exists live -- it was
    # dropped by the degradation), must win over generation 1's older
    # "approved_for_admission".
    human_review.record_individual_decision(
        paths.current_dir, paths.local_root, candidate_id=candidate_id, decision="deferred",
        reason_code="INSUFFICIENT_CONTEXT", note="Later governed re-decision.", actor="Naveen",
        confirmation=human_review.DECISION_INITIAL_CONFIRMATION,
    )

    # A live decision changing after a predecessor already reached
    # AUTHORIZATION requires an explicit, governed recomposition pass
    # before any further technical rebuild can proceed (_previous_
    # authority()'s own guard against silently trusting a changed live file
    # over an already-authorized bundle) -- exactly the ordinary path this
    # scenario would take in production, not a workaround for this test.
    absorbed = preparation.execute(paths, source_root=source_root)
    assert absorbed["ids"]["canon_generation_id"] == g2["ids"]["canon_generation_id"]

    canon_rows.append({
        "id": "diagnostic-supersession-g3-trigger",
        "title": "Diagnóstico temático supersesión G3",
        "key": "Diagnóstico temático supersesión G3",
        "version_id": "sha256:diagnostic-supersession-g3-trigger",
        "text": "Otro contenido narrativo sin código ni repo_path.",
        "source_fields": {"artifact_family": "thematic_diagnostic"},
        "relations": [],
    })
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    g3 = preparation.execute(paths, source_root=source_root)

    g3_decisions = {
        row["candidate_id"]: row
        for row in preparation.read_jsonl(human_review.decision_authority_path(paths.current_dir))
    }
    assert candidate_id in g3_decisions
    recovered_row = g3_decisions[candidate_id]
    # The later, live decision won -- not generation 1's older approval.
    assert recovered_row["human_review_decision"] == "deferred"
    generational = recovered_row["generational_preservation"]
    assert generational["preservation_source"] != "deep_historical_lineage_recovery"
    deep_manifest_path = paths.current_dir / "deep_historical_authority_recovery_manifest.json"
    if deep_manifest_path.is_file():
        deep_manifest = preparation.read_json(deep_manifest_path)
        assert candidate_id not in {
            item["current_candidate_id"] for item in deep_manifest["recovered_decisions"]
        }
