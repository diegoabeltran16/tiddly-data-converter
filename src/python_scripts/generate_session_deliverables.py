#!/usr/bin/env python3
"""Generate the 7 canonical session deliverable .md.json files for a new session.

Usage
-----
  python3 generate_session_deliverables.py \\
      --session-id m04-s0129 \\
      --topic "nombre legible de la sesión" \\
      --tags "tag1,tag2"

This script is the authoritative source of truth for the structure of session
deliverable files.  All field names, formats, and title patterns are derived
from here — the agent MUST use this script instead of hand-crafting files.

Why this script exists (S0128 post-mortem)
------------------------------------------
Agents hand-crafting .md.json files have introduced recurring errors:
  - S0125: "type" set to artifact-family name instead of MIME type
  - S0125: "created_at" instead of "created" (wrong field name)
  - S0125/S0126: "sesión S0125" instead of "sesión 0125" (S-prefix in title)

These errors are invisible to the admission pipeline and only surface when
reverse_tiddlers silently drops the tiddlers.  This generator makes those
errors structurally impossible.

Output
------
Creates 7 files under data/out/local/sessions/:
  00_contratos/{session_id}-contrato-{slug}.md.json
  01_procedencia/{session_id}-procedencia-{slug}.md.json
  02_detalles_de_sesion/{session_id}-{slug}.md.json
  03_hipotesis/{session_id}-hipotesis-{slug}.md.json
  04_balance_de_sesion/{session_id}-balance-{slug}.md.json
  05_propuesta_de_sesion/{session_id}-propuesta-{slug}.md.json
  06_diagnoses/sesion/diagnostico-sesion-{session_id_no_module}-{slug}.md.json

Each file has the correct canonical structure; the agent fills only the "text"
field with actual content.

Validation
----------
  python3 generate_session_deliverables.py --validate \\
      data/out/local/sessions/00_contratos/m04-s0129-contrato-...md.json

Validates an existing file against the schema without generating new files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_SESSIONS_DIR = REPO_ROOT / "data" / "out" / "local" / "sessions"

# ── Schema constants ──────────────────────────────────────────────────────────

CANONICAL_TYPE = "text/markdown"
CANONICAL_STATUS = "delivered"

SESSION_ID_RE = re.compile(r"^(m\d+)-s(\d{4}[a-z]?)$")

# Title prefix per artifact family.
# Format: "{heading} {emoji(s)} {Label} [de sesión] {NNNN} = {topic}"
# The detalles family omits "de sesión" — it's just "Sesión NNNN".
FAMILY_TITLE_PREFIX: dict[str, str] = {
    "contrato_de_sesion":    "#### 🌀 Contrato de sesión",
    "procedencia_de_sesion": "#### 🌀🧾 Procedencia de sesión",
    "detalles_de_sesion":    "#### 🌀 Sesión",
    "hipotesis_de_sesion":   "#### 🌀🧪 Hipótesis de sesión",
    "balance_de_sesion":     "#### 🌀 Balance de sesión",
    "propuesta_de_sesion":   "#### 🌀 Propuesta de sesión",
    "diagnostico_de_sesion": "#### 🌀 Diagnóstico de sesión",
}

# Directory (relative to sessions_dir) and file-name prefix per family.
FAMILY_DIR: dict[str, tuple[str, str]] = {
    "contrato_de_sesion":    ("00_contratos",          "{sid}-contrato-{slug}"),
    "procedencia_de_sesion": ("01_procedencia",         "{sid}-procedencia-{slug}"),
    "detalles_de_sesion":    ("02_detalles_de_sesion",  "{sid}-{slug}"),
    "hipotesis_de_sesion":   ("03_hipotesis",           "{sid}-hipotesis-{slug}"),
    "balance_de_sesion":     ("04_balance_de_sesion",   "{sid}-balance-{slug}"),
    "propuesta_de_sesion":   ("05_propuesta_de_sesion", "{sid}-propuesta-{slug}"),
    "diagnostico_de_sesion": ("06_diagnoses/sesion",    "diagnostico-sesion-{s_number}-{slug}"),
}

# Required fields in every .md.json file, in canonical order.
REQUIRED_FIELDS: tuple[str, ...] = (
    "title", "type", "created", "modified",
    "session_id", "module", "session", "status",
    "canonical_slug", "tags", "text",
)

# Fields that MUST NOT appear (they indicate authoring confusion).
FORBIDDEN_FIELDS: frozenset[str] = frozenset({
    "created_at",   # ISO format confused with TiddlyWiki "created"
    "updated_at",   # same confusion
    "artifact_family",  # belongs in source_fields, not in the raw .md.json
    "role_primary",     # same
    "source_type",      # same — set by admission pipeline, not authored
})

# Valid MIME types for the "type" field.
VALID_MIME_TYPES: frozenset[str] = frozenset({
    "text/markdown",
    "text/plain",
    "text/vnd.tiddlywiki",
    "text/csv",
    "application/json",
})

# TiddlyWiki timestamp format: YYYYMMDDHHmmSSmmm (17 digits)
TW_TIMESTAMP_RE = re.compile(r"^\d{17}$")


# ── Slug helpers ──────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Convert a topic string to a URL-safe slug."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s]+", "-", text.strip())
    text = re.sub(r"-+", "-", text)
    return text[:80].rstrip("-")


def _tw_now() -> str:
    """Return current UTC time in TiddlyWiki timestamp format (17 digits)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}"


