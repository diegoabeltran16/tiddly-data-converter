"""S0145 tests for unknown artifact_family characterization."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

from characterize_unknown_artifact_family import (  # noqa: E402
    REVIEW_COLUMNS,
    build_unknown_artifact_family_outputs,
)


def _record(
    tid: str,
    *,
    title: str | None = None,
    family: str | None = None,
    tags: list[str] | None = None,
    text: str = "Contenido estable sin senales fuertes.",
) -> dict:
    source_fields = {
        "canonical_status": "local_admitted",
        "source_path": "tests/fixture.md",
        "provenance_ref": "test",
    }
    if family is not None:
        source_fields["artifact_family"] = family
    return {
        "id": tid,
        "key": title or f"Title {tid}",
        "title": title or f"Title {tid}",
        "tags": tags or [],
        "source_tags": tags or [],
        "source_fields": source_fields,
        "relations": [],
        "text": text,
    }


def _semantic(records: list[dict], *, unknown_ids: set[str]) -> list[dict]:
    return [
        {
            "id": record["id"],
            "title": record["title"],
            "artifact_family": "unknown" if record["id"] in unknown_ids else "contrato_de_sesion",
            "semantic_text": f"semantic text for {record['id']}",
        }
        for record in records
    ]


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _run(tmp_path: Path, records: list[dict], *, unknown_ids: set[str]) -> tuple[dict, Path, Path]:
    canon = _write_jsonl(tmp_path / "canon" / "tiddlers_1.jsonl", records)
    semantic = _write_jsonl(tmp_path / "semantic" / "records.jsonl", _semantic(records, unknown_ids=unknown_ids))
    result = build_unknown_artifact_family_outputs(
        canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
        semantic_text_records=semantic,
        out_dir=tmp_path / "out",
        session="s0145",
    )
    return result, canon, semantic


def _candidates(result: dict) -> list[dict]:
    path = Path(result["paths"]["classification_candidates"])
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _mapping(result: dict) -> dict:
    return json.loads(Path(result["paths"]["mapping_preview"]).read_text(encoding="utf-8"))


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_detects_unknown_records(tmp_path: Path) -> None:
    result, _, _ = _run(
        tmp_path,
        [_record("unknown"), _record("known", family="contrato_de_sesion")],
        unknown_ids={"unknown"},
    )

    assert result["summary"]["total_unknown"] == 1
    assert _candidates(result)[0]["id"] == "unknown"


def test_does_not_classify_known_artifact_family_records(tmp_path: Path) -> None:
    result, _, _ = _run(
        tmp_path,
        [_record("unknown"), _record("known", family="contrato_de_sesion")],
        unknown_ids={"unknown"},
    )

    candidate_ids = {item["id"] for item in _candidates(result)}
    assert candidate_ids == {"unknown"}


def test_detects_referencia_documental_from_url_author_year_and_citation(tmp_path: Path) -> None:
    text = "Autor: Ana Perez (2024). Articulo citado. Fuente: https://example.org/paper"
    result, _, _ = _run(tmp_path, [_record("ref", title="Referencia de estudio", text=text)], unknown_ids={"ref"})

    candidate = _candidates(result)[0]
    assert candidate["candidate_artifact_family"] == "referencia_documental"
    assert candidate["confidence"] == "high"
    assert "url_detected" in candidate["signals"]


def test_detects_tiddler_tecnico_from_paths_scripts_and_extensions(tmp_path: Path) -> None:
    text = "Ejecutar python3 -m pytest para validar el script.\n```python\nprint('ok')\n```"
    result, _, _ = _run(
        tmp_path,
        [_record("tech", title="python_scripts/demo.py", tags=["codigo"], text=text)],
        unknown_ids={"tech"},
    )

    candidate = _candidates(result)[0]
    assert candidate["candidate_artifact_family"] == "tiddler_tecnico"
    assert candidate["confidence"] == "high"


def test_detects_indice_o_navegacion_from_link_lists(tmp_path: Path) -> None:
    text = "- [[A]]\n- [[B]]\n- [[C]]\n- [[D]]\n- [[E]]"
    result, _, _ = _run(tmp_path, [_record("nav", title="Indice de temas", text=text)], unknown_ids={"nav"})

    candidate = _candidates(result)[0]
    assert candidate["candidate_artifact_family"] == "indice_o_navegacion"
    assert candidate["confidence"] == "high"


def test_detects_concepto_from_definition_pattern(tmp_path: Path) -> None:
    text = "Memoria colectiva es una categoria conceptual usada para explicar el corpus."
    result, _, _ = _run(tmp_path, [_record("concept", title="Memoria colectiva", text=text)], unknown_ids={"concept"})

    candidate = _candidates(result)[0]
    assert candidate["candidate_artifact_family"] == "concepto"
    assert candidate["confidence"] == "high"


def test_tags_are_signal_not_decision(tmp_path: Path) -> None:
    result, _, _ = _run(
        tmp_path,
        [_record("tag-only", title="Entrada neutra", tags=["referencia"], text="Contenido sin evidencia externa.")],
        unknown_ids={"tag-only"},
    )

    candidate = _candidates(result)[0]
    assert candidate["candidate_artifact_family"] == "requires_human_review"
    assert candidate["confidence"] == "requires_human_review"
    assert "tags are evidence" in candidate["reason"]


def test_every_record_has_confidence_and_recommended_action(tmp_path: Path) -> None:
    result, _, _ = _run(
        tmp_path,
        [_record("a"), _record("b", title="Indice", text="- [[A]]\n- [[B]]")],
        unknown_ids={"a", "b"},
    )

    for candidate in _candidates(result):
        assert candidate["confidence"]
        assert candidate["recommended_action"]


def test_mapping_preview_is_non_applicable(tmp_path: Path) -> None:
    result, _, _ = _run(tmp_path, [_record("unknown")], unknown_ids={"unknown"})

    mapping = _mapping(result)
    assert mapping["dry_run"] is True
    assert mapping["applied_to_canon"] is False
    assert mapping["canon_modified"] is False
    assert mapping["mapping_allowed_in_s0145"] is False


def test_does_not_modify_input_canon_jsonl(tmp_path: Path) -> None:
    records = [_record("unknown", title="python_scripts/demo.py")]
    canon = _write_jsonl(tmp_path / "canon" / "tiddlers_1.jsonl", records)
    semantic = _write_jsonl(tmp_path / "semantic" / "records.jsonl", _semantic(records, unknown_ids={"unknown"}))
    before = _hash(canon)

    build_unknown_artifact_family_outputs(
        canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
        semantic_text_records=semantic,
        out_dir=tmp_path / "out",
        session="s0145",
    )

    assert _hash(canon) == before


def test_review_csv_contains_minimum_columns(tmp_path: Path) -> None:
    result, _, _ = _run(tmp_path, [_record("unknown")], unknown_ids={"unknown"})
    with Path(result["paths"]["review"]).open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == REVIEW_COLUMNS


def test_classification_jsonl_is_valid(tmp_path: Path) -> None:
    result, _, _ = _run(tmp_path, [_record("unknown")], unknown_ids={"unknown"})

    path = Path(result["paths"]["classification_candidates"])
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows
    assert rows[0]["dry_run"] is True
    assert rows[0]["applied_to_canon"] is False


def test_classification_is_deterministic_across_two_runs(tmp_path: Path) -> None:
    records = [
        _record("ref", title="Referencia", text="Autor: A (2024). Fuente: https://example.org"),
        _record("tech", title="data/out/local/report.json", text="{}"),
    ]
    canon = _write_jsonl(tmp_path / "canon" / "tiddlers_1.jsonl", records)
    semantic = _write_jsonl(tmp_path / "semantic" / "records.jsonl", _semantic(records, unknown_ids={"ref", "tech"}))

    first = build_unknown_artifact_family_outputs(
        canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
        semantic_text_records=semantic,
        out_dir=tmp_path / "out1",
        session="s0145",
    )
    second = build_unknown_artifact_family_outputs(
        canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
        semantic_text_records=semantic,
        out_dir=tmp_path / "out2",
        session="s0145",
    )

    assert Path(first["paths"]["classification_candidates"]).read_text(encoding="utf-8") == Path(
        second["paths"]["classification_candidates"]
    ).read_text(encoding="utf-8")
    assert Path(first["paths"]["mapping_preview"]).read_text(encoding="utf-8") == Path(
        second["paths"]["mapping_preview"]
    ).read_text(encoding="utf-8")


def test_ambiguous_records_require_human_review(tmp_path: Path) -> None:
    text = "python3\nPendiente de revision."
    result, _, _ = _run(tmp_path, [_record("ambiguous", title="Entrada ambigua", text=text)], unknown_ids={"ambiguous"})

    candidate = _candidates(result)[0]
    assert candidate["candidate_artifact_family"] == "requires_human_review"
    assert candidate["recommended_action"] == "review_manually"
