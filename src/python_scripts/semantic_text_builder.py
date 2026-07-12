#!/usr/bin/env python3
"""Deterministic semantic_text builder for S0144.

This module reads canon shards, builds a derived semantic_text sidecar, and
writes reports under data/out/local/pipeline. It never writes canon shards and
does not expose an apply mode.
"""

from __future__ import annotations

import csv
import glob
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from tag_sanitation_policy import DEFAULT_POLICY_PATH as DEFAULT_TAG_POLICY
from tag_sanitation_policy import filter_tags_for_rag, load_policy as load_tag_policy

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]

SCHEMA = "semantic-text-build/v1"
SEMANTIC_TEXT_VERSION = "semantic-text/v1"
DEFAULT_SESSION = "s0144"
DEFAULT_CANON_GLOB = str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl")
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "semantic_text" / "s0144"
DEFAULT_TYPE_POLICY = (
    REPO_ROOT
    / "data"
    / "out"
    / "local"
    / "pipeline"
    / "relation_type_governance"
    / "s0139"
    / "s0139_historical_relation_type_decisions.json"
)
DEFAULT_DRY_RUN_READY_GLOB = str(
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_admission" / "*" / "admission_ready_dry_run.json"
)
DEFAULT_PATCH_PREVIEW_GLOB = str(
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_admission" / "*" / "admission_patch_preview.json"
)

DEFAULT_MAX_CONTENT_CHARS = 12000
TRUNCATION_MARKER = "[TRUNCATED_DETERMINISTICALLY]"

PROFILE_SECTIONS = [
    "identity",
    "classification",
    "source_fields",
    "canonical_relations",
    "legacy_relations",
    "structural_relations",
    "content_core",
    "operational_notes",
]

FAMILY_ALIASES = {
    "sesion": "detalles_de_sesion",
    "detalles": "detalles_de_sesion",
    "contrato": "contrato_de_sesion",
    "procedencia": "procedencia_de_sesion",
    "hipotesis": "hipotesis_de_sesion",
    "balance": "balance_de_sesion",
    "propuesta": "propuesta_de_sesion",
    "diagnostico_sesion": "diagnostico_de_sesion",
    "diagnostico_de_sesion": "diagnostico_de_sesion",
    "micro_ciclo": "diagnostico_de_micro_ciclo",
    "meso_ciclo": "diagnostico_de_meso_ciclo",
    "proyecto": "diagnostico_de_proyecto",
    "tema": "diagnostico_tematico",
}

EXPECTED_PROFILE_FAMILIES = [
    "sesion",
    "diagnostico_sesion",
    "diagnostico_tematico",
    "contrato",
    "procedencia",
    "hipotesis",
    "balance",
    "propuesta",
    "micro_ciclo",
    "meso_ciclo",
    "proyecto",
    "tema",
    "canon",
    "unknown",
]

FAMILY_PRIORITIES = {
    "detalles_de_sesion": [
        "numero de sesion",
        "slug",
        "objetivo",
        "resultado",
        "pruebas",
        "restricciones",
        "rutas afectadas",
        "estado de canon",
        "propuesta siguiente",
    ],
    "diagnostico_de_sesion": [
        "problema diagnosticado",
        "evidencia",
        "riesgos",
        "decision recomendada",
        "impacto sobre canon",
        "proxima accion",
    ],
    "diagnostico_tematico": [
        "problema diagnosticado",
        "evidencia",
        "riesgos",
        "decision recomendada",
        "impacto sobre canon",
        "proxima accion",
    ],
    "contrato_de_sesion": [
        "objetivo",
        "alcance",
        "exclusiones",
        "criterios de aceptacion",
        "rutas permitidas/prohibidas",
        "tests requeridos",
    ],
    "procedencia_de_sesion": [
        "fuentes leidas",
        "scripts consultados",
        "artefactos previos",
        "evidencia de contexto",
        "limitaciones",
    ],
    "hipotesis_de_sesion": [
        "hipotesis",
        "condicion de verificacion",
        "resultado esperado",
        "riesgo si falla",
    ],
    "balance_de_sesion": [
        "que se completo",
        "que no se completo",
        "tests",
        "deuda residual",
        "estado de canon",
    ],
    "propuesta_de_sesion": [
        "siguiente sesion",
        "justificacion",
        "precondiciones",
        "riesgos",
        "criterios de exito",
    ],
}

