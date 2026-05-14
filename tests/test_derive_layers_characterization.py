"""
Characterization tests for the derive_layers.py pipeline — S0109.

These tests freeze the observable behavior of the derivation pipeline:
  canon → enriched → ai → chunks

They operate read-only on existing data/out/local/ outputs and via subprocess
for CLI checks. They do NOT run the full pipeline during tests; they verify
the invariants of the current state.

Counts frozen at: canon=1014, enriched=1014, AI=1014, chunks=879.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CANON_DIR = REPO_ROOT / "data" / "out" / "local"
ENRICHED_DIR = CANON_DIR / "enriched"
AI_DIR = CANON_DIR / "ai"

# ── Count invariants ─────────────────────────────────────────────────────────

EXPECTED_CANON_COUNT = 1014
EXPECTED_ENRICHED_COUNT = 1014
EXPECTED_AI_COUNT = 1014
EXPECTED_CHUNK_COUNT = 879


def _count_jsonl_records(directory: Path, glob: str) -> int:
    total = 0
    for path in sorted(directory.glob(glob)):
        with path.open(encoding="utf-8") as f:
            total += sum(1 for line in f if line.strip())
    return total


# ── CLI characterization ─────────────────────────────────────────────────────

class TestDeriveCLI:
    def test_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "python_scripts" / "derive_layers.py"), "--help"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0

    def test_help_contains_input_dir(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "python_scripts" / "derive_layers.py"), "--help"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert "--input-dir" in result.stdout

    def test_help_contains_enriched_dir(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "python_scripts" / "derive_layers.py"), "--help"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert "--enriched-dir" in result.stdout

    def test_help_contains_ai_dir(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "python_scripts" / "derive_layers.py"), "--help"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert "--ai-dir" in result.stdout

    def test_help_contains_strict_flag(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "python_scripts" / "derive_layers.py"), "--help"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert "--strict" in result.stdout


# ── Count characterization ────────────────────────────────────────────────────

class TestDeriveCountInvariants:
    def test_canon_shards_exist(self):
        shards = sorted(CANON_DIR.glob("tiddlers_*.jsonl"))
        assert len(shards) == 11, f"Expected 11 canon shards, got {len(shards)}"

    def test_canon_record_count(self):
        count = _count_jsonl_records(CANON_DIR, "tiddlers_*.jsonl")
        assert count == EXPECTED_CANON_COUNT, (
            f"Canon count mismatch: expected {EXPECTED_CANON_COUNT}, got {count}"
        )

    def test_enriched_record_count(self):
        count = _count_jsonl_records(ENRICHED_DIR, "tiddlers_enriched_*.jsonl")
        assert count == EXPECTED_ENRICHED_COUNT, (
            f"Enriched count mismatch: expected {EXPECTED_ENRICHED_COUNT}, got {count}"
        )

    def test_ai_record_count(self):
        count = _count_jsonl_records(AI_DIR, "tiddlers_ai_*.jsonl")
        assert count == EXPECTED_AI_COUNT, (
            f"AI record count mismatch: expected {EXPECTED_AI_COUNT}, got {count}"
        )

    def test_chunk_record_count(self):
        count = _count_jsonl_records(AI_DIR, "chunks_ai_*.jsonl")
        assert count == EXPECTED_CHUNK_COUNT, (
            f"Chunk count mismatch: expected {EXPECTED_CHUNK_COUNT}, got {count}"
        )

    def test_enriched_count_equals_canon_count(self):
        canon = _count_jsonl_records(CANON_DIR, "tiddlers_*.jsonl")
        enriched = _count_jsonl_records(ENRICHED_DIR, "tiddlers_enriched_*.jsonl")
        assert canon == enriched, f"Canon/enriched invariant broken: {canon} != {enriched}"

    def test_ai_count_equals_canon_count(self):
        canon = _count_jsonl_records(CANON_DIR, "tiddlers_*.jsonl")
        ai = _count_jsonl_records(AI_DIR, "tiddlers_ai_*.jsonl")
        assert canon == ai, f"Canon/AI invariant broken: {canon} != {ai}"


# ── Field structure characterization ─────────────────────────────────────────

AI_REQUIRED_FIELDS = {
    "title",
    "id",
    "role_primary",
    "ai_summary",
    "semantic_text",
    "preview_text",
    "retrieval_hints",
    "retrieval_terms",
    "token_estimate",
    "is_chunkable_text",
    "corpus_state",
    "derivation",
}

CHUNK_REQUIRED_FIELDS = {
    "title",
    "chunk_id",
    "chunk_index",
    "chunk_total",
    "source_id",
    "source_title",
    "text",
    "token_estimate",
    "role_primary",
    "corpus_state",
    "within_hard_max",
}

ENRICHED_REQUIRED_FIELDS = {
    "title",
    "id",
    "role_primary",
    "semantic_text",
    "preview_text",
    "taxonomy_path",
    "derivation",
    "schema_version",
}


def _load_first_record(directory: Path, glob: str) -> dict:
    for path in sorted(directory.glob(glob)):
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    return json.loads(line)
    raise FileNotFoundError(f"No records found in {directory}/{glob}")


class TestAIRecordStructure:
    @pytest.fixture(scope="class")
    def sample_ai_record(self):
        return _load_first_record(AI_DIR, "tiddlers_ai_*.jsonl")

    def test_ai_record_has_required_fields(self, sample_ai_record):
        missing = AI_REQUIRED_FIELDS - set(sample_ai_record.keys())
        assert not missing, f"AI record missing fields: {missing}"

    def test_ai_record_title_is_nonempty(self, sample_ai_record):
        assert isinstance(sample_ai_record.get("title"), str)
        assert sample_ai_record["title"].strip()

    def test_ai_record_token_estimate_is_positive(self, sample_ai_record):
        tok = sample_ai_record.get("token_estimate")
        assert isinstance(tok, int) and tok >= 0

    def test_ai_record_corpus_state_is_string(self, sample_ai_record):
        cs = sample_ai_record.get("corpus_state")
        assert isinstance(cs, str) and cs.strip()

    def test_ai_record_is_chunkable_text_is_bool(self, sample_ai_record):
        assert isinstance(sample_ai_record.get("is_chunkable_text"), bool)

    def test_ai_record_derivation_contains_session(self, sample_ai_record):
        deriv = sample_ai_record.get("derivation", {})
        assert isinstance(deriv, dict)
        assert "session" in deriv


class TestChunkStructure:
    @pytest.fixture(scope="class")
    def sample_chunk(self):
        return _load_first_record(AI_DIR, "chunks_ai_*.jsonl")

    def test_chunk_has_required_fields(self, sample_chunk):
        missing = CHUNK_REQUIRED_FIELDS - set(sample_chunk.keys())
        assert not missing, f"Chunk missing fields: {missing}"

    def test_chunk_text_is_nonempty(self, sample_chunk):
        assert isinstance(sample_chunk.get("text"), str)
        assert sample_chunk["text"].strip()

    def test_chunk_token_estimate_is_positive(self, sample_chunk):
        tok = sample_chunk.get("token_estimate")
        assert isinstance(tok, int) and tok > 0

    def test_chunk_within_hard_max_is_bool(self, sample_chunk):
        assert isinstance(sample_chunk.get("within_hard_max"), bool)

    def test_chunk_index_starts_at_zero_or_one(self, sample_chunk):
        idx = sample_chunk.get("chunk_index")
        assert isinstance(idx, int) and idx >= 0


class TestEnrichedRecordStructure:
    @pytest.fixture(scope="class")
    def sample_enriched(self):
        return _load_first_record(ENRICHED_DIR, "tiddlers_enriched_*.jsonl")

    def test_enriched_has_required_fields(self, sample_enriched):
        missing = ENRICHED_REQUIRED_FIELDS - set(sample_enriched.keys())
        assert not missing, f"Enriched record missing fields: {missing}"

    def test_enriched_title_is_nonempty(self, sample_enriched):
        assert isinstance(sample_enriched.get("title"), str)
        assert sample_enriched["title"].strip()

    def test_enriched_schema_version_present(self, sample_enriched):
        assert sample_enriched.get("schema_version")


# ── Canon immutability ────────────────────────────────────────────────────────

class TestCanonImmutability:
    def test_canon_files_are_valid_jsonl(self):
        for path in sorted(CANON_DIR.glob("tiddlers_*.jsonl")):
            with path.open(encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        json.loads(line)
                    except json.JSONDecodeError as e:
                        pytest.fail(f"Invalid JSON at {path}:{i}: {e}")

    def test_canon_records_all_have_title(self):
        missing_title = 0
        for path in sorted(CANON_DIR.glob("tiddlers_*.jsonl")):
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    if not rec.get("title"):
                        missing_title += 1
        assert missing_title == 0, f"{missing_title} canon records missing title"

    def test_canon_sha256_stable(self):
        """Freeze SHA-256 hashes of all canon shards.

        If this test fails after a legitimate canon update, update the
        EXPECTED_HASHES dict below with the new values.
        """
        EXPECTED_HASHES = {
            "tiddlers_1.jsonl":  "5a8ca8fa3377a78a3b2b0ea0ce4d62d26d37cfca272a08b3742d1bafc938dd8e",
            "tiddlers_2.jsonl":  "29bd311951e652b21926616f0655961a4d00055f0c06fa89d6855e6f9d79142e",
            "tiddlers_3.jsonl":  "1c20ff2c23b97c3c8fe9fea1bff2ecaf286ef227990d7b3a9a34560c02bdc246",
            "tiddlers_4.jsonl":  "e85f0632644473f62ae767f6ba8873ed862d30f0b1ba7f32c7dafccaf6d4d2e7",
            "tiddlers_5.jsonl":  "f57dfa29e42a3cbf7d9a1f7a84c9f5825dbfa47bf10edc9a2aaeebebfc5fedc7",
            "tiddlers_6.jsonl":  "e8419fdbbc991045054ace4535b1903a7f31456d031985f2348fe31f1b7b66b3",
            "tiddlers_7.jsonl":  "de6918be680b4ebeb857399cac98249450d12c68bf3ff6337161ae425224b358",
            "tiddlers_8.jsonl":  "20dbecd5e1b74f527c2d699492143b941fd37360bfafa479dcc474edf6dfca51",
            "tiddlers_9.jsonl":  "ef223e5f663ade142d8f0db7b0d71134b20b0dcda3b842e2283af549df1cdcae",
            "tiddlers_10.jsonl": "556047705e02b823361e0ebd2132d636deadbb6b9368df9848338420a94fe201",
            "tiddlers_11.jsonl": "f2b6ad3d7ce8509ccdffb45753a1d1a1f3999c79f3b6f6df5bb8ddca6187dd46",
        }
        mismatches = []
        for name, expected_hash in EXPECTED_HASHES.items():
            path = CANON_DIR / name
            if not path.exists():
                mismatches.append(f"{name}: file not found")
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected_hash:
                mismatches.append(f"{name}: expected {expected_hash[:16]}… got {actual[:16]}…")
        assert not mismatches, "Canon hash mismatch (canon changed):\n" + "\n".join(mismatches)


# ── Path governance ───────────────────────────────────────────────────────────

class TestPathGovernance:
    def test_no_sessions_in_root(self):
        forbidden = REPO_ROOT / "sessions"
        assert not forbidden.exists(), f"Forbidden path exists: {forbidden}"

    def test_no_data_sessions(self):
        forbidden = REPO_ROOT / "data" / "sessions"
        assert not forbidden.exists(), f"Forbidden path exists: {forbidden}"

    def test_no_data_local_at_root_level(self):
        forbidden = REPO_ROOT / "data" / "local"
        assert not forbidden.exists(), f"Forbidden path exists: {forbidden}"

    def test_governed_sessions_path_is_correct(self):
        governed = CANON_DIR / "sessions"
        assert governed.exists(), (
            f"Governed sessions path missing: {governed}"
        )

    def test_qc_reports_exist(self):
        reports_dir = AI_DIR / "reports"
        assert reports_dir.exists()
        reports = list(reports_dir.glob("*.json"))
        assert len(reports) >= 5, f"Expected ≥5 QC reports, got {len(reports)}"
