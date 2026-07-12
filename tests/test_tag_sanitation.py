from __future__ import annotations

import hashlib
import json
from pathlib import Path

import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

from audit_tags_inventory import build_inventory, read_canon_records  # noqa: E402
from build_tag_sanitation_plan import build_plan  # noqa: E402
from tag_sanitation_policy import classify_tag, classify_tag_for_rag, filter_tags_for_rag, load_policy, write_default_policy  # noqa: E402
from validate_rag_tag_gate import build_gate_report  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_tag_inventory_classifies_code_markers_as_p0(tmp_path: Path) -> None:
    policy = write_default_policy(tmp_path / "policy.json")

    decision = classify_tag("--- Codigo", policy)

    assert decision["classification"] == "p0_blocked"
    assert decision["rag_policy"] == "block"


def test_tag_inventory_classifies_markdown_headers(tmp_path: Path) -> None:
    policy = write_default_policy(tmp_path / "policy.json")

    decision = classify_tag("## Plain technical header", policy)

    assert decision["classification"] == "p0_blocked"
    assert decision["looks_like_markdown_header"] is True


def test_tag_inventory_preserves_human_navigation_tags(tmp_path: Path) -> None:
    policy = write_default_policy(tmp_path / "policy.json")

    decision = classify_tag("## 🧪🧱 Hipótesis", policy)

    assert decision["classification"] == "p2_human_nav"
    assert decision["rag_policy"] == "human_only"
    assert decision["recommended_action"] == "keep"


def test_rag_gate_blocks_p0_tags_from_semantic_text(tmp_path: Path) -> None:
    policy = write_default_policy(tmp_path / "policy.json")
    inventory = {
        "tags": [
            {"tag": "--- Codigo", "classification": "p0_blocked", "count": 1},
        ],
    }
    _write_jsonl(
        tmp_path / "rag" / "records.jsonl",
        [{"id": "r1", "title": "R1", "semantic_text": "noise --- Codigo leaked"}],
    )

    report = build_gate_report(policy=policy, inventory=inventory, roots=[tmp_path / "rag"])

    assert report["status"] == "blocked"
    assert report["p0_tags_in_semantic_text"] == 1


def test_rag_gate_passes_on_sanitized_preview(tmp_path: Path) -> None:
    policy = write_default_policy(tmp_path / "policy.json")
    inventory = {
        "tags": [
            {"tag": "--- Codigo", "classification": "p0_blocked", "count": 1},
            {"tag": "needs-review", "classification": "unknown", "count": 1},
        ],
    }
    _write_jsonl(
        tmp_path / "preview" / "records.jsonl",
        [
            {
                "id": "r1",
                "title": "R1",
                "semantic_text": "clean semantic text",
                "retrieval_hints": ["topic:canon"],
                "embedding_metadata": {"rag_allowed_tags": [], "metadata_only_tags": ["topic:canon"]},
            }
        ],
    )

    report = build_gate_report(policy=policy, inventory=inventory, roots=[tmp_path / "preview"])

    assert report["status"] == "pass"
    assert report["p0_tags_in_semantic_text"] == 0
    assert report["p0_tags_in_retrieval_hints"] == 0
    assert report["p0_tags_in_embedding_metadata"] == 0


def test_rag_gate_blocks_p0_tags_from_retrieval_hints(tmp_path: Path) -> None:
    policy = write_default_policy(tmp_path / "policy.json")
    inventory = {
        "tags": [
            {"tag": "src/example.py", "classification": "p0_blocked", "count": 1},
        ],
    }
    _write_jsonl(
        tmp_path / "rag" / "records.jsonl",
        [{"id": "r1", "title": "R1", "retrieval_hints": ["src/example.py"]}],
    )

    report = build_gate_report(policy=policy, inventory=inventory, roots=[tmp_path / "rag"])

    assert report["status"] == "blocked"
    assert report["p0_tags_in_retrieval_hints"] == 1


