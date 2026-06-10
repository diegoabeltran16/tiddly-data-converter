#!/usr/bin/env python3
"""build_minimal_reversible_metadata.py — S0134

Construye una matriz de metadata mínima reversible para artefactos
canonizables de sesión y diagnóstico, tomando como base los tiddlers
ya admitidos en el canon local y el contrato DT035 v1 (S0133).

Modo de operación:
  - Solo lectura del canon (data/out/local/tiddlers_*.jsonl).
  - No modifica ningún archivo del canon.
  - No admite relaciones ni escribe en relations de los tiddlers.
  - La metadata inferida queda marcada como inferida.

Uso
---
  # Generar matriz para todos los artefactos de sesión/diagnóstico
  python3 build_minimal_reversible_metadata.py

  # Especificar ruta de canon y salida
  python3 build_minimal_reversible_metadata.py \\
      --canon-root data/out/local/ \\
      --out-dir data/out/local/pipeline/reversible_metadata/s0134/ \\
      --session s0134

  # Filtrar por familia
  python3 build_minimal_reversible_metadata.py \\
      --family diagnostico_tematico

  # Modo verbose
  python3 build_minimal_reversible_metadata.py --verbose

Salida
------
  {out_dir}/s0134_reversible_metadata_matrix.json
  {out_dir}/s0134_reversible_metadata_summary.md
  {out_dir}/s0134_reversible_metadata_review.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_CANON_ROOT = REPO_ROOT / "data" / "out" / "local"
DEFAULT_OUT_DIR = DEFAULT_CANON_ROOT / "pipeline" / "reversible_metadata" / "s0134"
DEFAULT_SESSION = "s0134"

sys.path.insert(0, str(SCRIPT_DIR))

from source_fields_contract import (  # noqa: E402
    ERROR,
    WARNING,
    KNOWN_ARTIFACT_FAMILIES,
    FAMILY_ALIASES,
    validate_source_fields,
    summarize_issues,
)

# ── Constantes ────────────────────────────────────────────────────────────────

SCHEMA_VERSION = "minimal-reversible-metadata/v1"

# Families that belong to session artifacts (have m##-s#### session IDs)
SESSION_FAMILIES: frozenset[str] = frozenset({
    "contrato_de_sesion",
    "procedencia_de_sesion",
    "detalles_de_sesion",
    "hipotesis_de_sesion",
    "balance_de_sesion",
    "propuesta_de_sesion",
    "diagnostico_de_sesion",
})

# Families that are diagnostics (have DT### or cycle IDs)
DIAGNOSTIC_FAMILIES: frozenset[str] = frozenset({
    "diagnostico_tematico",
    "diagnostico_de_micro_ciclo",
    "diagnostico_de_meso_ciclo",
    "diagnostico_de_proyecto",
})

ALL_KNOWN_FAMILIES = SESSION_FAMILIES | DIAGNOSTIC_FAMILIES

# Spanish stopwords for keyword extraction
_STOPWORDS: frozenset[str] = frozenset({
    "de", "del", "la", "las", "los", "el", "un", "una", "y", "en", "a", "con",
    "que", "para", "por", "o", "es", "se", "al", "lo", "su", "como", "no",
    "si", "más", "desde", "hasta", "sobre", "entre", "hacia", "este", "esta",
    "ese", "esa", "hay", "son", "ser", "fue", "era", "han", "ha", "muy",
    "pero", "sin", "ya", "todo", "cuando", "donde", "quien", "cual", "qué",
    "cómo", "por qué", "sesion", "sesión", "balance", "contrato", "propuesta",
    "hipotesis", "hipótesis", "procedencia", "detalles", "diagnostico", "diagnóstico",
    "temático", "tematico", "sesion", "micro", "meso", "ciclo",
    "the", "and", "for", "with", "from", "into", "that", "this",
})

# Regex patterns
_SESSION_ORIGIN_RE = re.compile(r"^(m\d+)-(s\d{1,4}[a-z]?)-")
_DIAG_TEMATICO_ORIGIN_RE = re.compile(r"^diagnostico-tematico-(\d+)-")
_DIAG_SESION_RE = re.compile(r"^(m\d+)-(s\d{1,4})-diagnostico-sesion")
_CYCLE_ORIGIN_RE = re.compile(r"^(m\d+)-(?:micro|meso)-ciclo-(.+)")

_TITLE_SESSION_NUM_RE = re.compile(
    r"[Ss]esi[oó]n\s+(\d{1,4})\s*=", re.IGNORECASE
)
_TITLE_DIAG_TEMATICO_RE = re.compile(
    r"[Dd]iagn[oó]stico\s+tem[aá]tico\s+(\d{1,4})", re.IGNORECASE
)
_TITLE_DIAG_CICLO_RE = re.compile(
    r"[Dd]iagn[oó]stico\s+(?:de\s+)?(?:micro|meso)ciclo", re.IGNORECASE
)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_REF_SESSION_RE = re.compile(r"\bS(\d{4})\b")
_REF_SESSION_FULL_RE = re.compile(r"\bm\d+-s(\d{4})-\S+")
_REF_DT_RE = re.compile(r"\bDT(\d{2,3})\b")
_REF_DT_LONG_RE = re.compile(r"[Dd]iagn[oó]stico\s+tem[aá]tico\s+(\d{1,4})", re.IGNORECASE)
_REF_SCRIPT_RE = re.compile(r"`([a-zA-Z0-9_/.-]+\.(?:py|go|sh|js|ts))`")
_REF_PATH_SCRIPT_RE = re.compile(r"python_scripts/([a-zA-Z0-9_.-]+\.py)")

_SAFE_SOURCE_PATH_RE = re.compile(r"^data/out/local/sessions/")
_LEGACY_SOURCE_PATH_RE = re.compile(r"^data/sessions/")


# ── Extraction helpers ────────────────────────────────────────────────────────

def _normalize_family(family: str) -> str:
    return FAMILY_ALIASES.get(family, family)


def extract_session_id(record: dict[str, Any]) -> str | None:
    """Extract canonical session ID (e.g. 'm04-s0133') from tiddler."""
    sf = record.get("source_fields") or {}
    so = sf.get("session_origin", "") or ""

    m = _SESSION_ORIGIN_RE.match(so)
    if m:
        module, seq = m.group(1), m.group(2)
        # Normalize: s001 → s0001, s01 → s0001, s0133 stays
        digits = re.sub(r"[a-z]", "", seq[1:])  # remove letter suffix
        suffix = seq[len(digits) + 1:]  # any trailing letter
        norm_digits = digits.zfill(4)
        return f"{module}-s{norm_digits}{suffix}"

    # Try diagnostic-session pattern
    m2 = _DIAG_SESION_RE.match(so)
    if m2:
        module, seq = m2.group(1), m2.group(2)
        digits = seq[1:].zfill(4)
        return f"{module}-s{digits}"

    return None


def extract_diagnostic_id(record: dict[str, Any]) -> str | None:
    """Extract diagnostic ID (e.g. 'DT035') from title or session_origin."""
    title = record.get("title", "") or ""
    sf = record.get("source_fields") or {}
    so = sf.get("session_origin", "") or ""

    # From title: "Diagnóstico temático 035" or "Diagnóstico temático 0035"
    m = _TITLE_DIAG_TEMATICO_RE.search(title)
    if m:
        return f"DT{int(m.group(1)):03d}"

    # From session_origin: "diagnostico-tematico-01-..."
    m2 = _DIAG_TEMATICO_ORIGIN_RE.match(so)
    if m2:
        return f"DT{int(m2.group(1)):03d}"

    return None


def extract_module(session_id: str | None) -> str | None:
    if not session_id:
        return None
    m = re.match(r"^(m\d+)-", session_id)
    return m.group(1) if m else None


def extract_sequence(session_id: str | None) -> int | None:
    if not session_id:
        return None
    m = re.search(r"-s(\d+)", session_id)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def _detect_content_format(text: str | None, content_type: str) -> str:
    if not text:
        return "empty"
    if content_type and "json" in content_type.lower():
        return "json"
    if text.strip().startswith("{") or text.strip().startswith("["):
        try:
            json.loads(text)
            return "json"
        except (json.JSONDecodeError, ValueError):
            pass
    if content_type and "markdown" in content_type.lower():
        return "markdown"
    return "markdown"


def _extract_keywords(title: str) -> list[str]:
    """Extract keywords from the slug part of the title (after '=')."""
    m = re.search(r"=\s*(.+)$", title)
    if not m:
        # Fall back to all words in title
        raw = title
    else:
        raw = m.group(1)

    # Remove emoji and special chars
    raw = re.sub(r"[🌀🧾🧪#*_`\[\]]", " ", raw)
    words = re.split(r"[-_\s/]+", raw.lower())
    keywords = [
        w for w in words
        if len(w) >= 4 and w not in _STOPWORDS and re.match(r"^[a-záéíóúüñ]+$", w)
    ]
    return sorted(set(keywords))


def _extract_headings(text: str, content_format: str) -> list[str]:
    if content_format == "json" or not text:
        return []
    return [
        m.group(2).strip()
        for m in _HEADING_RE.finditer(text)
        if len(m.group(1)) <= 4
    ]


def _extract_referenced_sessions(text: str, content_format: str) -> list[str]:
    if content_format == "json" or not text:
        return []
    found: set[str] = set()
    for m in _REF_SESSION_RE.finditer(text):
        found.add(f"S{m.group(1)}")
    for m in _REF_SESSION_FULL_RE.finditer(text):
        found.add(f"S{m.group(1)}")
    return sorted(found)


def _extract_referenced_diagnostics(text: str, content_format: str) -> list[str]:
    if content_format == "json" or not text:
        return []
    found: set[str] = set()
    for m in _REF_DT_RE.finditer(text):
        found.add(f"DT{int(m.group(1)):03d}")
    for m in _REF_DT_LONG_RE.finditer(text):
        found.add(f"DT{int(m.group(1)):03d}")
    return sorted(found)


def _extract_referenced_scripts(text: str, content_format: str) -> list[str]:
    if content_format == "json" or not text:
        return []
    found: set[str] = set()
    for m in _REF_SCRIPT_RE.finditer(text):
        found.add(m.group(1))
    for m in _REF_PATH_SCRIPT_RE.finditer(text):
        found.add(f"python_scripts/{m.group(1)}")
    return sorted(found)


def infer_metadata(
    text: str | None,
    content_format: str,
    title: str = "",
) -> dict[str, Any]:
    text = text or ""
    return {
        "keywords": _extract_keywords(title),
        "headings": _extract_headings(text, content_format),
        "referenced_sessions": _extract_referenced_sessions(text, content_format),
        "referenced_diagnostics": _extract_referenced_diagnostics(text, content_format),
        "referenced_scripts": _extract_referenced_scripts(text, content_format),
    }


# ── Reversibility ─────────────────────────────────────────────────────────────

def _compute_reversibility(
    record: dict[str, Any],
    sf: dict[str, Any],
    artifact_family: str,
    validation_errors: list[str],
    validation_warnings: list[str],
    validation_warning_codes: list[str] | None = None,
) -> str:
    """Determine reversibility status: 'safe', 'warning', or 'blocked'.

    Criterios (S0134 §4, Regla 5):
      safe    — conserva título, texto y ruta fuente suficiente.
      warning — hay metadata inferida o incongruencia no bloqueante.
      blocked — falta título, texto, familia o hay error de contrato.

    Nota: SF007 (legacy TW fields) son warnings de migración, no de
    reversibilidad. No degradan 'safe' a 'warning' por sí solos.
    """
    title = record.get("title", "") or ""
    text = record.get("text", "") or ""

    # Blocked conditions
    if not title.strip():
        return "blocked"
    if not text.strip() and not record.get("content"):
        return "blocked"
    if not artifact_family:
        return "blocked"

    # Errors always → blocked
    if validation_errors:
        return "blocked"

    # SF007 (legacy TW fields) warnings alone do not downgrade to 'warning'.
    # They are migration recommendations, not reversibility risks.
    substantive_warning_codes = [
        c for c in (validation_warning_codes or [])
        if c not in ("SF007",)   # exclude legacy-field-only warnings
    ]
    if substantive_warning_codes:
        return "warning"

    source_path = sf.get("source_path", "") or ""
    if not source_path:
        return "warning"

    if _LEGACY_SOURCE_PATH_RE.match(source_path):
        return "warning"  # legacy path (data/sessions/) is a mild concern

    if not _SAFE_SOURCE_PATH_RE.match(source_path) and not _LEGACY_SOURCE_PATH_RE.match(source_path):
        return "warning"

    return "safe"


# ── Record builder ────────────────────────────────────────────────────────────

def build_record(tiddler: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal reversible metadata record from a canon tiddler."""
    sf = tiddler.get("source_fields") or {}
    title = tiddler.get("title", "") or ""
    text = tiddler.get("text", "") or ""
    content_type = tiddler.get("content_type", "") or ""
    artifact_family = (
        sf.get("artifact_family", "")
        or tiddler.get("artifact_family", "")
        or ""
    )
    artifact_family = _normalize_family(artifact_family)

    # ── Explicit metadata ─────────────────────────────────────────────────────
    session_id = extract_session_id(tiddler)
    diagnostic_id = extract_diagnostic_id(tiddler)
    module = extract_module(session_id)
    sequence = extract_sequence(session_id)
    slug = tiddler.get("canonical_slug", "") or ""
    content_format = _detect_content_format(text, content_type)

    reversible_metadata: dict[str, Any] = {
        "canonical_title": title,
        "artifact_family": artifact_family,
        "session_id": session_id,
        "diagnostic_id": diagnostic_id,
        "module": module,
        "sequence": sequence,
        "slug": slug,
        "content_format": content_format,
        "visibility": "canonizable",
        "reversibility_status": None,  # set below
    }

    # ── Inferred metadata ─────────────────────────────────────────────────────
    inferred = infer_metadata(text, content_format, title=title)

    # ── Validation (via S0133 contract) ───────────────────────────────────────
    issues = validate_source_fields(tiddler, level="baseline", strict_forbidden=True)
    summary = summarize_issues(issues)
    validation_errors = [
        i["message"] for i in summary["issues"] if i["severity"] == ERROR
    ]
    validation_warnings = [
        i["message"] for i in summary["issues"] if i["severity"] == WARNING
    ]
    validation = {
        "status": "error" if validation_errors else ("warning" if validation_warnings else "ok"),
        "error_codes": summary["error_codes"],
        "warning_codes": summary["warning_codes"],
        "errors": validation_errors[:5],   # cap at 5 for compactness
        "warnings": validation_warnings[:5],
    }

    # ── Reversibility ─────────────────────────────────────────────────────────
    rev_status = _compute_reversibility(
        tiddler, sf, artifact_family,
        validation_errors, validation_warnings,
        validation_warning_codes=summary["warning_codes"],
    )
    reversible_metadata["reversibility_status"] = rev_status

    return {
        "tiddler_id": tiddler.get("id", ""),
        "title": title,
        "artifact_family": artifact_family,
        "source_path": sf.get("source_path", "") or "",
        "source_fields": dict(sf),
        "reversible_metadata": reversible_metadata,
        "inferred_metadata": inferred,
        "validation": validation,
    }


