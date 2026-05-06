#!/usr/bin/env python3
"""Governance rules for non-session diagnostic artifacts.

Diagnostic artifacts differ from session artifacts:
  - Session artifacts:  mXX-sNN-<slug>.md.json  (go into canon via admission gate)
  - Diagnostic artifacts: named by family, live in 06_diagnoses/<family>/ (not in canon)

Valid diagnostic families and their filename patterns:

  tema       │ diagnostico-tematico-NN-slug.md.json
  micro_ciclo│ mXX-micro-ciclo-sNNN-sNNN-diagnostico.md.json
  meso_ciclo │ mXX-meso-ciclo-sNNN-sNNN-diagnostico.md.json
  proyecto   │ diagnostico-proyecto-NN-slug.md.json  OR  mXX-diagnostico-proyecto-slug.md.json
  sesion     │ diagnostico-sesion-sNNN-slug.md.json

Official root: data/out/local/sessions/06_diagnoses/<family>/

Sync path:
  LOCAL  data/out/local/sessions/06_diagnoses/<family>/
    → punctual publish (remote_publish_diagnostic.py)
    → OneDrive approot:/tiddly-data-converter/sessions/06_diagnoses/<family>/

  Equivalent roots:
    Local    data/out/local/sessions/06_diagnoses/<family>/
    OneDrive sessions/06_diagnoses/<family>/

  OneDrive _remote_outbox/sessions/ (flat)
    → pull (remote_pull_sessions.py)
    → data/tmp/remote_inbox/ (staged, flat)
    → manual placement into data/out/local/sessions/06_diagnoses/<family>/

NOTE: Creating a file in a remote runner does NOT automatically sync it to OneDrive.
The punctual publish workflow must run with dry_run=false for files to reach OneDrive.
The full mirror remains a controlled maintenance path and must not be used as
the default diagnostic publication mechanism from an incomplete remote workspace.
"""

from __future__ import annotations

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Session artifact pattern (reference — defined authoritatively in remote_pull_sessions.py)
# ---------------------------------------------------------------------------

