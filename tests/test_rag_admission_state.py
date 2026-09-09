"""Regression coverage for persisted, resumable productive rollback failures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "src" / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import rag_admission_state as admission  # noqa: E402
from rag_derivative_writers import snapshot_productive_derivatives  # noqa: E402


def _families(tmp_path: Path) -> tuple[dict[str, Path], Path]:
    families = {name: tmp_path / "productive" / name for name in admission.PRODUCTIVE_FAMILIES}
    for family, root in families.items():
        root.mkdir(parents=True)
        (root / "old.txt").write_text(f"old-{family}")
        (root / "nested").mkdir()
        (root / "nested" / "old-2.txt").write_text(f"old-2-{family}")
    snapshot = tmp_path / "snapshot"
    snapshot_productive_derivatives(snapshot, productive_families=families, session_id="S0175")
    return families, snapshot


def test_recorded_partial_rollback_failure_is_persisted(monkeypatch, tmp_path: Path) -> None:
    families, snapshot = _families(tmp_path)
    # Simulate exactly the observed post-failure surface: first family restored,
    # later families still at trial state.
    for family, root in families.items():
        if family != "enriched":
            (root / "old.txt").unlink()
            (root / "trial.txt").write_text(f"trial-{family}")
    error_path = tmp_path / "audit" / "rollback_error_report.json"
    monkeypatch.setattr(admission, "PRODUCTIVE_ROOTS", families)
    monkeypatch.setattr(admission, "TRIAL_SNAPSHOT", snapshot)
    monkeypatch.setattr(admission, "ROLLBACK_ERROR", error_path)
    monkeypatch.setattr(admission, "write_state", lambda: {})

    payload = admission.record_observed_rollback_error()

    assert payload["status"] == "error"
    assert payload["partial_effect"] == "confirmed"
    assert payload["affected_families"]["enriched"] == "snapshot_state"
    assert payload["affected_families"]["ai"] == "trial_state"
    assert json.loads(error_path.read_text())["next_action"] == "FIX_AND_RESUME_TRIAL_ROLLBACK"


def test_runtime_rollback_exception_persists_error_and_reraises(monkeypatch, tmp_path: Path) -> None:
    families, snapshot = _families(tmp_path)
    auth_path = tmp_path / "audit" / "trial_authorization.json"
    auth_path.parent.mkdir(parents=True)
    auth_path.write_text(json.dumps({"protected_before": admission._protected_snapshot()}))
    error_path = tmp_path / "audit" / "rollback_error_report.json"
    monkeypatch.setattr(admission, "PRODUCTIVE_ROOTS", families)
    monkeypatch.setattr(admission, "TRIAL_SNAPSHOT", snapshot)
    monkeypatch.setattr(admission, "TRIAL_AUTH", auth_path)
    monkeypatch.setattr(admission, "ROLLBACK_ERROR", error_path)
    monkeypatch.setattr(admission, "build_state", lambda: {"next_action": "EXECUTE_TRIAL_ROLLBACK", "verdict": "TRIAL_WRITE_VERIFIED"})
    monkeypatch.setattr(admission, "write_state", lambda: {})
    monkeypatch.setattr(admission, "rollback_productive_transaction", lambda **_kwargs: (_ for _ in ()).throw(TypeError("dict ordering")))

    with pytest.raises(TypeError, match="dict ordering"):
        admission.execute_trial_rollback()

    payload = json.loads(error_path.read_text())
    assert payload["error_type"] == "TypeError"
    assert payload["next_action"] == "FIX_AND_RESUME_TRIAL_ROLLBACK"
    assert payload["resolved"] is False


def test_manifest_change_makes_consumed_trial_authorization_stale(tmp_path: Path) -> None:
    authorization = tmp_path / "trial_authorization.json"
    authorization.write_text(
        json.dumps(
            {
                "operation": "trial_write",
                "staging_manifest_hash": "old-manifest",
                "planned_families": list(admission.PRODUCTIVE_FAMILIES),
                "deletion_policy": "none",
                "authorized_by": "human_operator",
                "consumed": True,
            }
        )
    )
    status, reasons = admission._authorization_status(authorization, "trial_write", "new-manifest")
    assert status == "stale"
    assert reasons == ["staging_manifest_hash_stale"]


def test_expected_canonical_evolution_is_an_explicit_non_blocking_status() -> None:
    assert "equivalent_with_expected_canonical_evolution" in admission.NON_BLOCKING_EQUIVALENCE_STATUSES
    assert "not_equivalent" not in admission.NON_BLOCKING_EQUIVALENCE_STATUSES


def test_validate_trial_blocks_without_a_current_successful_receipt(monkeypatch, tmp_path: Path) -> None:
    manifest = tmp_path / "staging_manifest.json"
    manifest.write_text("{}")
    authorization = tmp_path / "trial_authorization.json"
    authorization.write_text(json.dumps({"authorization_id": "current-authorization"}))
    validation = tmp_path / "current_trial" / "trial_post_write_validation.json"
    monkeypatch.setattr(admission, "STAGING_MANIFEST", manifest)
    monkeypatch.setattr(admission, "TRIAL_AUTH", authorization)
    monkeypatch.setattr(admission, "TRIAL_RECEIPT", tmp_path / "current_trial" / "trial_write_receipt.json")
    monkeypatch.setattr(admission, "TRIAL_VALIDATION", validation)
    monkeypatch.setattr(admission, "build_state", lambda: {"next_action": "EXECUTE_TRIAL_WRITE"})
    monkeypatch.setattr(admission, "write_state", lambda: {})

    with pytest.raises(admission.ProductiveWriteBlocked, match="trial_receipt_absent"):
        admission.validate_write("trial_write")

    report = json.loads(validation.read_text())
    assert report["status"] == "blocked"
    assert report["verdict"] == "TRIAL_VALIDATION_BLOCKED"
    assert report["next_action"] == "EXECUTE_TRIAL_WRITE"


def test_out_of_sequence_validation_preserves_the_successful_trial_report(monkeypatch, tmp_path: Path) -> None:
    authorization = tmp_path / "trial_authorization.json"
    authorization.write_text(json.dumps({"authorization_id": "current-authorization"}))
    validation = tmp_path / "trial_post_write_validation.json"
    validation.write_text(json.dumps({"status": "pass", "evidence": "pre-rollback"}))
    out_of_sequence = tmp_path / "trial_validation_out_of_sequence.json"
    monkeypatch.setattr(admission, "TRIAL_AUTH", authorization)
    monkeypatch.setattr(admission, "TRIAL_RECEIPT", tmp_path / "trial_write_receipt.json")
    monkeypatch.setattr(admission, "TRIAL_VALIDATION", validation)
    monkeypatch.setattr(admission, "TRIAL_VALIDATION_OUT_OF_SEQUENCE", out_of_sequence)
    monkeypatch.setattr(admission, "build_state", lambda: {"next_action": "REQUEST_DEFINITIVE_AUTHORIZATION"})

    with pytest.raises(admission.ProductiveWriteBlocked, match="out of sequence"):
        admission.validate_write("trial_write")

    assert json.loads(validation.read_text()) == {"status": "pass", "evidence": "pre-rollback"}
    assert json.loads(out_of_sequence.read_text())["verdict"] == "TRIAL_VALIDATION_OUT_OF_SEQUENCE"


def test_receipt_attested_recovery_preserves_current_trial_validation(monkeypatch, tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    for family in admission.PRODUCTIVE_FAMILIES:
        target = staging / family
        target.mkdir(parents=True)
        (target / "current.txt").write_text(f"current-{family}")
    manifest = tmp_path / "staging_manifest.json"
    manifest.write_text("{}")
    manifest_hash = admission.hashlib.sha256(manifest.read_bytes()).hexdigest()
    authorization = tmp_path / "trial_authorization.json"
    authorization.write_text(json.dumps({"authorization_id": "current-authorization", "protected_before": {}}))
    receipt = tmp_path / "trial_write_receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "operation": "trial_write",
                "status": "promotion_completed",
                "session_id": admission.ADMISSION_SCOPE_ID,
                "staging_manifest_hash": manifest_hash,
                "authorization_id": "current-authorization",
                "write_manifest": {
                    "operations": [
                        {
                            "family": family,
                            "after_files": [
                                {"relative_path": relative, "sha256": digest}
                                for relative, digest in admission._tree(staging / family).items()
                            ],
                        }
                        for family in admission.PRODUCTIVE_FAMILIES
                    ]
                },
            }
        )
    )
    validation = tmp_path / "trial_post_write_validation.json"
    monkeypatch.setattr(admission, "STAGING_ROOT", staging)
    monkeypatch.setattr(admission, "STAGING_MANIFEST", manifest)
    monkeypatch.setattr(admission, "TRIAL_AUTH", authorization)
    monkeypatch.setattr(admission, "TRIAL_RECEIPT", receipt)
    monkeypatch.setattr(admission, "TRIAL_VALIDATION", validation)
    monkeypatch.setattr(admission, "_assert_protected", lambda _auth: {"canon_mutated": False})
    monkeypatch.setattr(admission, "write_state", lambda: {})

    report = admission.recover_trial_validation_from_receipt()

    assert report["status"] == "pass"
    assert report["receipt_after_files_match_staging"] is True
    assert json.loads(validation.read_text())["authorization_id"] == "current-authorization"


def test_historical_receipt_cannot_satisfy_current_trial_validation() -> None:
    current, reasons = admission._current_trial_receipt(
        {
            "operation": "trial_write",
            "status": "promotion_completed",
            "session_id": "S0175",
            "write_manifest": {"staging_manifest_hash": "historical-manifest"},
        },
        {"authorization_id": "current-authorization"},
        "current-manifest",
        "trial_write",
    )

    assert current is False
    assert "trial_receipt_manifest_mismatch" in reasons
    assert "trial_receipt_authorization_mismatch" in reasons
    assert "trial_receipt_scope_mismatch" in reasons


def test_historical_snapshot_classification_preserves_the_original_path(monkeypatch, tmp_path: Path) -> None:
    families, snapshot = _families(tmp_path)
    receipt = tmp_path / "historical-trial-receipt.json"
    receipt.write_text(json.dumps({"session_id": "S0175", "write_manifest": {"staging_manifest_hash": "historical"}, "status": "promotion_completed"}))
    classification = tmp_path / "classification.json"
    monkeypatch.setattr(admission, "HISTORICAL_TRIAL_SNAPSHOT", snapshot)
    monkeypatch.setattr(admission, "HISTORICAL_TRIAL_RECEIPT", receipt)
    monkeypatch.setattr(admission, "HISTORICAL_TRIAL_VALIDATION", tmp_path / "validation.json")
    monkeypatch.setattr(admission, "HISTORICAL_ROLLBACK_REPORT", tmp_path / "rollback.json")
    monkeypatch.setattr(admission, "HISTORICAL_ROLLBACK_EQUALITY", tmp_path / "equality.json")
    monkeypatch.setattr(admission, "HISTORICAL_TRIAL_CLASSIFICATION", classification)
    monkeypatch.setattr(admission, "TRIAL_SNAPSHOT", tmp_path / "current-trial-snapshot")
    monkeypatch.setattr(admission, "ACTIVE_TRIAL_ROOT", tmp_path / "current-trial-audit")
    monkeypatch.setattr(admission, "PRODUCTIVE_ROOTS", families)

    payload = admission.classify_historical_trial_snapshot()

    assert payload["historical_snapshot"]["path"] == str(snapshot)
    assert payload["historical_snapshot"]["reusable_for_current_manifest"] is False
    assert payload["relocation_performed"] is False
    assert payload["productive_surfaces_mutated"] is False
    assert json.loads(classification.read_text())["historical_snapshot"]["files_manifest"] > 0


def test_audit_index_is_read_only_and_reports_absent_evidence(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(admission, "FINAL_MANIFEST", tmp_path / "final.json")
    monkeypatch.setattr(admission, "TRIAL_AUTH", tmp_path / "trial-auth.json")
    monkeypatch.setattr(admission, "TRIAL_RECEIPT", tmp_path / "trial-receipt.json")
    monkeypatch.setattr(admission, "TRIAL_VALIDATION", tmp_path / "trial-validation.json")
    monkeypatch.setattr(admission, "ROLLBACK_REPORT", tmp_path / "rollback.json")
    monkeypatch.setattr(admission, "ROLLBACK_EQUALITY", tmp_path / "equality.json")
    monkeypatch.setattr(admission, "DEFINITIVE_AUTH", tmp_path / "definitive-auth.json")
    monkeypatch.setattr(admission, "DEFINITIVE_RECEIPT", tmp_path / "definitive-receipt.json")
    monkeypatch.setattr(admission, "DEFINITIVE_VALIDATION", tmp_path / "definitive-validation.json")
    monkeypatch.setattr(admission, "EQUIVALENCE_REPORT", tmp_path / "equivalence.json")
    monkeypatch.setattr(admission, "GOVERNANCE_GATE", tmp_path / "governance.json")
    monkeypatch.setattr(admission, "TRIAL_SNAPSHOT", tmp_path / "active-snapshot")
    monkeypatch.setattr(admission, "ARCHIVED_TRIAL_ROOT", tmp_path / "archived")
    monkeypatch.setattr(admission, "HISTORICAL_TRIAL_SNAPSHOT", tmp_path / "legacy")
    monkeypatch.setattr(admission, "build_state", lambda: {"warnings": [], "equivalence": {"status": "absent"}, "governance_gate": {"status": "absent"}, "verdict": "NO_STAGING", "next_action": "UPDATE_STAGING"})
    monkeypatch.setattr(admission, "resolve_equivalence_baseline", lambda: (tmp_path / "baseline", None, "historical_bootstrap_baseline"))
    monkeypatch.setattr(admission, "_protected_snapshot", lambda: {"canon_hash": "canon", "remote_mutated": False})

    payload = admission.build_audit_index()

    assert payload["read_only"] is True
    assert payload["trial"]["receipt"]["status"] == "absent"
    assert "baseline:historical_fallback" in payload["warnings"]
    assert not any(tmp_path.iterdir())


def test_verified_rollback_archives_snapshot_and_frees_active_slot(monkeypatch, tmp_path: Path) -> None:
    snapshot = tmp_path / "active"
    for family in admission.PRODUCTIVE_FAMILIES:
        target = snapshot / family
        target.mkdir(parents=True)
        (target / "before.txt").write_text(f"before-{family}")
    receipt = tmp_path / "receipt.json"
    receipt.write_text("{}")
    archived = tmp_path / "archived"
    monkeypatch.setattr(admission, "TRIAL_SNAPSHOT", snapshot)
    monkeypatch.setattr(admission, "ARCHIVED_TRIAL_ROOT", archived)
    monkeypatch.setattr(admission, "TRIAL_RECEIPT", receipt)

    result = admission.archive_verified_trial_snapshot(
        {"authorization_id": "human-1"},
        {"staging_manifest_hash": "a" * 64},
        {"status": "pass", "state_equal": True, "mismatches": []},
    )

    assert result["snapshot_state"] == "archived"
    assert result["reusable"] is False
    assert not snapshot.exists()
    assert (archived / ("a" * 16) / "archive_manifest.json").exists()


# --- BLOCKER EN PROMOCION DEFINITIVA: historical/current snapshot collision -
#
# A CURRENT ``promote-definitive`` collided with a fixed, unscoped
# ``definitive_rollback_snapshot`` path left over from a prior (S0180-era)
# definitive promotion, and ``validate-definitive`` then read that same
# stale receipt and reported it with trial-flavored reason codes. Fixed by
# giving definitive promotion the same historical/active evidence
# separation trial already has, scoping the CURRENT snapshot by exactly
# (staging_manifest_hash, authorization_id) via ``_definitive_snapshot_path``,
# and prefixing receipt-check reason codes by the operation actually being
# validated.


from typing import Any


def _definitive_fixture(
    monkeypatch,
    tmp_path: Path,
    *,
    next_action: str = "EXECUTE_DEFINITIVE_PROMOTION",
    manifest_hash: str = "manifest-current",
    authorization_id: str = "auth-current",
    consumed: bool = False,
) -> dict[str, Any]:
    """Wire execute_write("definitive_promotion") to isolated tmp_path state,

    stubbing the underlying writer primitives so no real productive family
    is ever touched (mirrors how the existing trial-rollback tests stub
    ``rollback_productive_transaction`` rather than calling it for real).
    """

    auth_path = tmp_path / "definitive_authorization.json"
    auth_path.write_text(
        json.dumps(
            {
                "authorization_id": authorization_id,
                "operation": "definitive_promotion",
                "staging_manifest_hash": manifest_hash,
                "protected_before": admission._protected_snapshot(),
                "consumed": consumed,
            }
        )
    )
    receipt_path = tmp_path / "current_definitive" / "definitive_promotion_receipt.json"
    journal_path = tmp_path / "current_definitive" / "definitive_transaction_journal.jsonl"
    snapshot_root = tmp_path / "definitive_rollback_snapshots"

    monkeypatch.setattr(admission, "DEFINITIVE_AUTH", auth_path)
    monkeypatch.setattr(admission, "DEFINITIVE_RECEIPT", receipt_path)
    monkeypatch.setattr(admission, "DEFINITIVE_JOURNAL", journal_path)
    monkeypatch.setattr(admission, "DEFINITIVE_SNAPSHOT_ROOT", snapshot_root)
    monkeypatch.setattr(admission, "build_state", lambda: {"next_action": next_action, "staging": {"manifest_hash": manifest_hash}})
    monkeypatch.setattr(admission, "write_state", lambda: {})

    def fake_snapshot(snapshot_root_arg, *, productive_families=None, session_id="S0173"):
        del productive_families
        target = Path(snapshot_root_arg)
        if target.exists() and any(target.iterdir()):
            raise admission.ProductiveWriteBlocked(f"rollback snapshot is not empty: {target}")
        target.mkdir(parents=True, exist_ok=True)
        return {"schema_version": "rollback-manifest/v1", "session_id": session_id, "created_at": admission._now(), "files": []}

    promote_calls: list[dict[str, Any]] = []

    def fake_promote(**kwargs):
        promote_calls.append(kwargs)
        return {
            "schema_version": "productive-regeneration-receipt/v1",
            "status": "promotion_completed",
            "session_id": admission.ADMISSION_SCOPE_ID,
            "rollback_snapshot": str(kwargs["rollback_root"]),
            "write_manifest": {"staging_manifest_hash": kwargs.get("staging_manifest_hash")},
        }

    monkeypatch.setattr(admission, "snapshot_productive_derivatives", fake_snapshot)
    monkeypatch.setattr(admission, "promote_staging_transaction", fake_promote)

    return {
        "auth_path": auth_path,
        "receipt_path": receipt_path,
        "snapshot_root": snapshot_root,
        "promote_calls": promote_calls,
    }


# --- 1. historical definitive snapshot present -> CURRENT promotion proceeds


def test_historical_definitive_snapshot_present_does_not_block_current_promotion(monkeypatch, tmp_path: Path) -> None:
    historical = tmp_path / "historical_definitive_rollback_snapshot"
    (historical / "enriched").mkdir(parents=True)
    (historical / "enriched" / "old.txt").write_text("historical evidence")
    monkeypatch.setattr(admission, "HISTORICAL_DEFINITIVE_SNAPSHOT", historical)

    fixture = _definitive_fixture(monkeypatch, tmp_path)
    receipt = admission.execute_write("definitive_promotion")

    assert receipt["status"] == "promotion_completed"
    # The historical evidence is untouched -- a different, scoped path was used.
    assert (historical / "enriched" / "old.txt").read_text() == "historical evidence"
    assert str(historical) not in receipt["rollback_snapshot"]
    assert receipt["rollback_snapshot"].startswith(str(fixture["snapshot_root"]))


# --- 2. historical definitive evidence can never satisfy a CURRENT check ---


def test_historical_definitive_receipt_never_satisfies_current_manifest_check() -> None:
    historical_receipt = {
        "operation": "definitive_promotion",
        "status": "promotion_completed",
        "session_id": admission.ADMISSION_SCOPE_ID,
        "authorization_id": "historical-auth",
        "write_manifest": {"staging_manifest_hash": "historical-manifest"},
    }
    current, reasons = admission._current_trial_receipt(
        historical_receipt, {"authorization_id": "current-auth"}, "current-manifest", "definitive_promotion"
    )

    assert current is False
    assert "definitive_receipt_manifest_mismatch" in reasons
    assert "definitive_receipt_authorization_mismatch" in reasons


# --- 3. CURRENT definitive snapshot is scoped by manifest AND authorization


def test_current_definitive_snapshot_is_scoped_by_manifest_and_authorization() -> None:
    a = admission._definitive_snapshot_path("hash-a", "auth-1")
    b = admission._definitive_snapshot_path("hash-b", "auth-1")
    c = admission._definitive_snapshot_path("hash-a", "auth-2")

    assert len({a, b, c}) == 3
    assert "hash-a" in a.parts and "auth-1" in a.parts
    assert "hash-b" in b.parts
    assert "auth-2" in c.parts


# --- 4. the same CURRENT snapshot can never be overwritten/reused ---------


def test_same_current_definitive_snapshot_cannot_be_overwritten(monkeypatch, tmp_path: Path) -> None:
    _definitive_fixture(monkeypatch, tmp_path, manifest_hash="manifest-x", authorization_id="auth-x")
    first = admission.execute_write("definitive_promotion")
    assert first["status"] == "promotion_completed"

    # Simulate a retry of the exact same (manifest, authorization) pair --
    # e.g. option 11 invoked twice, or a stale operator script re-running.
    auth, _ = admission._read(admission.DEFINITIVE_AUTH)
    auth["consumed"] = False
    admission._write(admission.DEFINITIVE_AUTH, auth)

    with pytest.raises(admission.ProductiveWriteBlocked, match="already contains evidence"):
        admission.execute_write("definitive_promotion")


# --- 5. a stale staging manifest blocks the definitive authorization ------


def test_stale_manifest_blocks_definitive_authorization(tmp_path: Path) -> None:
    authorization = tmp_path / "definitive_authorization.json"
    authorization.write_text(
        json.dumps(
            {
                "operation": "definitive_promotion",
                "staging_manifest_hash": "old-manifest",
                "planned_families": list(admission.PRODUCTIVE_FAMILIES),
                "deletion_policy": "none",
                "authorized_by": "human_operator",
                "consumed": False,
            }
        )
    )
    status, reasons = admission._authorization_status(authorization, "definitive_promotion", "new-manifest")
    assert status == "stale"
    assert reasons == ["staging_manifest_hash_stale"]


# --- 6. a receipt bound to the wrong authorization blocks ------------------


def test_wrong_authorization_id_blocks_receipt_currentness() -> None:
    receipt = {
        "operation": "definitive_promotion",
        "status": "promotion_completed",
        "session_id": admission.ADMISSION_SCOPE_ID,
        "authorization_id": "someone-elses-authorization",
        "staging_manifest_hash": "manifest-current",
    }
    current, reasons = admission._current_trial_receipt(
        receipt, {"authorization_id": "auth-current"}, "manifest-current", "definitive_promotion"
    )
    assert current is False
    assert reasons == ["definitive_receipt_authorization_mismatch"]


# --- 7. failure before write leaves the definitive authorization unconsumed


def test_failure_before_write_leaves_definitive_authorization_unconsumed(monkeypatch, tmp_path: Path) -> None:
    fixture = _definitive_fixture(monkeypatch, tmp_path, manifest_hash="manifest-y", authorization_id="auth-y")
    # Pre-populate the exact scoped path this call will target, so the
    # collision guard fires before any write happens.
    collision_path = admission._definitive_snapshot_path("manifest-y", "auth-y")
    collision_path.mkdir(parents=True)
    (collision_path / "leftover.txt").write_text("stale evidence from an aborted attempt")

    with pytest.raises(admission.ProductiveWriteBlocked, match="already contains evidence"):
        admission.execute_write("definitive_promotion")

    auth, _ = admission._read(fixture["auth_path"])
    assert auth.get("consumed") is not True
    assert fixture["promote_calls"] == []


# --- 8. productive state is unchanged after a pre-write failure -----------


def test_productive_state_unchanged_after_pre_write_failure(monkeypatch, tmp_path: Path) -> None:
    families, _ = _families(tmp_path)
    before = {name: admission._tree(root) for name, root in families.items()}
    monkeypatch.setattr(admission, "PRODUCTIVE_ROOTS", families)
    fixture = _definitive_fixture(monkeypatch, tmp_path, manifest_hash="manifest-z", authorization_id="auth-z")
    collision_path = admission._definitive_snapshot_path("manifest-z", "auth-z")
    collision_path.mkdir(parents=True)
    (collision_path / "leftover.txt").write_text("stale")

    with pytest.raises(admission.ProductiveWriteBlocked):
        admission.execute_write("definitive_promotion")

    after = {name: admission._tree(root) for name, root in families.items()}
    assert before == after
    assert fixture["promote_calls"] == []


# --- 9. validate-definitive selects the CURRENT definitive receipt only ---


def test_validate_definitive_selects_current_receipt_only(monkeypatch, tmp_path: Path) -> None:
    manifest = tmp_path / "staging_manifest.json"
    manifest.write_text("{}")
    manifest_hash = admission.hashlib.sha256(manifest.read_bytes()).hexdigest()
    authorization = tmp_path / "definitive_authorization.json"
    authorization.write_text(json.dumps({"authorization_id": "current-auth", "protected_before": admission._protected_snapshot()}))
    current_receipt = tmp_path / "current_definitive" / "definitive_promotion_receipt.json"
    current_receipt.parent.mkdir(parents=True)
    current_receipt.write_text(
        json.dumps(
            {
                "operation": "definitive_promotion",
                "status": "promotion_completed",
                "session_id": admission.ADMISSION_SCOPE_ID,
                "staging_manifest_hash": manifest_hash,
                "authorization_id": "current-auth",
            }
        )
    )
    historical_receipt = tmp_path / "historical_definitive_promotion_receipt.json"
    historical_receipt.write_text(
        json.dumps(
            {
                "operation": "definitive_promotion",
                "status": "promotion_completed",
                "session_id": admission.ADMISSION_SCOPE_ID,
                "staging_manifest_hash": "a-completely-different-historical-manifest",
                "authorization_id": "historical-auth",
            }
        )
    )
    validation = tmp_path / "current_definitive" / "definitive_post_write_validation.json"
    monkeypatch.setattr(admission, "STAGING_MANIFEST", manifest)
    monkeypatch.setattr(admission, "DEFINITIVE_AUTH", authorization)
    monkeypatch.setattr(admission, "DEFINITIVE_RECEIPT", current_receipt)
    monkeypatch.setattr(admission, "HISTORICAL_DEFINITIVE_RECEIPT", historical_receipt)
    monkeypatch.setattr(admission, "DEFINITIVE_VALIDATION", validation)
    monkeypatch.setattr(admission, "build_post_write_validation", lambda **_kwargs: {"status": "pass"})
    monkeypatch.setattr(admission, "_assert_protected", lambda _auth: {"canon_mutated": False, "relations_mutated": False, "reverse_html_mutated": False, "remote_mutated": False})
    monkeypatch.setattr(admission, "write_state", lambda: {})

    report = admission.validate_write("definitive_promotion")

    assert report["status"] == "pass"
    assert report["receipt_checks"]["current"] is True


# --- 10. the historical definitive receipt is never reusable for validation


def test_historical_definitive_receipt_is_nonreusable_for_validation(monkeypatch, tmp_path: Path) -> None:
    manifest = tmp_path / "staging_manifest.json"
    manifest.write_text("{}")
    authorization = tmp_path / "definitive_authorization.json"
    authorization.write_text(json.dumps({"authorization_id": "current-auth"}))
    # Only the historical receipt exists, at the OLD fixed path -- the
    # active DEFINITIVE_RECEIPT points elsewhere and is absent.
    historical_receipt = tmp_path / "historical_definitive_promotion_receipt.json"
    historical_receipt.write_text(
        json.dumps(
            {
                "operation": "definitive_promotion",
                "status": "promotion_completed",
                "session_id": admission.ADMISSION_SCOPE_ID,
                "staging_manifest_hash": "historical-manifest",
                "authorization_id": "historical-auth",
            }
        )
    )
    monkeypatch.setattr(admission, "STAGING_MANIFEST", manifest)
    monkeypatch.setattr(admission, "DEFINITIVE_AUTH", authorization)
    monkeypatch.setattr(admission, "DEFINITIVE_RECEIPT", tmp_path / "current_definitive" / "definitive_promotion_receipt.json")
    monkeypatch.setattr(admission, "HISTORICAL_DEFINITIVE_RECEIPT", historical_receipt)
    monkeypatch.setattr(admission, "write_state", lambda: {})

    with pytest.raises(admission.ProductiveWriteBlocked, match="definitive_receipt_absent"):
        admission.validate_write("definitive_promotion")


# --- 11. a missing CURRENT definitive receipt gives the correct reason ----


def test_missing_current_definitive_receipt_gives_correct_reason(monkeypatch, tmp_path: Path) -> None:
    manifest = tmp_path / "staging_manifest.json"
    manifest.write_text("{}")
    authorization = tmp_path / "definitive_authorization.json"
    authorization.write_text(json.dumps({"authorization_id": "current-auth"}))
    validation = tmp_path / "current_definitive" / "definitive_post_write_validation.json"
    monkeypatch.setattr(admission, "STAGING_MANIFEST", manifest)
    monkeypatch.setattr(admission, "DEFINITIVE_AUTH", authorization)
    monkeypatch.setattr(admission, "DEFINITIVE_RECEIPT", tmp_path / "current_definitive" / "definitive_promotion_receipt.json")
    monkeypatch.setattr(admission, "DEFINITIVE_VALIDATION", validation)
    monkeypatch.setattr(admission, "write_state", lambda: {})

    with pytest.raises(admission.ProductiveWriteBlocked, match="definitive_receipt_absent"):
        admission.validate_write("definitive_promotion")

    report = json.loads(validation.read_text())
    assert report["verdict"] == "DEFINITIVE_VALIDATION_BLOCKED"
    assert "definitive_receipt_absent" in report["receipt_checks"]["reasons"]


# --- 15. Canon / relations / reverse_html / remote stay protected ---------


def test_assert_protected_flags_canon_and_relations_and_reverse_html_mutation(monkeypatch) -> None:
    before = {"canon_hash": "c1", "relations": {"a": "1"}, "reverse_html": {"b": "2"}}
    after_canon_mutated = {"canon_hash": "c2", "relations": {"a": "1"}, "reverse_html": {"b": "2"}}
    after_relations_mutated = {"canon_hash": "c1", "relations": {"a": "2"}, "reverse_html": {"b": "2"}}
    after_reverse_html_mutated = {"canon_hash": "c1", "relations": {"a": "1"}, "reverse_html": {"b": "3"}}

    monkeypatch.setattr(admission, "_protected_snapshot", lambda: after_canon_mutated)
    result = admission._assert_protected({"protected_before": before})
    assert result == {"canon_mutated": True, "relations_mutated": False, "reverse_html_mutated": False, "remote_mutated": False}

    monkeypatch.setattr(admission, "_protected_snapshot", lambda: after_relations_mutated)
    result = admission._assert_protected({"protected_before": before})
    assert result == {"canon_mutated": False, "relations_mutated": True, "reverse_html_mutated": False, "remote_mutated": False}

    monkeypatch.setattr(admission, "_protected_snapshot", lambda: after_reverse_html_mutated)
    result = admission._assert_protected({"protected_before": before})
    assert result == {"canon_mutated": False, "relations_mutated": False, "reverse_html_mutated": True, "remote_mutated": False}

    monkeypatch.setattr(admission, "_protected_snapshot", lambda: before)
    result = admission._assert_protected({"protected_before": before})
    assert result == {"canon_mutated": False, "relations_mutated": False, "reverse_html_mutated": False, "remote_mutated": False}


def test_governed_productive_manifest_is_preferred_only_when_family_hashes_bind(monkeypatch, tmp_path: Path) -> None:
    productive = {name: tmp_path / "productive" / name for name in admission.PRODUCTIVE_FAMILIES}
    for name, root in productive.items():
        root.mkdir(parents=True)
        (root / "record.txt").write_text(name)
    final = tmp_path / "productive-manifest.json"
    final.write_text(json.dumps({
        "status": "admitted",
        "families": {
            name: {"hash": admission.hashlib.sha256(json.dumps(admission._tree(root), sort_keys=True).encode()).hexdigest()}
            for name, root in productive.items()
        },
    }))
    monkeypatch.setattr(admission, "PRODUCTIVE_ROOTS", productive)
    monkeypatch.setattr(admission, "LOCAL_ROOT", tmp_path / "local")
    monkeypatch.setattr(admission, "FINAL_MANIFEST", final)

    root, manifest, source = admission.resolve_equivalence_baseline()

    assert root == tmp_path / "local"
    assert manifest == final
    assert source == "last_admitted_productive_manifest"
