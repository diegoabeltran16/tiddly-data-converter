"""S0186 Closure Prep, Track B Lane A: tests for repo_artifact_content_refresh.py.

Every test builds an isolated canon + repo_root under tmp_path; nothing
here ever touches the real repository's Canon or its own source files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import normalize_session_titles as nst  # noqa: E402
import repo_artifact_content_refresh as rac  # noqa: E402


def _fenced_text(header: str, lang: str, code: str) -> str:
    return f"{header}\n\n```{lang}\n{code}\n```"


def _repo_artifact_record(
    title: str,
    *,
    repo_path: str,
    code: str,
    created: str = "20260101000000000",
    modified: str = "20260101000000000",
    lang: str = "Python",
    is_current: str = "true",
) -> dict:
    """Build a canon_preflight --strict-valid repo-artifact record with the

    FULL real field set (matching a live production repo-artifact record's
    exact key list -- see the S0186 Closure Prep investigation that
    inspected shell_scripts/baseline_verify.sh's real Canon record), not a
    minimal subset. Using the SAME official identity functions
    repo_artifact_content_refresh.py itself imports.

    A minimal fixture (missing is_binary/is_reference_only/order_in_document/
    etc.) previously caused a false-positive UNEXPECTED classification: the
    official Go normalize step fills in genuinely-missing default fields
    for any incomplete record, which is correct behavior but is not what
    real, already-complete repo-artifact records ever need -- the fixture
    was the gap, not the writer.
    """
    key = nst._recompute_key(title)
    record_id = nst._recompute_id(key)
    slug = nst._recompute_canonical_slug(title)
    text = _fenced_text(f"## [[Tags]]\n[[{repo_path}]]", lang, code)
    version_id = nst._recompute_version_id(key, title, text, created, modified)
    return {
        "schema_version": "v0",
        "id": record_id,
        "key": key,
        "title": title,
        "canonical_slug": slug,
        "text": text,
        "content": None,
        "content_type": "text/markdown",
        "modality": "mixed",
        "encoding": "utf-8",
        "is_binary": False,
        "is_reference_only": False,
        "mime_type": "text/markdown",
        "document_id": nst._recompute_id(f"doc:{key}"),
        "raw_payload_ref": f"node:{record_id}",
        "role_primary": "code",
        "relations": None,
        "section_path": None,
        "semantic_text": None,
        "source_position": "html:block0:tiddler0",
        "source_type": "text/markdown",
        "order_in_document": 0,
        "tags": [repo_path],
        "source_tags": [repo_path],
        "normalized_tags": [repo_path.lower()],
        "created": created,
        "modified": modified,
        "version_id": version_id,
        "source_fields": {
            "is_current_repo_artifact": is_current,
            "repo_path": repo_path,
            "repo_lifecycle_state": "current_repo_artifact",
        },
    }


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    return path


def _canon(tmp_path: Path, shards: dict[str, list[dict]]) -> Path:
    canon_dir = tmp_path / "canon"
    for name, rows in shards.items():
        _write_jsonl(canon_dir / name, rows)
    return canon_dir


def _repo_file(tmp_path: Path, rel: str, content: str) -> Path:
    path = tmp_path / "repo" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return tmp_path / "repo"


# ---------------------------------------------------------------------------
# DISCOVER
# ---------------------------------------------------------------------------


def test_already_current_record_excluded_from_discovery(tmp_path: Path) -> None:
    code = "print('hello')\n"
    record = _repo_artifact_record("demo.py", repo_path="demo.py", code=code)
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [record]})
    repo_root = _repo_file(tmp_path, "demo.py", code)

    stale = rac.discover_live_stale(canon_dir, repo_root)

    assert stale == []


def test_stale_record_discovered_live_not_hardcoded(tmp_path: Path) -> None:
    old_code = "print('old')\n"
    new_code = "print('new')\n"
    record = _repo_artifact_record("demo.py", repo_path="demo.py", code=old_code)
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [record]})
    repo_root = _repo_file(tmp_path, "demo.py", new_code)

    stale = rac.discover_live_stale(canon_dir, repo_root)

    assert len(stale) == 1
    assert stale[0].canon_record_id == record["id"]
    # DISCOVER is a fresh scan every call -- adding a second stale record
    # must surface it too, proving nothing was cached/hardcoded.
    record2 = _repo_artifact_record("other.py", repo_path="other.py", code="a = 1\n")
    _write_jsonl(canon_dir / "tiddlers_1.jsonl", [record, record2])
    _repo_file(tmp_path, "other.py", "a = 2\n")
    stale2 = rac.discover_live_stale(canon_dir, repo_root)
    assert {s.canon_record_id for s in stale2} == {record["id"], record2["id"]}


def test_stale_s0146_cache_cannot_override_live() -> None:
    """The module's prose explains WHY it avoids the stale S0146 cache --

    that mention is expected. What must never appear is an actual
    reference to the cache file/module itself as a currentness source.
    """
    source = Path(rac.__file__).read_text(encoding="utf-8")
    import_lines = [line for line in source.splitlines() if line.strip().startswith(("import ", "from "))]
    joined_imports = "\n".join(import_lines)
    # the modules that actually read the stale S0146 classification cache
    # must never be imported here -- that would be the real contamination risk
    assert "build_repo_metadata_patch_preview" not in joined_imports
    assert "repo_metadata_admission_gate" not in joined_imports
    assert "repo_metadata_refresh_patch" not in joined_imports
    # and the module must never construct the cache's own file path
    assert 'repo_artifacts" / "s0146"' not in source


# ---------------------------------------------------------------------------
# PLAN
# ---------------------------------------------------------------------------


def _stale_fixture(tmp_path: Path, *, old_code: str = "print('old')\n", new_code: str = "print('new')\n"):
    record = _repo_artifact_record("demo.py", repo_path="demo.py", code=old_code)
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [record]})
    repo_root = _repo_file(tmp_path, "demo.py", new_code)
    return record, canon_dir, repo_root


def test_official_version_id_parity(tmp_path: Path) -> None:
    record, canon_dir, repo_root = _stale_fixture(tmp_path)
    plan = rac.build_plan(canon_dir, repo_root)
    entry = plan.entries[0]

    expected = nst._recompute_version_id(record["key"], record["title"], entry.new_text, record["created"], entry.new_modified)

    assert entry.projected_version_id == expected


def test_plan_preserves_identity_fields(tmp_path: Path) -> None:
    record, canon_dir, repo_root = _stale_fixture(tmp_path)
    plan = rac.build_plan(canon_dir, repo_root)
    entry = plan.entries[0]

    assert entry.canon_record_id == record["id"]
    assert set(entry.fields_expected_to_change) == {"text", "version_id"}
    for identity_field in rac.IDENTITY_FIELDS:
        assert identity_field not in entry.fields_expected_to_change


def test_plan_scope_is_not_hardcoded_length(tmp_path: Path) -> None:
    """Guards against ever reintroducing a hardcoded '61 records' assumption."""
    record, canon_dir, repo_root = _stale_fixture(tmp_path)
    plan_one = rac.build_plan(canon_dir, repo_root)
    assert plan_one.ready_count == 1

    record2 = _repo_artifact_record("second.py", repo_path="second.py", code="x = 1\n")
    _write_jsonl(canon_dir / "tiddlers_1.jsonl", [json.loads(l) for l in (canon_dir / "tiddlers_1.jsonl").read_text().splitlines()] + [record2])
    _repo_file(tmp_path, "second.py", "x = 2\n")
    plan_two = rac.build_plan(canon_dir, repo_root)
    assert plan_two.ready_count == 2
    assert plan_two.plan_hash != plan_one.plan_hash


# ---------------------------------------------------------------------------
# PROJECTED CANON + PREFLIGHT
# ---------------------------------------------------------------------------


def test_normalize_scope_is_exactly_content_no_unexpected(tmp_path: Path) -> None:
    """B2: official normalize's only contractual side effect on a

    complete, real-shaped fixture record must be `content` -- nothing else.
    """
    record, canon_dir, repo_root = _stale_fixture(tmp_path)
    plan = rac.build_plan(canon_dir, repo_root)

    result = rac.validate_projected_canon(plan, canon_dir, tmp_path / "out")

    assert result["unexpected_normalized_changes"] == 0, result["normalize_scope_classifications"]
    classifications = result["normalize_scope_classifications"]
    assert len(classifications) == 1
    assert set(classifications[0]["direct_refresh"]) == {"text", "version_id"}
    assert classifications[0]["required_derivation"] == ["content"]
    assert classifications[0]["unexpected"] == []


def test_projected_strict_pass(tmp_path: Path) -> None:
    record, canon_dir, repo_root = _stale_fixture(tmp_path)
    plan = rac.build_plan(canon_dir, repo_root)

    result = rac.validate_projected_canon(plan, canon_dir, tmp_path / "out")

    assert result["projected_strict"]["passed"] is True, result["projected_strict"]


def test_projected_reverse_preflight_pass(tmp_path: Path) -> None:
    record, canon_dir, repo_root = _stale_fixture(tmp_path)
    plan = rac.build_plan(canon_dir, repo_root)

    result = rac.validate_projected_canon(plan, canon_dir, tmp_path / "out")

    assert result["projected_reverse_preflight"]["passed"] is True, result["projected_reverse_preflight"]


def test_real_canon_untouched_by_projected_validation(tmp_path: Path) -> None:
    record, canon_dir, repo_root = _stale_fixture(tmp_path)
    before = (canon_dir / "tiddlers_1.jsonl").read_bytes()
    plan = rac.build_plan(canon_dir, repo_root)

    rac.validate_projected_canon(plan, canon_dir, tmp_path / "out")

    after = (canon_dir / "tiddlers_1.jsonl").read_bytes()
    assert before == after


# ---------------------------------------------------------------------------
# APPLY / RECEIPT / VALIDATE LIVE / ROLLBACK
# ---------------------------------------------------------------------------


def test_same_id_content_refresh_pass(tmp_path: Path) -> None:
    record, canon_dir, repo_root = _stale_fixture(tmp_path)
    out_dir = tmp_path / "out"
    plan = rac.build_plan(canon_dir, repo_root)

    report = rac.apply_plan(plan, canon_dir=canon_dir, repo_root=repo_root, out_dir=out_dir, apply_token=rac.APPLY_TOKEN)

    assert report["apply_executed"] is True, report
    assert report["records_modified"] == 1
    assert report["canon_modified"] is True

    rows = [json.loads(l) for l in (canon_dir / "tiddlers_1.jsonl").read_text().splitlines()]
    updated = rows[0]
    assert updated["id"] == record["id"]
    assert updated["key"] == record["key"]
    assert updated["title"] == record["title"]
    assert updated["canonical_slug"] == record["canonical_slug"]
    assert updated["created"] == record["created"]
    assert updated["text"] != record["text"]
    assert updated["modified"] == record["modified"]  # deliberately preserved -- no contract requires bumping it
    assert updated["version_id"] != record["version_id"]

    validation = rac.validate_live_canon(plan, canon_dir, repo_root)
    assert validation["remaining_substantive_diff"] == 0


def test_apply_without_valid_token_rejected(tmp_path: Path) -> None:
    record, canon_dir, repo_root = _stale_fixture(tmp_path)
    before = (canon_dir / "tiddlers_1.jsonl").read_bytes()
    plan = rac.build_plan(canon_dir, repo_root)

    report = rac.apply_plan(plan, canon_dir=canon_dir, repo_root=repo_root, out_dir=tmp_path / "out", apply_token="wrong phrase")

    assert report["apply_executed"] is False
    assert report["block_reason"] == "invalid_or_missing_apply_token"
    assert (canon_dir / "tiddlers_1.jsonl").read_bytes() == before


def test_unrelated_field_mutation_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Narrows the allowed-fields scope to prove the guard actually fires

    when a change would fall outside it -- 'version_id' is a real, needed
    change, so shrinking the allowlist to exclude it must raise.
    """
    record, canon_dir, repo_root = _stale_fixture(tmp_path)
    plan = rac.build_plan(canon_dir, repo_root)
    entry = plan.entries[0]

    monkeypatch.setattr(rac, "ALLOWED_CHANGED_TOP_LEVEL_FIELDS", frozenset({"text"}))

    with pytest.raises(RuntimeError, match="unexpected field mutation outside allowed scope"):
        rac._apply_entry_to_record(dict(record), entry)


def test_repo_source_drift_between_plan_and_apply_blocked(tmp_path: Path) -> None:
    record, canon_dir, repo_root = _stale_fixture(tmp_path)
    plan = rac.build_plan(canon_dir, repo_root)

    # The live file changes again after the plan was bound.
    (repo_root / "demo.py").write_text("print('drifted again')\n", encoding="utf-8")

    report = rac.apply_plan(plan, canon_dir=canon_dir, repo_root=repo_root, out_dir=tmp_path / "out", apply_token=rac.APPLY_TOKEN)

    assert report["apply_executed"] is False
    assert report["block_reason"] == "plan_drift_detected_recompute_before_reauthorizing"
    rows = [json.loads(l) for l in (canon_dir / "tiddlers_1.jsonl").read_text().splitlines()]
    assert rows[0]["text"] == record["text"]  # untouched


def test_canon_drift_between_plan_and_apply_blocked(tmp_path: Path) -> None:
    record, canon_dir, repo_root = _stale_fixture(tmp_path)
    plan = rac.build_plan(canon_dir, repo_root)

    # Canon changes (an unrelated record admitted) after the plan was bound.
    other = _repo_artifact_record("bystander.py", repo_path="bystander.py", code="y = 1\n")
    _repo_file(tmp_path, "bystander.py", "y = 1\n")
    rows = [json.loads(l) for l in (canon_dir / "tiddlers_1.jsonl").read_text().splitlines()]
    rows.append(other)
    _write_jsonl(canon_dir / "tiddlers_1.jsonl", rows)

    report = rac.apply_plan(plan, canon_dir=canon_dir, repo_root=repo_root, out_dir=tmp_path / "out", apply_token=rac.APPLY_TOKEN)

    assert report["apply_executed"] is False
    assert report["block_reason"] == "plan_drift_detected_recompute_before_reauthorizing"


def test_rollback_restores_exact_preimage(tmp_path: Path) -> None:
    record, canon_dir, repo_root = _stale_fixture(tmp_path)
    out_dir = tmp_path / "out"
    plan = rac.build_plan(canon_dir, repo_root)
    before_bytes = (canon_dir / "tiddlers_1.jsonl").read_bytes()

    report = rac.apply_plan(plan, canon_dir=canon_dir, repo_root=repo_root, out_dir=out_dir, apply_token=rac.APPLY_TOKEN)
    assert report["apply_executed"] is True
    assert (canon_dir / "tiddlers_1.jsonl").read_bytes() != before_bytes

    rollback_report = rac.rollback(plan.plan_id, out_dir=out_dir, canon_dir=canon_dir)

    assert rollback_report["rollback_executed"] is True
    assert (canon_dir / "tiddlers_1.jsonl").read_bytes() == before_bytes


## ---------------------------------------------------------------------------
## MULTI_BLOCK_DOCUMENT_REFRESH -- a separate, narrow, typed lane (S0186
## Closure Prep, 2026-09-08). Fixture: a live "document" containing several
## real fenced examples plus interstitial prose, wrapped the same way real
## .github/instructions/*.md repo-artifact records are (## [[Tags]]... +
## one outer ```Markdown fence). Go's ExtractCodeBlocks pairs ``` markers
## purely positionally (empirically verified, not assumed) -- these tests
## never hardcode "N examples -> N blocks"; they discover the real block
## count from Go itself, the same way the production code does.
## ---------------------------------------------------------------------------


def _multi_block_live_content(variant: str) -> str:
    return (
        "---\n"
        "description: test doc\n"
        "---\n\n"
        "# Section 1\n\n"
        "Some prose here.\n\n"
        "```bash\n"
        f"echo {variant}-one\n"
        "```\n\n"
        "More interstitial prose, unique to this document.\n\n"
        "```python\n"
        f"x = '{variant}-two'\n"
        "```\n\n"
        f"Final prose section, variant {variant}.\n"
    )


def _multi_block_record(title: str, *, repo_path: str, variant: str, created: str = "20260101000000000", modified: str = "20260101000000000") -> dict:
    key = nst._recompute_key(title)
    record_id = nst._recompute_id(key)
    slug = nst._recompute_canonical_slug(title)
    text = f"## [[Tags]]\n[[{repo_path}]]\n\n```Markdown\n{_multi_block_live_content(variant)}\n```"
    version_id = nst._recompute_version_id(key, title, text, created, modified)
    return {
        "schema_version": "v0", "id": record_id, "key": key, "title": title, "canonical_slug": slug,
        "text": text, "content": None, "content_type": "text/markdown", "modality": "mixed",
        "encoding": "utf-8", "is_binary": False, "is_reference_only": False, "mime_type": "text/markdown",
        "document_id": nst._recompute_id(f"doc:{key}"), "raw_payload_ref": f"node:{record_id}",
        "role_primary": "code", "relations": None, "section_path": None, "semantic_text": None,
        "source_position": "html:block0:tiddler0", "source_type": "text/markdown", "order_in_document": 0,
        "tags": [repo_path], "source_tags": [repo_path], "normalized_tags": [repo_path.lower()],
        "created": created, "modified": modified, "version_id": version_id,
        "source_fields": {"is_current_repo_artifact": "true", "repo_path": repo_path, "repo_lifecycle_state": "current_repo_artifact"},
    }


def _multi_block_stale_fixture(tmp_path: Path):
    record = _multi_block_record("docs/example.md", repo_path="docs/example.md", variant="old")
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [record]})
    repo_root = _repo_file(tmp_path, "docs/example.md", _multi_block_live_content("new"))
    return record, canon_dir, repo_root


