from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import repo_metadata_admission_gate as gate  # noqa: E402


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    return path


def patch_row(
    tid: str,
    *,
    title: str,
    batch_id: str,
    lane: str,
    risk: str = "low",
    fields: dict | None = None,
) -> dict:
    return {
        "op_id": f"op_{tid}",
        "target_id": tid,
        "target_title": title,
        "batch_id": batch_id,
        "patch_lane": lane,
        "source_risk_level": risk,
        "fields_preview": fields or {"authority_level": batch_id.removeprefix("batch_")},
        "dry_run": True,
        "applied_to_canon": False,
        "human_approved": False,
    }


def build_s0151_fixture(tmp_path: Path) -> dict[str, Path | str]:
    canon = write_jsonl(
        tmp_path / "canon" / "tiddlers_1.jsonl",
        [
            {"id": "cur", "title": "python_scripts/current.py", "source_fields": {"artifact_family": "unknown"}, "text": "current"},
            {"id": "emb", "title": "#### 🌀 Sesión 0101 = embedded", "source_fields": {"artifact_family": "hipotesis_de_sesion"}, "text": "```py\\nprint(1)\\n```"},
            {"id": "nar", "title": "#### 🌀 Sesión 0102 = narrative", "source_fields": {"artifact_family": "detalles_de_sesion"}, "text": "mentions python_scripts/current.py"},
            {"id": "hist", "title": "README-old", "source_fields": {"artifact_family": "artefacto_repositorio"}, "text": "old"},
            {"id": "gen", "title": "data/out/local/generated.json", "source_fields": {"artifact_family": "artefacto_repositorio"}, "text": "{}"},
            {"id": "excl", "title": "needs review", "source_fields": {"artifact_family": "unknown"}, "text": "review"},
        ],
    )
    canon_glob = str(canon.parent / "tiddlers_*.jsonl")
    patch = tmp_path / "s0151" / "s0151_metadata_patch_preview_refreshed.jsonl"
    rows = [
        patch_row(
            "cur",
            title="python_scripts/current.py",
            batch_id="batch_current_verified",
            lane="lane_a_current_verified",
            fields={"artifact_family": "artefacto_repositorio", "authority_level": "current_verified", "repo_path": "python_scripts/current.py"},
        ),
        patch_row(
            "emb",
            title="#### 🌀 Sesión 0101 = embedded",
            batch_id="batch_embedded_code",
            lane="lane_b_embedded_code",
            risk="high",
            fields={"authority_level": "embedded_code", "technical_content_role": "embedded_code_block"},
        ),
        patch_row(
            "nar",
            title="#### 🌀 Sesión 0102 = narrative",
            batch_id="batch_narrative_reference",
            lane="lane_c_narrative_reference",
            risk="high",
            fields={"authority_level": "narrative_reference", "technical_content_role": "session_or_diagnostic_narrative"},
        ),
        patch_row("hist", title="README-old", batch_id="batch_historical_review", lane="lane_d_historical_review", risk="high"),
        patch_row("gen", title="data/out/local/generated.json", batch_id="batch_generated_derivative", lane="lane_e_generated_derivative"),
        patch_row("excl", title="needs review", batch_id="batch_excluded_review_required", lane="lane_f_excluded_review_required", risk="high"),
    ]
    write_jsonl(patch, rows)

    batches_payload = {
        "schema": "repo-metadata-review-batches/v1",
        "session": "S0151",
        "source_session": "S0150",
        "dry_run": True,
        "applied_to_canon": False,
        "human_approved": False,
        "batches": {},
    }
    labels = {
        "batch_current_verified": "Código vigente verificado",
        "batch_embedded_code": "Código embebido",
        "batch_narrative_reference": "Narrativa técnica",
        "batch_historical_review": "Histórico/divergente",
        "batch_generated_derivative": "Generados",
        "batch_excluded_review_required": "Excluidos",
    }
    for batch_id in sorted({row["batch_id"] for row in rows}):
        batch_rows = [row for row in rows if row["batch_id"] == batch_id]
        batches_payload["batches"][batch_id] = {
            "batch_id": batch_id,
            "batch_label": labels[batch_id],
            "record_count": len(batch_rows),
            "patch_sha256": gate.subset_sha(batch_rows),
            "canon_before_sha256": gate.tree_sha256(canon_glob),
            "risk_profile": {"high": sum(row.get("source_risk_level") == "high" for row in batch_rows)},
            "dry_run": True,
            "applied_to_canon": False,
            "human_approved": False,
        }
    batches = write_json(tmp_path / "s0151" / "s0151_metadata_review_batches_refreshed.json", batches_payload)
    hashes = write_json(
        tmp_path / "s0151" / "s0151_metadata_patch_hashes_refreshed.json",
        {
            "schema": "repo-metadata-patch-hashes/v1",
            "session": "S0151",
            "source_session": "S0150",
            "dry_run": True,
            "applied_to_canon": False,
            "canon_modified": False,
            "canon_before_sha256": gate.tree_sha256(canon_glob),
            "patch_preview_sha256": gate.file_sha256(patch),
            "review_batches_sha256": gate.file_sha256(batches),
            "relations_generated": False,
            "candidate_relations_generated": False,
        },
    )
    refresh_report = write_json(
        tmp_path / "s0151" / "s0151_metadata_refresh_report.json",
        {
            "schema": "repo-metadata-s0151-refresh-report/v1",
            "session": "S0151",
            "operations_preserved": len(rows),
            "operations_blocked": 0,
            "canon_before_sha256_refreshed": gate.tree_sha256(canon_glob),
            "dry_run": True,
            "applied_to_canon": False,
            "canon_modified": False,
        },
    )
    manifest = write_json(
        tmp_path / "latest_metadata_patch_manifest.json",
        {
            "schema": "latest-metadata-patch-manifest/v1",
            "session": "S0151",
            "source_session": "S0150",
            "status": "ready_for_dry_run",
            "canon_before_sha256": gate.tree_sha256(canon_glob),
            "patch_preview": str(patch),
            "review_batches": str(batches),
            "patch_hashes": str(hashes),
            "refresh_report": str(refresh_report),
            "created_at": "2026-06-13T00:00:00Z",
            "dry_run": True,
            "applied_to_canon": False,
            "canon_modified": False,
        },
    )
    return {
        "canon": canon,
        "canon_glob": canon_glob,
        "patch": patch,
        "batches": batches,
        "hashes": hashes,
        "refresh_report": refresh_report,
        "manifest": manifest,
        "out_dir": tmp_path / "admission",
    }