# ── Canon reader ──────────────────────────────────────────────────────────────

def read_canon_tiddlers(
    canon_root: Path,
    *,
    families: set[str] | None = None,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """Read all tiddlers with artifact_family from canon shards."""
    records: list[dict[str, Any]] = []
    shards = sorted(canon_root.glob("tiddlers_*.jsonl"))

    if not shards:
        raise FileNotFoundError(
            f"No se encontraron archivos tiddlers_*.jsonl en {canon_root}"
        )

    for shard in shards:
        count = 0
        with shard.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                sf = rec.get("source_fields") or {}
                fam = sf.get("artifact_family", "") or rec.get("artifact_family", "")
                if not fam:
                    continue
                fam_norm = _normalize_family(fam)
                if families and fam_norm not in families and fam not in families:
                    continue
                records.append(rec)
                count += 1
        if verbose:
            print(f"  {shard.name}: {count} session artifacts", file=sys.stderr)

    return records


# ── Matrix builder ────────────────────────────────────────────────────────────

def build_matrix(
    records: list[dict[str, Any]],
    *,
    session: str = DEFAULT_SESSION,
    canon_root: Path = DEFAULT_CANON_ROOT,
) -> dict[str, Any]:
    """Build the full metadata matrix from a list of tiddlers."""
    built_records = [build_record(r) for r in records]

    statuses = {"safe": 0, "warning": 0, "blocked": 0}
    families: dict[str, int] = {}
    for r in built_records:
        s = r["reversible_metadata"]["reversibility_status"] or "unknown"
        statuses[s] = statuses.get(s, 0) + 1
        f = r["artifact_family"]
        families[f] = families.get(f, 0) + 1

    return {
        "schema": SCHEMA_VERSION,
        "session": session.upper(),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "source": {
            "canon_root": str(canon_root.relative_to(REPO_ROOT) if canon_root.is_relative_to(REPO_ROOT) else canon_root),
            "source_fields_contract": "S0133 (DT035-v1)",
        },
        "summary": {
            "total_records": len(built_records),
            "safe": statuses.get("safe", 0),
            "warning": statuses.get("warning", 0),
            "blocked": statuses.get("blocked", 0),
            "families": families,
        },
        "records": built_records,
    }


# ── Report writers ────────────────────────────────────────────────────────────

def write_matrix_json(matrix: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Write compact version without full source_fields for readability
    compact = dict(matrix)
    compact_records = []
    for r in matrix.get("records", []):
        cr = dict(r)
        # Summarize source_fields instead of full copy to keep file compact
        sf = r.get("source_fields", {})
        cr["source_fields_summary"] = {
            "has_artifact_family": bool(sf.get("artifact_family")),
            "has_source_path": bool(sf.get("source_path")),
            "has_provenance_ref": bool(sf.get("provenance_ref")),
            "canonical_status": sf.get("canonical_status", ""),
            "session_origin": sf.get("session_origin", ""),
        }
        del cr["source_fields"]
        compact_records.append(cr)
    compact["records"] = compact_records

    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(compact, fh, indent=2, ensure_ascii=False)
    print(f"[OK] Matriz JSON → {out_path}", file=sys.stderr)


def write_summary_md(matrix: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    s = matrix["summary"]
    records = matrix.get("records", [])
    families = s.get("families", {})

    # Compute explicit vs inferred stats
    total_headings = sum(
        len(r["inferred_metadata"]["headings"]) for r in records
    )
    total_ref_sessions = sum(
        len(r["inferred_metadata"]["referenced_sessions"]) for r in records
    )
    total_ref_diags = sum(
        len(r["inferred_metadata"]["referenced_diagnostics"]) for r in records
    )
    total_ref_scripts = sum(
        len(r["inferred_metadata"]["referenced_scripts"]) for r in records
    )
    records_with_session_id = sum(
        1 for r in records if r["reversible_metadata"].get("session_id")
    )
    records_with_diag_id = sum(
        1 for r in records if r["reversible_metadata"].get("diagnostic_id")
    )
    content_formats: dict[str, int] = {}
    for r in records:
        cf = r["reversible_metadata"].get("content_format", "unknown")
        content_formats[cf] = content_formats.get(cf, 0) + 1

    lines = [
        "# S0134 — Metadata mínima reversible",
        "",
        f"**Generado:** {matrix['generated_at']}  ",
        f"**Esquema:** `{matrix['schema']}`  ",
        f"**Contrato source_fields usado:** `{matrix['source']['source_fields_contract']}`",
        "",
        "## Fuente usada",
        "",
        f"- Canon: `{matrix['source']['canon_root']}`",
        "- Derivados: no procesados en esta sesión",
        f"- Contrato source_fields usado: `{matrix['source']['source_fields_contract']}`",
        "- Scripts revisados: `build_minimal_reversible_metadata.py`, `source_fields_contract.py`",
        "",
        "## Resultados",
        "",
        f"| Métrica | Valor |",
        f"|---------|-------|",
        f"| Total records analizados | {s['total_records']} |",
        f"| safe | {s['safe']} |",
        f"| warning | {s['warning']} |",
        f"| blocked | {s['blocked']} |",
        f"| Tasa de reversibilidad segura | {s['safe'] / max(s['total_records'], 1) * 100:.1f}% |",
        "",
        "## Familias detectadas",
        "",
        "| artifact_family | Registros | Reversibilidad típica |",
        "|-----------------|----------:|----------------------|",
    ]
    for fam, cnt in sorted(families.items(), key=lambda x: -x[1]):
        # Compute family-level reversibility
        fam_records = [r for r in records if r["artifact_family"] == fam]
        fam_statuses = {r["reversible_metadata"]["reversibility_status"] for r in fam_records}
        rev_note = "/".join(sorted(fam_statuses)) if fam_statuses else "?"
        lines.append(f"| `{fam}` | {cnt} | {rev_note} |")
    lines.append("")

    lines += [
        "## Metadata explícita encontrada",
        "",
        "| Campo | Registros con valor |",
        "|-------|--------------------:|",
        f"| session_id extraído | {records_with_session_id} |",
        f"| diagnostic_id extraído | {records_with_diag_id} |",
        "",
        "### Formatos de contenido",
        "",
        "| content_format | Registros |",
        "|----------------|----------:|",
    ]
    for cf, cnt in sorted(content_formats.items(), key=lambda x: -x[1]):
        lines.append(f"| `{cf}` | {cnt} |")
    lines.append("")

    lines += [
        "## Metadata inferida encontrada",
        "",
        "| Tipo | Total instancias |",
        "|------|----------------:|",
        f"| Headings markdown extraídos | {total_headings} |",
        f"| Referencias a sesiones (S####) | {total_ref_sessions} |",
        f"| Referencias a diagnósticos (DT###) | {total_ref_diags} |",
        f"| Scripts referenciados en texto | {total_ref_scripts} |",
        "",
        "> Nota: toda metadata inferida queda marcada en `inferred_metadata` y NO",
        "> se convierte en verdad canónica ni en relaciones admitidas.",
        "",
        "## Riesgos de reversibilidad",
        "",
    ]

    # List blocked records
    blocked = [r for r in records if r["reversible_metadata"]["reversibility_status"] == "blocked"]
    if blocked:
        lines.append(f"### Registros bloqueados ({len(blocked)})")
        lines.append("")
        for r in blocked[:10]:
            lines.append(f"- `{r['title'][:80]}`: {r['validation']['errors'][:2]}")
        if len(blocked) > 10:
            lines.append(f"- *(y {len(blocked) - 10} más)*")
    else:
        lines.append("No se detectaron registros bloqueados.")
    lines.append("")

    legacy_path = sum(
        1 for r in records
        if r.get("source_path", "").startswith("data/sessions/")
    )
    if legacy_path:
        lines.append(
            f"- **Rutas legadas**: {legacy_path} registros usan `data/sessions/` "
            "(ruta pre-S66, aceptada pero recomendada migrar a `data/out/local/sessions/`)."
        )
    else:
        lines.append("- No se detectaron rutas `data/sessions/` legadas en los registros analizados.")

    lines += [
        "",
        "## Decisión recomendada",
        "",
        "1. La metadata **explícita** (session_id, diagnostic_id, module, slug) puede usarse",
        "   en futuros enriquecimientos canónicos sin riesgo de pérdida de información.",
        "2. La metadata **inferida** (headings, referencias S####/DT###, scripts) debe",
        "   permanecer como evidencia para candidatos relacionales, no como verdad canónica.",
        "3. El contrato DT035 v1 (S0133) ya cubre la validación de source_fields para",
        "   artefactos nuevos. Aplicar en S0135+ al generar source_fields enriquecidos.",
        "4. Los registros 'warning' por rutas legadas pueden migrarse cuando se haga",
        "   backfill de source_path en sesiones históricas.",
        "",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Resumen Markdown → {out_path}", file=sys.stderr)


def write_review_csv(matrix: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "tiddler_id", "title", "artifact_family", "source_path",
        "reversibility_status", "warning_count", "error_count",
        "referenced_sessions", "referenced_diagnostics", "referenced_scripts",
    ]
    rows = []
    for r in matrix.get("records", []):
        inferred = r.get("inferred_metadata", {})
        val = r.get("validation", {})
        rows.append({
            "tiddler_id": r.get("tiddler_id", ""),
            "title": (r.get("title", "") or "")[:120],
            "artifact_family": r.get("artifact_family", ""),
            "source_path": r.get("source_path", ""),
            "reversibility_status": r["reversible_metadata"].get("reversibility_status", ""),
            "warning_count": len(val.get("warnings", [])),
            "error_count": len(val.get("errors", [])),
            "referenced_sessions": "|".join(inferred.get("referenced_sessions", [])[:10]),
            "referenced_diagnostics": "|".join(inferred.get("referenced_diagnostics", [])[:10]),
            "referenced_scripts": "|".join(inferred.get("referenced_scripts", [])[:5]),
        })
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[OK] CSV de revisión → {out_path}", file=sys.stderr)


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Construye la matriz de metadata mínima reversible (S0134).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--canon-root",
        type=Path,
        default=DEFAULT_CANON_ROOT,
        help=f"Raíz del canon local. Default: {DEFAULT_CANON_ROOT}",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Directorio de salida para reportes. Default: {DEFAULT_OUT_DIR}",
    )
    p.add_argument(
        "--session",
        default=DEFAULT_SESSION,
        help=f"ID de la sesión activa. Default: {DEFAULT_SESSION}",
    )
    p.add_argument(
        "--family",
        action="append",
        dest="families",
        default=None,
        help="Filtrar por artifact_family. Se puede repetir para múltiples familias.",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Mostrar progreso detallado.",
    )
    p.add_argument(
        "--json-only",
        action="store_true",
        default=False,
        help="Solo generar el JSON; omitir CSV y Markdown.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    families = set(args.families) if args.families else None

    if args.verbose:
        print(f"[build_minimal_reversible_metadata] canon_root={args.canon_root}", file=sys.stderr)
        print(f"  session={args.session}, out_dir={args.out_dir}", file=sys.stderr)
        if families:
            print(f"  familias filtradas: {families}", file=sys.stderr)

    # 1. Read canon
    try:
        tiddlers = read_canon_tiddlers(
            args.canon_root,
            families=families,
            verbose=args.verbose,
        )
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    if args.verbose:
        print(f"  Tiddlers con artifact_family: {len(tiddlers)}", file=sys.stderr)

    # 2. Build matrix
    matrix = build_matrix(tiddlers, session=args.session, canon_root=args.canon_root)
    s = matrix["summary"]

    # 3. Write reports
    session_tag = args.session.lower()
    out = args.out_dir

    write_matrix_json(matrix, out / f"{session_tag}_reversible_metadata_matrix.json")
    if not args.json_only:
        write_summary_md(matrix, out / f"{session_tag}_reversible_metadata_summary.md")
        write_review_csv(matrix, out / f"{session_tag}_reversible_metadata_review.csv")

    # 4. Print summary
    print(
        f"\n=== Minimal Reversible Metadata ({args.session.upper()}) ===\n"
        f"  Total records : {s['total_records']}\n"
        f"  safe          : {s['safe']}\n"
        f"  warning       : {s['warning']}\n"
        f"  blocked       : {s['blocked']}\n"
    )
    for fam, cnt in sorted(s["families"].items(), key=lambda x: -x[1]):
        print(f"    {cnt:4d}  {fam}")

    if s["blocked"] > 0:
        print(
            f"\n[WARN] {s['blocked']} registros con reversibilidad bloqueada.",
            file=sys.stderr,
        )
        return 1

    print("\n[OK] Todos los registros son seguros o con advertencias solamente.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
