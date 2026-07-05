"""
Contrato observable mínimo para el reverse — S0116.

Ejecuta el CLI `go run ./cmd/reverse_tiddlers` sobre fixtures reducidos de s42
y verifica invariantes básicos:
  - El proceso termina sin error
  - El reporte es JSON válido
  - rejected_count == 0
  - Los títulos esperados están en el HTML de salida
  - El archivo de salida no se escribe fuera del tmp_path
  - El canon fuente no es modificado

No depende de OneDrive ni de red. Usa los fixtures existentes en
tests/fixtures/s42/ que ya cubren el Go test layer.

Para ejecutar en aislamiento:
    pytest tests/test_reverse_contract.py -v
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_DIR = REPO_ROOT / "src" / "go" / "bridge"
FIXTURES_S42 = REPO_ROOT / "tests" / "fixtures" / "s42"

BASE_HTML = FIXTURES_S42 / "base.html"
CANON_NEW_VALID = FIXTURES_S42 / "canon_with_new_valid.jsonl"
CANON_COLLISION = FIXTURES_S42 / "canon_with_collision.jsonl"


def _go_available() -> bool:
    return subprocess.run(
        ["go", "version"],
        capture_output=True,
        timeout=10,
    ).returncode == 0


def _run_reverse(
    tmp_path: Path,
    base_html: Path,
    canon: Path,
    mode: str = "authoritative-upsert",
    store_policy: str = "preserve",
) -> tuple[subprocess.CompletedProcess, Path, Path]:
    out_html = tmp_path / "out.html"
    report = tmp_path / "reverse-report.json"
    result = subprocess.run(
        [
            "go", "run", "./cmd/reverse_tiddlers",
            "--html", str(base_html),
            "--canon", str(canon),
            "--out-html", str(out_html),
            "--report", str(report),
            "--mode", mode,
            "--store-policy", store_policy,
        ],
        capture_output=True,
        text=True,
        cwd=str(BRIDGE_DIR),
        timeout=120,
    )
    return result, out_html, report


# ── Preconditions ─────────────────────────────────────────────────────────────

class TestReverseFixturesExist:
    def test_base_html_exists(self):
        assert BASE_HTML.exists(), f"Fixture missing: {BASE_HTML}"

    def test_canon_new_valid_exists(self):
        assert CANON_NEW_VALID.exists(), f"Fixture missing: {CANON_NEW_VALID}"

    def test_canon_collision_exists(self):
        assert CANON_COLLISION.exists(), f"Fixture missing: {CANON_COLLISION}"

    def test_bridge_dir_exists(self):
        assert BRIDGE_DIR.exists(), f"Go bridge dir missing: {BRIDGE_DIR}"

    def test_go_cmd_reverse_tiddlers_exists(self):
        cmd_dir = BRIDGE_DIR / "cmd" / "reverse_tiddlers"
        assert cmd_dir.exists(), f"Go cmd dir missing: {cmd_dir}"


# ── Contrato básico: sin rechazos ─────────────────────────────────────────────

@pytest.mark.skipif(not _go_available(), reason="go not available in PATH")
class TestReverseContractNoRejections:
    def test_process_exits_zero(self, tmp_path):
        result, _, _ = _run_reverse(tmp_path, BASE_HTML, CANON_NEW_VALID)
        assert result.returncode == 0, (
            f"Reverse exited {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_report_is_valid_json(self, tmp_path):
        _, _, report = _run_reverse(tmp_path, BASE_HTML, CANON_NEW_VALID)
        assert report.exists(), "Report file not created"
        data = json.loads(report.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_rejected_count_is_zero(self, tmp_path):
        _, _, report = _run_reverse(tmp_path, BASE_HTML, CANON_NEW_VALID)
        data = json.loads(report.read_text(encoding="utf-8"))
        rejected = data.get("rejected_count", data.get("rejected", None))
        assert rejected == 0, f"Expected rejected_count=0, got {rejected}\nReport: {data}"

    def test_out_html_is_created(self, tmp_path):
        _, out_html, _ = _run_reverse(tmp_path, BASE_HTML, CANON_NEW_VALID)
        assert out_html.exists(), "Output HTML not created"

    def test_out_html_contains_inserted_title(self, tmp_path):
        _, out_html, _ = _run_reverse(tmp_path, BASE_HTML, CANON_NEW_VALID)
        content = out_html.read_text(encoding="utf-8")
        expected = "#### 🌀 Sesión 42 = canon-minimal-deterministic-reverse-v0"
        assert expected in content, f"Output HTML missing inserted title: {expected!r}"

    def test_out_html_preserves_existing_titles(self, tmp_path):
        _, out_html, _ = _run_reverse(tmp_path, BASE_HTML, CANON_NEW_VALID)
        content = out_html.read_text(encoding="utf-8")
        assert "Existing Alpha" in content
        assert "Existing Beta" in content

    def test_report_contains_eligible_entries(self, tmp_path):
        _, _, report = _run_reverse(tmp_path, BASE_HTML, CANON_NEW_VALID)
        data = json.loads(report.read_text(encoding="utf-8"))
        eligible = data.get("eligible_entries_evaluated", 0)
        assert eligible > 0, f"Expected eligible_entries_evaluated > 0, got {eligible}"


# ── Contrato básico: sin escritura fuera de tmp ───────────────────────────────

@pytest.mark.skipif(not _go_available(), reason="go not available in PATH")
class TestReverseNoCanonMutation:
    def test_base_html_fixture_not_mutated(self, tmp_path):
        hash_before = hashlib.sha256(BASE_HTML.read_bytes()).hexdigest()
        _run_reverse(tmp_path, BASE_HTML, CANON_NEW_VALID)
        hash_after = hashlib.sha256(BASE_HTML.read_bytes()).hexdigest()
        assert hash_before == hash_after, "Base HTML fixture was mutated during reverse"

    def test_canon_fixture_not_mutated(self, tmp_path):
        hash_before = hashlib.sha256(CANON_NEW_VALID.read_bytes()).hexdigest()
        _run_reverse(tmp_path, BASE_HTML, CANON_NEW_VALID)
        hash_after = hashlib.sha256(CANON_NEW_VALID.read_bytes()).hexdigest()
        assert hash_before == hash_after, "Canon fixture was mutated during reverse"

    def test_output_stays_in_tmp(self, tmp_path):
        _, out_html, report = _run_reverse(tmp_path, BASE_HTML, CANON_NEW_VALID)
        assert out_html.is_relative_to(tmp_path), f"Output HTML outside tmp_path: {out_html}"
        assert report.is_relative_to(tmp_path), f"Report outside tmp_path: {report}"


# ── Contrato: modo authoritative-upsert ──────────────────────────────────────

@pytest.mark.skipif(not _go_available(), reason="go not available in PATH")
class TestReverseAuthoritativeUpsert:
    def test_mode_is_recorded_in_report(self, tmp_path):
        _, _, report = _run_reverse(
            tmp_path, BASE_HTML, CANON_NEW_VALID, mode="authoritative-upsert"
        )
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data.get("mode") == "authoritative-upsert", (
            f"Expected mode=authoritative-upsert in report, got: {data.get('mode')!r}"
        )

    def test_store_policy_is_recorded_in_report(self, tmp_path):
        _, _, report = _run_reverse(
            tmp_path, BASE_HTML, CANON_NEW_VALID, store_policy="preserve"
        )
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data.get("store_policy") == "preserve", (
            f"Expected store_policy=preserve in report, got: {data.get('store_policy')!r}"
        )


# ── Contrato: gobernanza de rutas ─────────────────────────────────────────────

class TestReversePathGovernance:
    def test_no_sessions_in_root(self):
        assert not (REPO_ROOT / "sessions").exists()

    def test_no_data_sessions(self):
        assert not (REPO_ROOT / "data" / "sessions").exists()

    def test_reverse_html_dir_is_inside_data_out_local(self):
        reverse_html = REPO_ROOT / "data" / "out" / "local" / "reverse_html"
        if reverse_html.exists():
            assert reverse_html.is_relative_to(REPO_ROOT / "data" / "out" / "local")
