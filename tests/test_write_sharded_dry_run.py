"""
Characterization and safety tests for write_sharded() dry-run mode — S0111.

Validates:
  1. Non-write: dry_run=True never creates, modifies, or deletes files.
  2. Plan observability: dry_run=True returns a verifiable plan dict.
  3. Plan-write equivalence: plan shards match real write output in tmp_path.
  4. Prefix isolation: a prefix only touches its own shards.
  5. Backward compatibility: dry_run=False (default) preserves existing behavior.
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

from derive_layers import write_sharded, _plan_shards


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_records(n: int) -> list:
    return [{"id": i, "text": f"record {i}"} for i in range(n)]


# ── Non-write guarantees (dry_run=True) ───────────────────────────────────────

class TestDryRunNoWrite:
    """dry_run=True must never touch the filesystem."""

    def test_does_not_create_directory(self, tmp_path):
        target = tmp_path / "new_subdir"
        assert not target.exists()
        write_sharded(_make_records(5), target, "pfx", 3, dry_run=True)
        assert not target.exists()

    def test_does_not_create_jsonl_files(self, tmp_path):
        write_sharded(_make_records(5), tmp_path, "pfx", 3, dry_run=True)
        assert list(tmp_path.glob("pfx_*.jsonl")) == []

    def test_does_not_modify_existing_files(self, tmp_path):
        existing = tmp_path / "pfx_1.jsonl"
        existing.write_text("original content\n", encoding="utf-8")
        mtime_before = existing.stat().st_mtime

        write_sharded(_make_records(5), tmp_path, "pfx", 3, dry_run=True)

        assert existing.read_text(encoding="utf-8") == "original content\n"
        assert existing.stat().st_mtime == mtime_before

    def test_does_not_delete_existing_prefix_files(self, tmp_path):
        (tmp_path / "pfx_1.jsonl").write_text("{}\n")
        (tmp_path / "pfx_2.jsonl").write_text("{}\n")

        write_sharded(_make_records(5), tmp_path, "pfx", 3, dry_run=True)

        assert (tmp_path / "pfx_1.jsonl").exists()
        assert (tmp_path / "pfx_2.jsonl").exists()

    def test_does_not_delete_other_prefix_files(self, tmp_path):
        (tmp_path / "other_1.jsonl").write_text("{}\n")
        write_sharded(_make_records(5), tmp_path, "pfx", 3, dry_run=True)
        assert (tmp_path / "other_1.jsonl").exists()


# ── Plan observability (dry_run=True) ────────────────────────────────────────

class TestDryRunPlan:
    """dry_run=True must return a complete, accurate write plan."""

    def test_returns_dict(self, tmp_path):
        result = write_sharded(_make_records(5), tmp_path, "pfx", 3, dry_run=True)
        assert isinstance(result, dict)

    def test_dry_run_flag_is_true(self, tmp_path):
        result = write_sharded(_make_records(5), tmp_path, "pfx", 3, dry_run=True)
        assert result["dry_run"] is True

    def test_output_dir_in_plan(self, tmp_path):
        result = write_sharded(_make_records(5), tmp_path, "pfx", 3, dry_run=True)
        assert result["output_dir"] == str(tmp_path)

    def test_prefix_in_plan(self, tmp_path):
        result = write_sharded(_make_records(5), tmp_path, "pfx", 3, dry_run=True)
        assert result["prefix"] == "pfx"

    def test_shard_size_in_plan(self, tmp_path):
        result = write_sharded(_make_records(5), tmp_path, "pfx", 3, dry_run=True)
        assert result["shard_size"] == 3

    def test_total_records_correct(self, tmp_path):
        records = _make_records(7)
        result = write_sharded(records, tmp_path, "pfx", 3, dry_run=True)
        assert result["total_records"] == 7

    def test_shard_count_correct(self, tmp_path):
        # 7 records, shard_size=3 → 3 shards (3+3+1)
        result = write_sharded(_make_records(7), tmp_path, "pfx", 3, dry_run=True)
        assert result["shard_count"] == 3

    def test_shards_to_write_structure(self, tmp_path):
        result = write_sharded(_make_records(7), tmp_path, "pfx", 3, dry_run=True)
        shards = result["shards_to_write"]
        assert isinstance(shards, list)
        assert len(shards) == 3
        for shard in shards:
            assert "file" in shard
            assert "shard_index" in shard
            assert "record_count" in shard
            assert shard["file"].startswith("pfx_")
            assert shard["file"].endswith(".jsonl")

    def test_shards_to_write_record_counts(self, tmp_path):
        # 7 records, shard_size=3 → shards of 3, 3, 1
        result = write_sharded(_make_records(7), tmp_path, "pfx", 3, dry_run=True)
        counts = [s["record_count"] for s in result["shards_to_write"]]
        assert counts == [3, 3, 1]
        assert sum(counts) == 7

    def test_stale_shards_empty_when_dir_does_not_exist(self, tmp_path):
        target = tmp_path / "nonexistent"
        result = write_sharded(_make_records(5), target, "pfx", 3, dry_run=True)
        assert result["stale_shards_to_delete"] == []

    def test_stale_shards_lists_existing_prefix_files(self, tmp_path):
        (tmp_path / "pfx_1.jsonl").write_text("{}\n")
        (tmp_path / "pfx_2.jsonl").write_text("{}\n")
        result = write_sharded(_make_records(5), tmp_path, "pfx", 3, dry_run=True)
        assert sorted(result["stale_shards_to_delete"]) == ["pfx_1.jsonl", "pfx_2.jsonl"]

    def test_stale_shards_excludes_other_prefix(self, tmp_path):
        (tmp_path / "pfx_1.jsonl").write_text("{}\n")
        (tmp_path / "other_1.jsonl").write_text("{}\n")
        result = write_sharded(_make_records(5), tmp_path, "pfx", 3, dry_run=True)
        assert "other_1.jsonl" not in result["stale_shards_to_delete"]
        assert "pfx_1.jsonl" in result["stale_shards_to_delete"]

    def test_empty_records_gives_zero_shards(self, tmp_path):
        result = write_sharded([], tmp_path, "pfx", 100, dry_run=True)
        assert result["total_records"] == 0
        assert result["shard_count"] == 0
        assert result["shards_to_write"] == []

    def test_exact_shard_boundary(self, tmp_path):
        # 6 records, shard_size=3 → exactly 2 shards of 3
        result = write_sharded(_make_records(6), tmp_path, "pfx", 3, dry_run=True)
        assert result["shard_count"] == 2
        counts = [s["record_count"] for s in result["shards_to_write"]]
        assert counts == [3, 3]

    def test_single_record(self, tmp_path):
        result = write_sharded(_make_records(1), tmp_path, "pfx", 100, dry_run=True)
        assert result["shard_count"] == 1
        assert result["shards_to_write"][0]["record_count"] == 1


# ── Plan-write equivalence ────────────────────────────────────────────────────

class TestPlanWriteEquivalence:
    """The dry-run plan must match the real write outcome in tmp_path."""

    def test_plan_shards_match_real_write(self, tmp_path):
        records = _make_records(7)
        plan = write_sharded(records, tmp_path / "dry", "pfx", 3, dry_run=True)
        real = write_sharded(records, tmp_path / "real", "pfx", 3, dry_run=False)
        assert plan["shards_to_write"] == real

    def test_files_written_match_plan(self, tmp_path):
        records = _make_records(7)
        plan = write_sharded(records, tmp_path, "pfx", 3, dry_run=True)
        write_sharded(records, tmp_path, "pfx", 3, dry_run=False)

        written_files = sorted(f.name for f in tmp_path.glob("pfx_*.jsonl"))
        planned_files = sorted(s["file"] for s in plan["shards_to_write"])
        assert written_files == planned_files

    def test_record_count_per_shard_matches(self, tmp_path):
        records = _make_records(7)
        plan = write_sharded(records, tmp_path, "pfx", 3, dry_run=True)
        write_sharded(records, tmp_path, "pfx", 3, dry_run=False)

        for shard_info in plan["shards_to_write"]:
            fpath = tmp_path / shard_info["file"]
            actual_count = sum(1 for line in fpath.read_text().splitlines() if line.strip())
            assert actual_count == shard_info["record_count"]

    def test_total_records_written_matches_plan(self, tmp_path):
        records = _make_records(13)
        plan = write_sharded(records, tmp_path, "pfx", 5, dry_run=True)
        write_sharded(records, tmp_path, "pfx", 5, dry_run=False)

        total_written = sum(
            sum(1 for line in (tmp_path / s["file"]).read_text().splitlines() if line.strip())
            for s in plan["shards_to_write"]
        )
        assert total_written == plan["total_records"]

    def test_records_written_are_valid_json(self, tmp_path):
        records = _make_records(5)
        write_sharded(records, tmp_path, "pfx", 3, dry_run=False)
        for fpath in sorted(tmp_path.glob("pfx_*.jsonl")):
            for line in fpath.read_text().splitlines():
                if line.strip():
                    json.loads(line)  # must not raise

    def test_records_content_preserved(self, tmp_path):
        records = [{"id": i, "val": i * 10} for i in range(5)]
        write_sharded(records, tmp_path, "pfx", 3, dry_run=False)
        read_back = []
        for fpath in sorted(tmp_path.glob("pfx_*.jsonl")):
            for line in fpath.read_text().splitlines():
                if line.strip():
                    read_back.append(json.loads(line))
        assert read_back == records

    def test_plan_helper_consistent_with_write_sharded_plan(self, tmp_path):
        records = _make_records(7)
        helper_plan = _plan_shards(records, "pfx", 3)
        ws_plan = write_sharded(records, tmp_path, "pfx", 3, dry_run=True)
        assert ws_plan["shards_to_write"] == helper_plan


# ── Prefix isolation ──────────────────────────────────────────────────────────

class TestPrefixIsolation:
    """A prefix operation must not affect files belonging to another prefix."""

    def test_dry_run_does_not_list_other_prefix_as_stale(self, tmp_path):
        (tmp_path / "enriched_1.jsonl").write_text("{}\n")
        (tmp_path / "enriched_2.jsonl").write_text("{}\n")

        result = write_sharded(_make_records(5), tmp_path, "ai", 3, dry_run=True)

        for name in result["stale_shards_to_delete"]:
            assert not name.startswith("enriched_")

    def test_real_write_does_not_delete_other_prefix(self, tmp_path):
        (tmp_path / "enriched_1.jsonl").write_text('{"layer":"enriched"}\n')
        (tmp_path / "ai_1.jsonl").write_text('{"layer":"ai_old"}\n')

        write_sharded(_make_records(3), tmp_path, "ai", 10, dry_run=False)

        assert (tmp_path / "enriched_1.jsonl").exists()
        assert (tmp_path / "enriched_1.jsonl").read_text() == '{"layer":"enriched"}\n'

    def test_real_write_replaces_only_its_own_prefix(self, tmp_path):
        (tmp_path / "ai_1.jsonl").write_text('{"old": true}\n')
        (tmp_path / "ai_2.jsonl").write_text('{"old": true}\n')

        write_sharded(_make_records(3), tmp_path, "ai", 10, dry_run=False)

        # Old ai shards replaced by new single shard
        assert not (tmp_path / "ai_2.jsonl").exists()
        written = json.loads((tmp_path / "ai_1.jsonl").read_text().splitlines()[0])
        assert "old" not in written

    def test_two_prefixes_coexist_in_same_dir(self, tmp_path):
        write_sharded(_make_records(5), tmp_path, "ai", 3, dry_run=False)
        write_sharded(_make_records(4), tmp_path, "enriched", 3, dry_run=False)

        ai_files = sorted(tmp_path.glob("ai_*.jsonl"))
        enriched_files = sorted(tmp_path.glob("enriched_*.jsonl"))
        assert len(ai_files) == 2      # 3+2
        assert len(enriched_files) == 2  # 3+1

        ai_count = sum(
            sum(1 for l in f.read_text().splitlines() if l.strip())
            for f in ai_files
        )
        enriched_count = sum(
            sum(1 for l in f.read_text().splitlines() if l.strip())
            for f in enriched_files
        )
        assert ai_count == 5
        assert enriched_count == 4


# ── Backward compatibility ────────────────────────────────────────────────────

class TestBackwardCompatibility:
    """dry_run=False (default) must preserve the original behavior exactly."""

    def test_default_returns_list(self, tmp_path):
        result = write_sharded(_make_records(5), tmp_path, "pfx", 3)
        assert isinstance(result, list)

    def test_explicit_false_returns_list(self, tmp_path):
        result = write_sharded(_make_records(5), tmp_path, "pfx", 3, dry_run=False)
        assert isinstance(result, list)

    def test_creates_output_directory(self, tmp_path):
        target = tmp_path / "new_dir"
        assert not target.exists()
        write_sharded(_make_records(3), target, "pfx", 10)
        assert target.is_dir()

    def test_shard_info_has_required_keys(self, tmp_path):
        result = write_sharded(_make_records(5), tmp_path, "pfx", 3)
        for shard in result:
            assert "file" in shard
            assert "shard_index" in shard
            assert "record_count" in shard

    def test_empty_records_returns_empty_list(self, tmp_path):
        result = write_sharded([], tmp_path, "pfx", 100)
        assert result == []

    def test_deletes_stale_shards_before_write(self, tmp_path):
        # First write: 7 records → 3 shards
        write_sharded(_make_records(7), tmp_path, "pfx", 3)
        assert len(list(tmp_path.glob("pfx_*.jsonl"))) == 3

        # Second write: 2 records → 1 shard; stale shards 2 and 3 must be gone
        write_sharded(_make_records(2), tmp_path, "pfx", 3)
        remaining = sorted(f.name for f in tmp_path.glob("pfx_*.jsonl"))
        assert remaining == ["pfx_1.jsonl"]

    def test_large_shard_size_produces_single_shard(self, tmp_path):
        result = write_sharded(_make_records(10), tmp_path, "pfx", 1000)
        assert len(result) == 1
        assert result[0]["record_count"] == 10