# ── Canonical structure builder ───────────────────────────────────────────────

def build_deliverable(
    family: str,
    session_id: str,     # e.g. "m04-s0129"
    module: str,         # e.g. "m04"
    session_num: str,    # e.g. "0129"
    session_tag: str,    # e.g. "S0129"
    topic: str,          # human-readable topic, e.g. "nombre de la sesión"
    topic_slug: str,     # URL-safe slug of topic
    extra_tags: list[str],
    timestamp: str,
) -> dict[str, Any]:
    """Return a correctly-structured .md.json payload for one artifact family."""
    prefix = FAMILY_TITLE_PREFIX[family]
    title = f"{prefix} {session_num} = {topic}"

    # canonical_slug depends on family
    dir_path, fname_tmpl = FAMILY_DIR[family]
    fname = fname_tmpl.format(
        sid=session_id,
        slug=topic_slug,
        s_number=f"s{session_num}",
    )
    # The canonical_slug is the filename without .md.json
    # For diagnostico: "diagnostico-sesion-s0129-{slug}"
    # For others: "{session_id}-{family_short}-{slug}" or "{session_id}-{slug}"
    canonical_slug = fname

    # Derive the short family tag for the tags list
    family_tag_map = {
        "contrato_de_sesion":    "contrato",
        "procedencia_de_sesion": "procedencia",
        "detalles_de_sesion":    "detalles",
        "hipotesis_de_sesion":   "hipotesis",
        "balance_de_sesion":     "balance",
        "propuesta_de_sesion":   "propuesta",
        "diagnostico_de_sesion": "diagnostico",
    }
    family_tag = family_tag_map[family]

    tags = ["sesion", family_tag, module, session_tag.lower()] + extra_tags

    return {
        "title": title,
        "type": CANONICAL_TYPE,
        "created": timestamp,
        "modified": timestamp,
        "session_id": session_id,
        "module": module,
        "session": session_tag,
        "status": CANONICAL_STATUS,
        "canonical_slug": canonical_slug,
        "tags": tags,
        "text": f"## {prefix} {session_num} = {topic}\n\n<!-- Completar contenido aquí -->\n",
    }


# ── Schema validation ─────────────────────────────────────────────────────────

class SchemaError:
    def __init__(self, path: Path, field: str, message: str):
        self.path = path
        self.field = field
        self.message = message

    def __str__(self) -> str:
        return f"  ✗ [{self.field}] {self.message}"


