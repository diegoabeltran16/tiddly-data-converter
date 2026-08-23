#!/usr/bin/env python3
"""Deterministic, CommonMark-compatible fenced-code inventory and validator.

This is intentionally a validator, never an automatic formatter.  It models
the fenced-code rule needed by S0184 Impact 03A2: a closing fence has the same
character as its opener, contains no info string, and is at least as long.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
FENCE = re.compile(r"^(?P<indent> {0,3})(?P<run>`{3,}|~{3,})(?P<tail>.*)$")
SCHEMA = "markdown-fence-inventory/v1"
DEFAULT_SCOPE = ("README.md", "AGENTS.md", ".agents", ".github")


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def markdown_files(root: Path, scope: tuple[str, ...] = DEFAULT_SCOPE) -> list[Path]:
    """Return the documented primary scope without generated or VCS files."""
    files: set[Path] = set()
    for raw in scope:
        candidate = root / raw
        if candidate.is_file() and candidate.suffix == ".md":
            files.add(candidate)
        elif candidate.is_dir():
            files.update(path for path in candidate.rglob("*.md") if path.is_file())
    return sorted(files, key=lambda path: _relative(path, root))


def _occurrence(
    *, path: Path, root: Path, line: int, run: str, indent: str, tail: str,
    role: str, opener: dict[str, Any] | None, classification: str,
    justification: str,
) -> dict[str, Any]:
    return {
        "file": _relative(path, root),
        "line": line,
        "character": "backtick" if run[0] == "`" else "tilde",
        "length": len(run),
        "indentation": len(indent),
        "trailing_content": tail,
        "inferred_role": role,
        "opener_line": opener["line"] if opener else None,
        "opener_length": opener["length"] if opener else None,
        "closer_line": line if role == "closer" else None,
        "closer_length": len(run) if role == "closer" else None,
        "info_string": opener["info_string"] if opener else tail.strip(),
        "parser_verdict": "commonmark_fenced_code_rules",
        "review_comment_reference": "PR #159 review claim; exact local comment unavailable",
        "classification": classification,
        "action": "no_change",
        "justification": justification,
    }


def scan_file(path: Path, root: Path) -> dict[str, Any]:
    """Scan one Markdown file with a single fenced-code state machine."""
    occurrences: list[dict[str, Any]] = []
    defects: list[dict[str, Any]] = []
    opener: dict[str, Any] | None = None
    literal_inside_outer: list[int] = []
    literal_inner_openers: list[tuple[str, int]] = []

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        matched = FENCE.match(raw_line)
        if not matched:
            continue
        indent, run, tail = matched.group("indent", "run", "tail")
        tail_is_blank = not tail.strip()
        if opener is None:
            opener = {
                "line": line_number,
                "run": run,
                "length": len(run),
                "character": run[0],
                "info_string": tail.strip(),
            }
            occurrences.append(_occurrence(
                path=path, root=root, line=line_number, run=run, indent=indent,
                tail=tail, role="opener", opener=None,
                classification="opening_fence", justification="fence opens a new block",
            ))
            continue

        same_character = run[0] == opener["character"]
        compatible_close = same_character and tail_is_blank and len(run) >= opener["length"]
        if compatible_close:
            classification = (
                "valid_exact_pair" if len(run) == opener["length"] else "valid_longer_closer"
            )
            if opener["length"] >= 4 and literal_inside_outer:
                classification = "intentional_outer_fence"
            event = _occurrence(
                path=path, root=root, line=line_number, run=run, indent=indent,
                tail=tail, role="closer", opener=opener, classification=classification,
                justification=(
                    "outer fence preserves literal inner fence examples"
                    if classification == "intentional_outer_fence"
                    else "same character, blank closing suffix, and compatible length"
                ),
            )
            occurrences.append(event)
            opener = None
            literal_inside_outer = []
            continue

        if same_character and tail_is_blank and len(run) < opener["length"]:
            if literal_inner_openers and literal_inner_openers[-1][0] == run:
                literal_inner_openers.pop()
                classification = "literal_fence_content"
                justification = "closes a literal inner fence inside the outer block"
            else:
                classification = "short_closer"
                justification = "shorter than the currently open compatible fence"
        elif not same_character and tail_is_blank:
            classification = "mismatched_character"
            justification = "different fence character cannot close the current block"
        else:
            classification = "literal_fence_content"
            justification = "inside an open fence; not a compatible closing fence"
        event = _occurrence(
            path=path, root=root, line=line_number, run=run, indent=indent,
            tail=tail, role="literal", opener=opener, classification=classification,
            justification=justification,
        )
        occurrences.append(event)
        if classification in {"short_closer", "mismatched_character"}:
            defects.append(event)
        if len(run) < opener["length"] or not same_character:
            literal_inside_outer.append(line_number)
        if same_character and len(run) < opener["length"] and tail.strip():
            literal_inner_openers.append((run, line_number))

    if opener is not None:
        eof = {
            "file": _relative(path, root),
            "line": opener["line"],
            "character": "backtick" if opener["character"] == "`" else "tilde",
            "length": opener["length"],
            "indentation": None,
            "trailing_content": "",
            "inferred_role": "opener",
            "opener_line": opener["line"],
            "opener_length": opener["length"],
            "closer_line": None,
            "closer_length": None,
            "info_string": opener["info_string"],
            "parser_verdict": "commonmark_fenced_code_rules",
            "review_comment_reference": "PR #159 review claim; exact local comment unavailable",
            "classification": "unclosed_fence",
            "action": "manual_correction_required",
            "justification": "compatible closing fence was not found before EOF",
        }
        occurrences.append(eof)
        defects.append(eof)
    return {"occurrences": occurrences, "defects": defects}


def build_inventory(root: Path, scope: tuple[str, ...] = DEFAULT_SCOPE) -> dict[str, Any]:
    files = markdown_files(root, scope)
    all_occurrences: list[dict[str, Any]] = []
    all_defects: list[dict[str, Any]] = []
    for path in files:
        result = scan_file(path, root)
        all_occurrences.extend(result["occurrences"])
        all_defects.extend(result["defects"])
    counts = Counter(item["classification"] for item in all_occurrences)
    return {
        "schema_version": SCHEMA,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scope": list(scope),
        "parser_contract": {
            "dialect": "CommonMark-compatible fenced code blocks",
            "validator": "local deterministic state scanner",
            "limitation": "does not render HTML or model list/blockquote container nesting beyond up to three leading spaces",
        },
        "files_scanned": [_relative(path, root) for path in files],
        "occurrences": all_occurrences,
        "summary": {
            "files": len(files),
            "fences_total": len(all_occurrences),
            "four_or_more_backticks": sum(
                1 for item in all_occurrences
                if item["character"] == "backtick" and item["length"] >= 4
            ),
            "classifications": dict(sorted(counts.items())),
            "defects_confirmed": len(all_defects),
        },
    }


def write_reports(
    inventory: dict[str, Any], output_dir: Path, changes: list[dict[str, Any]] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    defects = [item for item in inventory["occurrences"] if item["classification"] in {
        "unclosed_fence", "short_closer", "mismatched_character",
    }]
    report = {
        "schema_version": "markdown-fence-validation-report/v1",
        "inventory_schema_version": SCHEMA,
        "allowed": not defects,
        "defects": defects,
        "summary": inventory["summary"],
    }
    recorded_changes = changes or []
    changes_manifest = {
        "schema_version": "s0184-post-fix-export-input/v1",
        "microphases": ["03A1", "03A2"],
        "files_changed": recorded_changes,
        "ready_for_repository_export": False,
        "justification": "03A2 validation only; future integration remains separately authorized.",
    }
    analysis = [
        "# S0184 Impacto 03A2 — análisis de fences Markdown",
        "",
        f"- Archivos escaneados: {inventory['summary']['files']}",
        f"- Ocurrencias: {inventory['summary']['fences_total']}",
        f"- Backticks de longitud ≥4: {inventory['summary']['four_or_more_backticks']}",
        f"- Defectos confirmados: {len(defects)}",
        f"- Cierres más largos válidos: {inventory['summary']['classifications'].get('valid_longer_closer', 0)}",
        f"- Fences exteriores intencionales: {inventory['summary']['classifications'].get('intentional_outer_fence', 0)}",
        f"- Correcciones estructurales registradas: {len(recorded_changes)}",
        "- Contrato: CommonMark-compatible; un cierre puede ser más largo que la apertura.",
        "- Limitación: scanner estructural local; no reemplaza un renderizador HTML completo.",
        "",
        "## Decisión",
        "",
        "No se realiza corrección automática. Los casos válidos de cierres más largos y fences exteriores intencionales se preservan.",
    ]
    if recorded_changes:
        analysis.extend([
            "",
            "## Correcciones focales",
            "",
            *[
                f"- `{change['path']}:{change['opening_line']}`: {change['defect']}; cambio estructural sin contenido sustantivo."
                for change in recorded_changes
            ],
        ])
    for filename, payload in (
        ("fence-inventory.json", inventory),
        ("fence-validation-report.json", report),
        ("changed-fences.json", changes_manifest),
    ):
        (output_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    (output_dir / "fence-analysis.md").write_text("\n".join(analysis) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--scope", nargs="*", default=list(DEFAULT_SCOPE))
    parser.add_argument(
        "--changed-fence", action="append", nargs=4, metavar=("FILE", "LINE", "BEFORE", "AFTER"),
        help="record one manual correction in the S0184 post-fix manifest",
    )
    args = parser.parse_args(argv)
    inventory = build_inventory(args.root.resolve(), tuple(args.scope))
    changes = [
        {
            "path": file,
            "originating_microphase": "03A2",
            "change_class": "markdown_fence_structural_repair",
            "opening_line": int(line),
            "closing_line": int(line),
            "before": before,
            "after": after,
            "defect": "unclosed_fence",
            "parser_before": "unclosed_fence_to_eof",
            "parser_after": "valid_after_rescan",
            "content_after_block_preserved": True,
            "semantic_change_expected": False,
        }
        for file, line, before, after in (args.changed_fence or [])
    ]
    write_reports(inventory, args.out_dir, changes)
    print(json.dumps(inventory["summary"], ensure_ascii=False, sort_keys=True))
    return 1 if inventory["summary"]["defects_confirmed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
