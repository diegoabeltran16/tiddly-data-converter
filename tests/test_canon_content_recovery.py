"""S0186 Unit I: governed recovery of canonical content proven from

certified historical evidence (canon_content_recovery.py).

Every test builds an isolated canon + certified-evidence tree under
tmp_path; nothing here ever touches the real repository's Canon.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import canon_content_recovery as ccr  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return path


def _record(record_id: str, *, title: str | None = None, text: str = "", content=None, **extra) -> dict:
    base = {"id": record_id, "title": title or f"Title {record_id}", "text": text, "content": content}
    base.update(extra)
    return base


def _canon(tmp_path: Path, shards: dict[str, list[dict]]) -> Path:
    canon_dir = tmp_path / "canon"
    for name, rows in shards.items():
        _write_jsonl(canon_dir / name, rows)
    return canon_dir


def _certified_root(tmp_path: Path) -> Path:
    root = tmp_path / "audit"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _certified_source(root: Path, filename: str, rows: list[dict]) -> Path:
    return _write_jsonl(root / filename, rows)


def _prepare_snapshot(plan: "ccr.RecoveryPlan", tmp_path: Path, *, name: str = "snapshot") -> Path:
    return ccr.prepare_snapshot(plan, tmp_path / name)


def _authorize(plan: "ccr.RecoveryPlan", tmp_path: Path, *, name: str = "snapshot") -> dict:
    snapshot_manifest = _prepare_snapshot(plan, tmp_path, name=name)
    return ccr.create_authorization(plan, snapshot_manifest, ccr.authorization_phrase(plan))


def _reload_plan_from_disk(plan: "ccr.RecoveryPlan", tmp_path: Path, *, name: str = "plan.json") -> "ccr.RecoveryPlan":
    """Round-trip a plan through disk exactly as the CLI/menu do: write it,

    reload the JSON, and re-derive recovered_record via the single shared
    ``materialize_recovered_record`` -- the plan file never embeds
    recovered_record itself (see ``RecoveryOperation.to_dict()``).
    """

    plan_file = tmp_path / name
    ccr.write_plan(plan, plan_file)
    plan_dict = json.loads(plan_file.read_text(encoding="utf-8"))
    canon_dir_from_plan = Path(plan_dict["canon_dir"])
    rebuilt_ops = [
        ccr.RecoveryOperation(**{**op_dict, "recovered_record": ccr.materialize_recovered_record(op_dict, canon_dir_from_plan)})
        for op_dict in plan_dict["operations"]
    ]
    return ccr.RecoveryPlan(**{**plan_dict, "operations": rebuilt_ops})


# --- 1. same-id missing record recovery -----------------------------------


def test_restore_missing_same_id_recovers_the_record(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered content")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1",
        certified_source_path=source_path,
        canon_dir=canon_dir,
        certified_root=certified,
    )
    plan = ccr.build_plan(canon_dir, [op])
    assert plan.expected_canon_after_count == 2

    report = ccr.dry_run(plan, out_dir=tmp_path / "scratch")
    assert report["overall_status"] == "pass"
    assert report["projected_canon_after"]["records"] == 2
    assert report["changed_record_ids"] == ["missing-1"]


# --- 2. same-id target already exists -> block -----------------------------


def test_restore_missing_same_id_blocks_when_target_already_exists(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("already-here")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("already-here", text="x")])

    with pytest.raises(ccr.RecoveryPlanError, match="STALE"):
        ccr.build_restore_missing_operation(
            target_record_id="already-here",
            certified_source_path=source_path,
            canon_dir=canon_dir,
            certified_root=certified,
        )


# --- 3. historical source hash drift -> block ------------------------------


def test_apply_blocks_on_source_artifact_drift(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="original")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    authorization = _authorize(plan, tmp_path)

    # Source drifts after planning, before apply.
    _write_jsonl(source_path, [_record("missing-1", text="TAMPERED")])

    with pytest.raises(ccr.RecoveryAuthorizationError, match="[Ss]ource.*drift"):
        ccr.apply(plan, authorization, out_dir=tmp_path / "scratch")


# --- 4. two divergent historical sources -> ambiguity -> block ------------


def test_restore_missing_blocks_on_divergent_certified_sources(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_a = _certified_source(certified, "backup_a.jsonl", [_record("missing-1", text="version A")])
    source_b = _certified_source(certified, "backup_b.jsonl", [_record("missing-1", text="version B")])

    with pytest.raises(ccr.RecoveryPlanError, match="divergent"):
        ccr.build_restore_missing_operation(
            target_record_id="missing-1",
            certified_source_path=source_a,
            canon_dir=canon_dir,
            certified_root=certified,
            other_certified_paths_for_divergence_check=[source_b],
        )


# --- 5. existing empty target repaired from unique predecessor -----------


def test_repair_existing_target_from_predecessor(tmp_path: Path) -> None:
    canon_dir = _canon(
        tmp_path,
        {"tiddlers_1.jsonl": [_record("target-1", title="16. Renumbered", text="", content=None)]},
    )
    certified = _certified_root(tmp_path)
    predecessor_path = _certified_source(
        certified, "backup.jsonl", [_record("predecessor-1", title="08. Original", text="the real transcript")]
    )

    op = ccr.build_repair_existing_operation(
        target_record_id="target-1",
        predecessor_record_id="predecessor-1",
        predecessor_certified_source_path=predecessor_path,
        canon_dir=canon_dir,
        certified_root=certified,
    )
    assert op.fields_recovered_from_history == ["text"]
    assert "version_id" in op.fields_recomputed
    assert "title" not in op.fields_recovered_from_history

    plan = ccr.build_plan(canon_dir, [op])
    assert plan.expected_canon_after_count == 1  # count delta = 0

    report = ccr.dry_run(plan, out_dir=tmp_path / "scratch")
    assert report["overall_status"] == "pass"
    check = report["per_operation"][0]
    assert check["present_exactly_once"]
    assert check["non_empty"]


# --- 6. non-empty target -> block ------------------------------------------


def test_repair_existing_target_blocks_when_target_not_empty(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("target-1", text="already has content")]})
    certified = _certified_root(tmp_path)
    predecessor_path = _certified_source(certified, "backup.jsonl", [_record("predecessor-1", text="history")])

    with pytest.raises(ccr.RecoveryPlanError, match="not empty"):
        ccr.build_repair_existing_operation(
            target_record_id="target-1",
            predecessor_record_id="predecessor-1",
            predecessor_certified_source_path=predecessor_path,
            canon_dir=canon_dir,
            certified_root=certified,
        )


# --- 7. ambiguous predecessor -> block -------------------------------------


def test_repair_existing_target_blocks_on_ambiguous_predecessor(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("target-1", text="")]})
    certified = _certified_root(tmp_path)
    predecessor_a = _certified_source(certified, "backup_a.jsonl", [_record("predecessor-1", text="version A")])
    predecessor_b = _certified_source(certified, "backup_b.jsonl", [_record("predecessor-1", text="version B")])

    with pytest.raises(ccr.RecoveryPlanError, match="divergent"):
        ccr.build_repair_existing_operation(
            target_record_id="target-1",
            predecessor_record_id="predecessor-1",
            predecessor_certified_source_path=predecessor_a,
            canon_dir=canon_dir,
            certified_root=certified,
            other_certified_paths_for_divergence_check=[predecessor_b],
        )


# --- 8. predecessor without certified provenance -> block -----------------


def test_repair_existing_target_blocks_uncertified_predecessor(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("target-1", text="")]})
    certified = _certified_root(tmp_path)
    uncertified_path = _certified_source(tmp_path / "uncertified_dir", "backup.jsonl", [_record("predecessor-1", text="x")])

    with pytest.raises(ccr.RecoveryPlanError, match="not certified evidence"):
        ccr.build_repair_existing_operation(
            target_record_id="target-1",
            predecessor_record_id="predecessor-1",
            predecessor_certified_source_path=uncertified_path,
            canon_dir=canon_dir,
            certified_root=certified,
        )


# --- 9. target identity changes -> block -----------------------------------


def test_repair_existing_target_blocks_if_identity_would_change(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("target-1", title="Current Title", text="")]})
    certified = _certified_root(tmp_path)
    predecessor_path = _certified_source(
        certified, "backup.jsonl", [_record("predecessor-1", title="Different Title", text="history")]
    )

    with pytest.raises(ccr.RecoveryPlanError, match="identity field"):
        ccr.build_repair_existing_operation(
            target_record_id="target-1",
            predecessor_record_id="predecessor-1",
            predecessor_certified_source_path=predecessor_path,
            canon_dir=canon_dir,
            certified_root=certified,
            recoverable_fields=("text", "title"),
        )


# --- 10. unrelated metadata overwritten -> block ---------------------------


def test_repair_existing_target_blocks_if_unrelated_metadata_would_change(tmp_path: Path) -> None:
    canon_dir = _canon(
        tmp_path,
        {"tiddlers_1.jsonl": [_record("target-1", text="", tags=["current-tag"])]},
    )
    certified = _certified_root(tmp_path)
    predecessor_path = _certified_source(
        certified, "backup.jsonl", [_record("predecessor-1", text="history", tags=["old-tag"])]
    )

    with pytest.raises(ccr.RecoveryPlanError, match="identity field"):
        ccr.build_repair_existing_operation(
            target_record_id="target-1",
            predecessor_record_id="predecessor-1",
            predecessor_certified_source_path=predecessor_path,
            canon_dir=canon_dir,
            certified_root=certified,
            recoverable_fields=("text", "tags"),
        )


# --- 11. dry-run never changes production ----------------------------------


def test_dry_run_never_writes_to_canon(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    before_bytes = (canon_dir / "tiddlers_1.jsonl").read_bytes()
    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    ccr.dry_run(plan, out_dir=tmp_path / "scratch")

    after_bytes = (canon_dir / "tiddlers_1.jsonl").read_bytes()
    assert before_bytes == after_bytes
    assert sorted(p.name for p in canon_dir.iterdir()) == ["tiddlers_1.jsonl"]


# --- 12. authorization binds exact plan (positive path incl. apply) -------


def test_authorize_and_apply_succeeds_end_to_end(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    authorization = _authorize(plan, tmp_path)
    receipt = ccr.apply(plan, authorization, out_dir=tmp_path / "scratch")

    assert receipt["status"] == "success"
    assert receipt["canon_after_records"] == 2
    assert authorization["consumed"] is True

    index = ccr.load_canon_index(canon_dir)
    assert "missing-1" in index
    assert index["missing-1"][0]["text"] == "recovered"


# --- 13. wrong authorization id -> block -----------------------------------


def test_apply_blocks_on_tampered_authorization(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    authorization = _authorize(plan, tmp_path)
    authorization["plan_hash"] = "0" * 64  # tampered

    with pytest.raises(ccr.RecoveryAuthorizationError, match="plan_hash"):
        ccr.apply(plan, authorization, out_dir=tmp_path / "scratch")


# --- 14. Canon drift -> block ------------------------------------------


def test_apply_blocks_on_canon_drift(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    authorization = _authorize(plan, tmp_path)

    # Canon drifts (an unrelated write) after planning, before apply.
    _write_jsonl(canon_dir / "tiddlers_1.jsonl", [_record("existing-1"), _record("unrelated-new")])

    with pytest.raises(ccr.RecoveryAuthorizationError, match="[Cc]anon drift"):
        ccr.apply(plan, authorization, out_dir=tmp_path / "scratch")


# --- 15. source drift -> block (duplicate class of #3, distinct API path) -


def test_apply_blocks_on_source_drift_for_mode_b(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("target-1", text="")]})
    certified = _certified_root(tmp_path)
    predecessor_path = _certified_source(certified, "backup.jsonl", [_record("predecessor-1", text="original")])

    op = ccr.build_repair_existing_operation(
        target_record_id="target-1",
        predecessor_record_id="predecessor-1",
        predecessor_certified_source_path=predecessor_path,
        canon_dir=canon_dir,
        certified_root=certified,
    )
    plan = ccr.build_plan(canon_dir, [op])
    authorization = _authorize(plan, tmp_path)

    _write_jsonl(predecessor_path, [_record("predecessor-1", text="TAMPERED")])

    with pytest.raises(ccr.RecoveryAuthorizationError, match="[Ss]ource.*drift"):
        ccr.apply(plan, authorization, out_dir=tmp_path / "scratch")


# --- 16. consumed authorization -> no replay -------------------------------


def test_apply_rejects_replay_of_consumed_authorization(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    authorization = _authorize(plan, tmp_path)
    ccr.apply(plan, authorization, out_dir=tmp_path / "scratch")

    with pytest.raises(ccr.RecoveryAuthorizationError, match="consumed"):
        ccr.apply(plan, authorization, out_dir=tmp_path / "scratch")


# --- 17. atomic two-operation success --------------------------------------


def test_atomic_two_operation_apply_succeeds(tmp_path: Path) -> None:
    canon_dir = _canon(
        tmp_path,
        {
            "tiddlers_1.jsonl": [_record("existing-1")],
            "tiddlers_2.jsonl": [_record("target-b", text="")],
        },
    )
    certified = _certified_root(tmp_path)
    source_a = _certified_source(certified, "backup_a.jsonl", [_record("missing-a", text="recovered A")])
    source_b = _certified_source(certified, "backup_b.jsonl", [_record("predecessor-b", text="recovered B")])

    op_a = ccr.build_restore_missing_operation(
        target_record_id="missing-a", certified_source_path=source_a, canon_dir=canon_dir, certified_root=certified
    )
    op_b = ccr.build_repair_existing_operation(
        target_record_id="target-b",
        predecessor_record_id="predecessor-b",
        predecessor_certified_source_path=source_b,
        canon_dir=canon_dir,
        certified_root=certified,
    )
    plan = ccr.build_plan(canon_dir, [op_a, op_b])
    assert plan.expected_canon_after_count == 3  # +1 (A) + 0 (B)

    authorization = _authorize(plan, tmp_path)
    receipt = ccr.apply(plan, authorization, out_dir=tmp_path / "scratch")
    assert receipt["status"] == "success"
    assert set(receipt["changed_record_ids"]) == {"missing-a", "target-b"}

    index = ccr.load_canon_index(canon_dir)
    assert index["missing-a"][0]["text"] == "recovered A"
    assert index["target-b"][0]["text"] == "recovered B"


# --- 18. partial failure -> exact rollback ---------------------------------


def test_partial_promotion_failure_rolls_back_exactly(tmp_path: Path) -> None:
    canon_dir = _canon(
        tmp_path,
        {
            "tiddlers_1.jsonl": [_record("existing-1")],
            "tiddlers_2.jsonl": [_record("target-b", text="")],
        },
    )
    certified = _certified_root(tmp_path)
    source_a = _certified_source(certified, "backup_a.jsonl", [_record("missing-a", text="recovered A")])
    source_b = _certified_source(certified, "backup_b.jsonl", [_record("predecessor-b", text="recovered B")])

    op_a = ccr.build_restore_missing_operation(
        target_record_id="missing-a", certified_source_path=source_a, canon_dir=canon_dir, certified_root=certified
    )
    op_b = ccr.build_repair_existing_operation(
        target_record_id="target-b",
        predecessor_record_id="predecessor-b",
        predecessor_certified_source_path=source_b,
        canon_dir=canon_dir,
        certified_root=certified,
    )
    plan = ccr.build_plan(canon_dir, [op_a, op_b])
    before_hash = plan.canon_before_hash
    authorization = _authorize(plan, tmp_path)

    with pytest.raises(RuntimeError, match="rolled back"):
        ccr.apply(plan, authorization, out_dir=tmp_path / "scratch", _inject_failure_after_shard_index=1)

    assert ccr.canon_snapshot(canon_dir)["hash"] == before_hash
    index = ccr.load_canon_index(canon_dir)
    assert "missing-a" not in index
    assert ccr._is_record_empty(index["target-b"][0])


# --- 19. rollback equality --------------------------------------------------


def test_explicit_rollback_restores_byte_exact(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    before_bytes = (canon_dir / "tiddlers_1.jsonl").read_bytes()
    authorization = _authorize(plan, tmp_path)
    receipt = ccr.apply(plan, authorization, out_dir=tmp_path / "scratch")

    assert (canon_dir / "tiddlers_1.jsonl").read_bytes() != before_bytes

    rollback_report = ccr.rollback(Path(receipt["rollback_snapshot"]), out_dir=tmp_path / "scratch")
    assert rollback_report["byte_exact"] is True
    assert (canon_dir / "tiddlers_1.jsonl").read_bytes() == before_bytes

    # Idempotent: rolling back again succeeds trivially.
    second = ccr.rollback(Path(receipt["rollback_snapshot"]), out_dir=tmp_path / "scratch")
    assert second["status"] == "already_restored"


# --- 20. projected changed ids exactly expected ----------------------------


def test_dry_run_flags_unexpected_third_party_change(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    report = ccr.dry_run(plan, out_dir=tmp_path / "scratch")
    assert report["changed_record_ids"] == report["expected_changed_record_ids"] == ["missing-1"]
    assert report["unexpected_changes"] == []
    assert report["missing_changes"] == []


# --- 21. unknown operation mode -> block -----------------------------------


def test_build_plan_rejects_unknown_operation_mode(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    op.operation_mode = "SOMETHING_ELSE"
    with pytest.raises(ccr.RecoveryPlanError, match="unknown operation mode"):
        ccr.build_plan(canon_dir, [op])


# --- extra: additional invariants worth locking in explicitly -------------


def test_repair_existing_target_never_reintroduces_predecessor_as_second_record(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("target-1", text="")]})
    certified = _certified_root(tmp_path)
    predecessor_path = _certified_source(certified, "backup.jsonl", [_record("predecessor-1", text="history")])

    op = ccr.build_repair_existing_operation(
        target_record_id="target-1",
        predecessor_record_id="predecessor-1",
        predecessor_certified_source_path=predecessor_path,
        canon_dir=canon_dir,
        certified_root=certified,
    )
    plan = ccr.build_plan(canon_dir, [op])
    authorization = _authorize(plan, tmp_path)
    ccr.apply(plan, authorization, out_dir=tmp_path / "scratch")

    index = ccr.load_canon_index(canon_dir)
    assert "predecessor-1" not in index
    assert len(index) == 1


def test_repair_existing_target_blocks_when_predecessor_still_current(tmp_path: Path) -> None:
    canon_dir = _canon(
        tmp_path,
        {"tiddlers_1.jsonl": [_record("target-1", text=""), _record("predecessor-1", text="still alive")]},
    )
    certified = _certified_root(tmp_path)
    predecessor_path = _certified_source(certified, "backup.jsonl", [_record("predecessor-1", text="still alive")])

    with pytest.raises(ccr.RecoveryPlanError, match="still present in CURRENT canon"):
        ccr.build_repair_existing_operation(
            target_record_id="target-1",
            predecessor_record_id="predecessor-1",
            predecessor_certified_source_path=predecessor_path,
            canon_dir=canon_dir,
            certified_root=certified,
        )


def test_authorization_phrase_must_match_plan_exactly(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    snapshot_manifest = _prepare_snapshot(plan, tmp_path)
    with pytest.raises(ccr.RecoveryAuthorizationError, match="phrase"):
        ccr.create_authorization(plan, snapshot_manifest, "wrong phrase entirely")


# --- AJUSTE FINAL PRE-AUTORIZACIÓN: snapshot-before-authorization binding --
#
# The rollback snapshot must exist and be hash-verified BEFORE an
# authorization can be created, and Apply must re-verify that exact
# snapshot -- not a rebuilt one -- immediately before mutating Canon.


# --- new 1. authorization carries rollback_snapshot / rollback_snapshot_hash


def test_authorization_contains_rollback_snapshot_hash(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    snapshot_manifest = _prepare_snapshot(plan, tmp_path)
    authorization = ccr.create_authorization(plan, snapshot_manifest, ccr.authorization_phrase(plan))

    assert authorization["rollback_snapshot"] == str(snapshot_manifest)
    assert authorization["rollback_snapshot_hash"] == ccr.sha256_path(snapshot_manifest)


# --- new 2. snapshot must exist before an authorization can be created ----


def test_create_authorization_blocks_when_snapshot_was_never_prepared(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    never_prepared = tmp_path / "snapshot" / "rollback_manifest.json"

    with pytest.raises(ccr.RecoveryAuthorizationError, match="does not exist"):
        ccr.create_authorization(plan, never_prepared, ccr.authorization_phrase(plan))


# --- new 3. snapshot content drift after authorization -> Apply blocked ---


def test_apply_blocks_when_snapshot_drifts_after_authorization(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    authorization = _authorize(plan, tmp_path)
    snapshot_manifest = Path(authorization["rollback_snapshot"])

    # The snapshot file itself is edited after the authorization already
    # bound to its hash -- this must never be silently tolerated.
    manifest = json.loads(snapshot_manifest.read_text(encoding="utf-8"))
    manifest["created_at"] = "TAMPERED"
    snapshot_manifest.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ccr.RecoveryAuthorizationError, match="[Ss]napshot drift"):
        ccr.apply(plan, authorization, out_dir=tmp_path / "scratch")


# --- new 4. snapshot absent at apply time -> Apply blocked -----------------


def test_apply_blocks_when_authorized_snapshot_is_missing(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    authorization = _authorize(plan, tmp_path)
    Path(authorization["rollback_snapshot"]).unlink()

    with pytest.raises(ccr.RecoveryAuthorizationError, match="missing"):
        ccr.apply(plan, authorization, out_dir=tmp_path / "scratch")


# --- new 5. snapshot silently replaced by another valid-but-different one -


def test_apply_blocks_when_snapshot_is_replaced_by_a_different_valid_snapshot(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    authorization = _authorize(plan, tmp_path)
    snapshot_manifest = Path(authorization["rollback_snapshot"])

    # A replacement snapshot that is itself well-formed and internally
    # self-verifying (same plan/plan_hash/canon_before_hash, backups whose
    # hashes match their own recorded values) but is NOT byte-identical to
    # the one this authorization actually bound to -- e.g. rebuilt at a
    # different moment. This must be rejected exactly like outright
    # tampering: the authorization is bound to one specific snapshot file.
    manifest = json.loads(snapshot_manifest.read_text(encoding="utf-8"))
    manifest["created_at"] = "2020-01-01T00:00:00Z"
    snapshot_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    assert ccr.sha256_path(snapshot_manifest) != authorization["rollback_snapshot_hash"]

    with pytest.raises(ccr.RecoveryAuthorizationError, match="[Ss]napshot drift"):
        ccr.apply(plan, authorization, out_dir=tmp_path / "scratch")


# --- new 6. Canon drift detected during snapshot preparation itself -------


def test_prepare_snapshot_blocks_on_canon_drift(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])

    # Canon drifts (an unrelated write) after planning, before the snapshot
    # preflight ever runs.
    _write_jsonl(canon_dir / "tiddlers_1.jsonl", [_record("existing-1"), _record("unrelated-new")])

    with pytest.raises(ccr.RecoveryAuthorizationError, match="[Cc]anon drift"):
        ccr.prepare_snapshot(plan, tmp_path / "snapshot")


# --- new 7. snapshot preparation never modifies Canon ----------------------


def test_prepare_snapshot_does_not_modify_canon(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    before_bytes = (canon_dir / "tiddlers_1.jsonl").read_bytes()
    before_hash = ccr.canon_snapshot(canon_dir)["hash"]

    ccr.prepare_snapshot(plan, tmp_path / "snapshot")

    assert (canon_dir / "tiddlers_1.jsonl").read_bytes() == before_bytes
    assert ccr.canon_snapshot(canon_dir)["hash"] == before_hash
    assert sorted(p.name for p in canon_dir.iterdir()) == ["tiddlers_1.jsonl"]


# --- new 8. rollback uses exactly the authorized snapshot, never a new one -


def test_rollback_uses_exactly_the_authorized_snapshot(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    authorization = _authorize(plan, tmp_path)
    authorized_snapshot_path = authorization["rollback_snapshot"]
    authorized_snapshot_hash = authorization["rollback_snapshot_hash"]

    receipt = ccr.apply(plan, authorization, out_dir=tmp_path / "scratch")

    # apply() must reference the pre-existing, authorized snapshot in its
    # receipt -- never a snapshot it created itself during apply.
    assert receipt["rollback_snapshot"] == authorized_snapshot_path
    assert receipt["rollback_snapshot_hash"] == authorized_snapshot_hash
    assert ccr.sha256_path(Path(authorized_snapshot_path)) == authorized_snapshot_hash


# --- new 9. Apply + rollback recovers byte equality under the new flow ----


def test_apply_then_rollback_recovers_byte_equality_under_snapshot_bound_flow(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    before_bytes = (canon_dir / "tiddlers_1.jsonl").read_bytes()
    before_hash = ccr.canon_snapshot(canon_dir)["hash"]

    authorization = _authorize(plan, tmp_path)
    receipt = ccr.apply(plan, authorization, out_dir=tmp_path / "scratch")
    assert ccr.canon_snapshot(canon_dir)["hash"] != before_hash

    rollback_report = ccr.rollback(Path(receipt["rollback_snapshot"]), out_dir=tmp_path / "scratch")
    assert rollback_report["byte_exact"] is True
    assert (canon_dir / "tiddlers_1.jsonl").read_bytes() == before_bytes
    assert ccr.canon_snapshot(canon_dir)["hash"] == before_hash


# --- DRY-RUN FAILURE BEFORE SNAPSHOT: plan/dry-run/apply producer parity --
#
# The productive PREIMPACT dry-run found overall_status=fail for MODE B:
# a materialization built directly in-memory (build_repair_existing_operation)
# and a materialization rebuilt from the persisted plan file after a
# disk round-trip disagreed on version_id, because the reload path used by
# the CLI's dry-run/apply commands AND by the operator menu was three
# separately hand-copied reimplementations, one of which (the operator
# menu) never recomputed version_id at all. Fixed by extracting ONE shared
# `materialize_recovered_record()` (built on the same `_repair_record_fields`
# / `_recompute_version_id_if_recovered` primitives `build_repair_existing_operation`
# itself uses) and routing every reload site through it. Separately,
# `plan_hash` depended on the plan's wall-clock `created_at`, so
# re-materializing the identical recovery request at a different moment
# produced a different plan_hash despite zero binding-relevant change;
# `_operation_id` also did not fold in `expected_target_after_hash`, so two
# operations that agreed on mode+target+source but committed to different
# resulting records were not guaranteed distinct ids/plan_ids.


def test_mode_b_plan_expected_hash_equals_dry_run_actual_hash_after_disk_reload(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("target-1", text="")]})
    certified = _certified_root(tmp_path)
    predecessor_path = _certified_source(certified, "backup.jsonl", [_record("predecessor-1", text="history")])

    op = ccr.build_repair_existing_operation(
        target_record_id="target-1",
        predecessor_record_id="predecessor-1",
        predecessor_certified_source_path=predecessor_path,
        canon_dir=canon_dir,
        certified_root=certified,
    )
    plan = ccr.build_plan(canon_dir, [op])
    reloaded_plan = _reload_plan_from_disk(plan, tmp_path)

    report = ccr.dry_run(reloaded_plan, out_dir=tmp_path / "scratch")
    assert report["overall_status"] == "pass"
    check = report["per_operation"][0]
    assert check["matches_expected_after_hash"] is True
    assert check["actual_after_hash"] == op.expected_target_after_hash


def test_mode_b_plan_expected_hash_equals_apply_materialization_hash(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("target-1", text="")]})
    certified = _certified_root(tmp_path)
    predecessor_path = _certified_source(certified, "backup.jsonl", [_record("predecessor-1", text="history")])

    op = ccr.build_repair_existing_operation(
        target_record_id="target-1",
        predecessor_record_id="predecessor-1",
        predecessor_certified_source_path=predecessor_path,
        canon_dir=canon_dir,
        certified_root=certified,
    )
    plan = ccr.build_plan(canon_dir, [op])
    reloaded_plan = _reload_plan_from_disk(plan, tmp_path)
    authorization = _authorize(reloaded_plan, tmp_path)
    receipt = ccr.apply(reloaded_plan, authorization, out_dir=tmp_path / "scratch")

    assert receipt["status"] == "success"
    index = ccr.load_canon_index(canon_dir)
    assert ccr._record_hash(index["target-1"][0]) == op.expected_target_after_hash


def test_version_id_recomputation_parity_between_build_and_reload(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("target-1", text="")]})
    certified = _certified_root(tmp_path)
    predecessor_path = _certified_source(certified, "backup.jsonl", [_record("predecessor-1", text="history")])

    op = ccr.build_repair_existing_operation(
        target_record_id="target-1",
        predecessor_record_id="predecessor-1",
        predecessor_certified_source_path=predecessor_path,
        canon_dir=canon_dir,
        certified_root=certified,
    )
    plan = ccr.build_plan(canon_dir, [op])
    reloaded_plan = _reload_plan_from_disk(plan, tmp_path)

    assert reloaded_plan.operations[0].recovered_record["version_id"] == op.recovered_record["version_id"]


def test_recomputed_version_id_matches_the_tdc_identity_contract(tmp_path: Path) -> None:
    """A recomputed version_id must obey the TDC S34 contract exactly

    (sha256 of canonical_json({key, title, text, created, modified})), the
    same formula the Go canon_preflight strict validator and
    normalize_session_titles.py use -- never a locally-invented shape. A
    prior version of this module used {text, content, modality} instead,
    which passed its own tests but produced a version_id that fails
    ``canon_preflight --mode strict`` against real Canon.
    """
    import normalize_session_titles as nst

    canon_dir = _canon(
        tmp_path,
        {
            "tiddlers_1.jsonl": [
                _record("target-1", title="T", text="", key="T.txt", created="2026-01-01", modified="2026-01-01")
            ]
        },
    )
    certified = _certified_root(tmp_path)
    predecessor_path = _certified_source(
        certified, "backup.jsonl", [_record("predecessor-1", title="T", text="recovered history")]
    )

    op = ccr.build_repair_existing_operation(
        target_record_id="target-1",
        predecessor_record_id="predecessor-1",
        predecessor_certified_source_path=predecessor_path,
        canon_dir=canon_dir,
        certified_root=certified,
    )

    expected = nst._recompute_version_id(
        op.recovered_record["key"],
        op.recovered_record["title"],
        op.recovered_record["text"],
        op.recovered_record.get("created"),
        op.recovered_record.get("modified"),
    )
    assert op.recovered_record["version_id"] == expected


def test_preserved_fields_parity_between_build_and_reload(tmp_path: Path) -> None:
    canon_dir = _canon(
        tmp_path,
        {"tiddlers_1.jsonl": [_record("target-1", text="", tags=["kept-tag"])]},
    )
    certified = _certified_root(tmp_path)
    predecessor_path = _certified_source(
        certified, "backup.jsonl", [_record("predecessor-1", text="history", tags=["kept-tag"])]
    )

    op = ccr.build_repair_existing_operation(
        target_record_id="target-1",
        predecessor_record_id="predecessor-1",
        predecessor_certified_source_path=predecessor_path,
        canon_dir=canon_dir,
        certified_root=certified,
    )
    plan = ccr.build_plan(canon_dir, [op])
    reloaded_plan = _reload_plan_from_disk(plan, tmp_path)

    # "tags" is not a recoverable field -- the reload must preserve it from
    # CURRENT exactly as the original build did, never pulling it from the
    # predecessor even though the predecessor happens to carry the same key.
    assert reloaded_plan.operations[0].recovered_record["tags"] == op.recovered_record["tags"] == ["kept-tag"]


def test_recovered_fields_parity_between_build_and_reload(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("target-1", text="", content=None)]})
    certified = _certified_root(tmp_path)
    predecessor_path = _certified_source(
        certified, "backup.jsonl", [_record("predecessor-1", text="recovered text", content={"plain": "recovered text"})]
    )

    op = ccr.build_repair_existing_operation(
        target_record_id="target-1",
        predecessor_record_id="predecessor-1",
        predecessor_certified_source_path=predecessor_path,
        canon_dir=canon_dir,
        certified_root=certified,
    )
    plan = ccr.build_plan(canon_dir, [op])
    reloaded_plan = _reload_plan_from_disk(plan, tmp_path)

    for key in ("text", "content"):
        assert reloaded_plan.operations[0].recovered_record[key] == op.recovered_record[key]


def test_same_target_and_predecessor_with_different_recoverable_fields_cannot_share_plan_id(tmp_path: Path) -> None:
    canon_dir = _canon(
        tmp_path, {"tiddlers_1.jsonl": [_record("target-1", title="T", text="", content=None, tags=["old"])]}
    )
    certified = _certified_root(tmp_path)
    predecessor_path = _certified_source(
        certified,
        "backup.jsonl",
        [_record("predecessor-1", title="T", text="history", content={"plain": "predecessor content"}, tags=["old"])],
    )

    op_narrow = ccr.build_repair_existing_operation(
        target_record_id="target-1",
        predecessor_record_id="predecessor-1",
        predecessor_certified_source_path=predecessor_path,
        canon_dir=canon_dir,
        certified_root=certified,
        recoverable_fields=("text",),
    )
    op_wide = ccr.build_repair_existing_operation(
        target_record_id="target-1",
        predecessor_record_id="predecessor-1",
        predecessor_certified_source_path=predecessor_path,
        canon_dir=canon_dir,
        certified_root=certified,
        recoverable_fields=("text", "content", "modality"),
    )

    # Same mode, same target, same predecessor content -- but a different
    # recoverable_fields selection commits to a DIFFERENT resulting record.
    # These must never collide onto the same operation_id/plan_id: the id
    # is the identity of "what will be mutated", not just "from where".
    assert op_narrow.expected_target_after_hash != op_wide.expected_target_after_hash
    assert op_narrow.operation_id != op_wide.operation_id

    plan_narrow = ccr.build_plan(canon_dir, [op_narrow])
    plan_wide = ccr.build_plan(canon_dir, [op_wide])
    assert plan_narrow.plan_id != plan_wide.plan_id


def test_plan_hash_drift_invalidates_authorization(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("existing-1")]})
    certified = _certified_root(tmp_path)
    source_path = _certified_source(certified, "backup.jsonl", [_record("missing-1", text="recovered")])

    op = ccr.build_restore_missing_operation(
        target_record_id="missing-1", certified_source_path=source_path, canon_dir=canon_dir, certified_root=certified
    )
    plan = ccr.build_plan(canon_dir, [op])
    authorization = _authorize(plan, tmp_path)

    # The plan itself drifts (its sealed content no longer matches what was
    # authorized) rather than the authorization being tampered with.
    import dataclasses

    drifted_plan = dataclasses.replace(plan, plan_hash="0" * 64)

    with pytest.raises(ccr.RecoveryAuthorizationError, match="plan_hash"):
        ccr.apply(drifted_plan, authorization, out_dir=tmp_path / "scratch")


def test_projected_canon_hash_identical_between_in_memory_and_disk_reloaded_plan(tmp_path: Path) -> None:
    canon_dir = _canon(
        tmp_path,
        {
            "tiddlers_1.jsonl": [_record("existing-1")],
            "tiddlers_2.jsonl": [_record("target-b", text="")],
        },
    )
    certified = _certified_root(tmp_path)
    source_a = _certified_source(certified, "backup_a.jsonl", [_record("missing-a", text="recovered A")])
    source_b = _certified_source(certified, "backup_b.jsonl", [_record("predecessor-b", text="recovered B")])

    op_a = ccr.build_restore_missing_operation(
        target_record_id="missing-a", certified_source_path=source_a, canon_dir=canon_dir, certified_root=certified
    )
    op_b = ccr.build_repair_existing_operation(
        target_record_id="target-b",
        predecessor_record_id="predecessor-b",
        predecessor_certified_source_path=source_b,
        canon_dir=canon_dir,
        certified_root=certified,
    )
    plan = ccr.build_plan(canon_dir, [op_a, op_b])
    reloaded_plan = _reload_plan_from_disk(plan, tmp_path)

    report_in_memory = ccr.dry_run(plan, out_dir=tmp_path / "u1")
    report_reloaded = ccr.dry_run(reloaded_plan, out_dir=tmp_path / "u2")

    assert report_in_memory["overall_status"] == report_reloaded["overall_status"] == "pass"
    assert report_in_memory["projected_canon_after"]["hash"] == report_reloaded["projected_canon_after"]["hash"]


def test_ab_projected_hash_deterministic_across_repeated_plan_construction(tmp_path: Path) -> None:
    canon_dir = _canon(
        tmp_path,
        {
            "tiddlers_1.jsonl": [_record("existing-1")],
            "tiddlers_2.jsonl": [_record("target-b", text="")],
        },
    )
    certified = _certified_root(tmp_path)
    source_a = _certified_source(certified, "backup_a.jsonl", [_record("missing-a", text="recovered A")])
    source_b = _certified_source(certified, "backup_b.jsonl", [_record("predecessor-b", text="recovered B")])

    def _build() -> ccr.RecoveryPlan:
        op_a = ccr.build_restore_missing_operation(
            target_record_id="missing-a", certified_source_path=source_a, canon_dir=canon_dir, certified_root=certified
        )
        op_b = ccr.build_repair_existing_operation(
            target_record_id="target-b",
            predecessor_record_id="predecessor-b",
            predecessor_certified_source_path=source_b,
            canon_dir=canon_dir,
            certified_root=certified,
        )
        return ccr.build_plan(canon_dir, [op_a, op_b])

    plan1 = _build()
    plan2 = _build()

    assert plan1.plan_id == plan2.plan_id
    assert plan1.plan_hash == plan2.plan_hash

    report1 = ccr.dry_run(plan1, out_dir=tmp_path / "u1")
    report2 = ccr.dry_run(plan2, out_dir=tmp_path / "u2")
    assert report1["projected_canon_after"]["hash"] == report2["projected_canon_after"]["hash"]


def test_plan_identity_stable_across_time_with_no_content_change(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_record("target-1", text="")]})
    certified = _certified_root(tmp_path)
    predecessor_path = _certified_source(certified, "backup.jsonl", [_record("predecessor-1", text="history")])

    def _build() -> ccr.RecoveryPlan:
        op = ccr.build_repair_existing_operation(
            target_record_id="target-1",
            predecessor_record_id="predecessor-1",
            predecessor_certified_source_path=predecessor_path,
            canon_dir=canon_dir,
            certified_root=certified,
        )
        return ccr.build_plan(canon_dir, [op])

    plan1 = _build()
    import time

    time.sleep(1.1)
    plan2 = _build()

    # created_at legitimately differs (wall-clock), but that is not
    # binding-relevant content: plan_id and plan_hash must not move just
    # because time passed with nothing else changing.
    assert plan1.created_at != plan2.created_at
    assert plan1.plan_id == plan2.plan_id
    assert plan1.plan_hash == plan2.plan_hash


# --- PREIMPACT FINAL: RECOMPUTE_INVALID_VERSION_ID (MODE C) ---------------
#
# A CURRENT record's version_id was computed by an earlier (now-fixed) bug
# in this module using the wrong shape ({text, content, modality} instead
# of the TDC contract {key, title, text, created, modified}), so it fails
# ``canon_preflight --mode strict``. This mode corrects ONLY version_id,
# derived exclusively from the target's own CURRENT fields via the same
# contract every other producer uses -- never a manually-supplied value,
# never any other field.


def _valid_contract_record(title: str, *, text: str = "fixture body text", version_id: str | None = None) -> dict:
    """Build a record whose id/key/canonical_slug are derived exactly as

    the Go identity contract requires, so canon_preflight --mode strict
    only ever flags what a test deliberately breaks (version_id).
    """
    import normalize_session_titles as nst

    key = nst._recompute_key(title)
    record_id = nst._recompute_id(key)
    slug = nst._recompute_canonical_slug(title)
    created = "2026-01-01T00:00:00Z"
    modified = "2026-01-01T00:00:00Z"
    resolved_version_id = version_id
    if resolved_version_id is None:
        resolved_version_id = nst._recompute_version_id(key, title, text, created, modified)
    return {
        "schema_version": "v0",
        "id": record_id,
        "key": key,
        "title": title,
        "canonical_slug": slug,
        "text": text,
        "content": None,
        "created": created,
        "modified": modified,
        "version_id": resolved_version_id,
    }


def test_recompute_invalid_version_id_builds_when_stored_value_is_wrong(tmp_path: Path) -> None:
    broken = _valid_contract_record("Fixture Title A", version_id="sha256:" + "0" * 64)
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [broken]})

    op = ccr.build_recompute_invalid_version_id_operation(target_record_id=broken["id"], canon_dir=canon_dir)

    assert op.operation_mode == ccr.MODE_RECOMPUTE_INVALID_VERSION_ID
    assert op.fields_recomputed == ["version_id"]
    assert op.fields_recovered_from_history == []
    assert op.recovered_record["version_id"] != broken["version_id"]
    assert op.expected_record_count_delta == 0


def test_recompute_invalid_version_id_refuses_when_already_consistent(tmp_path: Path) -> None:
    valid = _valid_contract_record("Fixture Title B")
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [valid]})

    with pytest.raises(ccr.RecoveryPlanError, match="already matches the identity contract"):
        ccr.build_recompute_invalid_version_id_operation(target_record_id=valid["id"], canon_dir=canon_dir)


def test_recompute_invalid_version_id_refuses_when_target_missing(tmp_path: Path) -> None:
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [_valid_contract_record("Fixture Title C")]})

    with pytest.raises(ccr.RecoveryPlanError, match="does not exist in CURRENT canon"):
        ccr.build_recompute_invalid_version_id_operation(target_record_id="not-there", canon_dir=canon_dir)


def test_recompute_invalid_version_id_changes_only_version_id(tmp_path: Path) -> None:
    broken = _valid_contract_record("Fixture Title D", version_id="sha256:" + "1" * 64)
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [broken]})

    op = ccr.build_recompute_invalid_version_id_operation(target_record_id=broken["id"], canon_dir=canon_dir)

    for key in broken:
        if key == "version_id":
            continue
        assert op.recovered_record[key] == broken[key], f"field {key!r} must not change"
    assert set(op.fields_preserved_from_current) == set(broken) - {"version_id"}


def test_recompute_invalid_version_id_dry_run_passes_with_exact_delta(tmp_path: Path) -> None:
    broken = _valid_contract_record("Fixture Title E", version_id="sha256:" + "2" * 64)
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [broken]})

    op = ccr.build_recompute_invalid_version_id_operation(target_record_id=broken["id"], canon_dir=canon_dir)
    plan = ccr.build_plan(canon_dir, [op])
    assert plan.expected_canon_after_count == 1  # count delta = 0

    report = ccr.dry_run(plan, out_dir=tmp_path / "scratch")
    assert report["overall_status"] == "pass"
    assert report["count_matches_expected"] is True
    assert report["unexpected_changes"] == []
    assert report["missing_changes"] == []
    assert report["changed_record_ids"] == [broken["id"]]
    check = report["per_operation"][0]
    assert check["present_exactly_once"] is True
    assert check["matches_expected_after_hash"] is True
    assert check["actual_after_hash"] != op.target_before_hash


def test_recompute_invalid_version_id_materialize_parity_after_disk_reload(tmp_path: Path) -> None:
    broken = _valid_contract_record("Fixture Title F", version_id="sha256:" + "3" * 64)
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [broken]})

    op = ccr.build_recompute_invalid_version_id_operation(target_record_id=broken["id"], canon_dir=canon_dir)
    plan = ccr.build_plan(canon_dir, [op])
    reloaded_plan = _reload_plan_from_disk(plan, tmp_path)

    assert reloaded_plan.operations[0].recovered_record == op.recovered_record


def test_verify_strict_projected_canon_confirms_the_real_go_validator_passes(tmp_path: Path) -> None:
    """End-to-end parity: Python builds the corrected record, and the REAL

    Go canon_preflight --mode strict independently confirms it -- the same
    tool that caught the original version_id contract violation.
    """
    broken = _valid_contract_record("Fixture Title G", version_id="sha256:" + "4" * 64)
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [broken]})

    op = ccr.build_recompute_invalid_version_id_operation(target_record_id=broken["id"], canon_dir=canon_dir)
    plan = ccr.build_plan(canon_dir, [op])

    verification = ccr.verify_strict_projected_canon(plan, out_dir=tmp_path / "strict")
    assert verification["status"] == "pass", verification
    assert verification["issues"] == []
