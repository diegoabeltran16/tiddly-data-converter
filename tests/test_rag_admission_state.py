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
