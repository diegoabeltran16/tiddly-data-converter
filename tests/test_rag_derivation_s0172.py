"""S0172 regression tests for the single RAG-safe derivative orchestrator."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "src" / "python_scripts"
sys.path.insert(0, str(SCRIPTS))

import derive_layers  # noqa: E402
from metadata_promotion_policy import write_default_policy as write_metadata_policy  # noqa: E402
from rag_derivation_plan import canonical_snapshot, evaluate_productive_write_preflight  # noqa: E402
from rag_derivation_preflight import manifest_diff, productive_derivatives_manifest  # noqa: E402
from rag_derivation_profile import build_profile, stable_json  # noqa: E402
from rag_derivative_writers import ProductiveWriteBlocked, require_nonproductive_evidence_target  # noqa: E402
from tag_sanitation_policy import write_default_policy as write_tag_policy  # noqa: E402
from validate_rag_tag_gate import build_gate_report  # noqa: E402


def _write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return path


def _fixture_paths(tmp_path: Path) -> dict[str, Path]:
    canon = tmp_path / "canon"
    record = {
        "schema_version": "v0",
        "id": "record-1",
        "key": "RAG safe record",
        "title": "RAG safe record",
        "version_id": "sha256:record-1",
        "role_primary": "readme",
        "content_type": "text/markdown",
        "modality": "text",
        "encoding": "utf-8",
        "is_binary": False,
        "is_reference_only": False,
        "tags": ["--- unsafe-code", "topic:rag", "unknown-review-tag"],
        "source_tags": ["--- unsafe-code", "topic:rag", "unknown-review-tag"],
        "normalized_tags": ["--- unsafe-code", "topic:rag", "unknown-review-tag"],
        "source_fields": {"tags": "--- unsafe-code topic:rag unknown-review-tag"},
        "text": "A controlled document about RAG safety and promoted metadata.",
        "content": {"plain": "A controlled document about RAG safety and promoted metadata."},
        "relations": [],
        "document_id": "document-1",
        "section_path": ["RAG safe record"],
        "taxonomy_path": ["readme"],
        "order_in_document": 1,
        "source_position": "fixture:1",
        "created": "20260713000000000",
        "modified": "20260713000000000",
    }
    _write_jsonl(canon / "tiddlers_1.jsonl", [record])
    tag_policy = tmp_path / "policies" / "tag.json"
    metadata_policy = tmp_path / "policies" / "metadata.json"
    write_tag_policy(tag_policy)
    write_metadata_policy(metadata_policy)
    inventory = _write_json(
        tmp_path / "policies" / "inventory.json",
        {
            "tags": [
                {"tag": "--- unsafe-code", "classification": "p0_blocked", "count": 1},
                {"tag": "topic:rag", "classification": "p1_promote", "count": 1},
                {"tag": "unknown-review-tag", "classification": "unknown", "count": 1},
            ]
        },
    )
    candidates = _write_jsonl(
        tmp_path / "policies" / "candidates.jsonl",
        [
            {
                "schema_version": "metadata-promotion-candidate/v1",
                "candidate_id": "candidate-topic",
                "tiddler_id": "record-1",
                "title": "RAG safe record",
                "source_tag": "topic:rag",
                "source_tag_classification": "p1_promote",
                "target_field": "topics",
                "proposed_value": "rag",
                "promotion_status": "candidate",
                "authority_level": "proposed",
                "requires_human_review": False,
                "source_policy": "tag-sanitation/v1",
                "promotion_policy": "metadata-promotion/v1",
                "canon_modified": False,
                "dry_run": True,
            },
            {
                "schema_version": "metadata-promotion-candidate/v1",
                "candidate_id": "candidate-template-node",
                "tiddler_id": "record-1",
                "title": "RAG safe record",
                "source_tag": "topic:rag",
                "source_tag_classification": "p1_metadata_only",
                "target_field": "template_node",
                "proposed_value": "rag-safe-template",
                "promotion_status": "candidate",
                "authority_level": "proposed",
                "requires_human_review": False,
                "source_policy": "tag-sanitation/v1",
                "promotion_policy": "metadata-promotion/v1",
                "canon_modified": False,
                "dry_run": True,
            },
            {
                "schema_version": "metadata-promotion-candidate/v1",
                "candidate_id": "candidate-formal-vocabulary",
                "tiddler_id": "record-1",
                "title": "RAG safe record",
                "source_tag": "topic:rag",
                "source_tag_classification": "p1_promote",
                "target_field": "formal_relation_vocab",
                "proposed_value": "uses",
                "promotion_status": "candidate",
                "authority_level": "proposed",
                "requires_human_review": False,
                "source_policy": "tag-sanitation/v1",
                "promotion_policy": "metadata-promotion/v1",
                "canon_modified": False,
                "dry_run": True,
            },
        ],
    )
    profile_payload = build_profile(tag_policy_path=tag_policy, metadata_policy_path=metadata_policy)
    profile = _write_json(tmp_path / "policies" / "profile.json", profile_payload)
    return {
        "canon": canon,
        "tag_policy": tag_policy,
        "metadata_policy": metadata_policy,
        "inventory": inventory,
        "candidates": candidates,
        "profile": profile,
        "preview": tmp_path / "preview",
        "audit": tmp_path / "audit",
        "evidence": tmp_path / "evidence",
    }


def _run_preview(tmp_path: Path) -> tuple[dict[str, Path], subprocess.CompletedProcess[str]]:
    paths = _fixture_paths(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "derive_layers.py"),
            "--mode",
            "preview",
            "--dry-run",
            "--input-dir",
            str(paths["canon"]),
            "--out-dir",
            str(paths["preview"]),
            "--profile",
            str(paths["profile"]),
            "--metadata-candidates",
            str(paths["candidates"]),
            "--tag-inventory",
            str(paths["inventory"]),
            "--preview-manifest",
            str(paths["evidence"] / "preview_manifest.json"),
            "--plan-out",
            str(paths["evidence"] / "plan.json"),
            "--gate-report",
            str(paths["audit"] / "rag_gate_report.json"),
            "--gate-report-md",
            str(paths["audit"] / "rag_gate_report.md"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return paths, result


def _preflight(paths: dict[str, Path]) -> dict:
    return evaluate_productive_write_preflight(
        plan_path=paths["evidence"] / "plan.json",
        preview_manifest_path=paths["evidence"] / "preview_manifest.json",
        gate_report_path=paths["audit"] / "rag_gate_report.json",
        profile_path=paths["profile"],
        tag_policy_path=paths["tag_policy"],
        metadata_policy_path=paths["metadata_policy"],
        metadata_candidates_path=paths["candidates"],
        tag_inventory_path=paths["inventory"],
        semantic_builder_path=SCRIPTS / "semantic_text_builder.py",
        semantic_type_policy_path=REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_type_governance" / "s0139" / "s0139_historical_relation_type_decisions.json",
        canon=canonical_snapshot(paths["canon"]),
    )


def test_derive_layers_remains_authoritative_productive_orchestrator() -> None:
    assert (SCRIPTS / "derive_layers.py").exists()
    assert not (SCRIPTS / "rag_productive_builder.py").exists()


def test_no_second_productive_derivative_builder_is_registered() -> None:
    profile = build_profile()
    assert profile["productive_orchestrator"] == "src/python_scripts/derive_layers.py"
    assert profile["artifact_families"] == ["enriched", "ai", "chunks_ai", "microsoft_copilot"]


def test_derive_layers_delegates_semantic_text_to_authoritative_builder() -> None:
    source = (SCRIPTS / "derive_layers.py").read_text(encoding="utf-8")
    assert "from semantic_text_builder import build_semantic_text_outputs" in source
    assert "_build_authoritative_semantic_projection" in source


def test_derive_layers_consumes_tag_sanitation_policy() -> None:
    source = (SCRIPTS / "derive_layers.py").read_text(encoding="utf-8")
    assert "load_tag_sanitation_policy" in source
    assert "TAG_SANITATION_POLICY_VERSION" in source


def test_derive_layers_consumes_metadata_promotion_policy() -> None:
    source = (SCRIPTS / "derive_layers.py").read_text(encoding="utf-8")
    assert "load_metadata_promotion_policy" in source
    assert "build_promoted_metadata_index" in source


def test_derive_layers_does_not_duplicate_policy_tables() -> None:
    source = (SCRIPTS / "derive_layers.py").read_text(encoding="utf-8")
    assert "DEFAULT_P0_BLOCK_PATTERNS" not in source
    assert "CURATED_EXACT_TAG_MAPPINGS" not in source


def test_preview_uses_authoritative_derive_layers_path(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (paths["preview"] / "semantic_text").exists()
    assert (paths["preview"] / "enriched").exists()
    assert (paths["preview"] / "ai").exists()
    assert (paths["preview"] / "microsoft_copilot").exists()


def test_preview_and_productive_plan_share_derivation_profile(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((paths["evidence"] / "preview_manifest.json").read_text(encoding="utf-8"))
    plan = json.loads((paths["evidence"] / "plan.json").read_text(encoding="utf-8"))
    assert manifest["derivation_profile_hash"] == plan["derivation_profile_hash"]
    assert manifest["tag_policy_hash"] == plan["tag_policy_hash"]
    assert manifest["metadata_policy_hash"] == plan["metadata_policy_hash"]
    assert manifest["source_canon_version_id"] == plan["source_canon_version_id"]


def test_derive_layers_does_not_emit_raw_source_tags_to_semantic_text(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    records = (paths["preview"] / "semantic_text").glob("*_semantic_text_records.jsonl")
    text = next(records).read_text(encoding="utf-8")
    assert "--- unsafe-code" not in text
    assert "unknown-review-tag" not in text
    assert "topic:rag" not in text


def test_derive_layers_does_not_emit_p0_unknown_or_raw_p1_to_rag_outputs(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    gate = json.loads((paths["audit"] / "rag_gate_report.json").read_text(encoding="utf-8"))
    assert gate["status"] == "pass"
    for key in (
        "p0_tags_in_semantic_text",
        "p0_tags_in_retrieval_hints",
        "p0_tags_in_embedding_metadata",
        "unknown_tags_in_semantic_text",
        "unknown_tags_in_retrieval_hints",
        "unknown_tags_in_embedding_metadata",
        "p1_raw_tags_in_semantic_text",
        "p1_raw_tags_in_retrieval_hints",
        "p1_raw_tags_in_embedding_metadata",
        "template_nodes_as_topics",
        "formal_relation_edges_emitted",
    ):
        assert gate[key] == 0


def test_derive_layers_does_not_emit_p0_to_retrieval_hints(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    gate = json.loads((paths["audit"] / "rag_gate_report.json").read_text(encoding="utf-8"))
    assert gate["p0_tags_in_retrieval_hints"] == 0


def test_derive_layers_does_not_emit_p0_to_embedding_metadata(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    gate = json.loads((paths["audit"] / "rag_gate_report.json").read_text(encoding="utf-8"))
    assert gate["p0_tags_in_embedding_metadata"] == 0


def test_derive_layers_does_not_emit_unknown_to_rag_outputs(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    gate = json.loads((paths["audit"] / "rag_gate_report.json").read_text(encoding="utf-8"))
    assert all(gate[key] == 0 for key in (
        "unknown_tags_in_semantic_text",
        "unknown_tags_in_retrieval_hints",
        "unknown_tags_in_embedding_metadata",
    ))


def test_derive_layers_does_not_emit_raw_p1_to_rag_outputs(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    gate = json.loads((paths["audit"] / "rag_gate_report.json").read_text(encoding="utf-8"))
    assert all(gate[key] == 0 for key in (
        "p1_raw_tags_in_semantic_text",
        "p1_raw_tags_in_retrieval_hints",
        "p1_raw_tags_in_embedding_metadata",
    ))


def test_derive_layers_preserves_promoted_metadata(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    ai_record = json.loads(next((paths["preview"] / "ai").glob("tiddlers_ai_*.jsonl")).read_text(encoding="utf-8"))
    assert ai_record["embedding_metadata"]["promoted_metadata"]["topics"] == ["rag"]
    assert ai_record["embedding_metadata"]["promoted_metadata"]["formal_relation_vocab"] == ["uses"]


def test_derive_layers_does_not_convert_template_nodes_to_topics(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    ai_record = json.loads(next((paths["preview"] / "ai").glob("tiddlers_ai_*.jsonl")).read_text(encoding="utf-8"))
    metadata = ai_record["embedding_metadata"]["promoted_metadata"]
    assert metadata["template_node"] == "rag-safe-template"
    assert metadata["template_node"] not in metadata["topics"]


def test_derive_layers_does_not_emit_formal_relation_edges(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    gate = json.loads((paths["audit"] / "rag_gate_report.json").read_text(encoding="utf-8"))
    assert gate["formal_relation_edges_emitted"] == 0


def test_preview_writes_only_to_isolated_output_root(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    preview_manifest = json.loads((paths["evidence"] / "preview_manifest.json").read_text(encoding="utf-8"))
    assert preview_manifest["output_root"] == str(paths["preview"].resolve())
    assert not (tmp_path / "enriched").exists()
    assert not (tmp_path / "ai").exists()


def test_s0172_preview_does_not_modify_productive_derivatives(tmp_path: Path) -> None:
    before = productive_derivatives_manifest()
    _, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    after = productive_derivatives_manifest()
    assert manifest_diff(before, after)["productive_derivatives_diff"] == "empty"


def test_preview_rejects_productive_output_overlap(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    result = subprocess.run(
        [
            sys.executable, str(SCRIPTS / "derive_layers.py"),
            "--mode", "preview", "--dry-run",
            "--input-dir", str(paths["canon"]),
            "--out-dir", str(REPO_ROOT / "data" / "out" / "local" / "ai" / "s0172-test"),
            "--profile", str(paths["profile"]),
            "--metadata-candidates", str(paths["candidates"]),
            "--tag-inventory", str(paths["inventory"]),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 3
    assert "must not overlap a productive derivative root" in result.stderr


def test_run_derivation_cannot_bypass_authoritative_projection() -> None:
    with pytest.raises(RuntimeError, match="authoritative semantic projection"):
        derive_layers.run_derivation(SimpleNamespace(), {"mode": "production"}, rag_context=None)


def test_supporting_evidence_writer_rejects_productive_destination() -> None:
    with pytest.raises(ProductiveWriteBlocked, match="overlaps productive derivatives"):
        require_nonproductive_evidence_target(REPO_ROOT / "data" / "out" / "local" / "ai" / "blocked.json")


def test_rag_gate_audits_nested_microsoft_copilot_entity_tags(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    copilot = paths["preview"] / "microsoft_copilot"
    _write_json(
        copilot / "entities.json",
        {"entities": [{"id": "record-1", "title": "unsafe", "tags": ["--- unsafe-code"]}]},
    )
    policy = json.loads(paths["tag_policy"].read_text(encoding="utf-8"))
    inventory = json.loads(paths["inventory"].read_text(encoding="utf-8"))
    report = build_gate_report(
        policy=policy,
        inventory=inventory,
        roots=[copilot],
        session="S0172",
        enforce_p1_raw=True,
    )
    assert report["status"] == "blocked"
    assert report["p0_tags_in_embedding_metadata"] == 1


def test_productive_write_blocked_without_gate_report(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    canon = canonical_snapshot(paths["canon"])
    report = evaluate_productive_write_preflight(
        plan_path=None,
        preview_manifest_path=None,
        gate_report_path=None,
        profile_path=paths["profile"],
        tag_policy_path=paths["tag_policy"],
        metadata_policy_path=paths["metadata_policy"],
        canon=canon,
    )
    assert report["productive_write_allowed"] is False
    assert "missing_gate_report" in report["blocking_reasons"]


def test_productive_write_blocked_when_gate_is_not_pass(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    gate_path = paths["audit"] / "rag_gate_report.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["status"] = "blocked"
    gate["blocking"] = True
    _write_json(gate_path, gate)
    assert "gate_status_not_pass" in _preflight(paths)["blocking_reasons"]


def test_productive_write_blocked_when_preview_hash_differs(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    preview_path = paths["evidence"] / "preview_manifest.json"
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    preview["record_count"] = 999
    _write_json(preview_path, preview)
    assert "preview_manifest_hash_mismatch" in _preflight(paths)["blocking_reasons"]


def test_productive_write_blocked_when_profile_hash_differs(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    profile = json.loads(paths["profile"].read_text(encoding="utf-8"))
    profile["authority"]["preview_only"] = False
    _write_json(paths["profile"], profile)
    assert "derivation_profile_hash_mismatch" in _preflight(paths)["blocking_reasons"]


def test_productive_write_blocked_when_policy_hash_differs(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    policy = json.loads(paths["tag_policy"].read_text(encoding="utf-8"))
    policy["rag_blocklist"].append("newly-blocked")
    _write_json(paths["tag_policy"], policy)
    assert "tag_policy_hash_mismatch" in _preflight(paths)["blocking_reasons"]


def test_productive_write_blocked_when_canon_version_changes(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    canon_path = paths["canon"] / "tiddlers_1.jsonl"
    original = json.loads(canon_path.read_text(encoding="utf-8"))
    original["text"] = "changed after preview"
    _write_jsonl(canon_path, [original])
    assert "source_canon_hash_mismatch" in _preflight(paths)["blocking_reasons"]


def test_productive_write_blocked_when_candidate_hash_differs(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    candidates = [json.loads(line) for line in paths["candidates"].read_text(encoding="utf-8").splitlines()]
    candidates[0]["proposed_value"] = "different-value"
    _write_jsonl(paths["candidates"], candidates)
    assert "metadata_candidates_hash_mismatch" in _preflight(paths)["blocking_reasons"]


def test_productive_write_blocked_when_plan_is_stale_even_if_allow_flag_is_set(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    plan_path = paths["evidence"] / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["status"] = "stale"
    plan["productive_write_allowed"] = True
    _write_json(plan_path, plan)
    assert "plan_status_not_validated_preview" in _preflight(paths)["blocking_reasons"]


def test_s0172_plan_never_enables_productive_write(tmp_path: Path) -> None:
    paths, result = _run_preview(tmp_path)
    assert result.returncode == 0, result.stderr
    plan = json.loads((paths["evidence"] / "plan.json").read_text(encoding="utf-8"))
    assert plan["productive_write_allowed"] is False
    assert "S0172" in plan["productive_write_reason"]


def test_legacy_semantic_builder_not_productive_default() -> None:
    source = (SCRIPTS / "build_semantic_text.py").read_text(encoding="utf-8")
    assert "semantic_text sidecar" in source
    assert "data/out/local/enriched" not in source
    assert "data/out/local/microsoft_copilot" not in source


def test_s45_wrapper_delegates_or_is_explicitly_non_authoritative() -> None:
    source = (SCRIPTS / "s45_derive_layers.py").read_text(encoding="utf-8")
    assert "DEPRECATED" in source
    assert "forwarding to python_scripts/derive_layers.py" in source


def test_legacy_root_scripts_do_not_write_productive_paths_by_default() -> None:
    assert not (REPO_ROOT / "python_scripts").exists()
    assert not (REPO_ROOT / "shell_scripts").exists()


def test_experimental_builder_not_reachable_from_normal_menu() -> None:
    source = (SCRIPTS / "operator_menu.py").read_text(encoding="utf-8")
    assert '"src/python_scripts/build_semantic_text_authority_aware.py"' not in source
    assert '"src/python_scripts/s45_derive_layers.py"' not in source