DEFAULT_RELATION_POLICY = {
    "references": {
        "decision_status": "canonical_keep",
        "proposed_canonical_type": "references",
    },
    "usa": {
        "decision_status": "legacy_alias_candidate",
        "proposed_canonical_type": "references",
    },
    "parte_de": {
        "decision_status": "legacy_alias_candidate",
        "proposed_canonical_type": "part_of",
    },
    "requiere": {
        "decision_status": "legacy_alias_candidate",
        "proposed_canonical_type": "depende_de",
    },
    "define": {
        "decision_status": "legacy_readonly",
        "proposed_canonical_type": "",
    },
    "child_of": {
        "decision_status": "structural_only",
        "proposed_canonical_type": "",
    },
}

REVIEW_COLUMNS = [
    "id",
    "title",
    "artifact_family",
    "semantic_text_chars",
    "sections_included",
    "has_canonical_relations",
    "has_legacy_relations",
    "has_structural_relations",
    "dry_run_preview_included",
    "semantic_text_sha256",
    "warnings",
]


def stable_json_dumps(value: Any, *, indent: int | None = None) -> str:
    if indent is None:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def truncate_deterministically(text: str, limit: int) -> tuple[str, bool]:
    if limit <= 0 or len(text) <= limit:
        return text, False
    usable = max(0, limit - len(TRUNCATION_MARKER) - 1)
    return text[:usable].rstrip() + "\n" + TRUNCATION_MARKER, True


def normalize_family(raw_family: Any) -> str:
    family = normalize_text(raw_family)
    if not family:
        return "unknown"
    return FAMILY_ALIASES.get(family, family)


def artifact_family_for(record: dict[str, Any]) -> str:
    sf = record.get("source_fields") if isinstance(record.get("source_fields"), dict) else {}
    return normalize_family(
        sf.get("artifact_family")
        or record.get("artifact_family")
        or record.get("family")
        or ""
    )


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
    for tag in sorted(tags, key=lambda item: item.casefold()):
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(tag)
    return deduped


def relation_target_id(relation: dict[str, Any]) -> str:
    return normalize_text(
        relation.get("target_id")
        or relation.get("target")
        or relation.get("to")
        or relation.get("target_ref")
        or ""
    )


def load_relation_policy(path: Path | str = DEFAULT_TYPE_POLICY) -> dict[str, dict[str, Any]]:
    policy = {key: dict(value) for key, value in DEFAULT_RELATION_POLICY.items()}
    p = Path(path)
    if not p.exists():
        return policy
    payload = json.loads(p.read_text(encoding="utf-8"))
    by_type = payload.get("decisions_by_type")
    if isinstance(by_type, dict):
        for rel_type, decision in by_type.items():
            if isinstance(decision, dict):
                policy[str(rel_type)] = dict(decision)
    for decision in payload.get("decisions") or []:
        if isinstance(decision, dict) and decision.get("relation_type"):
            policy[str(decision["relation_type"])] = dict(decision)
    return policy


