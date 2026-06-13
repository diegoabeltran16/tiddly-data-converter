#!/usr/bin/env python3
"""Characterize unknown artifact_family records for S0145.

This script is read-only with respect to canon shards. It consumes the S0144
semantic_text sidecar as the preferred source of the "unknown" set, joins those
ids back to the local canon for observable evidence, and writes review reports
under data/out/local/pipeline.
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

SCHEMA = "unknown-artifact-family-characterization/v1"
DEFAULT_SESSION = "s0145"
DEFAULT_CANON_GLOB = str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl")
DEFAULT_SEMANTIC_TEXT_RECORDS = (
    REPO_ROOT
    / "data"
    / "out"
    / "local"
    / "pipeline"
    / "semantic_text"
    / "s0144"
    / "s0144_semantic_text_records.jsonl"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "data"
    / "out"
    / "local"
    / "pipeline"
    / "unknown_artifact_family"
    / "s0145"
)

CANDIDATE_FAMILIES = [
    "referencia_documental",
    "referencia_tecnica",
    "fuente_bibliografica",
    "fuente_web",
    "concepto",
    "glosario",
    "nota_auxiliar",
    "recurso_externo",
    "tiddler_tecnico",
    "indice_o_navegacion",
    "fragmento_de_estudio",
    "unknown_real",
    "requires_human_review",
]

CONFIDENCE_VALUES = ["high", "medium", "low", "requires_human_review"]
RECOMMENDED_ACTIONS = [
    "accept_candidate_family_later",
    "review_manually",
    "keep_unknown_for_now",
    "needs_new_family",
    "merge_with_existing_family",
    "exclude_from_semantic_enrichment",
]

REVIEW_COLUMNS = [
    "id",
    "title",
    "tags",
    "candidate_artifact_family",
    "confidence",
    "signals",
    "reason",
    "sample_excerpt",
    "recommended_action",
]

URL_RE = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
DOI_RE = re.compile(r"\b(?:doi:\s*)?10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
AUTHOR_RE = re.compile(
    r"\b(?:autor|autora|author|authors|editor|publisher|editorial|journal|"
    r"revista|paper|articulo|article|libro|book|isbn|bibliografia|bibliography|"
    r"cita|citation|fuente|source|referencia|reference)\b",
    re.IGNORECASE,
)
TECH_EXT_RE = re.compile(
    r"(?:^|[/\\\s])[\w.-]+\.(?:py|json|jsonl|md|sh|yaml|yml|toml|txt|csv|"
    r"html|css|js|ts|tsx|sql|ini|cfg|lock)\b",
    re.IGNORECASE,
)
PATH_RE = re.compile(
    r"(?:^|\s)(?:\.?/)?(?:python_scripts|data/out|data/in|tests|docs|"
    r"shell_scripts|\.github|ux|esquemas|scripts|src|bin)/[^\s`]+",
    re.IGNORECASE,
)
COMMAND_RE = re.compile(
    r"\b(?:python3|pytest|bash|git|npm|node|cargo|go test|sha256sum|jq|rg|grep)\b",
    re.IGNORECASE,
)
CODE_RE = re.compile(r"```|\bdef\s+\w+\(|\bclass\s+\w+\b|\bimport\s+\w+|\{|\}", re.IGNORECASE)
NAV_LINK_RE = re.compile(r"\[\[[^\]]+\]\]|\[[^\]]+\]\([^)]+\)")
NAV_TERMS_RE = re.compile(r"\b(?:indice|index|toc|menu|navegacion|navigation|tabla de contenido|mapa)\b", re.IGNORECASE)
DEFINITION_RE = re.compile(
    r"(?:^|\n)\s*(?:definicion|definition)\s*:|"
    r"(?:^|\n)\s*[^.\n]{2,90}\s+(?:es|son|se define como|consiste en|significa)\s+",
    re.IGNORECASE,
)
CONCEPT_TERMS_RE = re.compile(r"\b(?:concepto|conceptual|marco conceptual|teoria|modelo)\b", re.IGNORECASE)
NOTE_TERMS_RE = re.compile(
    r"\b(?:nota|observacion|pendiente|todo|comentario|borrador|revision|"
    r"operativo|proceso|bitacora|seguimiento)\b",
    re.IGNORECASE,
)
FRAGMENT_TERMS_RE = re.compile(r"\b(?:fragmento|extracto|estudio tdc|corpus tdc|pieza de estudio)\b", re.IGNORECASE)
EXTERNAL_TERMS_RE = re.compile(r"\b(?:recurso externo|enlace externo|link externo|sitio web|pagina web)\b", re.IGNORECASE)


def stable_json_dumps(value: Any, *, indent: int | None = None) -> str:
    if indent is None:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    collapsed: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line
        if blank and previous_blank:
            continue
        collapsed.append(line)
        previous_blank = blank
    return "\n".join(collapsed).strip()


def parse_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [normalize_text(item) for item in value if normalize_text(item)]
    text = normalize_text(value)
    if not text:
        return []
    tags: list[str] = []
    for match in re.finditer(r"\[\[([^\]]+)\]\]|(\S+)", text):
        tag = normalize_text(match.group(1) or match.group(2))
        if tag:
            tags.append(tag)
    return tags


def collect_tags(record: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    tags.extend(parse_tags(record.get("tags")))
    tags.extend(parse_tags(record.get("source_tags")))
    sf = record.get("source_fields") if isinstance(record.get("source_fields"), dict) else {}
    tags.extend(parse_tags(sf.get("tags")))
    seen: set[str] = set()
    deduped: list[str] = []
    for tag in tags:
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(tag)
    return deduped


def artifact_family_for(record: dict[str, Any]) -> str:
    sf = record.get("source_fields") if isinstance(record.get("source_fields"), dict) else {}
    value = sf.get("artifact_family") or record.get("artifact_family") or record.get("family") or ""
    return normalize_text(value).casefold() or "unknown"


def content_text(record: dict[str, Any]) -> str:
    if record.get("text"):
        return normalize_text(record.get("text"))
    content = record.get("content")
    if isinstance(content, dict):
        return normalize_text(content.get("plain") or content.get("text") or content.get("markdown") or "")
    return normalize_text(content)


def source_fields_text(record: dict[str, Any]) -> str:
    sf = record.get("source_fields") if isinstance(record.get("source_fields"), dict) else {}
    structural_keys = {
        "canonical_status",
        "created",
        "modified",
        "provenance_ref",
        "source_path",
        "tags",
        "tmap.id",
        "type",
    }
    parts: list[str] = []
    for key in sorted(sf):
        if key.casefold() in structural_keys:
            continue
        parts.append(f"{key}: {normalize_text(sf.get(key))}")
    return "\n".join(part for part in parts if part.strip())


def deterministic_excerpt(record: dict[str, Any], limit: int = 420) -> str:
    text = content_text(record)
    if not text:
        semantic = record.get("_semantic_text_record") or {}
        text = normalize_text(semantic.get("semantic_text"))
    if not text:
        text = normalize_text(record.get("title"))
    if len(text) <= limit:
        return text
    return text[: limit - len("[TRUNCATED]") - 1].rstrip() + "\n[TRUNCATED]"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            record["_jsonl_source_path"] = str(path)
            record["_jsonl_source_line"] = line_no
            records.append(record)
    return records


def read_canon_records(canon_glob: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for shard in sorted(glob.glob(canon_glob)):
        for record in load_jsonl(Path(shard)):
            record["_canon_source_shard"] = shard
            record["_canon_source_line"] = record.pop("_jsonl_source_line")
            record.pop("_jsonl_source_path", None)
            records.append(record)
    return records


def read_semantic_text_records(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    return load_jsonl(path)


def record_key(record: dict[str, Any]) -> tuple[str, str]:
    return (normalize_text(record.get("title")).casefold(), normalize_text(record.get("id")))


class Evidence:
    def __init__(self) -> None:
        self.scores: dict[str, int] = defaultdict(int)
        self.signals: dict[str, list[str]] = defaultdict(list)
        self.non_tag_signals: dict[str, int] = defaultdict(int)
        self.tag_signals: dict[str, int] = defaultdict(int)

    def add(self, family: str, signal: str, points: int, *, from_tag: bool = False) -> None:
        if family not in CANDIDATE_FAMILIES:
            raise ValueError(f"unknown candidate family: {family}")
        self.scores[family] += points
        if signal not in self.signals[family]:
            self.signals[family].append(signal)
        if from_tag:
            self.tag_signals[family] += 1
        else:
            self.non_tag_signals[family] += 1


def add_textual_signals(evidence: Evidence, *, title: str, body: str) -> None:
    haystack = f"{title}\n{body}"
    link_count = len(NAV_LINK_RE.findall(body))

    if URL_RE.search(haystack):
        evidence.add("fuente_web", "url_detected", 4)
        evidence.add("referencia_documental", "url_detected", 2)
        evidence.add("recurso_externo", "external_url_detected", 2)
    if DOI_RE.search(haystack):
        evidence.add("referencia_documental", "doi_detected", 5)
        evidence.add("fuente_bibliografica", "doi_detected", 5)
    if AUTHOR_RE.search(haystack):
        evidence.add("referencia_documental", "bibliographic_or_source_terms", 3)
        evidence.add("fuente_bibliografica", "bibliographic_or_source_terms", 2)
    if YEAR_RE.search(haystack) and AUTHOR_RE.search(haystack):
        evidence.add("referencia_documental", "year_with_source_or_author_terms", 2)
    if EXTERNAL_TERMS_RE.search(haystack):
        evidence.add("recurso_externo", "external_resource_terms", 3)
        evidence.add("fuente_web", "external_resource_terms", 1)

    if TECH_EXT_RE.search(title) or TECH_EXT_RE.search(body):
        evidence.add("tiddler_tecnico", "technical_file_extension", 5)
    if PATH_RE.search(haystack):
        evidence.add("tiddler_tecnico", "repository_path_detected", 4)
    if COMMAND_RE.search(body):
        evidence.add("tiddler_tecnico", "command_or_tool_detected", 2)
    if CODE_RE.search(body):
        evidence.add("tiddler_tecnico", "code_or_structured_payload_detected", 2)
    if URL_RE.search(haystack) and (TECH_EXT_RE.search(haystack) or COMMAND_RE.search(haystack)):
        evidence.add("referencia_tecnica", "technical_reference_with_url_or_command", 4)

    if NAV_TERMS_RE.search(haystack):
        evidence.add("indice_o_navegacion", "navigation_terms", 3)
    if link_count >= 5:
        evidence.add("indice_o_navegacion", "many_wikilinks_or_markdown_links", 4)
    elif link_count >= 2:
        evidence.add("indice_o_navegacion", "multiple_wikilinks_or_markdown_links", 2)

    if DEFINITION_RE.search(body):
        evidence.add("concepto", "definition_pattern", 3)
        title_words = [word for word in re.split(r"\s+", title.strip()) if word]
        if 0 < len(title_words) <= 4 and len(body) <= 900:
            evidence.add("glosario", "short_term_definition_pattern", 3)
    if CONCEPT_TERMS_RE.search(haystack):
        evidence.add("concepto", "conceptual_terms", 2)
    if NOTE_TERMS_RE.search(haystack):
        evidence.add("nota_auxiliar", "process_or_note_terms", 2)
    if FRAGMENT_TERMS_RE.search(haystack):
        evidence.add("fragmento_de_estudio", "study_fragment_terms", 3)


def add_tag_signals(evidence: Evidence, tags: list[str]) -> None:
    for tag in tags:
        t = tag.casefold()
        if any(word in t for word in ("referencia", "reference", "fuente", "bibliografia", "cita")):
            evidence.add("referencia_documental", "tag_reference_hint", 1, from_tag=True)
        if any(word in t for word in ("json", "codigo", "script", "python", "markdown", "shell", "config")):
            evidence.add("tiddler_tecnico", "tag_technical_hint", 1, from_tag=True)
        if any(word in t for word in ("indice", "index", "menu", "navegacion", "toc")):
            evidence.add("indice_o_navegacion", "tag_navigation_hint", 1, from_tag=True)
        if any(word in t for word in ("concepto", "conceptual", "teoria")):
            evidence.add("concepto", "tag_concept_hint", 1, from_tag=True)
        if any(word in t for word in ("glosario", "vocabulario")):
            evidence.add("glosario", "tag_glossary_hint", 1, from_tag=True)
        if any(word in t for word in ("nota", "operativo", "proceso", "borrador")):
            evidence.add("nota_auxiliar", "tag_note_hint", 1, from_tag=True)


def choose_candidate(evidence: Evidence) -> tuple[str, str, list[str], str, str]:
    scored = [(family, evidence.scores[family]) for family in CANDIDATE_FAMILIES if evidence.scores.get(family, 0)]
    if not scored:
        return (
            "unknown_real",
            "low",
            ["no_reproducible_non_tag_signal"],
            "No reproducible signal was strong enough to propose a specific family.",
            "keep_unknown_for_now",
        )

    scored.sort(key=lambda item: (-item[1], CANDIDATE_FAMILIES.index(item[0])))
    top_family, top_score = scored[0]
    tied = [family for family, score in scored if score == top_score]
    non_tag = evidence.non_tag_signals.get(top_family, 0)

    if non_tag == 0:
        return (
            "requires_human_review",
            "requires_human_review",
            sorted({signal for signals in evidence.signals.values() for signal in signals}),
            "Only tag-derived hints were found; tags are evidence, not a classification decision.",
            "review_manually",
        )

    if len(tied) > 1 and top_score < 6:
        return (
            "requires_human_review",
            "requires_human_review",
            sorted({signal for family in tied for signal in evidence.signals[family]}),
            "Multiple candidate families have the same weak score; human review is required.",
            "review_manually",
        )

    if top_family == "fuente_bibliografica" and evidence.scores.get("referencia_documental", 0) >= 3:
        top_family = "referencia_documental"
        top_score = evidence.scores[top_family]
        non_tag = evidence.non_tag_signals.get(top_family, 0)

    if top_score >= 5 and non_tag >= 2:
        confidence = "high"
        action = "accept_candidate_family_later"
    elif top_score >= 3:
        confidence = "medium"
        action = "accept_candidate_family_later"
    else:
        confidence = "low"
        action = "review_manually"

    signals = evidence.signals.get(top_family, [])
    reason = (
        f"Deterministic score {top_score} for {top_family} with "
        f"{non_tag} non-tag signal(s); tag hints were auxiliary only."
    )
    return top_family, confidence, signals, reason, action


def classify_unknown_record(record: dict[str, Any]) -> dict[str, Any]:
    title = normalize_text(record.get("title"))
    tags = collect_tags(record)
    body = "\n".join(part for part in [content_text(record), source_fields_text(record)] if part)
    evidence = Evidence()
    add_textual_signals(evidence, title=title, body=body)
    add_tag_signals(evidence, tags)
    family, confidence, signals, reason, action = choose_candidate(evidence)

    return {
        "id": normalize_text(record.get("id")),
        "title": title,
        "tags": tags,
        "current_artifact_family": "unknown",
        "candidate_artifact_family": family,
        "confidence": confidence,
        "signals": sorted(signals),
        "reason": reason,
        "sample_excerpt": deterministic_excerpt(record),
        "recommended_action": action,
        "dry_run": True,
        "applied_to_canon": False,
    }


def select_unknown_records(
    canon_records: list[dict[str, Any]],
    semantic_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    canon_by_id = {
        normalize_text(record.get("id")): record
        for record in sorted(canon_records, key=record_key)
        if normalize_text(record.get("id"))
    }
    semantic_by_id = {
        normalize_text(record.get("id")): record
        for record in semantic_records
        if normalize_text(record.get("id"))
    }

    if semantic_records:
        unknown_ids = [
            normalize_text(record.get("id"))
            for record in semantic_records
            if normalize_text(record.get("artifact_family")).casefold() == "unknown"
        ]
        source = "semantic_text_records"
    else:
        unknown_ids = [
            normalize_text(record.get("id"))
            for record in canon_records
            if artifact_family_for(record) == "unknown"
        ]
        source = "canon_artifact_family"

    records: list[dict[str, Any]] = []
    missing_from_canon = 0
    for record_id in sorted(set(unknown_ids)):
        base = dict(canon_by_id.get(record_id) or {})
        if not base:
            missing_from_canon += 1
            sem = semantic_by_id.get(record_id, {})
            base = {
                "id": record_id,
                "title": sem.get("title") or record_id,
                "text": sem.get("semantic_text") or "",
                "source_fields": {},
            }
        if record_id in semantic_by_id:
            base["_semantic_text_record"] = semantic_by_id[record_id]
        records.append(base)

    meta = {
        "unknown_source": source,
        "semantic_text_records_available": bool(semantic_records),
        "semantic_text_record_count": len(semantic_records),
        "canon_record_count": len(canon_records),
        "unknown_id_count": len(set(unknown_ids)),
        "missing_unknown_records_from_canon": missing_from_canon,
    }
    return sorted(records, key=record_key), meta


def build_inventory(
    candidates: list[dict[str, Any]],
    *,
    meta: dict[str, Any],
    session: str,
) -> dict[str, Any]:
    return {
        "schema": "unknown-artifact-family-inventory/v1",
        "session": session.upper(),
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "semantic_text_regenerated": False,
        "embeddings_executed": False,
        "total_unknown": len(candidates),
        "source": meta,
        "records": [
            {
                "id": item["id"],
                "title": item["title"],
                "tags": item["tags"],
                "candidate_artifact_family": item["candidate_artifact_family"],
                "confidence": item["confidence"],
                "recommended_action": item["recommended_action"],
            }
            for item in candidates
        ],
    }


def top_tags_for(items: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for item in items:
        counts.update(item.get("tags") or [])
    return [
        {"tag": tag, "count": count}
        for tag, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0].casefold()))[:limit]
    ]


def build_grouped_summary(candidates: list[dict[str, Any]], *, session: str) -> dict[str, Any]:
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        by_family[item["candidate_artifact_family"]].append(item)

    family_counts = Counter(item["candidate_artifact_family"] for item in candidates)
    confidence_counts = Counter(item["confidence"] for item in candidates)
    action_counts = Counter(item["recommended_action"] for item in candidates)

    groups: dict[str, Any] = {}
    for family in sorted(by_family):
        items = sorted(by_family[family], key=lambda item: (item["title"].casefold(), item["id"]))
        groups[family] = {
            "count": len(items),
            "by_confidence": dict(sorted(Counter(item["confidence"] for item in items).items())),
            "top_tags": top_tags_for(items),
            "examples": [
                {
                    "id": item["id"],
                    "title": item["title"],
                    "confidence": item["confidence"],
                    "signals": item["signals"],
                }
                for item in items[:8]
            ],
        }

    high_or_medium = {
        family
        for family, items in by_family.items()
        if family not in {"unknown_real", "requires_human_review"}
        and any(item["confidence"] in {"high", "medium"} for item in items)
    }
    doubtful = {
        family
        for family, items in by_family.items()
        if family in {"unknown_real", "requires_human_review"}
        or any(item["confidence"] in {"low", "requires_human_review"} for item in items)
    }

    return {
        "schema": "unknown-artifact-family-grouped-summary/v1",
        "session": session.upper(),
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "total_unknown": len(candidates),
        "by_candidate_artifact_family": dict(sorted(family_counts.items())),
        "by_confidence": dict(sorted(confidence_counts.items())),
        "by_recommended_action": dict(sorted(action_counts.items())),
        "groups": groups,
        "new_candidate_families_recommended": sorted(high_or_medium),
        "doubtful_families_or_buckets": sorted(doubtful),
        "unknown_real": family_counts.get("unknown_real", 0),
        "requires_human_review": sum(
            1
            for item in candidates
            if item["confidence"] == "requires_human_review"
            or item["candidate_artifact_family"] == "requires_human_review"
        ),
    }


def build_mapping_preview(candidates: list[dict[str, Any]], *, session: str) -> dict[str, Any]:
    family_counts = Counter(item["candidate_artifact_family"] for item in candidates)
    return {
        "schema": "artifact-family-mapping-preview/v1",
        "session": session.upper(),
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "mapping_allowed_in_s0145": False,
        "total_unknown": len(candidates),
        "mapped_high_confidence": sum(1 for item in candidates if item["confidence"] == "high"),
        "mapped_medium_confidence": sum(1 for item in candidates if item["confidence"] == "medium"),
        "mapped_low_confidence": sum(1 for item in candidates if item["confidence"] == "low"),
        "requires_human_review": sum(1 for item in candidates if item["confidence"] == "requires_human_review"),
        "keep_unknown_for_now": sum(1 for item in candidates if item["recommended_action"] == "keep_unknown_for_now"),
        "by_candidate_artifact_family": dict(sorted(family_counts.items())),
    }


def classification_rules(session: str) -> dict[str, Any]:
    return {
        "schema": "unknown-artifact-family-classification-rules/v1",
        "session": session.upper(),
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "candidate_families": CANDIDATE_FAMILIES,
        "confidence_values": CONFIDENCE_VALUES,
        "recommended_actions": RECOMMENDED_ACTIONS,
        "principles": [
            "candidate_artifact_family is not canonical artifact_family",
            "tags are auxiliary signals and never decide a family by themselves",
            "high confidence enables later batch review only; it does not apply metadata",
            "semantic_text from S0144 can identify records but is not regenerated",
        ],
        "signal_groups": {
            "referencia_documental": [
                "url_detected",
                "doi_detected",
                "bibliographic_or_source_terms",
                "year_with_source_or_author_terms",
            ],
            "tiddler_tecnico": [
                "technical_file_extension",
                "repository_path_detected",
                "command_or_tool_detected",
                "code_or_structured_payload_detected",
            ],
            "indice_o_navegacion": [
                "navigation_terms",
                "multiple_wikilinks_or_markdown_links",
                "many_wikilinks_or_markdown_links",
            ],
            "concepto": ["definition_pattern", "conceptual_terms"],
            "glosario": ["short_term_definition_pattern"],
            "nota_auxiliar": ["process_or_note_terms"],
            "fragmento_de_estudio": ["study_fragment_terms"],
        },
        "non_apply_policy": {
            "mapping_allowed_in_s0145": False,
            "artifact_family_written_to_canon": False,
            "semantic_text_regenerated": False,
            "embeddings_executed": False,
        },
    }


def build_grouped_summary_md(summary: dict[str, Any]) -> str:
    lines = [
        "# S0145 unknown artifact_family grouped summary",
        "",
        f"- total_unknown: {summary['total_unknown']}",
        "- dry_run: true",
        "- applied_to_canon: false",
        "- canon_modified: false",
        "",
        "## Distribution by candidate_artifact_family",
        "",
        "| candidate_artifact_family | count |",
        "|---|---:|",
    ]
    for family, count in summary["by_candidate_artifact_family"].items():
        lines.append(f"| {family} | {count} |")

    lines.extend(["", "## Confidence", "", "| confidence | count |", "|---|---:|"])
    for confidence, count in summary["by_confidence"].items():
        lines.append(f"| {confidence} | {count} |")

    lines.extend(["", "## Top tags and examples by group", ""])
    for family, group in summary["groups"].items():
        lines.append(f"### {family}")
        lines.append("")
        lines.append(f"- count: {group['count']}")
        top_tags = ", ".join(f"{item['tag']} ({item['count']})" for item in group["top_tags"][:8]) or "(none)"
        lines.append(f"- top_tags: {top_tags}")
        lines.append("- examples:")
        for example in group["examples"][:5]:
            signals = ", ".join(example["signals"]) or "no_signal"
            lines.append(f"  - {example['title']} [{example['confidence']}]: {signals}")
        lines.append("")

    lines.extend(
        [
            "## Recommended new candidate families",
            "",
            ", ".join(summary["new_candidate_families_recommended"]) or "(none)",
            "",
            "## Doubtful families or buckets",
            "",
            ", ".join(summary["doubtful_families_or_buckets"]) or "(none)",
            "",
            f"- unknown_real: {summary['unknown_real']}",
            f"- requires_human_review: {summary['requires_human_review']}",
            "",
        ]
    )
    return "\n".join(lines)


def build_artifact_family_proposal(summary: dict[str, Any], mapping_preview: dict[str, Any]) -> str:
    lines = [
        "# S0145 artifact_family proposal",
        "",
        "S0145 proposes candidate families only. It does not apply metadata, does not",
        "rewrite canon shards, and does not regenerate semantic_text.",
        "",
        "## Counts",
        "",
        f"- total_unknown: {mapping_preview['total_unknown']}",
        f"- mapped_high_confidence: {mapping_preview['mapped_high_confidence']}",
        f"- mapped_medium_confidence: {mapping_preview['mapped_medium_confidence']}",
        f"- mapped_low_confidence: {mapping_preview['mapped_low_confidence']}",
        f"- requires_human_review: {mapping_preview['requires_human_review']}",
        f"- keep_unknown_for_now: {mapping_preview['keep_unknown_for_now']}",
        "",
        "## Candidate families to review in S0146",
        "",
    ]
    for family in summary["new_candidate_families_recommended"]:
        count = summary["by_candidate_artifact_family"].get(family, 0)
        lines.append(f"- {family}: {count}")
    if not summary["new_candidate_families_recommended"]:
        lines.append("- (none)")

    lines.extend(
        [
            "",
            "## Families not recommended yet",
            "",
            "- fuente_de_estudio: avoid introducing this UX layer until the clearer",
            "  technical families above are reviewed.",
            "- unknown_real: keep as a residual bucket until human review resolves it.",
            "- requires_human_review: not a canonical family; it is a workflow bucket.",
            "",
            "## S0146 orientation",
            "",
            "S0146 should build a reversible patch preview only, preserving:",
            "",
            "- dry_run: true",
            "- applied_to_canon: false unless a later explicit decision changes scope",
            "- canon_modified: false",
            "",
        ]
    )
    return "\n".join(lines)


def build_samples_md(summary: dict[str, Any]) -> str:
    lines = [
        "# S0145 unknown samples",
        "",
        "Deterministic examples by candidate family. Excerpts are in the JSONL review file.",
        "",
    ]
    for family, group in summary["groups"].items():
        lines.append(f"## {family}")
        lines.append("")
        for example in group["examples"][:8]:
            signals = ", ".join(example["signals"]) or "no_signal"
            lines.append(f"- {example['title']} [{example['confidence']}]: {signals}")
        lines.append("")
    return "\n".join(lines)


def review_rows(candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in candidates:
        rows.append(
            {
                "id": item["id"],
                "title": item["title"],
                "tags": "|".join(item["tags"]),
                "candidate_artifact_family": item["candidate_artifact_family"],
                "confidence": item["confidence"],
                "signals": "|".join(item["signals"]),
                "reason": item["reason"],
                "sample_excerpt": item["sample_excerpt"],
                "recommended_action": item["recommended_action"],
            }
        )
    return rows


def output_paths(out_dir: Path, session: str) -> dict[str, Path]:
    prefix = session.lower()
    return {
        "inventory": out_dir / f"{prefix}_unknown_inventory.json",
        "classification_candidates": out_dir / f"{prefix}_unknown_classification_candidates.jsonl",
        "grouped_summary": out_dir / f"{prefix}_unknown_grouped_summary.json",
        "grouped_summary_md": out_dir / f"{prefix}_unknown_grouped_summary.md",
        "review": out_dir / f"{prefix}_unknown_review.csv",
        "proposal": out_dir / f"{prefix}_artifact_family_proposal.md",
        "mapping_preview": out_dir / f"{prefix}_artifact_family_mapping_preview.json",
        "rules": out_dir / f"{prefix}_unknown_classification_rules.json",
        "samples": out_dir / f"{prefix}_unknown_samples.md",
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json_dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(stable_json_dumps(record) + "\n")


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def build_hashes(paths: dict[str, Path]) -> dict[str, Any]:
    return {
        "file_sha256": {
            name: sha256_bytes(path.read_bytes())
            for name, path in sorted(paths.items())
            if path.exists()
        }
    }


def build_unknown_artifact_family_outputs(
    *,
    canon_glob: str = DEFAULT_CANON_GLOB,
    semantic_text_records: Path | str | None = DEFAULT_SEMANTIC_TEXT_RECORDS,
    out_dir: Path | str = DEFAULT_OUT_DIR,
    session: str = DEFAULT_SESSION,
) -> dict[str, Any]:
    canon_records = read_canon_records(canon_glob)
    semantic_path = Path(semantic_text_records) if semantic_text_records else None
    semantic_records = read_semantic_text_records(semantic_path)
    unknown_records, meta = select_unknown_records(canon_records, semantic_records)
    candidates = [classify_unknown_record(record) for record in unknown_records]
    candidates.sort(key=lambda item: (item["title"].casefold(), item["id"]))

    session_lower = session.lower()
    paths = output_paths(Path(out_dir), session_lower)
    inventory = build_inventory(candidates, meta=meta, session=session_lower)
    grouped = build_grouped_summary(candidates, session=session_lower)
    mapping = build_mapping_preview(candidates, session=session_lower)
    rules = classification_rules(session_lower)

    write_json(paths["inventory"], inventory)
    write_jsonl(paths["classification_candidates"], candidates)
    write_json(paths["grouped_summary"], grouped)
    paths["grouped_summary_md"].write_text(build_grouped_summary_md(grouped), encoding="utf-8")
    write_csv(paths["review"], review_rows(candidates))
    paths["proposal"].write_text(build_artifact_family_proposal(grouped, mapping), encoding="utf-8")
    write_json(paths["mapping_preview"], mapping)
    write_json(paths["rules"], rules)
    paths["samples"].write_text(build_samples_md(grouped), encoding="utf-8")

    return {
        "schema": SCHEMA,
        "session": session_lower.upper(),
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "semantic_text_regenerated": False,
        "embeddings_executed": False,
        "paths": {name: str(path) for name, path in paths.items()},
        "summary": {
            "total_unknown": len(candidates),
            "by_candidate_artifact_family": mapping["by_candidate_artifact_family"],
            "by_confidence": grouped["by_confidence"],
            "by_recommended_action": grouped["by_recommended_action"],
        },
        "hashes": build_hashes(paths),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Characterize unknown artifact_family records without modifying canon.",
    )
    parser.add_argument("--canon-glob", default=DEFAULT_CANON_GLOB)
    parser.add_argument(
        "--semantic-text-records",
        default=str(DEFAULT_SEMANTIC_TEXT_RECORDS),
        help="S0144 semantic_text records JSONL. Use an empty string to infer unknowns from canon only.",
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--session", default=DEFAULT_SESSION)
    parser.add_argument("--dry-run", action="store_true", help="Accepted for explicit non-apply mode.")
    args = parser.parse_args()

    semantic_records = args.semantic_text_records or None
    result = build_unknown_artifact_family_outputs(
        canon_glob=args.canon_glob,
        semantic_text_records=semantic_records,
        out_dir=args.out_dir,
        session=args.session,
    )
    print(stable_json_dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
