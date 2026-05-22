#!/usr/bin/env python3
"""Governance authority for session artifacts under data/out/local/sessions/.

Provides family classification, session ID extraction, tag generation, and
canonizability validation for session artifacts.  Extracted from session_sync.py
to serve as the single authority for session artifact governance and eliminate
logic duplication across admit_session_candidates and session_sync.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from path_governance import as_display_path  # noqa: E402
from session_title_policy import needs_normalization  # noqa: E402


# ── Family registry ───────────────────────────────────────────────────────────

FAMILY_BY_RELATIVE_ROOT: dict[tuple[str, ...], dict[str, Any]] = {
    ("00_contratos",): {
        "family": "contrato_de_sesion",
        "role_primary": "policy",
        "source_role": "policy",
        "order": 1,
    },
    ("01_procedencia",): {
        "family": "procedencia_de_sesion",
        "role_primary": "evidence",
        "source_role": "procedencia",
        "order": 2,
    },
    ("02_detalles_de_sesion",): {
        "family": "detalles_de_sesion",
        "role_primary": "log",
        "source_role": "reporte",
        "order": 3,
    },
    ("03_hipotesis",): {
        "family": "hipotesis_de_sesion",
        "role_primary": "procedure",
        "source_role": "procedure",
        "order": 4,
    },
    ("04_balance_de_sesion",): {
        "family": "balance_de_sesion",
        "role_primary": "log",
        "source_role": "reporte",
        "order": 5,
    },
    ("05_propuesta_de_sesion",): {
        "family": "propuesta_de_sesion",
        "role_primary": "procedure",
        "source_role": "procedure",
        "order": 6,
    },
    ("06_diagnoses", "sesion"): {
        "family": "diagnostico_de_sesion",
        "role_primary": "log",
        "source_role": "reporte",
        "order": 7,
    },
    ("06_diagnoses", "tema"): {
        "family": "diagnostico_tematico",
        "role_primary": "log",
        "source_role": "reporte",
        "order": 8,
    },
    ("06_diagnoses", "module"): {
        "family": "diagnostico_de_modulo",
        "role_primary": "log",
        "source_role": "reporte",
        "order": 9,
    },
    ("06_diagnoses", "micro-ciclo"): {
        "family": "diagnostico_de_micro_ciclo",
        "role_primary": "log",
        "source_role": "reporte",
        "order": 10,
    },
    ("06_diagnoses", "meso-ciclo"): {
        "family": "diagnostico_de_meso_ciclo",
        "role_primary": "log",
        "source_role": "reporte",
        "order": 11,
    },
    ("06_diagnoses", "proyecto"): {
        "family": "diagnostico_de_proyecto",
        "role_primary": "log",
        "source_role": "reporte",
        "order": 12,
    },
}

# Matches standard session IDs: mXX-sNNN-slug  (e.g. m04-s0121-contrato-...)
SESSION_RE = re.compile(r"^(m\d+)-s([0-9]+[a-z]?)-(.+)$")

FAMILY_LABELS: dict[str, str] = {
    "contrato_de_sesion": "Contrato de sesión",
    "procedencia_de_sesion": "Procedencia de sesión",
    "detalles_de_sesion": "Detalles de sesión",
    "hipotesis_de_sesion": "Hipótesis de sesión",
    "balance_de_sesion": "Balance de sesión",
    "propuesta_de_sesion": "Propuesta de sesión",
    "diagnostico_de_sesion": "Diagnóstico de sesión",
    "diagnostico_tematico": "Diagnóstico temático",
    "diagnostico_de_modulo": "Diagnóstico de módulo",
    "diagnostico_de_micro_ciclo": "Diagnóstico de micro-ciclo",
    "diagnostico_de_meso_ciclo": "Diagnóstico de meso-ciclo",
    "diagnostico_de_proyecto": "Diagnóstico de proyecto",
}


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ArtifactFamilySpec:
    """Resolved family metadata for a session artifact."""
    family: str
    role_primary: str
    source_role: str
    order: int
    folder_key: tuple[str, ...]


@dataclass
class CanonizabilityResult:
    """Result of validating whether a session artifact can be canonized."""
    is_canonizable: bool
    path: Path
    session_id: str
    family_spec: ArtifactFamilySpec | None
    errors: list[str] = field(default_factory=list)
    title_warnings: list[str] = field(default_factory=list)  # S0124: non-canonical title flags


# ── Core functions ─────────────────────────────────────────────────────────────

def classify_artifact_family(path: Path, sessions_dir: Path) -> ArtifactFamilySpec | None:
    """Return the ArtifactFamilySpec for a session artifact path, or None if unknown.

    Matches by folder prefix relative to sessions_dir.  Thematic diagnostics
    (06_diagnoses/tema/) are recognized without requiring a standard mXX-sNNN
    filename prefix — they are valid by virtue of their folder location.
    """
    try:
        rel = path.relative_to(sessions_dir)
    except ValueError:
        return None
    parts = rel.parts
    for prefix, spec in FAMILY_BY_RELATIVE_ROOT.items():
        if parts[: len(prefix)] == prefix:
            return ArtifactFamilySpec(
                family=spec["family"],
                role_primary=spec["role_primary"],
                source_role=spec["source_role"],
                order=spec["order"],
                folder_key=prefix,
            )
    return None


def extract_session_id(path: Path) -> str:
    """Derive a session ID string from an artifact path.

    For standard artifacts: strips the ``.md.json`` double-extension.
    For any other file: uses the stem only.
    Thematic diagnostics (``diagnostico-tematico-NNN-...``) are preserved as-is.
    """
    name = path.name
    if name.endswith(".md.json"):
        return name[: -len(".md.json")]
    return path.stem


def parse_session_parts(session_id: str) -> tuple[str, str, str]:
    """Parse a session ID into (milestone, number, slug).

    Returns (``""``, ``""``, session_id) for non-standard IDs such as thematic
    diagnostic filenames that do not follow the mXX-sNNN-slug convention.
    This is intentional: thematic diagnostics keep their own identity.
    """
    match = SESSION_RE.match(session_id)
    if not match:
        return "", "", session_id
    milestone, number, slug = match.groups()
    if slug.startswith("session-"):
        slug = slug[len("session-") :]
    return milestone, number, slug


def build_session_tags(session_id: str, artifact_family: str) -> list[str]:
    """Generate canonical tags for a session artifact candidate.

    For standard sessions the first tag is ``session:mXX-sNNN``.
    For non-standard IDs (thematic diagnostics, micro-ciclo names, etc.)
    the tag is ``session:<full-session-id>``.
    """
    milestone, number, _slug = parse_session_parts(session_id)
    tags: list[str] = []
    if milestone and number:
        tags.append(f"session:{milestone}-s{number}")
        tags.append(f"milestone:{milestone}")
    else:
        tags.append(f"session:{session_id}")
    tags.extend([f"artifact:{artifact_family}", "status:candidate", "layer:session"])
    deduped: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            deduped.append(tag)
    return deduped


def describe_family(family: str | None) -> str:
    """Return a human-readable label for an artifact family name."""
    return FAMILY_LABELS.get(family or "", family or "desconocida")


def known_families() -> list[str]:
    """Return the list of all registered family names."""
    return [spec["family"] for spec in FAMILY_BY_RELATIVE_ROOT.values()]


# ── Validation ────────────────────────────────────────────────────────────────

def check_canonizable(path: Path, sessions_dir: Path) -> CanonizabilityResult:
    """Validate that a session artifact is canonizable.

    Returns a CanonizabilityResult with ``is_canonizable=True`` when all of:
    - The path is under sessions_dir
    - The file has ``.md.json`` extension
    - The file contains valid JSON with a non-empty ``title`` field
    - The artifact family can be detected from the folder structure

    Thematic diagnostics (``diagnostico-tematico-NNN-...``) are fully supported
    without requiring renaming to the standard mXX-sNNN- prefix.
    """
    errors: list[str] = []
    session_id = extract_session_id(path)

    # Must be under sessions_dir
    try:
        path.resolve().relative_to(sessions_dir.resolve())
    except ValueError:
        errors.append(f"path is not under sessions_dir: {as_display_path(path)}")

    # Must have .md.json extension
    if not path.name.endswith(".md.json"):
        errors.append(f"unsupported extension (expected .md.json): {path.name}")

    # Must belong to a known family
    family_spec: ArtifactFamilySpec | None = None
    if not errors:
        family_spec = classify_artifact_family(path, sessions_dir)
        if family_spec is None:
            try:
                rel = path.relative_to(sessions_dir)
                rel_str = str(rel)
            except ValueError:
                rel_str = str(path)
            errors.append(f"unknown artifact family for path: {rel_str}")

    # Must contain parseable JSON with title and text
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            tiddler: Any = payload[0] if isinstance(payload, list) and payload else payload
            if not isinstance(tiddler, dict):
                errors.append("JSON payload is not an object or tiddler array")
            else:
                raw_title = tiddler.get("title")
                if not raw_title or not str(raw_title).strip():
                    errors.append("artifact has no title")
                if tiddler.get("text") is None:
                    errors.append("artifact has no text field")
        except json.JSONDecodeError as exc:
            errors.append(f"invalid JSON: {exc}")
        except (OSError, ValueError, IndexError) as exc:
            errors.append(f"cannot read artifact: {exc}")
    else:
        errors.append(f"file does not exist: {as_display_path(path)}")

    # S0124: check title naming policy (non-blocking warning)
    title_warnings: list[str] = []
    if not errors and family_spec is not None:
        try:
            with path.open("r", encoding="utf-8") as fh:
                _payload = json.load(fh)
            _tiddler: Any = _payload[0] if isinstance(_payload, list) and _payload else _payload
            _title = str(_tiddler.get("title", "")) if isinstance(_tiddler, dict) else ""
            if _title and needs_normalization(_title, family_spec.family):
                title_warnings.append(f"needs_title_normalization: {_title[:80]}")
        except Exception:
            pass  # best-effort; do not block canonizability for title warning

    return CanonizabilityResult(
        is_canonizable=not errors,
        path=path,
        session_id=session_id,
        family_spec=family_spec,
        errors=errors,
        title_warnings=title_warnings,
    )
