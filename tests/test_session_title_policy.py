#!/usr/bin/env python3
"""Tests for session_title_policy.py — S0124."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "src" / "python_scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from session_title_policy import (  # noqa: E402
    FAMILY_CANONICAL_PREFIX,
    TitleClassification,
    canonical_title_for,
    classify_title,
    needs_normalization,
)


# ── Test case 1: S-prefix removed from session number ─────────────────────────

class TestSPrefixRemoval:
    def test_contrato_s0117_normalizable(self) -> None:
        title = "#### 🌀 Contrato de sesión S0117 = pruebas P0 para remote_pull_canon y session_sync scan"
        cls = classify_title(title, "contrato_de_sesion")
        assert cls.status == "normalizable"
        assert cls.proposed_title == "#### 🌀 Contrato de sesión 0117 = pruebas P0 para remote_pull_canon y session_sync scan"

    def test_contrato_s0111_normalizable(self) -> None:
        cls = classify_title(
            "#### 🌀 Contrato de sesión S0111 = dry-run gobernado para write_sharded y aislamiento de prefijos",
            "contrato_de_sesion",
        )
        assert cls.status == "normalizable"
        assert "s_prefix_in_number" in cls.issue
        assert cls.proposed_title is not None
        assert "0111" in cls.proposed_title
        assert "S0111" not in cls.proposed_title

    def test_procedencia_s0109_normalizable(self) -> None:
        cls = classify_title(
            "#### 🌀🧾 Procedencia de sesión S0109 = caracterización end-to-end de derivación",
            "procedencia_de_sesion",
        )
        assert cls.status == "normalizable"
        assert cls.proposed_title == "#### 🌀🧾 Procedencia de sesión 0109 = caracterización end-to-end de derivación"

    def test_sesion_s0111_normalizable(self) -> None:
        cls = classify_title(
            "#### 🌀 Sesión S0111 = dry-run gobernado para write_sharded",
            "detalles_de_sesion",
        )
        assert cls.status == "normalizable"
        assert cls.proposed_title == "#### 🌀 Sesión 0111 = dry-run gobernado para write_sharded"


# ── Test case 2: Unpadded number → 4-digit padding ────────────────────────────

class TestUnpaddedNumber:
    def test_contrato_65_padded_to_0065(self) -> None:
        cls = classify_title(
            "#### 🌀 Contrato de sesión 65 = microsoft-copilot-execution-surface-and-readme-hardening-v0",
            "contrato_de_sesion",
        )
        assert cls.status == "normalizable"
        assert cls.proposed_title is not None
        assert "0065" in cls.proposed_title
        assert "unpadded_number" in cls.issue

    def test_contrato_98_padded_to_0098(self) -> None:
        cls = classify_title(
            "#### 🌀 Contrato de sesión 98 = propagacion-relacional-chunks-ai-y-rule23",
            "contrato_de_sesion",
        )
        assert cls.status == "normalizable"
        assert cls.proposed_title is not None
        assert "0098" in cls.proposed_title

    def test_procedencia_98_padded(self) -> None:
        cls = classify_title(
            "#### 🌀🧾 Procedencia de sesión 98 = propagacion-relacional-chunks-ai-y-rule23",
            "procedencia_de_sesion",
        )
        assert cls.status == "normalizable"
        assert cls.proposed_title is not None
        assert "0098" in cls.proposed_title


# ── Test case 3: Wrong family label in title ──────────────────────────────────

class TestWrongFamilyLabel:
    def test_sesion_label_in_contrato_folder(self) -> None:
        """File in 00_contratos/ but titled as 'Sesión' → fix to 'Contrato de sesión'."""
        cls = classify_title(
            "#### 🌀 Sesión S0110 = tercer corte de refactor: clasificación de roles con tests de distribución",
            "contrato_de_sesion",
        )
        assert cls.status == "normalizable"
        assert cls.proposed_title is not None
        assert "Contrato de sesión" in cls.proposed_title
        assert "0110" in cls.proposed_title
        assert "wrong_family_label" in cls.issue

    def test_detalles_de_sesion_label_normalizes_to_sesion(self) -> None:
        """'Detalles de sesión' is an old form; canonical is 'Sesión'."""
        cls = classify_title(
            "#### 🌀 Detalles de sesión S0110 = tercer corte de refactor",
            "detalles_de_sesion",
        )
        assert cls.status == "normalizable"
        assert cls.proposed_title is not None
        assert "#### 🌀 Sesión 0110" in cls.proposed_title
        assert "wrong_family_label" in cls.issue


# ── Test case 4: Thematic diagnostic is NOT a session ─────────────────────────

class TestThematicDiagnosticUnchanged:
    def test_diagnostico_tematico_not_applicable(self) -> None:
        cls = classify_title(
            "#### 🌀 Diagnóstico temático 033 = frontera canon/archivo para diagnósticos temáticos",
            "diagnostico_tematico",
        )
        assert cls.status == "not_applicable"
        assert cls.proposed_title is None

    def test_diagnostico_tematico_does_not_need_normalization(self) -> None:
        assert not needs_normalization(
            "#### 🌀 Diagnóstico temático 033 = frontera canon",
            "diagnostico_tematico",
        )


# ── Test case 5: Microciclo/mesociclo not modified ────────────────────────────

class TestCyclesDiagnosticsUnchanged:
    def test_microciclo_not_applicable(self) -> None:
        cls = classify_title(
            "#### 🌀 Diagnóstico de microciclo = sesiones S95-S104",
            "diagnostico_de_micro_ciclo",
        )
        assert cls.status == "not_applicable"

    def test_mesociclo_not_applicable(self) -> None:
        cls = classify_title(
            "#### 🌀 Diagnóstico de mesociclo = microciclos S65-S94",
            "diagnostico_de_meso_ciclo",
        )
        assert cls.status == "not_applicable"


# ── Test case 6: Collision prevention ─────────────────────────────────────────

class TestCollisionPrevention:
    """Collision detection is handled in normalize_session_titles, but the
    policy itself returns the proposed title — it is the normalization module
    that marks collisions as blocked."""

    def test_two_different_titles_do_not_collide_at_policy_level(self) -> None:
        t1 = "#### 🌀 Contrato de sesión S0111 = dry-run gobernado"
        t2 = "#### 🌀 Contrato de sesión S0112 = equivalencia campo a campo"
        cls1 = classify_title(t1, "contrato_de_sesion")
        cls2 = classify_title(t2, "contrato_de_sesion")
        assert cls1.proposed_title != cls2.proposed_title


# ── Test case 7: Dry-run does not modify (policy-level) ───────────────────────

class TestPolicyIsPure:
    def test_classify_title_returns_dataclass_not_none(self) -> None:
        cls = classify_title("any title", "contrato_de_sesion")
        assert isinstance(cls, TitleClassification)

    def test_classify_does_not_raise_on_empty_title(self) -> None:
        cls = classify_title("", "contrato_de_sesion")
        assert cls.status in ("manual_review", "blocked", "not_applicable")

    def test_canonical_title_for_already_canonical(self) -> None:
        t = "#### 🌀 Contrato de sesión 0117 = pruebas P0"
        result = canonical_title_for(t, "contrato_de_sesion")
        assert result == t


# ── Test case 8: Extra emoji stripped ─────────────────────────────────────────

class TestExtraEmoji:
    def test_extra_emoji_clipboard_contrato(self) -> None:
        cls = classify_title(
            "#### 🌀📋 Contrato de sesión 0122 = saneamiento selectivo del canon",
            "contrato_de_sesion",
        )
        assert cls.status == "normalizable"
        assert cls.proposed_title == "#### 🌀 Contrato de sesión 0122 = saneamiento selectivo del canon"
        assert "extra_emoji" in cls.issue

    def test_correct_emoji_procedencia_not_extra(self) -> None:
        """🧾 is the correct emoji for procedencia — not classified as extra."""
        cls = classify_title(
            "#### 🌀🧾 Procedencia de sesión 0109 = caracterización end-to-end",
            "procedencia_de_sesion",
        )
        assert cls.status == "canonical"


# ── Test case 9: Already canonical ────────────────────────────────────────────

class TestAlreadyCanonical:
    def test_canonical_contrato(self) -> None:
        cls = classify_title(
            "#### 🌀 Contrato de sesión 0117 = pruebas P0 para remote_pull_canon y session_sync scan",
            "contrato_de_sesion",
        )
        assert cls.status == "canonical"

    def test_canonical_balance(self) -> None:
        cls = classify_title(
            "#### 🌀 Balance de sesión 0066 = family-and-canonical-closure-flow-v0",
            "balance_de_sesion",
        )
        assert cls.status == "canonical"

    def test_canonical_hipotesis(self) -> None:
        cls = classify_title(
            "#### 🌀🧪 Hipótesis de sesión 0121 = canonización gobernada",
            "hipotesis_de_sesion",
        )
        assert cls.status == "canonical"

    def test_needs_normalization_false_for_canonical(self) -> None:
        assert not needs_normalization(
            "#### 🌀 Contrato de sesión 0121 = algo",
            "contrato_de_sesion",
        )


# ── Test case 10: session_sync gate: needs_normalization flag ────────────────

class TestNeedsNormalizationFunction:
    def test_s_prefix_needs_normalization(self) -> None:
        assert needs_normalization(
            "#### 🌀 Contrato de sesión S0111 = dry-run gobernado",
            "contrato_de_sesion",
        )

    def test_unpadded_needs_normalization(self) -> None:
        assert needs_normalization(
            "#### 🌀 Contrato de sesión 65 = microsoft-copilot",
            "contrato_de_sesion",
        )

    def test_canonical_does_not_need_normalization(self) -> None:
        assert not needs_normalization(
            "#### 🌀 Contrato de sesión 0065 = microsoft-copilot",
            "contrato_de_sesion",
        )

    def test_unknown_family_does_not_need_normalization(self) -> None:
        # unknown family → not_applicable → needs_normalization returns False
        assert not needs_normalization(
            "#### 🌀 Contrato de sesión S0111 = slug",
            "unknown_family_xyz",
        )


# ── Test case 11: FAMILY_CANONICAL_PREFIX exported ───────────────────────────

class TestFamilyCanonicalPrefixExported:
    def test_all_expected_families_present(self) -> None:
        expected = {
            "contrato_de_sesion",
            "procedencia_de_sesion",
            "detalles_de_sesion",
            "hipotesis_de_sesion",
            "balance_de_sesion",
            "propuesta_de_sesion",
            "diagnostico_de_sesion",
        }
        assert expected.issubset(set(FAMILY_CANONICAL_PREFIX.keys()))

    def test_detalles_de_sesion_prefix_uses_sesion_not_detalles(self) -> None:
        """Canonical form for details uses 'Sesión', not 'Detalles de sesión'."""
        assert FAMILY_CANONICAL_PREFIX["detalles_de_sesion"] == "#### 🌀 Sesión"
