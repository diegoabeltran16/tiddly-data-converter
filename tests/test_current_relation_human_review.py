"""S0181 structured current-review, batch, and supersession guarantees."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import current_relation_human_review as review  # noqa: E402


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def _candidate(candidate_id: str = "rc_current_aabb1122334455667788") -> dict:
    return {
        "candidate_id": candidate_id,
        "candidate_schema_version": "technical-relation-candidates/v1",
        "relation_type": "depende_de",
        "source": {
            "canonical_id": "src", "canonical_title": "Source",
            "repo_path": "src/example.py", "artifact_family": "python_source",
            "repo_lifecycle_state": "current_repo_artifact",
        },
        "target": {
            "canonical_id": "tgt", "canonical_title": "Target",
            "repo_path": "src/target.py", "artifact_family": "python_source",
            "repo_lifecycle_state": "current_repo_artifact",
        },
        "evidence": {
            "file": "src/example.py", "line": 1, "raw_observation": "import target",
            "evidence_kind": "technical", "technical_evidence_kind": "ast_import",
            "parser": "python_ast", "confidence": "high",
        },
    }


def _fixture(tmp_path: Path, candidates: list[dict] | None = None) -> tuple[Path, Path, list[dict]]:
    current, canon = tmp_path / "current", tmp_path / "canon"
    canon.mkdir()
    (canon / "tiddlers_1.jsonl").write_text('{"id":"src"}\n', encoding="utf-8")
    candidates = candidates or [_candidate()]
    current.mkdir()
    (current / review.QUEUE_FILE).write_text(
        "".join(json.dumps(candidate) + "\n" for candidate in candidates), encoding="utf-8",
    )
    _write(current / "current_candidate_manifest.json", {"current": True})
    _write(current / "reconciliation_manifest.json", {"current": True})
    return current, canon, candidates


def _decision(current: Path, canon: Path, candidate: dict, **overrides: object) -> dict:
    values = {
        "decision": "approved_for_admission",
        "reason_code": "DIRECT_CODE_DEPENDENCY_CONFIRMED",
        "actor": "operator",
        "bindings": review.current_bindings(current, canon),
    }
    values.update(overrides)
    return review.build_decision_record(candidate, **values)


def _gate(candidates: list[dict], *, gate_022: set[str] | None = None) -> dict:
    gate_022 = gate_022 or set()
    return {
        "items": [
            {
                "candidate_id": candidate["candidate_id"],
                "decision": "blocked_technical" if candidate["candidate_id"] in gate_022 else "admission_ready_dry_run",
                "all_block_reasons": (
                    ["GATE-022: target.repo_path no existe"]
                    if candidate["candidate_id"] in gate_022 else []
                ),
            }
            for candidate in candidates
        ]
    }


def test_v2_record_is_structured_and_bound(tmp_path: Path) -> None:
    current, canon, (candidate,) = _fixture(tmp_path)
    record = _decision(current, canon, candidate)
    assert record["schema_version"] == "relation-human-review-decision/v2"
    assert record["human_review_reason_code"] == "DIRECT_CODE_DEPENDENCY_CONFIRMED"
    assert record["human_review_note"] is None
    assert record["approval_scope"] == "canonical_admission"
    assert record["candidate_manifest_hash"] == hashlib.sha256(
        (current / "current_candidate_manifest.json").read_bytes()
    ).hexdigest()


def test_migrate_equivalent_decisions_preserves_authority_and_rebinds(tmp_path: Path) -> None:
    old_candidate = _candidate("rc_current_" + "1" * 24)
    current_candidate = json.loads(json.dumps(old_candidate))
    current_candidate["candidate_id"] = "rc_current_" + "2" * 24
    current_candidate["evidence"]["line"] = 40
    current, canon, _ = _fixture(tmp_path, [current_candidate])
    (current / "relation_candidates.jsonl").write_text(
        json.dumps(current_candidate) + "\n", encoding="utf-8",
    )
    historical_candidates = tmp_path / "historical_candidates.jsonl"
    historical_candidates.write_text(json.dumps(old_candidate) + "\n", encoding="utf-8")
    historical_decisions = tmp_path / "historical_decisions.jsonl"
    old_decision = _decision(current, canon, old_candidate)
    historical_decisions.write_text(json.dumps(old_decision) + "\n", encoding="utf-8")
    historical_bytes = historical_decisions.read_bytes()

    audit = tmp_path / "audit"
    audit.mkdir()
    matrix = audit / "old_to_current_reconciliation.jsonl"
    matrix.write_text(json.dumps({
        "candidate_id": old_candidate["candidate_id"],
        "counterpart_candidate_id": current_candidate["candidate_id"],
        "classification": "equivalent",
        "decision_reusable": True,
    }) + "\n", encoding="utf-8")
    cross_manifest = audit / "cross_batch_reconciliation_manifest.json"
    _write(cross_manifest, {
        "schema_version": "s0183-cross-batch-reconciliation/v1",
        "historical_candidates_path": str(historical_candidates),
        "historical_candidates_hash": hashlib.sha256(historical_candidates.read_bytes()).hexdigest(),
        "current_candidates_hash": hashlib.sha256((current / "relation_candidates.jsonl").read_bytes()).hexdigest(),
        "old_to_current_path": str(matrix),
        "old_to_current_hash": hashlib.sha256(matrix.read_bytes()).hexdigest(),
    })

    report = review.migrate_equivalent_decisions(
        historical_decisions_file=historical_decisions,
        current_dir=current,
        canon_root=canon,
        cross_batch_manifest_path=cross_manifest,
        audit_dir=audit,
    )
    migrated = review.load_jsonl(current / review.DECISIONS_FILE)
    assert report["migrated_equivalent_count"] == 1
    assert report["pending_reviewable_candidate_ids"] == []
    assert migrated[0]["candidate_id"] == current_candidate["candidate_id"]
    assert migrated[0]["human_review_actor"] == old_decision["human_review_actor"]
    assert migrated[0]["human_review_timestamp"] == old_decision["human_review_timestamp"]
    assert migrated[0]["candidate_manifest_hash"] == review.current_bindings(current, canon)["candidate_manifest_hash"]
    assert historical_decisions.read_bytes() == historical_bytes


@pytest.mark.parametrize("reason", ["NA", "na", "N/A", "ok", "approved", ""])
def test_free_text_placeholders_are_not_reason_codes(tmp_path: Path, reason: str) -> None:
    current, canon, (candidate,) = _fixture(tmp_path)
    with pytest.raises(ValueError, match="human_review_reason_code"):
        _decision(current, canon, candidate, reason_code=reason)


def test_normal_reason_allows_no_note_but_exception_requires_one(tmp_path: Path) -> None:
    current, canon, (candidate,) = _fixture(tmp_path)
    assert _decision(current, canon, candidate)["human_review_note"] is None
    with pytest.raises(ValueError, match="human_review_note required"):
        _decision(current, canon, candidate, reason_code="OTHER")
    assert _decision(current, canon, candidate, reason_code="OTHER", note="Caso excepcional.")[
        "human_review_note"
    ] == "Caso excepcional."


def test_batch_mode_requires_batch_id(tmp_path: Path) -> None:
    current, canon, (candidate,) = _fixture(tmp_path)
    with pytest.raises(ValueError, match="decision_batch_id"):
        _decision(current, canon, candidate, decision_mode="batch")


def test_stale_and_duplicate_decisions_fail_closed(tmp_path: Path) -> None:
    current, canon, (candidate,) = _fixture(tmp_path)
    bindings = review.current_bindings(current, canon)
    record = _decision(current, canon, candidate)
    record["canon_hash"] = "0" * 64
    path = current / review.DECISIONS_FILE
    path.write_text(json.dumps(record) + "\n" + json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale canon_hash"):
        review.load_existing_decisions(path, {record["candidate_id"]}, bindings)


def test_legacy_is_recognized_only_when_explicitly_allowed(tmp_path: Path) -> None:
    current, canon, (candidate,) = _fixture(tmp_path)
    bindings = review.current_bindings(current, canon)
    legacy = {
        "schema_version": review.SCHEMA_HUMAN_DECISION_LINE_LEGACY,
        "candidate_id": candidate["candidate_id"], "human_review_decision": "approved_for_admission",
        "human_review_actor": "operator", "human_review_timestamp": "2026-07-20T00:00:00Z",
        "human_review_rationale": "na", "approval_scope": "canonical_admission",
        **bindings,
    }
    path = current / review.DECISIONS_FILE
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="audit/migration only"):
        review.load_existing_decisions(path, {candidate["candidate_id"]}, bindings)
    assert review.load_existing_decisions(
        path, {candidate["candidate_id"]}, bindings, allow_legacy=True,
    )[candidate["candidate_id"]] == legacy


def test_preview_is_deterministic_and_never_writes(tmp_path: Path) -> None:
    candidates = [_candidate(), _candidate("rc_current_bbbb1122334455667788")]
    current, _, candidates = _fixture(tmp_path, candidates)
    first = review.build_batch_previews(candidates, _gate(candidates))
    second = review.build_batch_previews(list(reversed(candidates)), _gate(candidates))
    assert first == second
    assert first[0]["candidate_count"] == 2
    assert first[0]["writes_performed"] is False
    assert len(first[0]["examples"]) <= 5
    assert not (current / review.DECISIONS_FILE).exists()


def test_gate_022_has_one_explicit_deferred_batch(tmp_path: Path) -> None:
    candidates = [
        _candidate(f"rc_current_{index:016x}") for index in range(17)
    ] + [_candidate("rc_current_eeee1122334455667788")]
    _, _, candidates = _fixture(tmp_path, candidates)
    stale = {candidate["candidate_id"] for candidate in candidates[:17]}
    previews = review.build_batch_previews(candidates, _gate(candidates, gate_022=stale))
    gate_batch = next(item for item in previews if item["selection_rule"].get("gate_code") == "GATE-022")
    assert gate_batch["candidate_count"] == 17
    assert gate_batch["proposed_decision"] == "deferred"
    assert gate_batch["proposed_reason_code"] == "STALE_TARGET_PATH"
    assert gate_batch["review_policy_id"] == "S0181_GATE_022_DEFERRAL_V1"


def test_wrong_confirmation_cancels_batch_without_write(tmp_path: Path) -> None:
    current, canon, candidates = _fixture(tmp_path)
    preview = review.build_batch_previews(candidates, _gate(candidates))[0]
    assert review.persist_batch_preview(
        current, canon, preview=preview, actor="operator", confirmation="CONFIRM",
    ) == 0
    assert not (current / review.DECISIONS_FILE).exists()


def test_exclusion_remains_pending_and_confirmation_persists_individual_records(tmp_path: Path) -> None:
    candidates = [_candidate(), _candidate("rc_current_bbbb1122334455667788")]
    current, canon, candidates = _fixture(tmp_path, candidates)
    excluded = candidates[1]["candidate_id"]
    preview = review.build_batch_previews(candidates, _gate(candidates), exclusions={excluded})[0]
    assert preview["exclusions"] == [excluded]
    assert preview["candidate_ids"] == [candidates[0]["candidate_id"]]
    assert review.persist_batch_preview(
        current, canon, preview=preview, actor="operator", confirmation=review.BATCH_CONFIRMATION,
    ) == 1
    rows = review.load_jsonl(current / review.DECISIONS_FILE)
    assert [row["candidate_id"] for row in rows] == [candidates[0]["candidate_id"]]
    assert rows[0]["decision_batch_id"] == preview["batch_id"]
    assert excluded not in {row["candidate_id"] for row in rows}


def test_tampered_batch_preview_is_rejected(tmp_path: Path) -> None:
    current, canon, candidates = _fixture(tmp_path)
    preview = review.build_batch_previews(candidates, _gate(candidates))[0]
    preview["candidate_set_hash"] = "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        review.persist_batch_preview(
            current, canon, preview=preview, actor="operator",
            confirmation=review.BATCH_CONFIRMATION,
        )


def _separate_batch_candidates() -> list[dict]:
    first = _candidate("rc_current_1111111111111111")
    second = _candidate("rc_current_2222222222222222")
    stale = _candidate("rc_current_3333333333333333")
    first["source"]["repo_path"] = "tests/first_test.py"
    second["source"]["repo_path"] = "tests/second_test.py"
    stale["source"]["repo_path"] = "tests/stale_test.py"
    return [first, second, stale]


def _multi_inventory(
    current: Path, canon: Path, candidates: list[dict], gate: dict,
) -> tuple[dict[str, str], dict[str, dict], list[dict]]:
    bindings = review.current_bindings(current, canon)
    decisions = review.load_existing_decisions(
        current / review.DECISIONS_FILE,
        {candidate["candidate_id"] for candidate in candidates},
        bindings,
    )
    return bindings, decisions, review.build_batch_inventory(candidates, gate, decisions)


def test_multi_selection_normalizes_spaces_and_rejects_empty_or_duplicate_ids() -> None:
    assert review.parse_multi_batch_ids(" hrb_b ,hrb_a ") == ["hrb_a", "hrb_b"]
    for invalid in ("", "  ", "hrb_a,", "hrb_a,,hrb_b", "hrb_a, hrb_a"):
        with pytest.raises(ValueError):
            review.parse_multi_batch_ids(invalid)


def test_multiple_homogeneous_batches_persist_individually_and_are_idempotent(tmp_path: Path) -> None:
    candidates = _separate_batch_candidates()[:2]
    current, canon, candidates = _fixture(tmp_path, candidates)
    gate = _gate(candidates)
    bindings = review.current_bindings(current, canon)
    inventory = review.build_batch_inventory(candidates, gate, {})
    selected = [item["batch_id"] for item in inventory]
    preview = review.build_multi_batch_preview(inventory, selected, bindings)
    result = review.persist_multi_batch_preview(
        current, canon, gate_report=gate, preview=preview, actor="operator",
        confirmation=preview["confirmation_required"], note="Revisión homogénea.",
    )
    assert result["persisted"] == 2
    rows = review.load_jsonl(current / review.DECISIONS_FILE)
    assert len(rows) == 2
    assert {row["decision_batch_id"] for row in rows} == set(selected)
    assert {row["multi_review_operation_id"] for row in rows} == {
        preview["multi_review_operation_id"]
    }
    assert len({row["human_review_timestamp"] for row in rows}) == 1
    assert all(row["decision_mode"] == "batch" for row in rows)

    repeated = review.persist_multi_batch_preview(
        current, canon, gate_report=gate, preview=preview, actor="operator",
        confirmation=preview["confirmation_required"], note="Revisión homogénea.",
    )
    assert repeated["persisted"] == 0
    assert repeated["already_reviewed"] == 2
    assert len(review.load_jsonl(current / review.DECISIONS_FILE)) == 2


def test_partial_batch_reports_resolved_and_writes_only_pending_candidate(tmp_path: Path) -> None:
    candidates = [_candidate(), _candidate("rc_current_bbbb1122334455667788")]
    current, canon, candidates = _fixture(tmp_path, candidates)
    gate = _gate(candidates)
    full = review.build_batch_previews(candidates, gate)[0]
    existing = _decision(
        current, canon, candidates[0], decision_mode="batch",
        decision_batch_id=full["batch_id"], review_policy_id=full["review_policy_id"],
    )
    review.atomic_write_jsonl(current / review.DECISIONS_FILE, {existing["candidate_id"]: existing})
    bindings, decisions, inventory = _multi_inventory(current, canon, candidates, gate)
    item = inventory[0]
    assert item["pending_candidates"] == 1
    assert item["already_reviewed_candidates"] == 1
    preview = review.build_multi_batch_preview(inventory, [item["batch_id"]], bindings)
    result = review.persist_multi_batch_preview(
        current, canon, gate_report=gate, preview=preview, actor="operator",
        confirmation=preview["confirmation_required"],
    )
    rows = {row["candidate_id"]: row for row in review.load_jsonl(current / review.DECISIONS_FILE)}
    assert result["persisted"] == 1
    assert result["already_reviewed"] == 1
    assert rows[existing["candidate_id"]] == decisions[existing["candidate_id"]]


def test_multiple_review_rejects_unknown_mixed_or_incompatible_batches(tmp_path: Path) -> None:
    candidates = _separate_batch_candidates()
    current, canon, candidates = _fixture(tmp_path, candidates)
    stale_id = candidates[-1]["candidate_id"]
    gate = _gate(candidates, gate_022={stale_id})
    bindings = review.current_bindings(current, canon)
    inventory = review.build_batch_inventory(candidates, gate, {})
    approved = [item for item in inventory if item["full_preview"]["proposed_decision"] == "approved_for_admission"]
    deferred = next(item for item in inventory if item["full_preview"]["proposed_decision"] == "deferred")
    with pytest.raises(ValueError, match="not live"):
        review.build_multi_batch_preview(inventory, ["hrb_missing"], bindings)
    with pytest.raises(ValueError, match="compatibility signature"):
        review.build_multi_batch_preview(
            inventory, [approved[0]["batch_id"], deferred["batch_id"]], bindings,
        )
    approved[1]["full_preview"]["proposed_reason_code"] = "EVIDENCE_AND_ENDPOINTS_VERIFIED"
    with pytest.raises(ValueError, match="compatibility signature"):
        review.build_multi_batch_preview(
            inventory, [approved[0]["batch_id"], approved[1]["batch_id"]], bindings,
        )
    approved[1]["full_preview"]["proposed_reason_code"] = approved[0]["full_preview"]["proposed_reason_code"]
    approved[1]["full_preview"]["review_policy_id"] = "INCOMPATIBLE_POLICY"
    with pytest.raises(ValueError, match="compatibility signature"):
        review.build_multi_batch_preview(
            inventory, [approved[0]["batch_id"], approved[1]["batch_id"]], bindings,
        )


def test_multiple_review_conflict_does_not_overwrite_existing_decision(tmp_path: Path) -> None:
    current, canon, candidates = _fixture(tmp_path)
    gate = _gate(candidates)
    full = review.build_batch_previews(candidates, gate)[0]
    conflicting = _decision(
        current, canon, candidates[0], decision="deferred", reason_code="INSUFFICIENT_CONTEXT",
    )
    review.atomic_write_jsonl(current / review.DECISIONS_FILE, {conflicting["candidate_id"]: conflicting})
    before = (current / review.DECISIONS_FILE).read_bytes()
    bindings, _, inventory = _multi_inventory(current, canon, candidates, gate)
    assert inventory[0]["status"] == "conflict"
    with pytest.raises(ValueError, match="conflict"):
        review.build_multi_batch_preview(inventory, [full["batch_id"]], bindings)
    assert (current / review.DECISIONS_FILE).read_bytes() == before


@pytest.mark.parametrize("confirmation", ["", "CONFIRM MULTIPLE REVIEW BATCHES", "wrong"])
def test_multiple_review_wrong_confirmation_writes_nothing(tmp_path: Path, confirmation: str) -> None:
    current, canon, candidates = _fixture(tmp_path)
    gate = _gate(candidates)
    bindings = review.current_bindings(current, canon)
    inventory = review.build_batch_inventory(candidates, gate, {})
    preview = review.build_multi_batch_preview(inventory, [inventory[0]["batch_id"]], bindings)
    result = review.persist_multi_batch_preview(
        current, canon, gate_report=gate, preview=preview, actor="operator",
        confirmation=confirmation,
    )
    assert result["cancelled"] is True
    assert not (current / review.DECISIONS_FILE).exists()


def test_multiple_review_atomic_replace_failure_preserves_existing_authority(tmp_path: Path) -> None:
    candidates = _separate_batch_candidates()[:2]
    current, canon, candidates = _fixture(tmp_path, candidates)
    gate = _gate(candidates)
    existing = _decision(current, canon, candidates[0])
    review.atomic_write_jsonl(current / review.DECISIONS_FILE, {existing["candidate_id"]: existing})
    before = (current / review.DECISIONS_FILE).read_bytes()
    bindings, decisions, inventory = _multi_inventory(current, canon, candidates, gate)
    pending_item = next(item for item in inventory if item["pending_candidates"])
    preview = review.build_multi_batch_preview(inventory, [pending_item["batch_id"]], bindings)
    with mock.patch.object(review.os, "replace", side_effect=OSError("replace failed")):
        with pytest.raises(OSError, match="replace failed"):
            review.persist_multi_batch_preview(
                current, canon, gate_report=gate, preview=preview, actor="operator",
                confirmation=preview["confirmation_required"],
            )
    assert (current / review.DECISIONS_FILE).read_bytes() == before
    assert review.load_jsonl(current / review.DECISIONS_FILE) == list(decisions.values())


def test_multiple_review_interruption_before_confirmation_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, canon, candidates = _fixture(tmp_path)
    gate_path = tmp_path / "gate.json"
    _write(gate_path, _gate(candidates))
    batch_id = review.build_batch_previews(candidates, _gate(candidates))[0]["batch_id"]
    answers: list[object] = [batch_id, KeyboardInterrupt()]

    def interrupted_input(_: str) -> str:
        answer = answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return str(answer)

    monkeypatch.setattr("builtins.input", interrupted_input)
    assert review.run_multiple_batch_review(current, canon, gate_path, "operator") == 0
    assert not (current / review.DECISIONS_FILE).exists()


def test_cli_apply_batch_requires_the_hash_printed_by_preview(tmp_path: Path) -> None:
    current, canon, candidates = _fixture(tmp_path)
    gate_path = tmp_path / "gate.json"
    _write(gate_path, _gate(candidates))
    preview = review.build_batch_previews(candidates, _gate(candidates))[0]
    base = [
        "--current-dir", str(current), "--canon-root", str(canon),
        "--gate-report", str(gate_path), "--apply-batch", preview["batch_id"],
        "--reviewer", "operator", "--confirmation", review.BATCH_CONFIRMATION,
    ]
    assert review.main(base) == 2
    assert not (current / review.DECISIONS_FILE).exists()
    assert review.main(base + ["--candidate-set-hash", preview["candidate_set_hash"]]) == 0
    assert len(review.load_jsonl(current / review.DECISIONS_FILE)) == 1


def _legacy_supersession_fixture(tmp_path: Path) -> tuple[Path, Path, Path, bytes, bytes]:
    local = tmp_path / "local"
    current = local / "pipeline" / "relation_candidates" / "current"
    canon = local
    candidate = _candidate()
    current.mkdir(parents=True)
    (canon / "tiddlers_1.jsonl").write_text('{"id":"src"}\n', encoding="utf-8")
    (current / review.QUEUE_FILE).write_text(json.dumps(candidate) + "\n", encoding="utf-8")
    _write(current / "current_candidate_manifest.json", {"current": True})
    _write(current / "reconciliation_manifest.json", {"current": True})
    bindings = review.current_bindings(current, canon)
    legacy = {
        "schema_version": review.SCHEMA_HUMAN_DECISION_LINE_LEGACY,
        "candidate_id": candidate["candidate_id"], "human_review_decision": "approved_for_admission",
        "human_review_actor": "operator", "human_review_timestamp": "2026-07-20T00:00:00Z",
        "human_review_rationale": "na", "approval_scope": "canonical_admission", **bindings,
    }
    decisions_bytes = (json.dumps(legacy, sort_keys=True) + "\n").encode()
    audit_bytes = b'{"legacy_event":true}\n'
    (current / review.DECISIONS_FILE).write_bytes(decisions_bytes)
    (current / review.AUDIT_FILE).write_bytes(audit_bytes)
    gate_dir = local / "audit" / "relation_admission" / "current"
    gate_path = gate_dir / "admission_gate_dry_run.json"
    _write(gate_path, {"summary": {
        "total_evaluated": 1, "approved_for_admission": 1,
        "human_rejected": 0, "human_deferred": 0,
    }})
    _write(gate_dir / "current_run_manifest.json", {
        "human_review_decisions_hash": hashlib.sha256(decisions_bytes).hexdigest(),
        "report_hash": hashlib.sha256(gate_path.read_bytes()).hexdigest(),
    })
    return current, canon, local / "audit" / "s0181", decisions_bytes, audit_bytes


def test_supersession_preserves_bytes_hash_and_resets_current_authority(tmp_path: Path) -> None:
    current, canon, audit_root, decisions_before, audit_before = _legacy_supersession_fixture(tmp_path)
    canon_before = review.canon_hash(canon)
    manifest_path = review.supersede_legacy_current(
        current, canon, audit_root, actor="operator", note="La justificación libre no es auditable.",
        confirmation=review.SUPERSESSION_CONFIRMATION, timestamp="20260721T120000Z",
    )
    history = manifest_path.parent
    manifest = review.load_json(manifest_path)
    assert (history / review.DECISIONS_FILE).read_bytes() == decisions_before
    assert (history / review.AUDIT_FILE).read_bytes() == audit_before
    assert manifest["previous_hash"] == hashlib.sha256(decisions_before).hexdigest()
    assert manifest["status"] == "superseded_not_authoritative"
    assert manifest["apply_executed"] is False
    assert manifest["canon_modified"] is False
    assert (current / review.DECISIONS_FILE).read_bytes() == b""
    assert review.canon_hash(canon) == canon_before
    assert (history / review.AUDIT_FILE).read_bytes() == audit_before


def test_supersession_requires_exact_confirmation_and_complete_evidence(tmp_path: Path) -> None:
    current, canon, audit_root, decisions_before, _ = _legacy_supersession_fixture(tmp_path)
    with pytest.raises(ValueError, match="exact confirmation"):
        review.supersede_legacy_current(
            current, canon, audit_root, actor="operator", note="Motivo.", confirmation="WRONG",
        )
    assert (current / review.DECISIONS_FILE).read_bytes() == decisions_before
    (audit_root.parent / "relation_admission" / "current" / "current_run_manifest.json").unlink()
    with pytest.raises(ValueError, match="gate report and run manifest"):
        review.supersede_legacy_current(
            current, canon, audit_root, actor="operator", note="Motivo.",
            confirmation=review.SUPERSESSION_CONFIRMATION, timestamp="20260721T130000Z",
        )
    assert not (audit_root / "human_review_superseded" / "20260721T130000Z").exists()
    assert (current / review.DECISIONS_FILE).read_bytes() == decisions_before


def test_individual_supersession_records_previous_hash_and_note(tmp_path: Path) -> None:
    current, canon, (candidate,) = _fixture(tmp_path)
    previous = _decision(current, canon, candidate)
    review.atomic_write_jsonl(current / review.DECISIONS_FILE, {candidate["candidate_id"]: previous})
    new = review.supersede_individual_decision(
        current, canon, candidate_id=candidate["candidate_id"], decision="deferred",
        reason_code="INSUFFICIENT_CONTEXT", note="Revisión manual posterior.", actor="operator-2",
        confirmation=review.DECISION_SUPERSESSION_CONFIRMATION,
    )
    assert new["supersedes_decision_hash"] == review.decision_hash(previous)
    event = review.load_jsonl(current / review.AUDIT_FILE)[0]
    assert event["action"] == "decision_superseded"
    assert event["previous_decision"] == previous


def test_quit_and_audit_failure_keep_safe_authority_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, canon, (candidate,) = _fixture(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _: "q")
    assert review.run_review(current, canon, "operator") == 0
    assert not (current / review.DECISIONS_FILE).exists()

    answers = iter(("d", "INSUFFICIENT_CONTEXT", ""))
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(review, "append_audit", mock.Mock(side_effect=OSError("audit unavailable")))
    with pytest.raises(RuntimeError, match="authoritative decision persisted"):
        review.run_review(current, canon, "operator")
    assert review.load_jsonl(current / review.DECISIONS_FILE)[0]["candidate_id"] == candidate["candidate_id"]


def test_empty_actor_is_rejected_before_queue_is_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(review, "current_bindings", lambda *_: pytest.fail("queue opened before actor validation"))
    assert review.main([
        "--current-dir", str(tmp_path), "--canon-root", str(tmp_path), "--reviewer", "  ",
    ]) == 2
