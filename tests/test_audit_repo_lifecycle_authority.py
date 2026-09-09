from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import audit_repo_lifecycle_authority as authority  # noqa: E402


def _canon_record(rid: str, title: str, *, lifecycle: str | None = None) -> dict:
    source_fields: dict = {}
    if lifecycle:
        source_fields["repo_lifecycle_state"] = lifecycle
    return {"id": rid, "title": title, "key": title, "text": "", "source_fields": source_fields}


def _write_canon(local_root: Path, rows: list[dict]) -> None:
    local_root.mkdir(parents=True, exist_ok=True)
    (local_root / "tiddlers_1.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8",
    )


def _code_block_text(code: str, lang: str = "Python") -> str:
    return f"## [[Tags]]\n\n```{lang}\n{code}\n```"


# ---------------------------------------------------------------------------
# classify_content_authority: never infer current_repo_artifact from path
# existence alone
# ---------------------------------------------------------------------------

def test_missing_path_is_classified_not_resolvable(tmp_path: Path) -> None:
    record = {"id": "a", "title": "", "key": "", "text": "", "source_fields": {}}
    result = authority.classify_content_authority(record, tmp_path)
    assert result["classification"] == "NO_RESOLVABLE_PATH"


def test_resolved_path_but_no_real_file_is_never_current_repo_artifact(tmp_path: Path) -> None:
    record = _canon_record("a", "src/python_scripts/does_not_exist.py")
    result = authority.classify_content_authority(record, tmp_path)
    assert result["classification"] == "NO_REAL_FILE"
    assert result["classification"] not in authority.DETERMINISTIC_CURRENT_REPO_ARTIFACT


def test_exact_content_match_is_deterministic_current_repo_artifact(tmp_path: Path) -> None:
    real = tmp_path / "src" / "python_scripts" / "foo.py"
    real.parent.mkdir(parents=True)
    real.write_text("VALUE = 1\n", encoding="utf-8")
    record = _canon_record("a", "src/python_scripts/foo.py")
    record["text"] = _code_block_text("VALUE = 1\n")

    result = authority.classify_content_authority(record, tmp_path)

    assert result["classification"] == "CONTENT_EXACT_MATCH"
    assert result["classification"] in authority.DETERMINISTIC_CURRENT_REPO_ARTIFACT


def test_content_mismatch_is_never_current_repo_artifact_even_though_file_exists(tmp_path: Path) -> None:
    # This is the prohibited shortcut ("file exists -> current_repo_artifact")
    # made concrete: the file DOES exist, but Canon's own snapshot has
    # drifted from it, so it must not be treated as current.
    real = tmp_path / "src" / "python_scripts" / "foo.py"
    real.parent.mkdir(parents=True)
    real.write_text("VALUE = 2\n", encoding="utf-8")
    record = _canon_record("a", "src/python_scripts/foo.py")
    record["text"] = _code_block_text("VALUE = 1\n")

    result = authority.classify_content_authority(record, tmp_path)

    assert result["classification"] == "CONTENT_MISMATCH"
    assert result["classification"] not in authority.DETERMINISTIC_CURRENT_REPO_ARTIFACT
    assert result["classification"] in authority.REQUIRES_HUMAN_REVIEW


def test_no_code_block_requires_human_review_not_silent_accept(tmp_path: Path) -> None:
    real = tmp_path / "src" / "python_scripts" / "foo.py"
    real.parent.mkdir(parents=True)
    real.write_text("VALUE = 1\n", encoding="utf-8")
    record = _canon_record("a", "src/python_scripts/foo.py")
    record["text"] = "## [[Tags]]\n\njust narrative text, no fenced code block"

    result = authority.classify_content_authority(record, tmp_path)

    assert result["classification"] == "NO_CODE_BLOCK"
    assert result["classification"] in authority.REQUIRES_HUMAN_REVIEW