def read_canon_records(canon_glob: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for shard in sorted(glob.glob(canon_glob)):
        with open(shard, encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                record["_semantic_text_source_shard"] = str(Path(shard))
                record["_semantic_text_source_line"] = line_no
                records.append(record)
    return records


def canon_index(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(record["id"]): record
        for record in records
        if record.get("id")
    }


def profile_for_family(family: str, max_content_chars: int) -> dict[str, Any]:
    return {
        "artifact_family": family,
        "sections": list(PROFILE_SECTIONS),
        "include_tags": True,
        "include_canonical_relations": True,
        "include_legacy_relations_as_historical": True,
        "include_structural_relations": True,
        "include_dry_run_candidates": False,
        "include_patch_preview": False,
        "max_content_chars_per_section": max_content_chars,
        "truncation_marker": TRUNCATION_MARKER,
        "family_priorities": FAMILY_PRIORITIES.get(family, []),
    }


def build_profiles(detected_families: set[str], max_content_chars: int) -> dict[str, Any]:
    canonical_expected = {normalize_family(family) for family in EXPECTED_PROFILE_FAMILIES}
    all_families = set(detected_families) | canonical_expected | {"unknown"}
    profiles = {
        family: profile_for_family(family, max_content_chars)
        for family in sorted(all_families)
    }
    expected_status = {
        family: {
            "canonical_family": normalize_family(family),
            "present": normalize_family(family) in detected_families,
        }
        for family in EXPECTED_PROFILE_FAMILIES
    }
    return {
        "schema": "semantic-text-profiles/v1",
        "session": "S0144",
        "semantic_text_version": SEMANTIC_TEXT_VERSION,
        "dry_run": True,
        "canon_modified": False,
        "profiles": profiles,
        "detected_artifact_families": sorted(detected_families),
        "expected_families": expected_status,
        "missing_expected_families": [
            family
            for family, status in expected_status.items()
            if not status["present"]
        ],
    }


def load_dry_run_preview_index(
    ready_glob: str = DEFAULT_DRY_RUN_READY_GLOB,
    patch_glob: str = DEFAULT_PATCH_PREVIEW_GLOB,
) -> dict[str, dict[str, int]]:
    index: dict[str, dict[str, int]] = defaultdict(lambda: {"dry_run_ready": 0, "patch_preview": 0})
    for path in sorted(glob.glob(ready_glob)):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        for item in payload.get("items") or []:
            source_id = normalize_text(item.get("source_tiddler_id") or item.get("source_id") or "")
            if source_id:
                index[source_id]["dry_run_ready"] += 1
    for path in sorted(glob.glob(patch_glob)):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        for operation in payload.get("operations") or []:
            source_id = normalize_text(operation.get("source_id") or operation.get("source_tiddler_id") or "")
            if source_id:
                index[source_id]["patch_preview"] += 1
    return dict(index)


def format_relation(
    relation: dict[str, Any],
    *,
    index: dict[str, dict[str, Any]],
    policy: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rel_type = normalize_text(relation.get("type"))
    target_id = relation_target_id(relation)
    target_title = normalize_text(index.get(target_id, {}).get("title", "")) if target_id else ""
    evidence = normalize_text(relation.get("evidence"))
    decision = policy.get(rel_type) or {}
    status = normalize_text(decision.get("decision_status")) or "canonical_existing_unclassified"
    proposed = normalize_text(decision.get("proposed_canonical_type"))
    line = f"- {rel_type} -> {target_id or '(target missing)'}"
    if target_title:
        line += f" ({target_title})"
    if evidence:
        line += f"; evidence={evidence}"
    if status == "legacy_alias_candidate":
        line += f"; historical alias candidate only"
        if proposed:
            line += f" (not applied as {proposed})"
    elif status == "legacy_readonly":
        line += "; historical readonly"
    elif status == "structural_only":
        line += "; structural only"
    elif status == "canonical_keep":
        line += "; canonical"
    else:
        line += f"; policy={status}"
    return {
        "type": rel_type,
        "target_id": target_id,
        "target_title": target_title,
        "evidence": evidence,
        "decision_status": status,
        "proposed_canonical_type": proposed,
        "line": line,
    }


def classify_relations(
    record: dict[str, Any],
    *,
    index: dict[str, dict[str, Any]],
    policy: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    classified = {
        "canonical": [],
        "legacy": [],
        "structural": [],
        "unclassified": [],
    }
    relations = record.get("relations") or []
    if not isinstance(relations, list):
        return classified
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        formatted = format_relation(relation, index=index, policy=policy)
        status = formatted["decision_status"]
        if status == "canonical_keep" or status == "canonical_existing_unclassified":
            classified["canonical"].append(formatted)
        elif status in {"legacy_readonly", "legacy_alias_candidate", "canonical_equivalent"}:
            classified["legacy"].append(formatted)
        elif status == "structural_only":
            classified["structural"].append(formatted)
        else:
            classified["unclassified"].append(formatted)
    for rels in classified.values():
        rels.sort(key=lambda item: (item["type"], item["target_id"], item["evidence"], item["line"]))
    return classified


def content_core(record: dict[str, Any]) -> str:
    text = record.get("text")
    if text:
        return normalize_text(text)
    content = record.get("content")
    if isinstance(content, dict):
        return normalize_text(content.get("plain") or content.get("text") or "")
    return normalize_text(content)


def redact_terms_for_rag(text: str, blocked_terms: list[str]) -> str:
    redacted = text
    for term in sorted(set(blocked_terms), key=len, reverse=True):
        if not term:
            continue
        redacted = redacted.replace(term, "[RAG_TAG_BLOCKED]")
    return redacted


def build_retrieval_hints(
    *,
    family: str,
    record: dict[str, Any],
    source_fields: dict[str, Any],
    tag_filter: dict[str, Any],
    relations: dict[str, list[dict[str, Any]]],
) -> list[str]:
    hints: list[str] = []
    for value in (
        family,
        normalize_text(record.get("role_primary")),
        normalize_text(source_fields.get("artifact_family")),
        normalize_text(source_fields.get("language")),
    ):
        if value and value not in hints:
            hints.append(value)
    for tag in tag_filter["retrieval_hint_tags"]:
        if tag not in hints:
            hints.append(tag)
    for relation in relations["canonical"][:8]:
        hint = normalize_text(relation.get("type"))
        if hint and hint not in hints:
            hints.append(hint)
    return sorted(hints, key=lambda item: item.casefold())


def build_embedding_metadata(
    *,
    family: str,
    record: dict[str, Any],
    source_fields: dict[str, Any],
    tag_filter: dict[str, Any],
) -> dict[str, Any]:
    return {
        "semantic_family": family,
        "artifact_family": family,
        "role_primary": normalize_text(record.get("role_primary")) or None,
        "language": normalize_text(source_fields.get("language")) or None,
        "rag_allowed_tags": tag_filter["allowed_semantic_tags"],
        "metadata_only_tags": tag_filter["metadata_only_tags"],
        "projectable_tags": tag_filter["projectable_tags"],
        "human_navigation_tag_count": len(tag_filter["human_navigation_tags"]),
        "audit_only_blocked_tags_count": len(tag_filter["blocked_tags"]),
        "audit_only_unknown_tags_count": len(tag_filter["unknown_tags"]),
    }


def build_semantic_text_record(
    record: dict[str, Any],
    *,
    index: dict[str, dict[str, Any]],
    policy: dict[str, dict[str, Any]],
    tag_policy: dict[str, Any] | None = None,
    global_redacted_terms: list[str] | None = None,
    profiles: dict[str, Any],
    preview_index: dict[str, dict[str, int]] | None = None,
    max_content_chars: int = DEFAULT_MAX_CONTENT_CHARS,
) -> dict[str, Any]:
    preview_index = preview_index or {}
    record_id = normalize_text(record.get("id"))
    title = normalize_text(record.get("title"))
    key = normalize_text(record.get("key"))
    family = artifact_family_for(record)
    profile = profiles.get("profiles", {}).get(family) or profile_for_family("unknown", max_content_chars)
    sf = record.get("source_fields") if isinstance(record.get("source_fields"), dict) else {}
    raw_tags = collect_tags(record)
    tag_policy = tag_policy or load_tag_policy(DEFAULT_TAG_POLICY)
    tag_filter = filter_tags_for_rag(raw_tags, tag_policy)
    tags = tag_filter["allowed_semantic_tags"]
    blocked_tags = tag_filter["blocked_tags"]
    unknown_tags = tag_filter["unknown_tags"]
    redacted_terms = global_redacted_terms or (blocked_tags + unknown_tags)
    relations = classify_relations(record, index=index, policy=policy)
    retrieval_hints = build_retrieval_hints(
        family=family,
        record=record,
        source_fields=sf,
        tag_filter=tag_filter,
        relations=relations,
    )
    embedding_metadata = build_embedding_metadata(
        family=family,
        record=record,
        source_fields=sf,
        tag_filter=tag_filter,
    )
    source_hash = sha256_text(stable_json_dumps({k: v for k, v in record.items() if not k.startswith("_semantic_text_")}))
    sections: list[tuple[str, str, list[str]]] = []
    warnings: list[str] = []
    truncated = False

    identity_lines = [
        f"Titulo: {redact_terms_for_rag(title, redacted_terms)}",
        f"ID: {record_id}",
        f"Key: {redact_terms_for_rag(key, redacted_terms)}" if key else "",
        f"Familia documental: {family}",
    ]
    for field in ("session", "session_id", "canonical_slug", "version_id"):
        value = normalize_text(record.get(field) or sf.get(field))
        if value:
            identity_lines.append(f"{field}: {value}")
    sections.append(("identity", "# Identidad", [line for line in identity_lines if line]))

    classification_lines = [
        f"Artifact family: {family}",
        "Perfil aplicado: " + profile["artifact_family"],
        "Tags RAG permitidos (clasificacion solamente; tag != relation): "
        + (", ".join(tags) if tags else "(sin tags declarados)"),
    ]
    if profile.get("family_priorities"):
        classification_lines.append("Prioridades de familia: " + ", ".join(profile["family_priorities"]))
    sections.append(("classification", "# Clasificacion", classification_lines))

    if sf:
        sf_lines = []
        for key_name in sorted(sf):
            if key_name in {"tags", "source_tags", "normalized_tags"}:
                sf_lines.append(f"{key_name}: excluded_from_semantic_text_by_tag_sanitation_policy")
                continue
            value = normalize_text(sf.get(key_name))
            value, was_truncated = truncate_deterministically(value, max_content_chars)
            truncated = truncated or was_truncated
            value = redact_terms_for_rag(value, redacted_terms)
            sf_lines.append(f"{key_name}: {value}")
        sections.append(("source_fields", "# Procedencia / source_fields", sf_lines))
    else:
        sections.append(("source_fields", "# Procedencia / source_fields", ["source_fields: (ausente)"]))
        if family == "unknown":
            warnings.append("missing_artifact_family")

    if profile.get("include_canonical_relations"):
        canonical_lines = [item["line"] for item in relations["canonical"]]
        if canonical_lines:
            sections.append(("canonical_relations", "# Relaciones canonicas", canonical_lines))

    if profile.get("include_legacy_relations_as_historical"):
        legacy_lines = [item["line"] for item in relations["legacy"]]
        if legacy_lines:
            sections.append(("legacy_relations", "# Relaciones historicas gobernadas", legacy_lines))

    if profile.get("include_structural_relations"):
        structural_lines = [item["line"] for item in relations["structural"]]
        if structural_lines:
            sections.append(("structural_relations", "# Estructura historica no semantica", structural_lines))

    core = content_core(record)
    core, was_truncated = truncate_deterministically(core, max_content_chars)
    truncated = truncated or was_truncated
    core = redact_terms_for_rag(core, redacted_terms)
    sections.append(("content_core", "# Contenido principal", [core if core else "(sin contenido textual)"]))

    preview_counts = preview_index.get(record_id, {"dry_run_ready": 0, "patch_preview": 0})
    dry_run_preview_excluded = bool(preview_counts.get("dry_run_ready"))
    patch_preview_excluded = bool(preview_counts.get("patch_preview"))
    operational_lines = [
        "dry_run_candidates_included: false",
        "patch_preview_included: false",
    ]
    if dry_run_preview_excluded:
        operational_lines.append(
            f"dry_run_candidates_excluded: {preview_counts['dry_run_ready']} (preview aprobado en dry-run, no admitido al canon)"
        )
        warnings.append("dry_run_preview_excluded")
    if patch_preview_excluded:
        operational_lines.append(f"patch_preview_excluded: {preview_counts['patch_preview']} (preview no canonico)")
        warnings.append("patch_preview_excluded")
    sections.append(("operational_notes", "# Notas operativas no canonicas", operational_lines))

    if truncated:
        warnings.append("truncated_deterministically")
    if blocked_tags:
        warnings.append("p0_tags_blocked_from_semantic_text")
    if unknown_tags:
        warnings.append("unknown_tags_blocked_from_rag")

    section_chunks = []
    sections_included: list[str] = []
    for key_name, heading, lines in sections:
        section_chunks.append(heading + "\n" + "\n".join(lines))
        sections_included.append(key_name)
    semantic_text = "\n\n".join(section_chunks).strip() + "\n"
    semantic_text = redact_terms_for_rag(semantic_text, redacted_terms)
    semantic_hash = sha256_text(semantic_text)

    return {
        "id": record_id,
        "title": title,
        "artifact_family": family,
        "semantic_text": semantic_text,
        "semantic_text_version": SEMANTIC_TEXT_VERSION,
        "semantic_text_sha256": semantic_hash,
        "retrieval_hints": retrieval_hints,
        "embedding_metadata": embedding_metadata,
        "source_record_sha256": source_hash,
        "source_canon_version_id": normalize_text(record.get("version_id")),
        "derivation_profile_version": SEMANTIC_TEXT_VERSION,
        "authority_level": normalize_text(sf.get("authority_level")) or None,
        "authority_state": "inherited" if sf.get("authority_level") else "not_recorded",
        "repo_lifecycle_state": normalize_text(sf.get("repo_lifecycle_state")) or None,
        "repo_lifecycle_applicability": "applicable" if sf.get("repo_lifecycle_state") else "not_applicable",
        "sections_included": sections_included,
        "dry_run": True,
        "canon_modified": False,
        "profile_applied": profile["artifact_family"],
        "has_canonical_relations": bool(relations["canonical"]),
        "has_legacy_relations": bool(relations["legacy"]),
        "has_structural_relations": bool(relations["structural"]),
        "dry_run_preview_included": False,
        "dry_run_preview_excluded": dry_run_preview_excluded,
        "patch_preview_included": False,
        "patch_preview_excluded": patch_preview_excluded,
        "records_truncated": truncated,
        "canonical_relation_count": len(relations["canonical"]),
        "legacy_relation_count": len(relations["legacy"]),
        "structural_relation_count": len(relations["structural"]),
        "warnings": sorted(set(warnings)),
        "source_tag_count": len(raw_tags),
        "rag_allowed_tag_count": len(tags),
        "metadata_only_tag_count": len(tag_filter["metadata_only_tags"]),
        "human_navigation_tag_count": len(tag_filter["human_navigation_tags"]),
        "audit_only_blocked_tags_count": len(blocked_tags),
        "audit_only_unknown_tags_count": len(unknown_tags),
        "tag_filter_counts": tag_filter["counts"],
    }


def build_records(
    records: list[dict[str, Any]],
    *,
    policy: dict[str, dict[str, Any]],
    tag_policy: dict[str, Any] | None = None,
    global_redacted_terms: list[str] | None = None,
    profiles: dict[str, Any],
    preview_index: dict[str, dict[str, int]] | None = None,
    max_content_chars: int = DEFAULT_MAX_CONTENT_CHARS,
) -> list[dict[str, Any]]:
    index = canon_index(records)
    return [
        build_semantic_text_record(
            record,
            index=index,
            policy=policy,
            tag_policy=tag_policy,
            global_redacted_terms=global_redacted_terms,
            profiles=profiles,
            preview_index=preview_index,
            max_content_chars=max_content_chars,
        )
        for record in records
    ]


def build_index(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_family = Counter(record["artifact_family"] for record in records)
    return {
        "schema": "semantic-text-index/v1",
        "record_count": len(records),
        "by_artifact_family": dict(sorted(by_family.items())),
        "semantic_text_version": SEMANTIC_TEXT_VERSION,
        "dry_run": True,
        "canon_modified": False,
        "records": {
            record["id"]: {
                "title": record["title"],
                "artifact_family": record["artifact_family"],
                "semantic_text_sha256": record["semantic_text_sha256"],
                "source_record_sha256": record["source_record_sha256"],
            }
            for record in sorted(records, key=lambda item: (item["id"], item["title"]))
        },
    }


def build_coverage_report(records: list[dict[str, Any]], profiles: dict[str, Any]) -> dict[str, Any]:
    by_family: dict[str, dict[str, int]] = {}
    for record in records:
        family = record["artifact_family"]
        bucket = by_family.setdefault(
            family,
            {
                "total_records": 0,
                "records_with_semantic_text": 0,
                "records_with_canonical_relations": 0,
                "records_with_legacy_relations": 0,
                "records_with_structural_relations": 0,
                "records_with_dry_run_preview_excluded": 0,
                "records_truncated": 0,
                "blocked_tags": 0,
                "unknown_tags": 0,
            },
        )
        bucket["total_records"] += 1
        bucket["records_with_semantic_text"] += int(bool(record["semantic_text"]))
        bucket["records_with_canonical_relations"] += int(record["has_canonical_relations"])
        bucket["records_with_legacy_relations"] += int(record["has_legacy_relations"])
        bucket["records_with_structural_relations"] += int(record["has_structural_relations"])
        bucket["records_with_dry_run_preview_excluded"] += int(record["dry_run_preview_excluded"])
        bucket["records_truncated"] += int(record["records_truncated"])
        bucket["blocked_tags"] += int(record["audit_only_blocked_tags_count"])
        bucket["unknown_tags"] += int(record["audit_only_unknown_tags_count"])

    return {
        "schema": "semantic-text-coverage-report/v1",
        "session": "S0144",
        "semantic_text_version": SEMANTIC_TEXT_VERSION,
        "dry_run": True,
        "canon_modified": False,
        "embeddings_executed": False,
        "relations_admitted": False,
        "total_records": len(records),
        "records_with_semantic_text": sum(1 for record in records if record["semantic_text"]),
        "records_missing_artifact_family": sum(1 for record in records if record["artifact_family"] == "unknown"),
        "records_with_canonical_relations": sum(1 for record in records if record["has_canonical_relations"]),
        "records_with_legacy_relations": sum(1 for record in records if record["has_legacy_relations"]),
        "records_with_structural_relations": sum(1 for record in records if record["has_structural_relations"]),
        "records_with_dry_run_preview_excluded": sum(1 for record in records if record["dry_run_preview_excluded"]),
        "records_with_patch_preview_excluded": sum(1 for record in records if record["patch_preview_excluded"]),
        "records_truncated": sum(1 for record in records if record["records_truncated"]),
        "blocked_tags_excluded_from_rag": sum(record["audit_only_blocked_tags_count"] for record in records),
        "unknown_tags_excluded_from_rag": sum(record["audit_only_unknown_tags_count"] for record in records),
        "records_with_blocked_tags": sum(1 for record in records if record["audit_only_blocked_tags_count"]),
        "records_with_unknown_tags": sum(1 for record in records if record["audit_only_unknown_tags_count"]),
        "artifact_family_count": len(by_family),
        "profiles_applied": sorted({record["profile_applied"] for record in records}),
        "by_artifact_family": dict(sorted(by_family.items())),
        "missing_expected_families": profiles.get("missing_expected_families", []),
    }


def build_coverage_summary(report: dict[str, Any]) -> str:
    lines = [
        "# S0144 semantic_text coverage summary",
        "",
        "- semantic_text deterministico generado: si",
        f"- total_records: {report['total_records']}",
        f"- records_with_semantic_text: {report['records_with_semantic_text']}",
        f"- artifact_family_count: {report['artifact_family_count']}",
        f"- records_missing_artifact_family: {report['records_missing_artifact_family']}",
        f"- records_with_canonical_relations: {report['records_with_canonical_relations']}",
        f"- records_with_legacy_relations: {report['records_with_legacy_relations']}",
        f"- records_with_structural_relations: {report['records_with_structural_relations']}",
        f"- records_with_dry_run_preview_excluded: {report['records_with_dry_run_preview_excluded']}",
        f"- records_with_patch_preview_excluded: {report['records_with_patch_preview_excluded']}",
        f"- records_truncated: {report['records_truncated']}",
        f"- blocked_tags_excluded_from_rag: {report['blocked_tags_excluded_from_rag']}",
        f"- unknown_tags_excluded_from_rag: {report['unknown_tags_excluded_from_rag']}",
        "- dry_run_candidates_included: no",
        "- patch_preview_included: no",
        "- embeddings_executed: no",
        "- relations_admitted: no",
        "- canon_modified: false",
        "",
        "## By artifact_family",
        "",
        "| artifact_family | total | semantic_text | canonical_rel | legacy_rel | structural_rel | truncated |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for family, bucket in report["by_artifact_family"].items():
        lines.append(
            "| {family} | {total_records} | {records_with_semantic_text} | "
            "{records_with_canonical_relations} | {records_with_legacy_relations} | "
            "{records_with_structural_relations} | {records_truncated} |".format(
                family=family,
                **bucket,
            )
        )
    lines.append("")
    return "\n".join(lines)


def records_to_review_rows(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for record in records:
        rows.append(
            {
                "id": record["id"],
                "title": record["title"],
                "artifact_family": record["artifact_family"],
                "semantic_text_chars": str(len(record["semantic_text"])),
                "sections_included": "|".join(record["sections_included"]),
                "has_canonical_relations": str(record["has_canonical_relations"]).lower(),
                "has_legacy_relations": str(record["has_legacy_relations"]).lower(),
                "has_structural_relations": str(record["has_structural_relations"]).lower(),
                "dry_run_preview_included": str(record["dry_run_preview_included"]).lower(),
                "semantic_text_sha256": record["semantic_text_sha256"],
                "warnings": "|".join(record["warnings"]),
            }
        )
    return rows


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


def output_paths(out_dir: Path, session: str) -> dict[str, Path]:
    prefix = session.lower()
    return {
        "records": out_dir / f"{prefix}_semantic_text_records.jsonl",
        "index": out_dir / f"{prefix}_semantic_text_index.json",
        "profiles": out_dir / f"{prefix}_semantic_text_profiles.json",
        "coverage_report": out_dir / f"{prefix}_semantic_text_coverage_report.json",
        "coverage_summary": out_dir / f"{prefix}_semantic_text_coverage_summary.md",
        "review": out_dir / f"{prefix}_semantic_text_review.csv",
        "hashes": out_dir / f"{prefix}_semantic_text_hashes.json",
    }


def build_hashes(paths: dict[str, Path], records: list[dict[str, Any]]) -> dict[str, Any]:
    file_hashes = {
        name: sha256_bytes(path.read_bytes())
        for name, path in sorted(paths.items())
        if name != "hashes" and path.exists()
    }
    record_hashes = {
        record["id"]: record["semantic_text_sha256"]
        for record in sorted(records, key=lambda item: (item["id"], item["title"]))
    }
    return {
        "schema": "semantic-text-hashes/v1",
        "session": "S0144",
        "semantic_text_version": SEMANTIC_TEXT_VERSION,
        "dry_run": True,
        "canon_modified": False,
        "file_sha256": file_hashes,
        "record_semantic_text_sha256": record_hashes,
        "hashes_file_self_hash_included": False,
    }


def write_outputs(
    records: list[dict[str, Any]],
    profiles: dict[str, Any],
    *,
    out_dir: Path,
    session: str,
) -> dict[str, Path]:
    paths = output_paths(out_dir, session)
    index = build_index(records)
    coverage = build_coverage_report(records, profiles)
    summary = build_coverage_summary(coverage)
    review_rows = records_to_review_rows(records)

    write_jsonl(paths["records"], records)
    write_json(paths["index"], index)
    write_json(paths["profiles"], profiles)
    write_json(paths["coverage_report"], coverage)
    paths["coverage_summary"].write_text(summary, encoding="utf-8")
    write_csv(paths["review"], review_rows)
    write_json(paths["hashes"], build_hashes(paths, records))
    return paths


def build_semantic_text_outputs(
    *,
    canon_glob: str = DEFAULT_CANON_GLOB,
    out_dir: Path | str = DEFAULT_OUT_DIR,
    session: str = DEFAULT_SESSION,
    type_policy: Path | str = DEFAULT_TYPE_POLICY,
    tag_policy: Path | str = DEFAULT_TAG_POLICY,
    strict_tag_gate: bool = True,
    dry_run_ready_glob: str = DEFAULT_DRY_RUN_READY_GLOB,
    patch_preview_glob: str = DEFAULT_PATCH_PREVIEW_GLOB,
    max_content_chars: int = DEFAULT_MAX_CONTENT_CHARS,
) -> dict[str, Any]:
    unsafe_legacy_mode = False
    if strict_tag_gate and not Path(tag_policy).exists():
        raise FileNotFoundError(f"strict tag gate requires a tag policy file: {tag_policy}")
    if not strict_tag_gate and not Path(tag_policy).exists():
        unsafe_legacy_mode = True
    canon_records = read_canon_records(canon_glob)
    detected_families = {artifact_family_for(record) for record in canon_records}
    profiles = build_profiles(detected_families, max_content_chars)
    policy = load_relation_policy(type_policy)
    loaded_tag_policy = load_tag_policy(tag_policy)
    global_filter = filter_tags_for_rag(
        [
            tag
            for record in canon_records
            for tag in collect_tags(record)
        ],
        loaded_tag_policy,
    )
    global_redacted_terms = global_filter["blocked_tags"] + global_filter["unknown_tags"]
    preview_index = load_dry_run_preview_index(dry_run_ready_glob, patch_preview_glob)
    semantic_records = build_records(
        canon_records,
        policy=policy,
        tag_policy=loaded_tag_policy,
        global_redacted_terms=global_redacted_terms,
        profiles=profiles,
        preview_index=preview_index,
        max_content_chars=max_content_chars,
    )
    paths = write_outputs(
        semantic_records,
        profiles,
        out_dir=Path(out_dir),
        session=session.lower(),
    )
    coverage = build_coverage_report(semantic_records, profiles)
    return {
        "schema": SCHEMA,
        "session": session.upper(),
        "dry_run": True,
        "canon_modified": False,
        "strict_tag_gate": strict_tag_gate,
        "unsafe_legacy_mode": unsafe_legacy_mode,
        "tag_policy": str(tag_policy),
        "paths": {name: str(path) for name, path in paths.items()},
        "summary": {
            "record_count": len(semantic_records),
            "records_with_semantic_text": coverage["records_with_semantic_text"],
            "artifact_family_count": coverage["artifact_family_count"],
            "records_with_canonical_relations": coverage["records_with_canonical_relations"],
            "records_with_legacy_relations": coverage["records_with_legacy_relations"],
            "records_with_structural_relations": coverage["records_with_structural_relations"],
            "records_with_dry_run_preview_excluded": coverage["records_with_dry_run_preview_excluded"],
            "records_with_patch_preview_excluded": coverage["records_with_patch_preview_excluded"],
            "records_truncated": coverage["records_truncated"],
            "blocked_tags_excluded_from_rag": coverage["blocked_tags_excluded_from_rag"],
            "unknown_tags_excluded_from_rag": coverage["unknown_tags_excluded_from_rag"],
            "records_with_blocked_tags": coverage["records_with_blocked_tags"],
            "records_with_unknown_tags": coverage["records_with_unknown_tags"],
            "global_redacted_terms": len(global_redacted_terms),
        },
    }