class TestMultiBlockDocumentRefresh:
    def test_single_block_document_remains_supported(self, tmp_path: Path) -> None:
        """The original, single-fence lane must be unaffected by adding

        multi-block support alongside it.
        """
        record, canon_dir, repo_root = _stale_fixture(tmp_path)
        plan = rac.build_plan(canon_dir, repo_root)
        assert plan.ready_count == 1
        assert plan.entries[0].is_multi_block_document is False
        assert plan.entries[0].intended_action == "REPO_ARTIFACT_CONTENT_REFRESH"

    def test_multi_block_document_supported(self, tmp_path: Path) -> None:
        record, canon_dir, repo_root = _multi_block_stale_fixture(tmp_path)
        plan = rac.build_plan(canon_dir, repo_root)

        assert plan.ready_count == 1, plan.entries
        entry = plan.entries[0]
        assert entry.is_multi_block_document is True
        assert entry.intended_action == "MULTI_BLOCK_DOCUMENT_REFRESH"
        assert entry.block_correspondence is not None
        assert entry.block_correspondence["block_count_matches"] is True
        assert entry.block_correspondence["block_text_matches_in_order"] is True
        assert entry.block_correspondence["actual_block_count"] > 1  # genuinely multi-block, discovered not assumed

    def test_nested_fence_examples_supported(self, tmp_path: Path) -> None:
        """Both fenced examples (bash + python) survive the refresh intact."""
        record, canon_dir, repo_root = _multi_block_stale_fixture(tmp_path)
        plan = rac.build_plan(canon_dir, repo_root)
        entry = plan.entries[0]
        assert "echo new-one" in entry.new_text
        assert "x = 'new-two'" in entry.new_text
        assert "echo old-one" not in entry.new_text

    def test_interstitial_prose_preserved(self, tmp_path: Path) -> None:
        record, canon_dir, repo_root = _multi_block_stale_fixture(tmp_path)
        plan = rac.build_plan(canon_dir, repo_root)
        entry = plan.entries[0]
        assert "More interstitial prose, unique to this document." in entry.new_text
        assert "Final prose section, variant new." in entry.new_text
        assert "# Section 1" in entry.new_text

    def test_already_current_multi_block_document_excluded_from_discovery(self, tmp_path: Path) -> None:
        """The real finding this whole lane exists for: a multi-block

        document whose text ALREADY matches the live file exactly must
        never be misclassified as stale (compare_content()'s single-block
        model would wrongly flag it substantive_diff).
        """
        live_content = _multi_block_live_content("same")
        record = _multi_block_record("docs/example.md", repo_path="docs/example.md", variant="same")
        canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [record]})
        repo_root = _repo_file(tmp_path, "docs/example.md", live_content)

        stale = rac.discover_live_stale(canon_dir, repo_root)

        assert stale == []

    def test_unexpected_trailer_blocks(self, tmp_path: Path) -> None:
        """A record with content AFTER the closing fence is not a shape

        this lane's whole-region model can safely handle -- must block,
        never guess where the 'real' boundary is.
        """
        record = _multi_block_record("docs/example.md", repo_path="docs/example.md", variant="old")
        record["text"] = record["text"] + "\nunexpected trailing content"
        canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [record]})
        repo_root = _repo_file(tmp_path, "docs/example.md", _multi_block_live_content("new"))

        stale = rac.discover_live_stale(canon_dir, repo_root)

        assert stale == []  # not_applicable -> excluded, not silently guessed

    def test_repo_drift_blocks_multi_block_entry(self, tmp_path: Path) -> None:
        record, canon_dir, repo_root = _multi_block_stale_fixture(tmp_path)
        plan = rac.build_plan(canon_dir, repo_root)

        (repo_root / "docs/example.md").write_text(_multi_block_live_content("drifted-again"), encoding="utf-8")

        report = rac.apply_plan(plan, canon_dir=canon_dir, repo_root=repo_root, out_dir=tmp_path / "out", apply_token=rac.APPLY_TOKEN)

        assert report["apply_executed"] is False
        assert report["block_reason"] == "plan_drift_detected_recompute_before_reauthorizing"

    def test_canon_drift_blocks_multi_block_entry(self, tmp_path: Path) -> None:
        record, canon_dir, repo_root = _multi_block_stale_fixture(tmp_path)
        plan = rac.build_plan(canon_dir, repo_root)

        other = _repo_artifact_record("bystander.py", repo_path="bystander.py", code="y = 1\n")
        _repo_file(tmp_path, "bystander.py", "y = 1\n")
        rows = [json.loads(l) for l in (canon_dir / "tiddlers_1.jsonl").read_text().splitlines()]
        rows.append(other)
        _write_jsonl(canon_dir / "tiddlers_1.jsonl", rows)

        report = rac.apply_plan(plan, canon_dir=canon_dir, repo_root=repo_root, out_dir=tmp_path / "out", apply_token=rac.APPLY_TOKEN)

        assert report["apply_executed"] is False
        assert report["block_reason"] == "plan_drift_detected_recompute_before_reauthorizing"

    def test_normalize_produces_no_unrelated_mutation_for_multi_block(self, tmp_path: Path) -> None:
        record, canon_dir, repo_root = _multi_block_stale_fixture(tmp_path)
        plan = rac.build_plan(canon_dir, repo_root)

        result = rac.validate_projected_canon(plan, canon_dir, tmp_path / "out")

        assert result["unexpected_normalized_changes"] == 0, result["normalize_scope_classifications"]
        assert result["all_passed"] is True

    def test_exact_rollback_restoration_for_multi_block(self, tmp_path: Path) -> None:
        record, canon_dir, repo_root = _multi_block_stale_fixture(tmp_path)
        out_dir = tmp_path / "out"
        plan = rac.build_plan(canon_dir, repo_root)
        before_bytes = (canon_dir / "tiddlers_1.jsonl").read_bytes()

        report = rac.apply_plan(plan, canon_dir=canon_dir, repo_root=repo_root, out_dir=out_dir, apply_token=rac.APPLY_TOKEN)
        assert report["apply_executed"] is True, report
        assert (canon_dir / "tiddlers_1.jsonl").read_bytes() != before_bytes

        rollback_report = rac.rollback(plan.plan_id, out_dir=out_dir, canon_dir=canon_dir)

        assert rollback_report["rollback_executed"] is True
        assert (canon_dir / "tiddlers_1.jsonl").read_bytes() == before_bytes

    def test_multi_block_apply_preserves_identity_and_lifecycle(self, tmp_path: Path) -> None:
        record, canon_dir, repo_root = _multi_block_stale_fixture(tmp_path)
        out_dir = tmp_path / "out"
        plan = rac.build_plan(canon_dir, repo_root)

        report = rac.apply_plan(plan, canon_dir=canon_dir, repo_root=repo_root, out_dir=out_dir, apply_token=rac.APPLY_TOKEN)
        assert report["apply_executed"] is True

        rows = [json.loads(l) for l in (canon_dir / "tiddlers_1.jsonl").read_text().splitlines()]
        updated = rows[0]
        assert updated["id"] == record["id"]
        assert updated["key"] == record["key"]
        assert updated["title"] == record["title"]
        assert updated["created"] == record["created"]
        assert updated["modified"] == record["modified"]
        assert updated["source_fields"] == record["source_fields"]
        assert updated["relations"] == record["relations"]
        assert updated["text"] != record["text"]
        assert updated["version_id"] != record["version_id"]


def test_apply_blocked_when_no_ready_entries(tmp_path: Path) -> None:
    code = "print('same')\n"
    record = _repo_artifact_record("demo.py", repo_path="demo.py", code=code)
    canon_dir = _canon(tmp_path, {"tiddlers_1.jsonl": [record]})
    repo_root = _repo_file(tmp_path, "demo.py", code)
    plan = rac.build_plan(canon_dir, repo_root)
    assert plan.ready_count == 0

    report = rac.apply_plan(plan, canon_dir=canon_dir, repo_root=repo_root, out_dir=tmp_path / "out", apply_token=rac.APPLY_TOKEN)

    assert report["apply_executed"] is False
    assert report["block_reason"] == "no_ready_entries"
