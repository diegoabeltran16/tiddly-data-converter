#!/usr/bin/env python3
"""Session title policy for tiddly-data-converter.

Defines the canonical naming contract for session artifact titles and
provides pure classification/normalization functions with no I/O.

Used by normalize_session_titles.py and session_artifact_governance.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# ── Canonical title prefixes (by family key) ─────────────────────────────────

FAMILY_CANONICAL_PREFIX: dict[str, str] = {
    "contrato_de_sesion":    "#### 🌀 Contrato de sesión",
    "procedencia_de_sesion": "#### 🌀🧾 Procedencia de sesión",
    "detalles_de_sesion":    "#### 🌀 Sesión",
    "hipotesis_de_sesion":   "#### 🌀🧪 Hipótesis de sesión",
    "balance_de_sesion":     "#### 🌀 Balance de sesión",
    "propuesta_de_sesion":   "#### 🌀 Propuesta de sesión",
    "diagnostico_de_sesion": "#### 🌀 Diagnóstico de sesión",
}

# Expected emoji between 🌀 and the first space in the canonical prefix
FAMILY_EMOJI_SUFFIX: dict[str, str] = {
    fam: prefix[len("#### 🌀"):].split(" ")[0]
    for fam, prefix in FAMILY_CANONICAL_PREFIX.items()
}

# Compiled canonical patterns: <prefix> NNNN = <slug>
_CANONICAL_RE: dict[str, re.Pattern[str]] = {
    fam: re.compile(r"^" + re.escape(prefix) + r" (\d{4}) = (.+)$")
    for fam, prefix in FAMILY_CANONICAL_PREFIX.items()
}

# Title label aliases → canonical family key
# Longer entries first to ensure greedy alternation matches correctly
_LABEL_TO_FAMILY: dict[str, str] = {
    "Contrato de sesión":    "contrato_de_sesion",
    "Procedencia de sesión": "procedencia_de_sesion",
    "Sesión":                "detalles_de_sesion",
    "Detalles de sesión":    "detalles_de_sesion",   # old form
    "Detalle de sesión":     "detalles_de_sesion",   # old form variant
    "Hipótesis de sesión":   "hipotesis_de_sesion",
    "Balance de sesión":     "balance_de_sesion",
    "Propuesta de sesión":   "propuesta_de_sesion",
    "Diagnóstico de sesión": "diagnostico_de_sesion",
}

_LABEL_PATTERN = "|".join(
    re.escape(k) for k in sorted(_LABEL_TO_FAMILY, key=len, reverse=True)
)

# Canonical label text by family (the label part after "#### 🌀[emoji] " in the prefix)
FAMILY_CANONICAL_LABEL: dict[str, str] = {}
for _fam, _pfx in FAMILY_CANONICAL_PREFIX.items():
    _after_wave = _pfx[len("#### 🌀"):]        # e.g. "🧾 Procedencia…" or " Contrato…"
    _space_idx = _after_wave.index(" ")
    FAMILY_CANONICAL_LABEL[_fam] = _after_wave[_space_idx + 1:]

# Parser for any recognised variant of a session artifact title
#   #### 🌀[extra_emoji] LABEL S?NUM = SLUG
_ANY_SESSION_RE: re.Pattern[str] = re.compile(
    r"^#### 🌀(\S*?)\s+"
    r"(" + _LABEL_PATTERN + r")"
    r"\s+(S?\d{1,4})\s*=\s*(.+)$",
    re.DOTALL,
)

# Families where session-number title policy does NOT apply
_NON_SESSION_FAMILIES: frozenset[str] = frozenset({
    "diagnostico_tematico",
    "diagnostico_de_modulo",
    "diagnostico_de_micro_ciclo",
    "diagnostico_de_meso_ciclo",
    "diagnostico_de_proyecto",
})

TitleStatus = Literal["canonical", "normalizable", "manual_review", "blocked", "not_applicable"]


@dataclass
class TitleClassification:
    """Outcome of classifying a session artifact title."""
    status: TitleStatus
    issue: str = ""                    # comma-separated machine codes
    proposed_title: str | None = None  # filled when status == "normalizable"
    reason: str = ""                   # human-readable explanation


# ── Internal helpers ──────────────────────────────────────────────────────────

def _normalize_session_num(raw: str) -> str | None:
    """Strip S/s prefix; zero-pad to 4 digits.  Returns None if not parseable."""
    cleaned = raw.lstrip("Ss")
    if not cleaned.isdigit():
        return None
    n = int(cleaned)
    if not 0 <= n <= 9999:
        return None
    return str(n).zfill(4)


# ── Public API ────────────────────────────────────────────────────────────────

def classify_title(title: str, family: str) -> TitleClassification:
    """Classify a session artifact title against the canonical naming contract.

    Returns TitleClassification with status:
    - ``canonical``      — already conforms to the contract.
    - ``normalizable``   — safe, unambiguous normalization available.
    - ``manual_review``  — pattern unrecognised; human must decide.
    - ``blocked``        — parsed but normalisation would be invalid.
    - ``not_applicable`` — family not subject to session-number policy.
    """
    if family in _NON_SESSION_FAMILIES or family not in FAMILY_CANONICAL_PREFIX:
        return TitleClassification(
            status="not_applicable",
            reason=f"family not subject to session-number title policy: {family!r}",
        )

    # Already canonical?
    if _CANONICAL_RE[family].fullmatch(title):
        return TitleClassification(status="canonical")

    # Try to parse a recognised variant
    m = _ANY_SESSION_RE.fullmatch(title)
    if not m:
        return TitleClassification(
            status="manual_review",
            issue="unparseable",
            reason="title does not match any known session artifact title pattern",
        )

    emoji_extra, label_raw, num_raw, slug = (
        m.group(1), m.group(2), m.group(3), m.group(4).strip()
    )

    if not slug:
        return TitleClassification(
            status="blocked",
            issue="empty_slug",
            reason="no slug text found after ' = '",
        )

    norm_num = _normalize_session_num(num_raw)
    if norm_num is None:
        return TitleClassification(
            status="manual_review",
            issue="bad_number",
            reason=f"cannot normalise session number: {num_raw!r}",
        )

    # Identify individual issues
    issues: list[str] = []

    if num_raw.upper().startswith("S"):
        issues.append("s_prefix_in_number")
    if len(num_raw.lstrip("Ss")) < 4:
        issues.append("unpadded_number")

    canonical_label = FAMILY_CANONICAL_LABEL.get(family, "")
    if label_raw != canonical_label:
        issues.append("wrong_family_label")

    expected_emoji = FAMILY_EMOJI_SUFFIX.get(family, "")
    if emoji_extra != expected_emoji:
        if emoji_extra and not expected_emoji:
            issues.append("extra_emoji")
        elif not emoji_extra and expected_emoji:
            issues.append("missing_emoji")
        else:
            issues.append("wrong_emoji")

    if not issues:
        issues.append("unknown_deviation")

    proposed = f"{FAMILY_CANONICAL_PREFIX[family]} {norm_num} = {slug}"

    return TitleClassification(
        status="normalizable",
        issue=",".join(issues),
        proposed_title=proposed,
        reason="; ".join(issues),
    )


def canonical_title_for(title: str, family: str) -> str | None:
    """Return the canonical form of *title*, or ``None`` if undeterminable."""
    cls = classify_title(title, family)
    if cls.status == "canonical":
        return title
    if cls.status == "normalizable":
        return cls.proposed_title
    return None


def needs_normalization(title: str, family: str) -> bool:
    """Return ``True`` when the title requires normalisation."""
    return classify_title(title, family).status == "normalizable"
