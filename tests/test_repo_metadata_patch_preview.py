"""S0147 tests for dry-run repo metadata patch preview."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import build_repo_metadata_patch_preview as preview  # noqa: E402


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _row(
    tid: str,
    title: str,
    category: str,
    *,
    authority: str = "unknown",
    current: str = "false",
    risk: str = "low",
    confidence: str = "high",
    path: str = "",
    family: str = "artefacto_repositorio",
    lifecycle: str = "",
    kind: str = "source_code",
) -> dict:
    return {
        "id": tid,
        "title": title,
        "diagnostic_category": category,
        "candidate_authority_level": authority,
        "candidate_is_current_repo_artifact": current,
        "risk_level": risk,
        "confidence": confidence,
        "candidate_repo_path": path,
        "candidate_repo_directory": str(Path(path).parent) if path else "",
        "candidate_repo_extension": Path(path).suffix if path else "",
        "candidate_repo_artifact_kind": kind,
        "candidate_repo_lifecycle_state": lifecycle,
        "candidate_artifact_family": family,
        "candidate_content_sha256": f"sha-{tid}",
        "canon_content_sha256": f"canon-sha-{tid}",
        "content_comparison": "exact_match" if current == "true" else "not_current",
    }


def _canon_row(tid: str, title: str, family: str = "unknown") -> dict:
    return {
        "id": tid,
        "title": title,
        "source_fields": {"artifact_family": family},
        "text": title,
    }


def _run(tmp_path: Path, rows: list[dict], canon_rows: list[dict], *, out_name: str = "out") -> dict:
    classification = _write_jsonl(tmp_path / "s0146" / "classification.jsonl", rows)
    metadata_contract = tmp_path / "s0146" / "metadata_contract.md"
    metadata_contract.write_text("# contract\n", encoding="utf-8")
    canon = _write_jsonl(tmp_path / "canon" / "tiddlers_1.jsonl", canon_rows)
    return preview.build_repo_metadata_patch_preview(
        classification=classification,
        metadata_contract=metadata_contract,
        canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
        out_dir=tmp_path / out_name,
        session="S0147",
        dry_run=True,
    )


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _ops(result: dict) -> list[dict]:
    return _jsonl(Path(result["paths"]["patch_preview"]))


def _excluded(result: dict) -> list[dict]:
    return _jsonl(Path(result["paths"]["excluded"]))


def test_reads_s0146_classification_and_generates_dry_run_patch_without_canon_change(tmp_path: Path) -> None:
    rows = [
        _row(
            "current",
            "python_scripts/current.py",
            "repo_snapshot_current",
            authority="current_verified",
            current="true",
            path="python_scripts/current.py",
        ),
        _row(
            "historical",
            "python_scripts/old.py",
            "repo_snapshot_drifted",
            authority="historical_snapshot",
            lifecycle="historical_snapshot",
            path="python_scripts/old.py",
        ),
        _row("review", "needs review", "review_required", risk="high", confidence="requires_human_review"),
    ]
    canon_rows = [
        _canon_row("current", "python_scripts/current.py", "unknown"),
        _canon_row("historical", "python_scripts/old.py", "tiddler_tecnico"),
        _canon_row("review", "needs review", "unknown"),
    ]
    canon_path = _write_jsonl(tmp_path / "canon_before" / "tiddlers_1.jsonl", canon_rows)
    canon_before = canon_path.read_text(encoding="utf-8")
    classification = _write_jsonl(tmp_path / "s0146" / "classification.jsonl", rows)
    metadata_contract = tmp_path / "s0146" / "metadata_contract.md"
    metadata_contract.write_text("# contract\n", encoding="utf-8")

    result = preview.build_repo_metadata_patch_preview(
        classification=classification,
        metadata_contract=metadata_contract,
        canon_glob=str(canon_path.parent / "tiddlers_*.jsonl"),
        out_dir=tmp_path / "out",
        session="S0147",
        dry_run=True,
    )

    assert canon_path.read_text(encoding="utf-8") == canon_before
    summary = result["summary"]
    assert summary["classification_records_read"] == 3
    assert summary["patch_operations_generated"] == 2
    assert summary["excluded_records"] == 1
    assert summary["patch_lane_counts"]["lane_a_current_verified"] == 1
    assert summary["patch_lane_counts"]["lane_b_historical_review"] == 1
    assert summary["patch_lane_counts"]["lane_f_excluded_review_required"] == 1
    assert summary["candidate_relations_generated"] is False
    assert summary["formal_relation_candidates_generated"] is False

    operations = _ops(result)
    current_op = next(op for op in operations if op["target_id"] == "current")
    historical_op = next(op for op in operations if op["target_id"] == "historical")
    assert current_op["batch_id"] == "batch_current_verified"
    assert current_op["fields_preview"]["artifact_family"] == "artefacto_repositorio"
    assert historical_op["batch_id"] == "batch_historical_review"
    assert "artifact_family" not in historical_op["fields_preview"]
    assert _excluded(result)[0]["target_id"] == "review"
    assert all(op["human_approved"] is False for op in operations)
    assert all(op["applied_to_canon"] is False for op in operations)
    assert all(op["dry_run"] is True for op in operations)
    assert all("relations" not in op and "candidate_relations" not in op for op in operations)


def test_generates_required_batches_and_excludes_critical_risk(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [
            _row("cur", "python_scripts/current.py", "repo_snapshot_current", authority="current_verified", current="true", path="python_scripts/current.py"),
            _row("crit", "python_scripts/critical.py", "repo_snapshot_current", authority="current_verified", current="true", risk="critical", path="python_scripts/critical.py"),
        ],
        [_canon_row("cur", "python_scripts/current.py"), _canon_row("crit", "python_scripts/critical.py")],
    )

    batches = json.loads(Path(result["paths"]["review_batches"]).read_text(encoding="utf-8"))
    assert set(batches["batches"]) == set(preview.LANE_BATCHES.values())
    assert batches["batches"]["batch_current_verified"]["record_count"] == 1
    assert batches["batches"]["batch_excluded_review_required"]["record_count"] == 1
    assert all(batch["human_approved"] is False for batch in batches["batches"].values())
    assert all(batch["approval_disabled_in_s0147"] is True for batch in batches["batches"].values())
    assert _excluded(result)[0]["excluded_reason"] == "critical_risk"


def test_preserves_session_family_and_uses_narrative_metadata(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [_row("session", "#### 🌀 Sesión 0146 = demo", "session_or_diagnostic_narrative", authority="narrative_reference")],
        [_canon_row("session", "#### 🌀 Sesión 0146 = demo", "sesion")],
    )

    op = _ops(result)[0]
    assert op["batch_id"] == "batch_narrative_reference"
    assert op["current_artifact_family"] == "sesion"
    assert "artifact_family" not in op["fields_preview"]
    assert op["fields_preview"]["contains_repo_references"] == "true"
    assert op["fields_preview"]["technical_content_role"] == "session_or_diagnostic_narrative"


def test_embedded_and_generated_records_get_auxiliary_metadata_only(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [
            _row("embedded", "Ejemplo tecnico", "embedded_code_block", authority="narrative_reference"),
            _row("generated", "data/out/local/report.json", "generated_output", authority="generated_derivative", kind="generated_output"),
        ],
        [
            _canon_row("embedded", "Ejemplo tecnico", "unknown"),
            _canon_row("generated", "data/out/local/report.json", "unknown"),
        ],
    )

    by_id = {op["target_id"]: op for op in _ops(result)}
    assert by_id["embedded"]["fields_preview"]["contains_code"] == "true"
    assert by_id["embedded"]["fields_preview"]["technical_content_role"] == "embedded_code_block"
    assert "artifact_family" not in by_id["embedded"]["fields_preview"]
    assert by_id["generated"]["fields_preview"]["technical_content_role"] == "generated_output"
    assert "artifact_family" not in by_id["generated"]["fields_preview"]


def test_patch_preview_and_patch_hash_are_deterministic(tmp_path: Path) -> None:
    rows = [
        _row("cur", "python_scripts/current.py", "repo_snapshot_current", authority="current_verified", current="true", path="python_scripts/current.py"),
        _row("narr", "#### 🌀 Diagnóstico de sesión 0146 = demo", "session_or_diagnostic_narrative", authority="narrative_reference"),
    ]
    canon_rows = [_canon_row("cur", "python_scripts/current.py"), _canon_row("narr", "diag", "diagnostico_de_sesion")]
    first = _run(tmp_path, rows, canon_rows, out_name="out1")
    second = _run(tmp_path, rows, canon_rows, out_name="out2")

    first_patch = Path(first["paths"]["patch_preview"]).read_text(encoding="utf-8")
    second_patch = Path(second["paths"]["patch_preview"]).read_text(encoding="utf-8")
    assert first_patch == second_patch
    assert first["hashes"]["patch_preview_sha256"] == second["hashes"]["patch_preview_sha256"]
