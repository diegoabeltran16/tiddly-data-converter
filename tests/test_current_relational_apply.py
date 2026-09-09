"""S0186 (sealed_apply_execution_blocked closure): regression coverage for
current_relational_apply.py's authorize/apply boundary.

Root cause: guarded_apply_relations() gates every apply attempt on the
on-disk mtime of the dry-run report it is given being < max_dry_run_age_minutes
(default 1440 = 24h) old. current_relational_apply.apply() passes the dry-run
report living INSIDE the immutable, already-published bundle
(authority["artifacts"]["admission_gate"]) -- a file whose mtime is fixed
forever at bundle-publish time. Any authorized CURRENT apply attempted more
than 24h after the bundle was published was therefore permanently and
unrecoverably blocked (sealed_apply_execution_blocked), with no governed
remedy, even though nothing about candidates/decisions/Canon had drifted --
that drift-freedom is independently and exhaustively proven byte-exact by
preflight()'s canon_before_hash check plus the exact_bindings/semantic-id
comparisons guarded_apply_relations() and _validate_plan_against_bundle()
already perform.

Fix: guarded_apply_relations() gained an opt-in, default-True
`dry_run_freshness_required` parameter. Only current_relational_apply.apply()
passes False (documented at both call sites) -- every other existing caller
(the plain production_path/manual dry-run-then-apply flow) is completely
unaffected; a genuinely missing dry-run report still blocks unconditionally,
and any OTHER content drift (decisions changed, Canon changed, plan mutated)
still blocks exactly as before.

Fixtures/TMP only. Never CURRENT productivo, never a real Apply execution
against production Canon.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import current_relational_apply as apply_module  # noqa: E402
import current_relational_authority as authority_module  # noqa: E402
import prepare_current_relational_generation as preparation  # noqa: E402
import relation_admission_gate as admission_gate  # noqa: E402

from test_generational_decision_preservation import (  # noqa: E402
    _reach_ready_for_authorization_single_candidate,
)


TDC_SH = REPO_ROOT / "src" / "shell_scripts" / "tdc.sh"


def _resolve(paths: preparation.Paths) -> dict:
    return authority_module.resolve_current_relational_authority(paths.local_root)


def _authorize(paths: preparation.Paths, *, reviewer: str = "Naveen") -> dict:
    authority = _resolve(paths)
    confirmation = f"AUTHORIZE CURRENT RELATIONAL APPLY {authority['readiness_id']}"
    return apply_module.authorize(paths.local_root, reviewer, confirmation)


def _backdate_bundle_dry_run(paths: preparation.Paths, *, hours: float = 30.0) -> Path:
    """Simulate the exact real-production shape: an authorized, unconsumed
    apply attempted more than 24h after the (immutable) bundle was
    published -- never a live/mutable file, matching what apply() actually
    reads (authority["artifacts"]["admission_gate"])."""
    authority = _resolve(paths)
    path = authority["artifacts"]["admission_gate"]
    stamp = time.time() - hours * 3600
    os.utime(path, (stamp, stamp))
    return path


# --- 1: no authorization -> blocked -----------------------------------------

def test_apply_blocked_without_authorization(tmp_path: Path) -> None:
    paths, _source_root, _candidate_id = _reach_ready_for_authorization_single_candidate(
        tmp_path
    )
    fake_id = "cra_" + "0" * 24
    with pytest.raises(authority_module.CurrentRelationalAuthorityError) as excinfo:
        apply_module.apply(
            paths.local_root, fake_id,
            f"CONFIRM APPLY CURRENT RELATIONS {fake_id}",
        )
    assert "authorization_not_current" in excinfo.value.reason_codes


# --- 2: seal legitimately closed (staleness NOT bypassed by default) -------

def test_seal_legitimately_closed_still_blocks_outside_the_opt_in(tmp_path: Path) -> None:
    """The exact guard this whole fix touches, exercised directly and WITHOUT
    the new opt-out: proves guarded_apply_relations()'s own default behavior
    is completely unchanged -- dry_run_freshness_required defaults to True,
    so a stale prevalidated plan still blocks for any caller that doesn't
    explicitly ask for the CURRENT-bundle exemption.
    """
    paths, _source_root, _candidate_id = _reach_ready_for_authorization_single_candidate(
        tmp_path
    )
    _authorize(paths)
    dry_run_path = _backdate_bundle_dry_run(paths)
    authority = _resolve(paths)

    code, report = admission_gate.guarded_apply_relations(
        candidates_file=authority["artifacts"]["ready_queue"],
        canon_glob=str(paths.local_root / "tiddlers_*.jsonl"),
        human_review_decisions_file=authority["artifacts"]["effective_decisions"],
        dry_run_report_path=dry_run_path,
        out_dir=tmp_path / "manual_attempt",
        terminal_confirmation=admission_gate.APPLY_CONFIRMATION,
        perform_write=True,
        target_scope="current_relational_bundle",
        binding_paths={
            "candidate_manifest": authority["artifacts"]["candidate_manifest"],
            "validation_report": authority["artifacts"]["validation_report"],
            "reconciliation_manifest": authority["artifacts"]["reconciliation_manifest"],
            "reviewable_manifest": authority["artifacts"]["reviewable_manifest"],
            "human_review_decisions": authority["artifacts"]["effective_decisions"],
        },
        prevalidated_plan_path=authority["artifacts"]["apply_plan"],
        # dry_run_freshness_required intentionally omitted -- default True.
    )
    assert code == 1
    reasons = report["apply_plan"]["block_reasons"]
    assert any(reason.startswith("stale_dry_run_report") for reason in reasons)


# --- 3: governed correct state -> Apply permitted ---------------------------

def test_apply_permitted_once_seal_and_authorization_hold(tmp_path: Path) -> None:
    paths, _source_root, _candidate_id = _reach_ready_for_authorization_single_candidate(
        tmp_path
    )
    authorization = _authorize(paths)
    _backdate_bundle_dry_run(paths)
    canon_before = preparation.canon_snapshot(paths.local_root)["hash"]

    authorization_id = authorization["authorization_id"]
    confirmation = f"CONFIRM APPLY CURRENT RELATIONS {authorization_id}"
    result = apply_module.apply(paths.local_root, authorization_id, confirmation)

    assert result["status"] == "applied" or result.get("applied_count", 0) > 0
    assert Path(result["receipt_path"]).is_file()
    stored_authorization = json.loads(
        apply_module.authorization_path(
            paths.local_root, str(_resolve_readiness(paths))
        ).read_text(encoding="utf-8")
    )
    assert stored_authorization["consumed"] is True
    # The 24h dry-run staleness gate never invalidated a byte-for-byte
    # unchanged, already-authorized bundle.
    assert preparation.canon_snapshot(paths.local_root)["hash"] != canon_before


def _resolve_readiness(paths: preparation.Paths) -> str:
    return str(_resolve(paths)["readiness_id"])


# --- 4: wrong authorization_id -> blocked -----------------------------------

def test_wrong_authorization_id_is_blocked(tmp_path: Path) -> None:
    paths, _source_root, _candidate_id = _reach_ready_for_authorization_single_candidate(
        tmp_path
    )
    _authorize(paths)
    _backdate_bundle_dry_run(paths)
    bogus_id = "cra_" + "f" * 24
    with pytest.raises(authority_module.CurrentRelationalAuthorityError) as excinfo:
        apply_module.apply(
            paths.local_root, bogus_id,
            f"CONFIRM APPLY CURRENT RELATIONS {bogus_id}",
        )
    assert "authorization_not_current" in excinfo.value.reason_codes


# --- 5: authorization consumed -> not reusable ------------------------------

def test_consumed_authorization_is_not_reusable(tmp_path: Path) -> None:
    """Isolate the "consumed" check itself, independent of a real apply's
    Canon side effect: mark the authorization consumed directly (mirroring
    what apply() itself does to the same file on success) without ever
    running a real apply, then confirm preflight()/apply() refuse it purely
    because it is consumed -- Canon and every bundle artifact stay
    untouched, so a genuine drift-based reason cannot be the explanation.
    """
    paths, _source_root, _candidate_id = _reach_ready_for_authorization_single_candidate(
        tmp_path
    )
    authorization = _authorize(paths)
    _backdate_bundle_dry_run(paths)
    authorization_id = authorization["authorization_id"]
    canon_before = preparation.canon_snapshot(paths.local_root)["hash"]

    auth_path = apply_module.authorization_path(
        paths.local_root, str(_resolve_readiness(paths))
    )
    stored = json.loads(auth_path.read_text(encoding="utf-8"))
    stored["consumed"] = True
    auth_path.write_text(json.dumps(stored, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    confirmation = f"CONFIRM APPLY CURRENT RELATIONS {authorization_id}"
    with pytest.raises(authority_module.CurrentRelationalAuthorityError) as excinfo:
        apply_module.apply(paths.local_root, authorization_id, confirmation)
    assert "authorization_not_current" in excinfo.value.reason_codes
    assert preparation.canon_snapshot(paths.local_root)["hash"] == canon_before


# --- 6: readiness/plan/Canon drift after authorization -> blocked ----------

def test_canon_drift_after_authorization_is_blocked(tmp_path: Path) -> None:
    paths, _source_root, _candidate_id = _reach_ready_for_authorization_single_candidate(
        tmp_path
    )
    authorization = _authorize(paths)
    _backdate_bundle_dry_run(paths)

    canon_file = sorted(paths.local_root.glob("tiddlers_*.jsonl"))[0]
    canon_file.write_text(
        canon_file.read_text(encoding="utf-8")
        + json.dumps({
            "id": "drift-after-authorization",
            "title": "Drift after authorization",
            "key": "Drift after authorization",
            "version_id": "sha256:drift-after-authorization",
            "text": "Unrelated content admitted after authorization.",
            "source_fields": {"artifact_family": "thematic_diagnostic"},
            "relations": [],
        }) + "\n",
        encoding="utf-8",
    )

    authorization_id = authorization["authorization_id"]
    confirmation = f"CONFIRM APPLY CURRENT RELATIONS {authorization_id}"
    with pytest.raises(authority_module.CurrentRelationalAuthorityError) as excinfo:
        apply_module.apply(paths.local_root, authorization_id, confirmation)
    assert "current_bundle_canon_stale" in excinfo.value.reason_codes


# --- 7: retry cannot skip the seal ------------------------------------------

def test_retry_cannot_skip_the_seal_via_the_freshness_opt_out(tmp_path: Path) -> None:
    """The freshness bypass touches ONLY the wall-clock check: a genuine
    content drift in the SEALED (bundle-local, immutable-by-contract)
    decisions still blocks Apply. This edits the bundle's own copy directly
    -- apply() never even reads the live pipeline/current mirror, so that is
    the only way to prove the seal (not just the live decision authority) is
    what is being verified. apply_plan.json/gate_g_readiness.json/
    decision_checkpoint.json/authorization.json are all left byte-identical,
    so nothing about the tampering is "pre-declared" anywhere else -- it is
    caught by the bundle's own artifact-hash integrity check.
    """
    paths, _source_root, candidate_id = _reach_ready_for_authorization_single_candidate(
        tmp_path
    )
    authorization = _authorize(paths)
    _backdate_bundle_dry_run(paths)
    authority = _resolve(paths)

    decisions_path = authority["artifacts"]["effective_decisions"]
    rows = [
        json.loads(line)
        for line in decisions_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    for row in rows:
        if row.get("candidate_id") == candidate_id:
            row["human_review_decision"] = "deferred"
            row["human_review_reason_code"] = "LIFECYCLE_UNRESOLVED"
    decisions_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8",
    )

    authorization_id = authorization["authorization_id"]
    confirmation = f"CONFIRM APPLY CURRENT RELATIONS {authorization_id}"
    with pytest.raises(authority_module.CurrentRelationalAuthorityError) as excinfo:
        apply_module.apply(paths.local_root, authorization_id, confirmation)
    # The bundle's own artifact-hash integrity check (resolve_current_
    # relational_authority, evaluated before preflight()/guarded_apply_
    # relations() ever run) already refuses a tampered immutable artifact --
    # an even earlier, more fundamental proof that the seal cannot be
    # bypassed than the specific sealed_apply_plan_drift comparison this
    # test originally targeted.
    assert "current_bundle_artifact_hash_mismatch" in excinfo.value.reason_codes


# --- 8: menu points to the real apply option --------------------------------

def test_menu_apply_retry_message_points_to_the_real_option() -> None:
    text = TDC_SH.read_text(encoding="utf-8")
    assert "Vuelva a seleccionar la opción 6 para ejecutar." in text
    assert "Vuelva a seleccionar la opción 5 para ejecutar." not in text


# --- 9: production-shaped fixture reaches the Apply boundary cleanly -------

def test_production_shaped_fixture_reaches_apply_boundary_without_seal_block(
    tmp_path: Path,
) -> None:
    paths, _source_root, _candidate_id = _reach_ready_for_authorization_single_candidate(
        tmp_path
    )
    status_before = preparation.read_current_bundle_status(paths.local_root)
    assert status_before["valid"] is True
    plan_before = status_before["planning"]
    assert plan_before["approved_candidate_representations"] == 2
    assert plan_before["planned_unique_relations"] == 2
    assert plan_before["conservation_valid"] is True

    authorization = _authorize(paths)
    _backdate_bundle_dry_run(paths, hours=48.0)

    authorization_id = authorization["authorization_id"]
    confirmation = f"CONFIRM APPLY CURRENT RELATIONS {authorization_id}"
    result = apply_module.apply(paths.local_root, authorization_id, confirmation)

    assert result.get("applied_count", 0) == 2
    assert result["canon_modified"] is True
