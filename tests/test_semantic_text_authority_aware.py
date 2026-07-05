"""S0149 tests for authority-aware semantic_text sidecar."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import build_semantic_text_authority_aware as authority_builder  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    return path


def _canon(tmp_path: Path) -> Path:
    return _write_jsonl(
        tmp_path / "canon" / "tiddlers_1.jsonl",
        [
            {
                "id": "cur",
                "title": "python_scripts/current.py",
                "source_fields": {"artifact_family": "artefacto_repositorio", "authority_level": "current_verified"},
                "text": "def current(): pass",
            },
            {
                "id": "hist",
                "title": "README-old",
                "source_fields": {"artifact_family": "artefacto_repositorio", "authority_level": "historical_snapshot"},
                "text": "historical readme",
            },
            {
                "id": "nar",
                "title": "#### 🌀 Sesión 0102 = narrative",
                "source_fields": {"artifact_family": "detalles_de_sesion", "authority_level": "narrative_reference"},
                "text": "mentions python_scripts/current.py",
            },
            {
                "id": "gen",
                "title": "data/out/local/generated.json",
                "source_fields": {"artifact_family": "artefacto_repositorio", "authority_level": "generated_derivative"},
                "text": "generated output",
            },
            {
                "id": "unk",
                "title": "unknown",
                "source_fields": {"artifact_family": "unknown"},
                "text": "unknown authority",
            },
        ],
    )


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def test_semantic_text_authority_preview_writes_required_outputs(tmp_path: Path) -> None:
    canon = _canon(tmp_path)
    out_dir = tmp_path / "semantic_text_authority" / "s0149"

    result = authority_builder.build_authority_outputs(
        canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
        out_dir=out_dir,
        session="S0149",
        mode="preview",
    )

    assert result["authority_aware"] is True
    assert result["modified_canon"] is False
    assert result["mode"] == "preview"
    paths = {name: Path(path) for name, path in result["paths"].items()}
    for key in ["records", "index", "coverage_report", "summary", "review", "hashes"]:
        assert paths[key].exists()
    coverage = json.loads(paths["coverage_report"].read_text(encoding="utf-8"))
    assert coverage["authority_aware"] is True
    assert coverage["source_session"] == "S0149"
    assert coverage["modified_canon"] is False
    assert sorted(coverage["authority_levels_detected"]) == [
        "current_verified",
        "generated_derivative",
        "historical_snapshot",
        "narrative_reference",
        "unknown",
    ]


def test_semantic_text_generate_distinguishes_authority_levels_and_is_deterministic(tmp_path: Path) -> None:
    canon = _canon(tmp_path)
    out_dir = tmp_path / "semantic_text_authority" / "s0149"

    first = authority_builder.build_authority_outputs(
        canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
        out_dir=out_dir,
        session="S0149",
        mode="generate",
    )
    records_path = Path(first["paths"]["records"])
    first_records_text = records_path.read_text(encoding="utf-8")
    second = authority_builder.build_authority_outputs(
        canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
        out_dir=out_dir,
        session="S0149",
        mode="generate",
    )

    records = _read_jsonl(records_path)
    by_id = {record["id"]: record for record in records}
    assert by_id["cur"]["authority_statement"].startswith("Este tiddler representa un artefacto actual")
    assert by_id["hist"]["authority_statement"].startswith("Este tiddler representa o describe un artefacto histórico")
    assert by_id["nar"]["authority_statement"].startswith("Este tiddler documenta o menciona contenido técnico")
    assert by_id["gen"]["authority_statement"].startswith("Este tiddler corresponde a una salida derivada")
    assert by_id["unk"]["authority_statement"].startswith("La autoridad técnica")
    assert first_records_text == records_path.read_text(encoding="utf-8")
    assert first["summary"]["records_sha256"] == second["summary"]["records_sha256"]


def test_semantic_text_authority_builder_does_not_overwrite_s0144(tmp_path: Path) -> None:
    canon = _canon(tmp_path)
    forbidden = tmp_path / "semantic_text" / "s0144"

    with pytest.raises(ValueError):
        authority_builder.build_authority_outputs(
            canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
            out_dir=forbidden,
            session="S0149",
            mode="preview",
        )


def test_semantic_text_authority_jsonl_outputs_are_valid(tmp_path: Path) -> None:
    canon = _canon(tmp_path)
    result = authority_builder.build_authority_outputs(
        canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
        out_dir=tmp_path / "semantic_text_authority" / "s0149",
        session="S0149",
        mode="preview",
    )
    paths = {name: Path(path) for name, path in result["paths"].items()}

    json.loads(paths["index"].read_text(encoding="utf-8"))
    json.loads(paths["coverage_report"].read_text(encoding="utf-8"))
    json.loads(paths["hashes"].read_text(encoding="utf-8"))
    assert len(_read_jsonl(paths["records"])) == 5