def test_rag_gate_blocks_legacy_contaminated_outputs(tmp_path: Path) -> None:
    policy = write_default_policy(tmp_path / "policy.json")
    inventory = {
        "tags": [
            {"tag": "--- Codigo", "classification": "p0_blocked", "count": 1},
        ],
    }
    _write_jsonl(
        tmp_path / "legacy" / "records.jsonl",
        [{"id": "r1", "title": "R1", "embedding_metadata": {"tags": ["--- Codigo"]}}],
    )

    report = build_gate_report(policy=policy, inventory=inventory, roots=[tmp_path / "legacy"])

    assert report["status"] == "blocked"
    assert report["p0_tags_in_embedding_metadata"] == 1


def test_tag_policy_required_in_strict_mode(tmp_path: Path) -> None:
    from semantic_text_builder import build_semantic_text_outputs  # noqa: PLC0415

    canon = _write_jsonl(tmp_path / "canon" / "tiddlers_1.jsonl", [{"id": "r1", "title": "R1", "tags": []}])

    try:
        build_semantic_text_outputs(
            canon_glob=str(canon.parent / "tiddlers_*.jsonl"),
            out_dir=tmp_path / "out",
            tag_policy=tmp_path / "missing.json",
            strict_tag_gate=True,
        )
    except FileNotFoundError as exc:
        assert "strict tag gate requires" in str(exc)
    else:
        raise AssertionError("strict tag gate accepted missing policy")


def test_tdc_projected_tags_do_not_generate_metadata(tmp_path: Path) -> None:
    policy = write_default_policy(tmp_path / "policy.json")
    inventory = {
        "tags": [
            {"tag": "tdc:role/base", "classification": "p3_projectable", "count": 1},
        ],
    }

    report = build_gate_report(policy=policy, inventory=inventory, roots=[tmp_path / "missing"])

    assert report["status"] == "warning"
    assert report["tdc_projected_tag_risks"][0]["tag"] == "tdc:role/base"
    assert "tdc:*" in policy["never_use_as_primary_metadata_source"]


def test_filter_tags_for_rag_separates_required_buckets(tmp_path: Path) -> None:
    policy = write_default_policy(tmp_path / "policy.json")

    result = filter_tags_for_rag(
        ["--- Codigo", "status:local_admitted", "## 🧪🧱 Hipótesis", "tdc:role/base", "needs-review"],
        policy,
    )

    assert result["blocked_tags"] == ["--- Codigo"]
    assert result["metadata_only_tags"] == ["status:local_admitted"]
    assert result["human_navigation_tags"] == ["## 🧪🧱 Hipótesis"]
    assert result["projectable_tags"] == ["tdc:role/base"]
    assert result["unknown_tags"] == ["needs-review"]
    assert result["allowed_semantic_tags"] == []
    assert classify_tag_for_rag("needs-review", policy)["rag_class"] == "unknown_review"


def test_tag_sanitation_plan_is_dry_run_by_default(tmp_path: Path) -> None:
    policy = write_default_policy(tmp_path / "policy.json")
    records = [{"id": "r1", "title": "R1", "tags": ["--- Codigo", "session:s0169"]}]

    plan = build_plan(records, policy)

    assert plan["dry_run"] is True
    assert plan["canon_modified"] is False
    assert plan["summary"]["exclude_from_rag_count"] == 1
    assert plan["summary"]["promote_to_metadata_count"] == 1


def test_tag_sanitation_plan_does_not_modify_canon(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    policy = write_default_policy(policy_path)
    canon = _write_jsonl(tmp_path / "canon" / "tiddlers_1.jsonl", [{"id": "r1", "tags": ["--- Codigo"]}])
    before = _hash(canon)

    records = read_canon_records(str(canon.parent / "tiddlers_*.jsonl"))
    inventory = build_inventory(records, policy)
    plan = build_plan(records, load_policy(policy_path))

    assert inventory["summary"]["canon_modified"] is False
    assert plan["canon_modified"] is False
    assert _hash(canon) == before
