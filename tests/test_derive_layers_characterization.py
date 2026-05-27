"""
Characterization tests for the derive_layers.py pipeline — S0109, updated S0116, reconciled S0126/S0127.

These tests freeze the observable behavior of the derivation pipeline:
  canon → enriched → ai → chunks

They operate read-only on existing data/out/local/ outputs and via subprocess
for CLI checks. They do NOT run the full pipeline during tests; they verify
the invariants of the current state.

Counts frozen at: canon=1389, enriched=1389, AI=1389, chunks=1255, shards=14.
Updated from post-S0115 baseline (1090/1090/1090/1012, 11 shards) to post-S0125 state (1375),
then to post-S0125/S0126 admission state (1389 = 1375 + 14 entregables S0125+S0126 admitidos).

When the canon changes legitimately, update the constants below and run
  sha256sum data/out/local/tiddlers_*.jsonl
to refresh EXPECTED_HASHES.
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

# Post-S0125/S0126 admission state (S0127 reconciliation). Previous: 1375/1375/1375/1255 (post-S0125).
# 14 entregables de S0125 y S0126 admitidos al canon; roles: +6 log, +4 procedure, +2 evidence, +2 policy.
# Chunks estables en 1255: los nuevos entregables de sesión no superan el umbral de chunking.
EXPECTED_CANON_COUNT = 1389
EXPECTED_ENRICHED_COUNT = 1389
EXPECTED_AI_COUNT = 1389
EXPECTED_CHUNK_COUNT = 1255


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
        # Post-S0125 state: 14 shards. Previous (post-S0115): 11 shards.
        assert len(shards) == 14, f"Expected 14 canon shards, got {len(shards)}"

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
        # Hashes actualizados al estado post-S0128 (corrección source_type + created S0125).
        # S0128 fix 1: S0125 re-admitida con source_type='text/markdown' (hash a8462a...).
        # S0128 fix 2: S0125 reemplazada con created correcto 20260526222157000 (hash b27a17...).
        # tiddlers_14.jsonl: única modificada. Los shards 1-13 sin cambio.
        # Para actualizar: sha256sum data/out/local/tiddlers_*.jsonl
        EXPECTED_HASHES = {
            "tiddlers_1.jsonl":  "52734cd16165aa1936d24f8a05cbe7a8845ee91dc94d7bdb2d8b5f95a87e633a",
            "tiddlers_2.jsonl":  "0dcd85c1fc6d5b3811461a4006400124f4988fe5ff9a83f38d90606efeb60d79",
            "tiddlers_3.jsonl":  "3ecd53d6b3a7be062643f15962f07c9b17fa1f5d1d631cec9ba723de26a12096",
            "tiddlers_4.jsonl":  "80e334b5476efed1b82284be17f8ac072b359e3e97a547cff46586fa245b84fb",
            "tiddlers_5.jsonl":  "32adcca1defb54c7e3ea6992be0f6167478927b16841f033d4a0b0ed7d0517de",
            "tiddlers_6.jsonl":  "6d585df1d11898729f6308114a0515f15aac9ebdfb32c40bd1e335b69ea3bb2d",
            "tiddlers_7.jsonl":  "0b9718024f855a882810214ee3c56f3c01fc9513f94ad0095e34e61a0a13d7be",
            "tiddlers_8.jsonl":  "0097909509e724c8a85b18c33877ddcd6768decaf3e7a185a8a5bd1bb90d49c3",
            "tiddlers_9.jsonl":  "ff23fd64ad542065774355bf3cef4a14a5997f43b4645fb7bb7676041d945377",
            "tiddlers_10.jsonl": "811917ff9754e34ca0d79c8f260184139ed7780e1bac5200aeedd6fc5fa08391",
            "tiddlers_11.jsonl": "73c66df1414d8f321674ecfc416eb66c03fc29f6c6629a72b2a34526c1a29cbb",
            "tiddlers_12.jsonl": "655c21b2f6729eb126e07aca8ee456ec769cb6dd58b6a7718759c155c6c92f9a",
            "tiddlers_13.jsonl": "be7fb62b5bc25c28c04b31b79fc466a2999b3805304b098977683ac6ed929afc",
            "tiddlers_14.jsonl": "b27a17daafeba4e906dd5de686579723cc9a3f2c838ea8dd0ceee8be420533c6",
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


# ── source_type MIME invariant (S0128 post-mortem) ────────────────────────────

class TestCanonSourceTypeMime:
    """All canon records with a non-null source_type must carry a valid MIME type.

    A valid MIME type contains a forward slash (e.g. 'text/markdown',
    'application/json').  Values like 'contrato', 'procedencia', or any other
    artifact-family name written into the wrong field are caught here.

    This test is the permanent regression guard for the S0128 incident where
    7 S0125 session deliverables had source_type set to the artifact-family
    name instead of 'text/markdown', causing reverse_tiddlers to silently
    skip them (rule: out-of-scope-source-type).

    Root cause: _validated_source_type() was absent from session_sync.py and
    admit_session_candidates.py; the raw 'type' field was forwarded to the
    canon without MIME validation.
    """

    def test_all_source_types_are_valid_mime(self):
        bad: list[str] = []
        for path in sorted(CANON_DIR.glob("tiddlers_*.jsonl")):
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    st = rec.get("source_type")
                    if st is not None and st != "" and "/" not in st:
                        bad.append(
                            f"{path.name}: title={rec.get('title','')[:60]!r} "
                            f"source_type={st!r}"
                        )
        assert not bad, (
            f"Canon records with non-MIME source_type (S0128 regression):\n"
            + "\n".join(bad)
        )

    def test_session_deliverables_use_text_markdown(self):
        """Session deliverables (layer:session tag) must use text/markdown or
        application/json — never a bare artifact-family name.
        """
        bad: list[str] = []
        allowed = {"text/markdown", "application/json", "text/plain",
                   "text/vnd.tiddlywiki", "text/csv", None, ""}
        for path in sorted(CANON_DIR.glob("tiddlers_*.jsonl")):
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    tags = rec.get("tags") or []
                    if "layer:session" not in tags:
                        continue
                    st = rec.get("source_type")
                    if st not in allowed:
                        bad.append(
                            f"{path.name}: {rec.get('title','')[:60]!r} → {st!r}"
                        )
        assert not bad, (
            f"Session deliverables with wrong source_type:\n" + "\n".join(bad)
        )
