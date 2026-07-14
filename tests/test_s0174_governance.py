"""S0174 governance, writer-boundary and reversible sandbox checks."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "src" / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from rag_derivative_writers import (  # noqa: E402
    ProductiveWriteBlocked,
    promote_staging_transaction,
    rollback_productive_transaction,
    snapshot_productive_derivatives,
)
from s0174_governance import build_governance_gate, build_producer_inventory  # noqa: E402


def test_s0174_governance_gate_is_pass_but_authorization_pending() -> None:
    gate = json.loads(
        (REPO_ROOT / "data/out/local/audit/rag_derivation/s0174/governance_gate_report.json").read_text()
    )
    assert gate["status"] == "pass"
    assert gate["authorization_state"] == "authorization_pending"
    assert gate["planned_families"] == ["enriched", "ai", "microsoft_copilot"]


def test_inventory_has_one_authoritative_writer() -> None:
    inventory = build_producer_inventory()
    assert inventory["authoritative_producer"] == "src/python_scripts/derive_layers.py"
    assert inventory["authoritative_writer"] == "src/python_scripts/rag_derivative_writers.py"
    assert inventory["parallel_productive_writers"] == []


def test_s0174_writer_requires_explicit_scoped_authorization(tmp_path: Path) -> None:
    with pytest.raises(ProductiveWriteBlocked, match="explicit authorization phrase"):
        promote_staging_transaction(
            staging_root=tmp_path / "staging",
            rollback_root=tmp_path / "rollback",
            authorization={"session_id": "S0174", "authorized_by": "human_operator"},
            planned_families=["enriched"],
            transaction_journal=tmp_path / "journal.jsonl",
            receipt_path=tmp_path / "receipt.json",
            expected_session_id="S0174",
            required_authorization_phrase=None,
            productive_families={"enriched": tmp_path / "productive" / "enriched"},
        )


def test_s0174_sandbox_write_and_real_rollback(tmp_path: Path) -> None:
    families = {name: tmp_path / "productive" / name for name in ("enriched", "ai", "microsoft_copilot")}
    staging = tmp_path / "staging"
    for family, target in families.items():
        target.mkdir(parents=True)
        (target / "old.txt").write_text(f"old-{family}")
        source = staging / family
        source.mkdir(parents=True)
        (source / "new.txt").write_text(f"new-{family}")
    manifest_path = staging / "staging_manifest.json"
    manifest_path.write_text("{}")
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    rollback = tmp_path / "rollback"
    snapshot_productive_derivatives(rollback, productive_families=families, session_id="S0174")
    promote_staging_transaction(
        staging_root=staging,
        rollback_root=rollback,
        authorization={
            "session_id": "S0174",
            "authorized_by": "human_operator",
            "authorization_phrase": "AUTHORIZE S0174",
            "staging_manifest_hash": digest,
            "planned_families": list(families),
        },
        planned_families=list(families),
        transaction_journal=tmp_path / "journal.jsonl",
        receipt_path=tmp_path / "receipt.json",
        expected_session_id="S0174",
        required_authorization_phrase=None,
        staging_manifest_path=manifest_path,
        staging_manifest_hash=digest,
        productive_families=families,
    )
    report = rollback_productive_transaction(
        rollback_root=rollback,
        planned_families=list(families),
        transaction_journal=tmp_path / "journal.jsonl",
        verification_report_path=tmp_path / "rollback-report.json",
        productive_families=families,
        expected_session_id="S0174",
    )
    assert report["status"] == "pass"
    assert all((target / "old.txt").exists() and not (target / "new.txt").exists() for target in families.values())