def validate_deliverable_file(path: Path) -> list[SchemaError]:
    """Validate a single .md.json session deliverable against the canonical schema.

    Returns a list of SchemaError objects; empty list means valid.
    """
    errors: list[SchemaError] = []

    if not path.exists():
        return [SchemaError(path, "file", f"does not exist: {path}")]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [SchemaError(path, "json", f"invalid JSON: {exc}")]

    if not isinstance(data, dict):
        return [SchemaError(path, "root", "root must be a JSON object")]

    # 1. Forbidden fields
    for field in FORBIDDEN_FIELDS:
        if field in data:
            errors.append(SchemaError(path, field,
                f"forbidden field present — {_forbidden_hint(field)}"))

    # 2. Required fields present
    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(SchemaError(path, field, "required field missing"))

    # 3. type must be a valid MIME type
    t = data.get("type", "")
    if t:
        if "/" not in t:
            errors.append(SchemaError(path, "type",
                f"not a MIME type: {t!r} — should be 'text/markdown' for textual deliverables. "
                f"Did you write the artifact-family name instead of the content type?"))
        elif t not in VALID_MIME_TYPES:
            errors.append(SchemaError(path, "type",
                f"unrecognized MIME type: {t!r} — expected one of {sorted(VALID_MIME_TYPES)}"))

    # 4. created / modified must be TiddlyWiki 17-digit timestamps
    for field in ("created", "modified"):
        val = str(data.get(field, ""))
        if val and not TW_TIMESTAMP_RE.match(val):
            errors.append(SchemaError(path, field,
                f"invalid TiddlyWiki timestamp: {val!r} — must be 17 digits (YYYYMMDDHHmmSSmmm). "
                f"ISO format (YYYY-MM-DDT...) is wrong here."))

    # 5. title must not contain 'sesión S\\d+' (S-prefix error)
    title = str(data.get("title", ""))
    if re.search(r"sesión\s+S\d+", title, re.IGNORECASE):
        errors.append(SchemaError(path, "title",
            f"S-prefix in session number: {title[:80]!r} — "
            f"use four-digit number without S (e.g. 'sesión 0129', not 'sesión S0129')"))

    # 6. session field must be "S{NNNN}" format
    session = str(data.get("session", ""))
    if session and not re.match(r"^S\d{4}[a-z]?$", session):
        errors.append(SchemaError(path, "session",
            f"invalid session tag: {session!r} — expected 'S0129' format (S + 4 digits)"))

    # 7. session_id must be "mXX-sNNNN" format
    session_id = str(data.get("session_id", ""))
    if session_id and not re.match(r"^m\d+-s\d{4}[a-z]?$", session_id):
        errors.append(SchemaError(path, "session_id",
            f"invalid session_id: {session_id!r} — expected 'm04-s0129' format"))

    # 8. tags must be a list
    tags = data.get("tags")
    if tags is not None and not isinstance(tags, list):
        errors.append(SchemaError(path, "tags", f"must be a list, got {type(tags).__name__}"))

    # 9. title must start with '#### 🌀' (canonical heading)
    if title and not title.startswith("#### 🌀"):
        errors.append(SchemaError(path, "title",
            f"must start with '#### 🌀': {title[:60]!r}"))

    return errors


