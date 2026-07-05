"""S0150 tests for non-destructive repo metadata patch refresh."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import repo_metadata_refresh_patch as refresh  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    return path


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def _patch_row(tid: str, *, title: str, batch_id: str = "batch_current_verified", risk: str = "low", fields: dict | None = None) -> dict:
    return {
        "op_id": f"op_{tid}",
        "target_id": tid,
        "target_title": title,
        "batch_id": batch_id,
        "patch_lane": "lane_a_current_verified",
        "source_risk_level": risk,
        "fields_preview": fields or {"authority_level": "current_verified"},
        "dry_run": True,
        "applied_to_canon": False,
        "human_approved": False,
    }


def _fixture(tmp_path: Path) -> dict[str, Path | str]:
    canon = _write_jsonl(
        tmp_path / "canon" / "tiddlers_1.jsonl",
        [
            {"id": "cur", "title": "python_scripts/current.py", "source_fields": {"artifact_family": "unknown"}},
            {"id": "crit", "title": "critical.py", "source_fields": {"artifact_family": "unknown"}},
            {"id": "session", "title": "#### 🌀 Sesión 0101 = session", "source_fields": {"artifact_family": "detalles_de_sesion"}},
        ],
    )
    patch = _write_jsonl(
        tmp_path / "s0147" / "patch.jsonl",
        [
            _patch_row("cur", title="python_scripts/current.py", fields={"artifact_family": "artefacto_repositorio", "authority_level": "current_verified"}),
            _patch_row("missing", title="missing.py"),
            _patch_row("crit", title="critical.py", risk="critical"),
            _patch_row("session", title="#### 🌀 Sesión 0101 = session", fields={"artifact_family": "artefacto_repositorio"}),
        ],
    )
    batches = _write_json(
        tmp_path / "s0147" / "batches.json",
        {
            "schema": "repo-metadata-review-batches/v1",
            "session": "S0147",
            "batches": {
                "batch_current_verified": {
                    "batch_id": "batch_current_verified",
                    "record_count": 4,
                    "patch_sha256": "old",
                    "canon_before_sha256": "old-canon",
                }
            },
        },
    )
    hashes = _write_json(
        tmp_path / "s0147" / "hashes.json",
        {
            "schema": "repo-metadata-patch-hashes/v1",
            "session": "S0147",
            "canon_before_sha256": "old-canon",
            "patch_preview_sha256": "old-patch",
            "review_batches_sha256": "old-batches",
        },
    )
    return {
        "canon": canon,
        "canon_glob": str(canon.parent / "tiddlers_*.jsonl"),
        "patch": patch,
        "batches": batches,
        "hashes": hashes,
        "out": tmp_path / "s0150",
    }


def test_refresh_recalculates_canon_hash_and_preserves_safe_operations(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)
    canon = fx["canon"]
    assert isinstance(canon, Path)
    before = canon.read_text(encoding="utf-8")

    report = refresh.refresh_metadata_patch(
        patch_preview=fx["patch"],
        review_batches=fx["batches"],
        patch_hashes=fx["hashes"],
        canon_glob=str(fx["canon_glob"]),
        out_dir=fx["out"],
        session="S0150",
        dry_run=True,
    )

    assert report["canon_before_sha256_old"] == "old-canon"
    assert report["canon_before_sha256_refreshed"] == refresh.tree_sha256(str(fx["canon_glob"]))
    assert report["operations_preserved"] == 1
    assert report["operations_blocked"] == 3
    assert report["canon_modified"] is False
    assert canon.read_text(encoding="utf-8") == before


def test_refresh_blocks_missing_critical_and_family_conflict(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)

    refresh.refresh_metadata_patch(
        patch_preview=fx["patch"],
        review_batches=fx["batches"],
        patch_hashes=fx["hashes"],
        canon_glob=str(fx["canon_glob"]),
        out_dir=fx["out"],
        session="S0150",
        dry_run=True,
    )
    blocked = refresh.read_jsonl(refresh.refreshed_paths(fx["out"])["blocked"])
    reasons = {row["target_id"]: set(row["block_reasons"]) for row in blocked}

    assert "target_missing" in reasons["missing"]
    assert "critical_risk" in reasons["crit"]
    assert "artifact_family_session_preserved" in reasons["session"]


def test_refresh_recalculates_batch_hashes_and_writes_valid_outputs(tmp_path: Path) -> None:
    fx = _fixture(tmp_path)

    refresh.refresh_metadata_patch(
        patch_preview=fx["patch"],
        review_batches=fx["batches"],
        patch_hashes=fx["hashes"],
        canon_glob=str(fx["canon_glob"]),
        out_dir=fx["out"],
        session="S0150",
        dry_run=True,
    )
    paths = refresh.refreshed_paths(fx["out"])
    ready = refresh.read_jsonl(paths["patch_preview"])
    batches = refresh.read_json(paths["review_batches"])
    hashes = refresh.read_json(paths["patch_hashes"])

    assert batches["batches"]["batch_current_verified"]["record_count"] == 1
    assert batches["batches"]["batch_current_verified"]["patch_sha256"] == refresh.subset_sha(ready)
    assert hashes["patch_preview_sha256"] == refresh.file_sha256(paths["patch_preview"])
    assert hashes["review_batches_sha256"] == refresh.file_sha256(paths["review_batches"])
    assert hashes["relations_generated"] is False
    assert hashes["candidate_relations_generated"] is False
