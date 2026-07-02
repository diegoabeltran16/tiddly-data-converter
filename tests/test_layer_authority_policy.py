from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python_scripts"))

from layer_authority_policy import coverage_state, final_evidence_allowed, observed_metadata, relation_status
from validate_layer_authority import render_human, validate_layers


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _fixture(tmp_path: Path, *, chunk: dict | None = None, enriched: dict | None = None) -> dict:
    canon = {"id": "canon-1", "title": "Source", "version_id": "v1", "source_fields": {}}
    _write_jsonl(tmp_path / "canon" / "tiddlers_1.jsonl", [canon])
    _write_jsonl(tmp_path / "enriched" / "tiddlers_enriched_1.jsonl", [enriched or {"id": "canon-1", "title": "Source", "version_id": "v1"}])
    _write_jsonl(tmp_path / "ai" / "tiddlers_ai_1.jsonl", [{"id": "canon-1", "title": "Source", "version_id": "v1"}])
    _write_jsonl(tmp_path / "ai" / "chunks_ai_1.jsonl", [chunk or {"chunk_id": "c1", "source_id": "canon-1", "source_title": "Source", "source_anchor": {"canon_id": "canon-1"}, "source_version_id": "v1"}])
    (tmp_path / "audit").mkdir()
    (tmp_path / "audit" / "manifest.json").write_text("{}", encoding="utf-8")
    return {name: tmp_path / name for name in ("canon", "enriched", "ai", "audit")}


def test_chunks_require_recoverable_source_title_and_anchor(tmp_path):
    paths = _fixture(tmp_path, chunk={"chunk_id": "orphan", "source_id": "", "source_title": "", "source_anchor": {}})
    report = validate_layers(**{f"{key}_dir": value for key, value in paths.items()})
    chunks = next(row for row in report["layers"] if row["layer"] == "chunks")
    assert chunks["state"] == "blocked"
    assert any(item["code"] == "chunk_missing_grounding" for item in chunks["warnings"])


def test_stale_derived_version_warns_and_cannot_be_final_evidence(tmp_path):
    paths = _fixture(tmp_path, enriched={"id": "canon-1", "title": "Source", "version_id": "old"})
    report = validate_layers(**{f"{key}_dir": value for key, value in paths.items()})
    enriched = next(row for row in report["layers"] if row["layer"] == "enriched")
    assert enriched["freshness"] == "stale"
    assert not final_evidence_allowed("enriched")
    assert not final_evidence_allowed("ai")
    assert not final_evidence_allowed("chunks")


def test_relation_target_is_never_admitted_outside_canon(tmp_path):
    paths = _fixture(tmp_path, chunk={"chunk_id": "c1", "source_id": "canon-1", "source_title": "Source", "source_anchor": {"canon_id": "canon-1"}, "source_version_id": "v1", "relation_targets": [{"target_id": "x"}]})
    report = validate_layers(**{f"{key}_dir": value for key, value in paths.items()})
    chunks = next(row for row in report["layers"] if row["layer"] == "chunks")
    assert relation_status("chunks") == "candidate_or_derived_not_admitted"
    assert any(item["code"] == "relation_targets_not_admitted" for item in chunks["warnings"])


def test_human_output_has_operational_columns(tmp_path):
    paths = _fixture(tmp_path)
    report = validate_layers(**{f"{key}_dir": value for key, value in paths.items()})
    output = render_human(report)
    for column in ("capa", "estado", "linaje", "frescura", "grounding", "autoridad", "acción segura"):
        assert column in output
    assert "transición | cobertura | severidad" in output


def test_observed_post_s0151_aliases_are_partial_not_universal(tmp_path):
    paths = _fixture(tmp_path)
    canon = paths["canon"] / "tiddlers_1.jsonl"
    canon.write_text(json.dumps({"id": "canon-1", "title": "Source", "version_id": "v1", "source_fields": {"authority_level": "current_verified", "repo_lifecycle_state": "current_repo_artifact"}}) + "\n" + json.dumps({"id": "canon-2", "title": "Other", "version_id": "v2", "source_fields": {}}) + "\n", encoding="utf-8")
    report = validate_layers(**{f"{key}_dir": value for key, value in paths.items()})
    assert report["coverage"]["authority_level"]["state"] == "partial"
    assert report["coverage"]["repo_lifecycle_state"]["state"] == "partial"
    assert observed_metadata({"source_fields": {"authority_level": "current_verified"}})["authority"] == "current_verified"
    assert coverage_state(0, 1) == "not_recorded"


def test_transition_contracts_keep_historical_gaps_explicit(tmp_path):
    paths = _fixture(tmp_path)
    report = validate_layers(**{f"{key}_dir": value for key, value in paths.items()})
    by_name = {row["transition"]: row for row in report["transitions"]}
    assert by_name["source_to_session"]["coverage"] == "not_recorded"
    assert by_name["canon_to_chunk"]["coverage"] == "ok"
