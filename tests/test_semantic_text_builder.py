"""S0144 tests for deterministic semantic_text sidecar generation."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

from semantic_text_builder import (  # noqa: E402
    REVIEW_COLUMNS,
    build_semantic_text_outputs,
)


def _record(
    tid: str,
    *,
    title: str | None = None,
    family: str | None = "balance",
    tags: list[str] | None = None,
    text: str = "Texto fuente estable para semantic_text.",
    relations: list[dict] | None = None,
    source_fields: dict | None = None,
) -> dict:
    sf = {
        "artifact_family": family,
        "canonical_status": "local_admitted",
        "session_origin": "m04-s0144-test",
        "source_path": "data/out/local/sessions/test.md.json",
        "provenance_ref": "test",
    } if family is not None else {}
    if source_fields:
        sf.update(source_fields)
    base = {
        "id": tid,
        "key": title or f"Title {tid}",
        "title": title or f"Title {tid}",
        "tags": tags or ["tag:b", "tag:a"],
        "source_tags": tags or ["tag:b", "tag:a"],
        "source_fields": sf,
        "relations": relations or [],
        "text": text,
    }
    if family is None:
        base["source_fields"] = {}
    return base


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def _run_build(
    tmp_path: Path,
    records: list[dict],
    *,
    ready_payload: dict | None = None,
    patch_payload: dict | None = None,
    max_chars: int = 4000,
) -> dict:
    canon = _write_jsonl(tmp_path / "canon" / "tiddlers_1.jsonl", records)
    ready_glob = str(tmp_path / "admission" / "*" / "admission_ready_dry_run.json")
    patch_glob = str(tmp_path / "admission" / "*" / "admission_patch_preview.json")
    if ready_payload is not None:
        _write_json(tmp_path / "admission" / "s0143" / "admission_ready_dry_run.json", ready_payload)
    if patch_payload is not None:
        _write_json(tmp_path / "admission" / "s0143" / "admission_patch_preview.json", patch_payload)
    result = build_semantic_text_outputs(
        canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
        out_dir=tmp_path / "out",
        session="s0144",
        type_policy=tmp_path / "missing_policy.json",
        dry_run_ready_glob=ready_glob,
        patch_preview_glob=patch_glob,
        max_content_chars=max_chars,
    )
    return result


def _records_from_output(result: dict) -> list[dict]:
    path = Path(result["paths"]["records"])
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _semantic_text(result: dict, tid: str) -> str:
    for record in _records_from_output(result):
        if record["id"] == tid:
            return record["semantic_text"]
    raise AssertionError(f"missing record {tid}")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_build_is_deterministic_for_same_inputs(tmp_path: Path) -> None:
    records = [
        _record("src", relations=[{"type": "references", "target_id": "tgt", "evidence": "wikilink"}]),
        _record("tgt", title="Target"),
    ]

    first = _run_build(tmp_path, records)
    first_hashes = Path(first["paths"]["hashes"]).read_text(encoding="utf-8")
    second = _run_build(tmp_path, records)
    second_hashes = Path(second["paths"]["hashes"]).read_text(encoding="utf-8")

    assert first_hashes == second_hashes


def test_tags_are_classification_not_relations(tmp_path: Path) -> None:
    result = _run_build(tmp_path, [_record("src", tags=["topic:zeta", "topic:alpha"])])
    text = _semantic_text(result, "src")

    assert "Tags RAG permitidos (clasificacion solamente; tag != relation): (sin tags declarados)" in text
    record = _records_from_output(result)[0]
    assert record["metadata_only_tag_count"] == 2
    assert "# Relaciones canonicas\n- alpha" not in text


def test_semantic_text_blocks_p0_tags_from_classification_section(tmp_path: Path) -> None:
    result = _run_build(tmp_path, [_record("src", tags=["topic:alpha", "--- Codigo", "src/python_scripts/example.py"])])
    record = _records_from_output(result)[0]
    text = record["semantic_text"]

    assert "Tags RAG permitidos (clasificacion solamente; tag != relation): (sin tags declarados)" in text
    assert "--- Codigo" not in text
    assert "src/python_scripts/example.py" not in text
    assert record["audit_only_blocked_tags_count"] == 2
    assert "p0_tags_blocked_from_semantic_text" in record["warnings"]


def test_semantic_text_builder_excludes_unknown_tags_by_default(tmp_path: Path) -> None:
    result = _run_build(tmp_path, [_record("src", tags=["needs-review-token"])])
    record = _records_from_output(result)[0]

    assert "needs-review-token" not in record["semantic_text"]
    assert record["audit_only_unknown_tags_count"] == 1
    assert "unknown_tags_blocked_from_rag" in record["warnings"]


def test_semantic_text_builder_preserves_human_navigation_when_allowed(tmp_path: Path) -> None:
    result = _run_build(tmp_path, [_record("src", tags=["## 🧪🧱 Hipótesis"])])
    record = _records_from_output(result)[0]

    assert "## 🧪🧱 Hipótesis" not in record["semantic_text"]
    assert record["human_navigation_tag_count"] == 1
    assert record["embedding_metadata"]["human_navigation_tag_count"] == 1


def test_semantic_text_builder_does_not_emit_source_tags_raw(tmp_path: Path) -> None:
    result = _run_build(tmp_path, [_record("src", tags=["--- Codigo", "src/python_scripts/example.py"])])
    record = _records_from_output(result)[0]

    assert "rag_blocked_tags" not in record
    assert "--- Codigo" not in json.dumps(record, ensure_ascii=False)
    assert "src/python_scripts/example.py" not in json.dumps(record, ensure_ascii=False)


def test_embedding_metadata_excludes_p0_tags(tmp_path: Path) -> None:
    result = _run_build(tmp_path, [_record("src", tags=["--- Codigo", "status:local_admitted"])])
    record = _records_from_output(result)[0]

    metadata_text = json.dumps(record["embedding_metadata"], ensure_ascii=False)
    assert "--- Codigo" not in metadata_text
    assert "status:local_admitted" in record["embedding_metadata"]["metadata_only_tags"]
    assert record["embedding_metadata"]["audit_only_blocked_tags_count"] == 1


def test_retrieval_hints_exclude_p0_tags(tmp_path: Path) -> None:
    result = _run_build(tmp_path, [_record("src", tags=["--- Codigo", "topic:canon"])])
    record = _records_from_output(result)[0]

    assert "--- Codigo" not in record["retrieval_hints"]
    assert "topic:canon" in record["retrieval_hints"]


def test_canonical_relations_are_in_canonical_section(tmp_path: Path) -> None:
    records = [
        _record("src", relations=[{"type": "references", "target_id": "tgt", "evidence": "wikilink"}]),
        _record("tgt", title="Target"),
    ]
    text = _semantic_text(_run_build(tmp_path, records), "src")

    assert "# Relaciones canonicas" in text
    assert "- references -> tgt (Target); evidence=wikilink; canonical" in text


def test_legacy_readonly_is_included_as_historical(tmp_path: Path) -> None:
    records = [
        _record("src", relations=[{"type": "define", "target_id": "tgt"}]),
        _record("tgt", title="Target"),
    ]
    text = _semantic_text(_run_build(tmp_path, records), "src")

    assert "# Relaciones historicas gobernadas" in text
    assert "- define -> tgt (Target); historical readonly" in text


def test_structural_only_is_structure_not_semantic(tmp_path: Path) -> None:
    records = [
        _record("src", relations=[{"type": "child_of", "target_id": "tgt"}]),
        _record("tgt", title="Target"),
    ]
    text = _semantic_text(_run_build(tmp_path, records), "src")

    assert "# Estructura historica no semantica" in text
    assert "- child_of -> tgt (Target); structural only" in text
    assert "# Relaciones canonicas\n- child_of" not in text


def test_legacy_alias_candidate_is_not_applied_as_alias(tmp_path: Path) -> None:
    records = [
        _record("src", relations=[{"type": "usa", "target_id": "tgt"}]),
        _record("tgt", title="Target"),
    ]
    text = _semantic_text(_run_build(tmp_path, records), "src")

    assert "historical alias candidate only (not applied as references)" in text
    assert "# Relaciones canonicas\n- usa ->" not in text


def test_admission_ready_dry_run_is_excluded_from_canonical_relations(tmp_path: Path) -> None:
    ready = {
        "items": [
            {
                "source_tiddler_id": "src",
                "target_tiddler_id": "tgt",
                "relation_type": "menciona_diagnostico",
                "gate_status": "admission_ready_dry_run",
            }
        ]
    }
    result = _run_build(tmp_path, [_record("src"), _record("tgt")], ready_payload=ready)
    record = _records_from_output(result)[0]
    text = _semantic_text(result, "src")

    assert record["dry_run_preview_excluded"] is True
    assert record["dry_run_preview_included"] is False
    assert "dry_run_candidates_excluded: 1" in text
    assert "# Relaciones canonicas\n- menciona_diagnostico" not in text


def test_patch_preview_is_not_included_as_canon(tmp_path: Path) -> None:
    patch = {
        "operations": [
            {
                "operation": "add_relation_preview_only",
                "source_id": "src",
                "target_id": "tgt",
                "relation_type": "references",
                "applied": False,
            }
        ]
    }
    result = _run_build(tmp_path, [_record("src"), _record("tgt")], patch_payload=patch)
    record = _records_from_output(result)[0]
    text = _semantic_text(result, "src")

    assert record["patch_preview_excluded"] is True
    assert record["patch_preview_included"] is False
    assert "patch_preview_excluded: 1" in text
    assert "# Relaciones canonicas\n- references -> tgt" not in text


def test_profiles_by_artifact_family_are_applied(tmp_path: Path) -> None:
    result = _run_build(tmp_path, [_record("src", family="balance")])
    record = _records_from_output(result)[0]
    profiles = json.loads(Path(result["paths"]["profiles"]).read_text(encoding="utf-8"))

    assert record["artifact_family"] == "balance_de_sesion"
    assert record["profile_applied"] == "balance_de_sesion"
    assert "balance_de_sesion" in profiles["profiles"]


def test_unknown_family_uses_unknown_profile(tmp_path: Path) -> None:
    result = _run_build(tmp_path, [_record("src", family=None)])
    record = _records_from_output(result)[0]

    assert record["artifact_family"] == "unknown"
    assert record["profile_applied"] == "unknown"
    assert "missing_artifact_family" in record["warnings"]


def test_semantic_text_sha256_is_generated(tmp_path: Path) -> None:
    record = _records_from_output(_run_build(tmp_path, [_record("src")]))[0]

    assert re.fullmatch(r"[0-9a-f]{64}", record["semantic_text_sha256"])


def test_build_does_not_modify_canon_shards(tmp_path: Path) -> None:
    canon = _write_jsonl(tmp_path / "canon" / "tiddlers_1.jsonl", [_record("src")])
    before = _hash(canon)

    build_semantic_text_outputs(
        canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
        out_dir=tmp_path / "out",
        session="s0144",
        type_policy=tmp_path / "missing_policy.json",
        dry_run_ready_glob=str(tmp_path / "missing_ready" / "*.json"),
        patch_preview_glob=str(tmp_path / "missing_patch" / "*.json"),
    )

    assert _hash(canon) == before


def test_coverage_report_contains_counts_by_family(tmp_path: Path) -> None:
    result = _run_build(tmp_path, [_record("src", family="balance"), _record("unknown", family=None)])
    report = json.loads(Path(result["paths"]["coverage_report"]).read_text(encoding="utf-8"))

    assert report["total_records"] == 2
    assert report["records_with_semantic_text"] == 2
    assert report["records_missing_artifact_family"] == 1
    assert report["by_artifact_family"]["balance_de_sesion"]["total_records"] == 1
    assert report["by_artifact_family"]["unknown"]["total_records"] == 1


def test_review_csv_contains_minimum_columns(tmp_path: Path) -> None:
    result = _run_build(tmp_path, [_record("src")])
    with Path(result["paths"]["review"]).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    assert reader.fieldnames == REVIEW_COLUMNS
    assert rows[0]["id"] == "src"


def test_semantic_text_has_no_generated_timestamps(tmp_path: Path) -> None:
    text = _semantic_text(_run_build(tmp_path, [_record("src")]), "src")

    assert "generated_at" not in text
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", text)
