"""Regression tests: provenance-only producer-fingerprint drift and
volatile-only validation_report drift must never invalidate an otherwise-
correct READY_FOR_AUTHORIZATION CURRENT bundle, nor block a semantically
equivalent retry-publication at the same (unchanged) identity. A genuinely
currentness-relevant binding, or a real semantic change in
validation_report, must keep failing closed exactly as before.

Fixtures/TMP only; never CURRENT productivo, never Canon, never a write
against real human decisions.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "src" / "python_scripts"
sys.path.insert(0, str(SCRIPTS))

import prepare_current_relational_generation as preparation  # noqa: E402
import current_relation_human_review as human_review  # noqa: E402

from test_generational_decision_preservation import (  # noqa: E402
    _reach_ready_for_authorization_single_candidate,
)


def _published_bundle(paths: preparation.Paths) -> tuple[Path, dict]:
    pointer = preparation.read_json(paths.pointer)
    bundle = Path(pointer["bundle_path"])
    manifest = preparation.read_json(bundle / "bundle_manifest.json")
    return bundle, manifest


def _rewrite_published_manifest(paths: preparation.Paths, bundle: Path, manifest: dict) -> None:
    """Rewrite an already-published bundle_manifest.json and keep the
    pointer's declared bundle_manifest_hash self-consistent -- the same
    surgical-but-honest technique _degrade_published_bundle() established:
    never used against CURRENT productivo, only under tmp_path.
    """
    manifest_path = bundle / "bundle_manifest.json"
    preparation.write_json(manifest_path, manifest)
    new_hash = preparation.sha256_file(manifest_path)
    pointer = preparation.read_json(paths.pointer)
    if Path(str(pointer.get("bundle_path") or "")).resolve() == bundle.resolve():
        pointer["bundle_manifest_hash"] = new_hash
        preparation.write_json(paths.pointer, pointer)


def _manifest_semantic_differences(staged_manifest: dict, existing_manifest: dict) -> list[str]:
    """The exact manifest-level half of what execute()'s retry-collision
    check computes -- reused directly, not reimplemented."""
    exclude = {"artifacts", "created_at", "published_at", "producer_fingerprints"}
    staged_projection = preparation._retry_semantic_value(
        {k: v for k, v in staged_manifest.items() if k not in exclude}
    )
    existing_projection = preparation._retry_semantic_value(
        {k: v for k, v in existing_manifest.items() if k not in exclude}
    )
    return preparation._semantic_projection_differences(
        staged_projection, existing_projection, prefix="manifest",
    )


# --- A: provenance-only producer fingerprint drift is harmless ---------

def test_provenance_only_producer_fingerprint_drift_is_not_a_collision(tmp_path: Path) -> None:
    paths, _source_root, _candidate_id = _reach_ready_for_authorization_single_candidate(tmp_path)
    bundle, manifest = _published_bundle(paths)
    manifest_bytes_before = (bundle / "bundle_manifest.json").read_bytes()

    # Simulate a cosmetic edit to the orchestrator since publish: its
    # recorded provenance fingerprint no longer matches what the file
    # would hash to today. Only the RECORDED (published) side is mutated;
    # producer_bindings() still points at the real, unmodified file.
    tampered = copy.deepcopy(manifest)
    tampered["producer_fingerprints"]["preparation_orchestrator"] = "deadbeef" * 8
    _rewrite_published_manifest(paths, bundle, tampered)

    # Fix 2: status reporting must not flag this or invalidate the bundle.
    status = preparation.read_current_bundle_status(paths.local_root)
    assert status["valid"] is True
    assert status["reason_codes"] == []
    assert status["producer_fingerprint_drift"] == ["preparation_orchestrator"]
    assert status["next_action"] == manifest["next_action"]

    # Fix 1: a staged manifest whose ONLY difference is a freshly
    # recomputed producer_fingerprints (the real, non-tampered value) must
    # not collide with the tampered-but-otherwise-identical published one.
    staged = copy.deepcopy(tampered)
    staged["producer_fingerprints"] = preparation.producer_fingerprints()
    assert staged["producer_fingerprints"]["preparation_orchestrator"] != tampered[
        "producer_fingerprints"
    ]["preparation_orchestrator"]
    assert _manifest_semantic_differences(staged, tampered) == []

    # The published bundle itself was never touched beyond this test's own
    # deliberate manifest rewrite (immutability of everything else).
    assert (bundle / "bundle_manifest.json").read_bytes() != manifest_bytes_before  # our own edit
    assert (bundle / "relation_candidates.jsonl").is_file()


# --- B: a genuinely currentness-relevant binding still blocks ----------

def test_real_binding_drift_still_blocks(tmp_path: Path) -> None:
    paths, _source_root, _candidate_id = _reach_ready_for_authorization_single_candidate(tmp_path)
    canon_before = preparation.canon_snapshot(paths.local_root)["hash"]

    # A genuine live-mirror change unrelated to provenance: the live
    # candidate manifest diverges from what the bundle certified.
    live_path = paths.current_dir / "current_candidate_manifest.json"
    live_content = json.loads(live_path.read_text(encoding="utf-8"))
    live_content["__test_drift_marker__"] = True
    live_path.write_text(json.dumps(live_content), encoding="utf-8")

    status = preparation.read_current_bundle_status(paths.local_root)
    assert status["valid"] is False
    assert "current_bundle_binding_stale:candidate_manifest" in status["reason_codes"]
    assert preparation.canon_snapshot(paths.local_root)["hash"] == canon_before


# --- C: validation_report drifts only in volatile fields ---------------

def test_validation_report_volatile_only_drift_does_not_invalidate(tmp_path: Path) -> None:
    paths, _source_root, _candidate_id = _reach_ready_for_authorization_single_candidate(tmp_path)

    live_path = paths.current_dir / "validation_report.json"
    live_content = preparation.read_json(live_path)
    live_content["generated_at"] = "2099-01-01T00:00:00Z"
    preparation.write_json(live_path, live_content)

    status = preparation.read_current_bundle_status(paths.local_root)
    assert status["valid"] is True
    assert status["reason_codes"] == []


# --- D: validation_report drifts semantically ---------------------------

def test_validation_report_semantic_drift_still_invalidates(tmp_path: Path) -> None:
    paths, _source_root, _candidate_id = _reach_ready_for_authorization_single_candidate(tmp_path)

    live_path = paths.current_dir / "validation_report.json"
    live_content = preparation.read_json(live_path)
    live_content["generated_at"] = "2099-01-01T00:00:00Z"
    live_content["summary"] = dict(live_content["summary"])
    live_content["summary"]["total"] = live_content["summary"]["total"] + 1
    preparation.write_json(live_path, live_content)

    status = preparation.read_current_bundle_status(paths.local_root)
    assert status["valid"] is False
    assert "current_bundle_binding_stale:validation_report" in status["reason_codes"]


# --- E: clean READY_FOR_AUTHORIZATION reproduction ----------------------

def test_ready_for_authorization_bundle_reports_valid_with_conserved_planning(
    tmp_path: Path,
) -> None:
    paths, _source_root, _candidate_id = _reach_ready_for_authorization_single_candidate(tmp_path)
    canon_before = preparation.canon_snapshot(paths.local_root)["hash"]

    status = preparation.read_current_bundle_status(paths.local_root)
    assert status["valid"] is True
    assert status["reason_codes"] == []
    assert status["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    assert status["next_action"] == "AUTHORIZE_CURRENT_RELATIONAL_APPLY"

    planning = status["planning"]
    assert planning["conservation_valid"] is True
    assert planning["effective_pending"] == 0
    assert (
        planning["approved_candidate_representations"]
        == planning["planned_unique_relations"]
        + planning["omitted_duplicate_representations"]
        + planning["unaccounted_approved_representations"]
    )

    assert preparation.canon_snapshot(paths.local_root)["hash"] == canon_before