SESSION_ARTIFACT_RE = re.compile(
    r"^m\d+-s\d+[a-z]?-.+\.md\.json$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Per-family patterns
# ---------------------------------------------------------------------------

DIAGNOSTIC_FAMILIES: dict[str, dict] = {
    "tema": {
        "filename_re": re.compile(
            r"^diagnostico-tematico-\d+-[a-z0-9]+(?:-[a-z0-9]+)*\.md\.json$",
            re.IGNORECASE,
        ),
        "subfolder": "tema",
    },
    "micro_ciclo": {
        "filename_re": re.compile(
            r"^m\d+-micro-ciclo-s\d+-s\d+-diagnostico\.md\.json$",
            re.IGNORECASE,
        ),
        "subfolder": "micro-ciclo",
    },
    "meso_ciclo": {
        "filename_re": re.compile(
            r"^m\d+-meso-ciclo-s\d+-s\d+-diagnostico\.md\.json$",
            re.IGNORECASE,
        ),
        "subfolder": "meso-ciclo",
    },
    "proyecto": {
        "filename_re": re.compile(
            r"^(?:"
            r"diagnostico-proyecto-\d+-[a-z0-9]+(?:-[a-z0-9]+)*"
            r"|m\d+-diagnostico-proyecto-[a-z0-9]+(?:-[a-z0-9]+)*"
            r")\.md\.json$",
            re.IGNORECASE,
        ),
        "subfolder": "proyecto",
    },
    "sesion": {
        "filename_re": re.compile(
            r"^diagnostico-sesion-s\d+-[a-z0-9]+(?:-[a-z0-9]+)*\.md\.json$",
            re.IGNORECASE,
        ),
        "subfolder": "sesion",
    },
}

# Combined pattern for quick "is this any diagnostic?" check
DIAGNOSTIC_FILENAME_RE = re.compile(
    r"^(?:"
    r"diagnostico-tematico-\d+-[a-z0-9]+(?:-[a-z0-9]+)*"
    r"|m\d+-micro-ciclo-s\d+-s\d+-diagnostico"
    r"|m\d+-meso-ciclo-s\d+-s\d+-diagnostico"
    r"|diagnostico-proyecto-\d+-[a-z0-9]+(?:-[a-z0-9]+)*"
    r"|m\d+-diagnostico-proyecto-[a-z0-9]+(?:-[a-z0-9]+)*"
    r"|diagnostico-sesion-s\d+-[a-z0-9]+(?:-[a-z0-9]+)*"
    r")\.md\.json$",
    re.IGNORECASE,
)

# Valid subfolders under 06_diagnoses/
VALID_DIAGNOSIS_SUBFOLDERS: frozenset[str] = frozenset(
    spec["subfolder"] for spec in DIAGNOSTIC_FAMILIES.values()
)

# Required extension for all artifacts in this system
REQUIRED_EXTENSION = ".md.json"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_diagnostic_artifact(filename: str) -> bool:
    """Return True if filename matches any known diagnostic pattern."""
    return bool(DIAGNOSTIC_FILENAME_RE.match(filename))


def detect_family(filename: str) -> str | None:
    """Return the diagnostic family key (e.g. 'tema', 'micro_ciclo'), or None."""
    for family, spec in DIAGNOSTIC_FAMILIES.items():
        if spec["filename_re"].match(filename):
            return family
    return None


def expected_subfolder(filename: str) -> str | None:
    """Return the 06_diagnoses subfolder name for filename, or None if unknown."""
    family = detect_family(filename)
    if family is None:
        return None
    return DIAGNOSTIC_FAMILIES[family]["subfolder"]


def classify_artifact(filename: str) -> tuple[str, str]:
    """Classify a filename into (artifact_type, family).

    artifact_type: 'session_artifact' | 'diagnostic_artifact' | 'unknown'
    family: diagnostic family key for diagnostic_artifact, '' otherwise
    """
    if SESSION_ARTIFACT_RE.match(filename):
        return "session_artifact", ""
    family = detect_family(filename)
    if family is not None:
        return "diagnostic_artifact", family
    return "unknown", ""


def is_safe_path(path_str: str) -> tuple[bool, str]:
    """Reject path traversal (..) and absolute paths.

    Returns (safe, reason). reason is '' when safe.
    """
    normalized = path_str.replace("\\", "/")
    parts = normalized.split("/")
    if ".." in parts:
        return False, "path_traversal"
    if Path(path_str).is_absolute():
        return False, "absolute_path"
    return True, ""


def has_valid_extension(filename: str) -> bool:
    """Return True only if filename ends with .md.json (not .json, .md, etc.)."""
    return filename.endswith(REQUIRED_EXTENSION) and len(filename) > len(REQUIRED_EXTENSION)


def validate_diagnostic_artifact_path(filename: str, subfolder: str) -> tuple[bool, str]:
    """Validate that a diagnostic filename belongs in the given 06_diagnoses subfolder.

    Args:
        filename:  bare filename (e.g. 'diagnostico-tematico-08-foo.md.json')
        subfolder: the 06_diagnoses subfolder where the file lives (e.g. 'tema')

    Returns:
        (valid, reason) — reason is '' when valid.
    """
    # Extension check first
    if not has_valid_extension(filename):
        return False, "invalid_extension"

    # Reject path traversal in filename itself
    safe, reason = is_safe_path(filename)
    if not safe:
        return False, reason

    # Must be a known diagnostic pattern
    family = detect_family(filename)
    if family is None:
        return False, "unknown_diagnostic_family"

    # Subfolder must match family
    expected = DIAGNOSTIC_FAMILIES[family]["subfolder"]
    if subfolder != expected:
        return False, f"wrong_subfolder:expected={expected},got={subfolder}"

    # Subfolder must be a valid one
    if subfolder not in VALID_DIAGNOSIS_SUBFOLDERS:
        return False, f"invalid_diagnosis_subfolder:{subfolder}"

    return True, ""


def validate_full_path(path_str: str, sessions_root: Path) -> tuple[bool, str]:
    """Validate a full path under data/out/local/sessions/06_diagnoses/.

    Accepts both absolute and relative paths.
    Checks:
    1. No path traversal (..) in the raw string.
    2. Path resolves under sessions_root/06_diagnoses/<valid-subfolder>/.
    3. Filename matches the family expected for that subfolder.

    Returns (valid, reason).
    """
    # Reject traversal components in raw string
    normalized = path_str.replace("\\", "/")
    if ".." in normalized.split("/"):
        return False, "path_traversal"

    try:
        path = Path(path_str).resolve()
    except Exception:
        return False, "invalid_path"

    diagnoses_root = (sessions_root / "06_diagnoses").resolve()

    # Must be under diagnoses root
    try:
        rel = path.relative_to(diagnoses_root)
    except ValueError:
        return False, "path_outside_diagnoses_root"

    parts = rel.parts
    if len(parts) < 2:
        return False, "missing_subfolder_or_filename"

    subfolder = parts[0]
    filename = parts[-1]

    if subfolder not in VALID_DIAGNOSIS_SUBFOLDERS:
        return False, f"invalid_diagnosis_subfolder:{subfolder}"

    return validate_diagnostic_artifact_path(filename, subfolder)