def _forbidden_hint(field: str) -> str:
    hints = {
        "created_at": "use 'created' (TiddlyWiki format: 17-digit YYYYMMDDHHmmSSmmm)",
        "updated_at": "use 'modified' (TiddlyWiki format: 17-digit YYYYMMDDHHmmSSmmm)",
        "artifact_family": "this field is set by the admission pipeline, not authored manually",
        "role_primary": "set by the admission pipeline from the artifact family",
        "source_type": "set by the admission pipeline from the 'type' field",
    }
    return hints.get(field, "not part of the canonical .md.json schema")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cmd_generate(args: argparse.Namespace) -> int:
    session_id: str = args.session_id.strip()
    m = SESSION_ID_RE.match(session_id)
    if not m:
        print(f"ERROR: --session-id must match 'mXX-sNNNN' (e.g. 'm04-s0129'), got: {session_id!r}",
              file=sys.stderr)
        return 1
    module = m.group(1)
    session_num = m.group(2)
    session_tag = f"S{session_num}"   # e.g. "S0129"

    topic: str = args.topic.strip()
    if not topic:
        print("ERROR: --topic cannot be empty", file=sys.stderr)
        return 1

    topic_slug = _slugify(topic)
    extra_tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    sessions_dir = Path(args.sessions_dir)
    timestamp = _tw_now()

    print(f"Generating deliverables for {session_id} ({session_tag})")
    print(f"  Topic:     {topic}")
    print(f"  Slug:      {topic_slug}")
    print(f"  Timestamp: {timestamp}")
    print(f"  Extra tags:{extra_tags}")
    print()

    created: list[Path] = []
    skipped: list[Path] = []

    for family in FAMILY_TITLE_PREFIX:
        payload = build_deliverable(
            family=family,
            session_id=session_id,
            module=module,
            session_num=session_num,
            session_tag=session_tag,
            topic=topic,
            topic_slug=topic_slug,
            extra_tags=extra_tags,
            timestamp=timestamp,
        )
        dir_rel, fname_tmpl = FAMILY_DIR[family]
        fname = fname_tmpl.format(
            sid=session_id,
            slug=topic_slug,
            s_number=f"s{session_num}",
        ) + ".md.json"
        out_path = sessions_dir / dir_rel / fname
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if out_path.exists() and not args.force:
            try:
                display_skip = out_path.relative_to(REPO_ROOT)
            except ValueError:
                display_skip = out_path
            print(f"  SKIP (exists): {display_skip}")
            skipped.append(out_path)
            continue

        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            display = out_path.relative_to(REPO_ROOT)
        except ValueError:
            display = out_path
        print(f"  CREATED: {display}")
        created.append(out_path)

    print()
    print(f"Done: {len(created)} created, {len(skipped)} skipped.")
    if skipped and not args.force:
        print("  (use --force to overwrite existing files)")
    print()
    print("Next steps:")
    print(f"  1. Fill in the 'text' field of each file with the session content.")
    print(f"  2. Run: python3 src/python_scripts/generate_session_deliverables.py --validate \\")
    print(f"          data/out/local/sessions/00_contratos/{session_id}-contrato-{topic_slug}.md.json")
    print("  3. Run session_sync with an explicit scope and filter, for example:")
    print(
        f"     python3 src/python_scripts/session_sync.py scan --scope missing "
        f"--filter-type session_id --filter-value {session_id.split('-', 2)[0]}-{session_id.split('-', 2)[1]}"
    )
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in args.paths]
    all_errors: list[tuple[Path, list[SchemaError]]] = []

    for path in paths:
        errs = validate_deliverable_file(path)
        if errs:
            all_errors.append((path, errs))

    if not all_errors:
        print(f"✓ All {len(paths)} file(s) valid.")
        return 0

    for path, errs in all_errors:
        print(f"\n✗ {path}")
        for e in errs:
            print(e)

    print(f"\n{sum(len(e) for _, e in all_errors)} error(s) in {len(all_errors)} file(s).")
    return 1


def _cmd_validate_dir(args: argparse.Namespace) -> int:
    sessions_dir = Path(args.sessions_dir)
    paths = sorted(sessions_dir.rglob("*.md.json"))
    if not paths:
        print(f"No .md.json files found under {sessions_dir}", file=sys.stderr)
        return 1
    # Reuse validate logic
    args.paths = [str(p) for p in paths]
    return _cmd_validate(args)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate or validate canonical session deliverable .md.json files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # generate
    gen = sub.add_parser("generate", help="Generate 7 deliverable files for a new session.")
    gen.add_argument("--session-id", required=True,
                     help="Session ID in mXX-sNNNN format (e.g. m04-s0129)")
    gen.add_argument("--topic", required=True,
                     help="Human-readable topic for the session (used in titles and slug)")
    gen.add_argument("--tags", default="",
                     help="Comma-separated extra tags to add to all files")
    gen.add_argument("--sessions-dir", default=str(DEFAULT_SESSIONS_DIR),
                     help="Path to the sessions directory")
    gen.add_argument("--force", action="store_true",
                     help="Overwrite existing files")
    gen.set_defaults(func=_cmd_generate)

    # validate (one or more files)
    val = sub.add_parser("validate", help="Validate one or more .md.json files against schema.")
    val.add_argument("paths", nargs="+", help=".md.json file(s) to validate")
    val.set_defaults(func=_cmd_validate)

    # validate-dir (all files under sessions_dir)
    vdir = sub.add_parser("validate-dir", help="Validate all .md.json files under sessions-dir.")
    vdir.add_argument("--sessions-dir", default=str(DEFAULT_SESSIONS_DIR),
                      help="Path to the sessions directory")
    vdir.set_defaults(func=_cmd_validate_dir)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
