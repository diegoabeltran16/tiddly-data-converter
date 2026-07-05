"""S0151 tests for guided metadata admission UX."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import repo_metadata_admission_gate as gate  # noqa: E402
import repo_metadata_review_menu as menu  # noqa: E402
from repo_metadata_s0151_helpers import build_s0151_fixture  # noqa: E402


def test_normal_metadata_menu_hides_technical_ids_and_exposes_guided_options() -> None:
    header = menu.S0151_MENU_HEADER

    assert "Metadata técnica" in header
    assert "Modo normal: guiado" in header
    assert "IDs y hashes: solo en avanzado" in header
    assert "Usar selección recomendada" in header
    assert "Selección personalizada guiada" in header
    assert "batch_current_verified" not in header
    assert "patch_sha256" not in header
    assert "canon_before_sha256" not in header


def test_guided_presets_select_expected_batches(tmp_path: Path) -> None:
    fx = build_s0151_fixture(tmp_path)
    manifest = fx["manifest"]
    out_dir = fx["out_dir"]
    assert isinstance(manifest, Path)
    assert isinstance(out_dir, Path)

    recommended = gate.select_s0151_batches("recommended", manifest=manifest, out_dir=out_dir / "recommended")
    current = gate.select_s0151_batches("current_only", manifest=manifest, out_dir=out_dir / "current")
    auxiliary = gate.select_s0151_batches("auxiliary_only", manifest=manifest, out_dir=out_dir / "auxiliary")

    assert recommended["valid"] is True
    assert recommended["selected_batch_ids"] == [
        "batch_current_verified",
        "batch_embedded_code",
        "batch_narrative_reference",
    ]
    assert current["selected_batch_ids"] == ["batch_current_verified"]
    assert auxiliary["selected_batch_ids"] == ["batch_embedded_code", "batch_narrative_reference"]


def test_custom_guided_selection_uses_numbers_blocks_excluded_and_warns(tmp_path: Path) -> None:
    fx = build_s0151_fixture(tmp_path)
    manifest = fx["manifest"]
    out_dir = fx["out_dir"]
    assert isinstance(manifest, Path)
    assert isinstance(out_dir, Path)

    custom = gate.select_s0151_batches("1,2,3", manifest=manifest, out_dir=out_dir / "custom")
    missing = gate.select_s0151_batches("batch_missing", manifest=manifest, out_dir=out_dir / "missing")
    excluded = gate.select_s0151_batches("6", manifest=manifest, out_dir=out_dir / "excluded")
    warned = gate.select_s0151_batches("4,5", manifest=manifest, out_dir=out_dir / "warned")

    assert custom["valid"] is True
    assert custom["selected_batch_ids"] == [
        "batch_current_verified",
        "batch_embedded_code",
        "batch_narrative_reference",
    ]
    assert missing["valid"] is False
    assert missing["invalid_batch_ids"] == ["batch_missing"]
    assert excluded["valid"] is False
    assert excluded["blocked_batch_ids"] == ["batch_excluded_review_required"]
    assert warned["valid"] is True
    assert "historical_or_divergent_batch_selected" in warned["operator_warnings"]
    assert "generated_derivative_batch_selected" in warned["operator_warnings"]


def test_hash_mismatch_detection_drives_guided_refresh_offer(tmp_path: Path) -> None:
    fx = build_s0151_fixture(tmp_path)
    manifest = fx["manifest"]
    canon = fx["canon"]
    assert isinstance(manifest, Path)
    assert isinstance(canon, Path)

    assert menu._manifest_needs_refresh(manifest, canon_glob=str(fx["canon_glob"])) is False
    canon.write_text(canon.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    assert menu._manifest_needs_refresh(manifest, canon_glob=str(fx["canon_glob"])) is True