def test_normalized_newline_match_is_deterministic(tmp_path: Path) -> None:
    # Path.read_text() applies universal-newline translation on read (\r\n ->
    # \n), so a worktree \r\n file reads back as plain \n. To exercise the
    # normalization branch, the DIFFERENCE must instead live on the canon
    # side (a \r\n sequence captured verbatim inside the JSON-encoded text,
    # which json.loads() preserves literally, unaffected by that read-time
    # translation).
    real = tmp_path / "src" / "python_scripts" / "foo.py"
    real.parent.mkdir(parents=True)
    real.write_text("VALUE = 1\n", encoding="utf-8")
    record = _canon_record("a", "src/python_scripts/foo.py")
    record["text"] = _code_block_text("VALUE = 1\r\n")

    result = authority.classify_content_authority(record, tmp_path)

    assert result["classification"] == "CONTENT_NORMALIZED_MATCH"
    assert result["classification"] in authority.DETERMINISTIC_CURRENT_REPO_ARTIFACT


# ---------------------------------------------------------------------------
# build_lifecycle_authority_report: population scope, no Canon writes
# ---------------------------------------------------------------------------

def test_report_separates_governed_from_missing_and_never_writes_canon(tmp_path: Path) -> None:
    local_root = tmp_path / "local"
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "python_scripts").mkdir(parents=True)
    (repo_root / "src" / "python_scripts" / "governed.py").write_text("A = 1\n", encoding="utf-8")
    (repo_root / "src" / "python_scripts" / "ungoverned.py").write_text("B = 1\n", encoding="utf-8")

    governed = _canon_record("g", "src/python_scripts/governed.py", lifecycle="current_repo_artifact")
    governed["source_fields"]["repo_path"] = "src/python_scripts/governed.py"
    ungoverned = _canon_record("u", "src/python_scripts/ungoverned.py")
    ungoverned["text"] = _code_block_text("B = 1\n")
    not_repo_like = {"id": "n", "title": "Some narrative diagnostic", "text": "", "source_fields": {}}

    _write_canon(local_root, [governed, ungoverned, not_repo_like])
    canon_before = (local_root / "tiddlers_1.jsonl").read_bytes()

    report = authority.build_lifecycle_authority_report(
        local_root, repo_root, gate_report_path=local_root / "does_not_exist.json",
    )

    assert (local_root / "tiddlers_1.jsonl").read_bytes() == canon_before
    assert report["repo_like_records_total"] == 2  # not_repo_like excluded
    assert report["already_have_lifecycle"] == 1
    assert report["missing_lifecycle_total"] == 1
    assert report["missing_lifecycle_by_classification"] == {"CONTENT_EXACT_MATCH": 1}
    assert report["deterministic_current_repo_artifact_count"] == 1
    assert report["requires_human_review_count"] == 0
    assert report["gate_020_cross_reference"] == {"gate_report_found": False}


def test_report_cross_references_gate_020_and_distinguishes_resolvable_from_review(tmp_path: Path) -> None:
    local_root = tmp_path / "local"
    repo_root = tmp_path / "repo"
    current_dir = local_root / "pipeline" / "relation_candidates" / "current"
    current_dir.mkdir(parents=True)
    (repo_root / "src" / "python_scripts").mkdir(parents=True)
    (repo_root / "src" / "python_scripts" / "clean.py").write_text("A = 1\n", encoding="utf-8")
    (repo_root / "src" / "python_scripts" / "drifted.py").write_text("B = 2\n", encoding="utf-8")

    clean = _canon_record("clean-id", "src/python_scripts/clean.py")
    clean["text"] = _code_block_text("A = 1\n")
    drifted = _canon_record("drifted-id", "src/python_scripts/drifted.py")
    drifted["text"] = _code_block_text("B = 1\n")  # mismatched on purpose
    target = _canon_record("target-id", "src/python_scripts/target.py", lifecycle="current_repo_artifact")
    _write_canon(local_root, [clean, drifted, target])

    (current_dir / "ready_for_human_review.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in [
            {"candidate_id": "rc_current_" + "1" * 24, "source": {"canonical_id": "clean-id"}, "target": {"canonical_id": "target-id"}},
            {"candidate_id": "rc_current_" + "2" * 24, "source": {"canonical_id": "drifted-id"}, "target": {"canonical_id": "target-id"}},
        ]),
        encoding="utf-8",
    )
    gate_report_path = tmp_path / "admission_gate_dry_run.json"
    gate_report_path.write_text(json.dumps({
        "items": [
            {
                "candidate_id": "rc_current_" + "1" * 24, "human_review_decision": "approved_for_admission",
                "all_block_reasons": ["GATE-020: source.lifecycle_state ausente."],
            },
            {
                "candidate_id": "rc_current_" + "2" * 24, "human_review_decision": "approved_for_admission",
                "all_block_reasons": ["GATE-020: source.lifecycle_state ausente."],
            },
        ],
    }), encoding="utf-8")

    report = authority.build_lifecycle_authority_report(local_root, repo_root, gate_report_path=gate_report_path)

    gate = report["gate_020_cross_reference"]
    assert gate["gate_report_found"] is True
    assert gate["approved_but_blocked_by_gate_020"] == 2
    assert gate["would_resolve_via_deterministic_content_match"] == 1
    assert gate["still_requires_human_review"] == 1


def test_render_compact_is_human_readable_and_short() -> None:
    fake_report = {
        "repo_like_records_total": 679, "already_have_lifecycle": 154, "missing_lifecycle_total": 525,
        "missing_lifecycle_by_classification": {"CONTENT_EXACT_MATCH": 509, "CONTENT_MISMATCH": 16},
        "deterministic_current_repo_artifact_count": 509, "requires_human_review_count": 16,
        "gate_020_cross_reference": {
            "gate_report_found": True, "approved_but_blocked_by_gate_020": 97,
            "would_resolve_via_deterministic_content_match": 86, "still_requires_human_review": 11,
        },
        "ownership_finding": {"repo_lifecycle_state": "CANON_DERIVED", "materialization_owner": "governed pipeline"},
    }
    rendered = authority.render_compact(fake_report)
    assert "679" in rendered
    assert "CANON_DERIVED" in rendered
    assert len(rendered.splitlines()) < 25


# ---------------------------------------------------------------------------
# Forward-looking safety: repo_root is an explicit parameter, not global
# state, so two repositories sharing the same relative path can never be
# conflated by this module (S0186 Unit H: "repository_id + repository_revision
# + repo_path + repo_lifecycle_state" future model -- two repos with the same
# relative path must never share identity).
# ---------------------------------------------------------------------------

def test_same_relative_path_in_two_different_repo_roots_never_collides(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    (repo_a / "src" / "python_scripts").mkdir(parents=True)
    (repo_b / "src" / "python_scripts").mkdir(parents=True)
    (repo_a / "src" / "python_scripts" / "shared_name.py").write_text("A = 1\n", encoding="utf-8")
    (repo_b / "src" / "python_scripts" / "shared_name.py").write_text("B = 2\n", encoding="utf-8")

    record = _canon_record("shared-id", "src/python_scripts/shared_name.py")
    record["text"] = _code_block_text("A = 1\n")

    result_a = authority.classify_content_authority(record, repo_a)
    result_b = authority.classify_content_authority(record, repo_b)

    assert result_a["classification"] == "CONTENT_EXACT_MATCH"
    assert result_b["classification"] == "CONTENT_MISMATCH"
    assert result_a["classification"] != result_b["classification"]


def test_ambiguous_lifecycle_evidence_is_never_auto_classified_as_current(tmp_path: Path) -> None:
    # A record with content that cannot be positively verified either way
    # (no extractable code block to compare) must be routed to human review,
    # never silently treated as current_repo_artifact by default.
    real = tmp_path / "src" / "python_scripts" / "ambiguous.py"
    real.parent.mkdir(parents=True)
    real.write_text("VALUE = 1\n", encoding="utf-8")
    record = _canon_record("ambiguous-id", "src/python_scripts/ambiguous.py")
    record["text"] = "## [[Tags]]\n\nNo fenced code block, just narrative prose about the file."

    result = authority.classify_content_authority(record, tmp_path)

    assert result["classification"] not in authority.DETERMINISTIC_CURRENT_REPO_ARTIFACT
    assert result["classification"] in authority.REQUIRES_HUMAN_REVIEW
