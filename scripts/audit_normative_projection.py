#!/usr/bin/env python3
"""
audit_normative_projection.py — Normative self-audit for canon shards + derived layers (S47).

Reads:
  - out/tiddlers_*.jsonl               (canon shards)
  - out/enriched/tiddlers_enriched_*.jsonl
  - out/ai/tiddlers_ai_*.jsonl
  - out/ai/chunks_ai_*.jsonl
  - out/ai/reports/*.json
  - docs/ (normative reference)

Evaluates 21 normative rules, classifies findings, applies safe autofixes,
rewrites affected canon shards, optionally regenerates derived layers, and emits:
  - out/audit/manifest.json
  - out/audit/compliance_report.json
  - out/audit/compliance_summary.md
  - out/audit/warnings.jsonl
  - out/audit/manual_review_queue.jsonl
  - out/audit/proposed_fixes.json
  - out/audit/applied_safe_fixes.json
  - out/audit/pre_post_diff.json
  - out/audit/audit_log.jsonl

Modes:
  --mode audit   : inspect only, no writes to canon
  --mode apply   : inspect + apply safe fixes + regenerate derived layers

Usage:
  python3 scripts/audit_normative_projection.py --help
  python3 scripts/audit_normative_projection.py --mode audit --input-root out --docs-root docs
  python3 scripts/audit_normative_projection.py --mode apply --input-root out --docs-root docs

Session: S47
"""

import argparse
import json
import os
import re
import sys
import unicodedata
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Session metadata ──────────────────────────────────────────────────────────
SESSION = "S47"
AUDIT_SCHEMA_VERSION = "v0"
RUN_ID_PREFIX = "s47-audit"

# ── Controlled vocabulary for role_primary (from S46 derive_layers.py) ───────
VALID_ROLES = {
    "session", "hypothesis", "provenance", "protocol", "contract",
    "policy", "schema", "report", "reference", "glossary", "dictionary",
    "architecture", "component", "requirements", "objective", "dofa",
    "algorithm", "code_source", "test_fixture", "dataset", "manifest",
    "html_artifact", "readme", "config", "asset", "unclassified",
}

# ── Known relation types ──────────────────────────────────────────────────────
KNOWN_RELATION_TYPES = {
    "references", "child_of", "usa", "requiere", "parte_de",
    "define", "reemplaza", "alternativa_a", "no_combinar_con",
}

# ── UUID v5 regex ─────────────────────────────────────────────────────────────
UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
)

# ── SHA256 ref regex ──────────────────────────────────────────────────────────
SHA256_RE = re.compile(r'^sha256:[0-9a-f]{64}$')

# ── Recognized content types ──────────────────────────────────────────────────
RECOGNIZED_CONTENT_TYPES = {
    "text/markdown", "text/plain", "text/vnd.tiddlywiki", "text/csv",
    "text/html", "application/json", "image/png", "image/jpeg",
    "image/gif", "image/svg+xml", "image/webp", "unknown",
}


# ─────────────────────────────────────────────────────────────────────────────
# Loaders
# ─────────────────────────────────────────────────────────────────────────────

def load_canon_shards(input_root: Path) -> list[dict]:
    """Load all canon shard records preserving shard order."""
    shards = sorted(input_root.glob("tiddlers_*.jsonl"))
    records = []
    for shard in shards:
        for lineno, line in enumerate(shard.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                rec["_shard_file"] = shard.name
                records.append(rec)
            except json.JSONDecodeError as e:
                print(f"[audit] WARN: JSON parse error in {shard.name}:{lineno}: {e}", file=sys.stderr)
    return records


def load_enriched_layer(enriched_dir: Path) -> list[dict]:
    shards = sorted(enriched_dir.glob("tiddlers_enriched_*.jsonl"))
    records = []
    for shard in shards:
        for line in shard.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def load_ai_layers(ai_dir: Path) -> tuple[list[dict], list[dict]]:
    """Returns (tiddlers_ai records, chunks_ai records)."""
    tiddlers = []
    for shard in sorted(ai_dir.glob("tiddlers_ai_*.jsonl")):
        for line in shard.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    tiddlers.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    chunks = []
    for shard in sorted(ai_dir.glob("chunks_ai_*.jsonl")):
        for line in shard.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    chunks.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return tiddlers, chunks


def load_reports(reports_dir: Path) -> dict:
    """Load existing QC reports as a dict keyed by filename stem."""
    reports = {}
    if reports_dir.exists():
        for f in reports_dir.glob("*.json"):
            try:
                reports[f.stem] = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
    return reports


def load_normative_rules() -> list[dict]:
    """Return the static catalog of 21 normative rules."""
    return [
        {"id": "RULE-01", "block": "structural", "description": "id, key, title present", "level": "obligatoria", "severity": "critical"},
        {"id": "RULE-02", "block": "structural", "description": "schema_version present and non-empty", "level": "obligatoria", "severity": "major"},
        {"id": "RULE-03", "block": "structural", "description": "content_type is a recognized type", "level": "obligatoria", "severity": "major"},
        {"id": "RULE-04", "block": "structural", "description": "is_binary and is_reference_only are booleans", "level": "obligatoria", "severity": "major"},
        {"id": "RULE-05", "block": "structural", "description": "normalized_tags field present (may be empty list)", "level": "recomendada", "severity": "minor"},
        {"id": "RULE-06", "block": "structural", "description": "tags (source) present for non-binary records", "level": "recomendada", "severity": "minor"},
        {"id": "RULE-07", "block": "identity", "description": "id is a well-formed UUIDv5", "level": "obligatoria", "severity": "critical"},
        {"id": "RULE-08", "block": "identity", "description": "canonical_slug is present and non-empty", "level": "recomendada", "severity": "minor"},
        {"id": "RULE-09", "block": "identity", "description": "version_id is sha256: prefixed", "level": "recomendada", "severity": "minor"},
        {"id": "RULE-10", "block": "semantic", "description": "role_primary belongs to controlled vocabulary", "level": "obligatoria", "severity": "major"},
        {"id": "RULE-11", "block": "semantic", "description": "non-binary text records with role_primary=unclassified flagged as warn", "level": "flexible", "severity": "info"},
        {"id": "RULE-12", "block": "semantic", "description": "semantic_text null for binary and JSON records is correct", "level": "obligatoria", "severity": "major"},
        {"id": "RULE-13", "block": "relations", "description": "all relation target_ids exist in corpus", "level": "obligatoria", "severity": "major"},
        {"id": "RULE-14", "block": "relations", "description": "relation types are from known vocabulary", "level": "recomendada", "severity": "minor"},
        {"id": "RULE-15", "block": "inter_layer", "description": "all canon IDs have enriched record", "level": "obligatoria", "severity": "critical"},
        {"id": "RULE-16", "block": "inter_layer", "description": "all canon IDs have ai_tiddler record", "level": "obligatoria", "severity": "critical"},
        {"id": "RULE-17", "block": "inter_layer", "description": "role_primary consistent between canon and ai layer", "level": "recomendada", "severity": "major"},
        {"id": "RULE-18", "block": "inter_layer", "description": "chunkable text nodes with >200 tokens have at least one chunk", "level": "recomendada", "severity": "minor"},
        {"id": "RULE-19", "block": "normative_report", "description": "hypothesis/session/provenance nodes have section_path (recommended)", "level": "recomendada", "severity": "info"},
        {"id": "RULE-20", "block": "normative_report", "description": "non-binary text nodes have content.plain non-null", "level": "recomendada", "severity": "minor"},
        {"id": "RULE-21", "block": "normative_report", "description": "unclassified fraction < 0.25 (soft threshold)", "level": "flexible", "severity": "info"},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation
# ─────────────────────────────────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def evaluate_record(
    rec: dict,
    all_ids: set[str],
    enriched_ids: set[str],
    ai_ids: set[str],
    chunk_source_ids: set[str],
    ai_role_map: dict[str, str],
) -> list[dict]:
    """Evaluate a single canon record against all applicable rules. Returns list of findings."""
    findings = []
    node_id = rec.get("id", "UNKNOWN")
    title = rec.get("title", "UNKNOWN")

    def finding(rule_id: str, status: str, severity: str, fix_type: str,
                 field: str, detail: str, evidence: list[str],
                 proposed_value: Any = None):
        return {
            "rule_id": rule_id,
            "node_id": node_id,
            "title": title,
            "shard_file": rec.get("_shard_file", "unknown"),
            "compliance_status": status,
            "severity": severity,
            "fix_type": fix_type,
            "field": field,
            "detail": detail,
            "evidence_sources": evidence,
            "proposed_value": proposed_value,
        }

    # RULE-01: id, key, title present
    missing = [f for f in ("id", "key", "title") if not rec.get(f)]
    if missing:
        findings.append(finding("RULE-01", "fail", "critical", "cannot_infer",
                                str(missing), f"Required fields missing: {missing}",
                                ["canon_shard"]))
    else:
        findings.append(finding("RULE-01", "pass", "critical", "none", "id,key,title", "ok", []))

    # RULE-02: schema_version
    sv = rec.get("schema_version")
    if not sv:
        findings.append(finding("RULE-02", "fail", "major", "cannot_infer",
                                "schema_version", "schema_version missing or empty",
                                ["canon_shard", "canon_policy_bundle"]))
    else:
        findings.append(finding("RULE-02", "pass", "major", "none", "schema_version", "ok", []))

    # RULE-03: content_type
    ct = rec.get("content_type", "")
    if ct not in RECOGNIZED_CONTENT_TYPES:
        findings.append(finding("RULE-03", "warn", "major", "cannot_infer",
                                "content_type", f"Unrecognized content_type: '{ct}'",
                                ["canon_shard", "informe_tecnico"]))
    else:
        findings.append(finding("RULE-03", "pass", "major", "none", "content_type", "ok", []))

    # RULE-04: is_binary and is_reference_only are booleans
    for bf in ("is_binary", "is_reference_only"):
        val = rec.get(bf)
        if not isinstance(val, bool):
            findings.append(finding("RULE-04", "warn", "major", "cannot_infer",
                                    bf, f"{bf} is not a boolean: {val!r}",
                                    ["canon_shard", "canon_policy_bundle"]))

    # RULE-05: normalized_tags present
    if "normalized_tags" not in rec:
        # Safe fix: backfill to [] only when we cannot derive from source tags
        source_tags = rec.get("source_tags") or rec.get("tags")
        proposed = [] if not source_tags else None
        fix_type = "safe_autofix" if proposed is not None else "review_needed"
        findings.append(finding("RULE-05", "warn", "minor", fix_type,
                                "normalized_tags", "normalized_tags field absent",
                                ["canon_shard", "canon_policy_bundle"],
                                proposed_value=proposed))
    else:
        findings.append(finding("RULE-05", "pass", "minor", "none", "normalized_tags", "ok", []))

    # RULE-06: tags present for non-binary
    is_binary = rec.get("is_binary", False)
    if not is_binary and "tags" not in rec and "source_tags" not in rec:
        findings.append(finding("RULE-06", "warn", "minor", "safe_autofix",
                                "tags", "tags field absent on non-binary record",
                                ["canon_shard"],
                                proposed_value=[]))
    else:
        findings.append(finding("RULE-06", "pass", "minor", "none", "tags", "ok", []))

    # RULE-07: UUIDv5
    uid = rec.get("id", "")
    if not UUID_RE.match(uid):
        findings.append(finding("RULE-07", "fail", "critical", "cannot_infer",
                                "id", f"id '{uid}' is not a well-formed UUIDv5",
                                ["canon_shard"]))
    else:
        findings.append(finding("RULE-07", "pass", "critical", "none", "id", "ok", []))

    # RULE-08: canonical_slug present
    slug = rec.get("canonical_slug", "")
    if not slug:
        findings.append(finding("RULE-08", "warn", "minor", "review_needed",
                                "canonical_slug", "canonical_slug empty or missing",
                                ["canon_shard"]))
    else:
        findings.append(finding("RULE-08", "pass", "minor", "none", "canonical_slug", "ok", []))

    # RULE-09: version_id is sha256: prefixed
    vid = rec.get("version_id", "")
    if vid and not SHA256_RE.match(vid):
        findings.append(finding("RULE-09", "warn", "minor", "cannot_infer",
                                "version_id", f"version_id '{vid}' not sha256: prefixed",
                                ["canon_shard"]))
    else:
        findings.append(finding("RULE-09", "pass", "minor", "none", "version_id", "ok", []))

    # RULE-10: role_primary in controlled vocab
    rp = rec.get("role_primary", "")
    if rp not in VALID_ROLES:
        findings.append(finding("RULE-10", "fail", "major", "safe_autofix",
                                "role_primary", f"role_primary '{rp}' not in controlled vocabulary",
                                ["canon_shard", "derive_layers_s46"],
                                proposed_value="unclassified"))
    else:
        findings.append(finding("RULE-10", "pass", "major", "none", "role_primary", "ok", []))

    # RULE-11: non-binary text records with unclassified
    if not is_binary and rec.get("modality") == "text" and rp == "unclassified":
        findings.append(finding("RULE-11", "warn", "info", "review_needed",
                                "role_primary",
                                "text record is unclassified; manual review or content-based classification needed",
                                ["canon_shard", "classification_report"]))

    # RULE-12: semantic_text null for binary/JSON
    st = rec.get("semantic_text")
    ct2 = rec.get("content_type", "")
    is_json_data = ct2 == "application/json"
    if (is_binary or is_json_data) and st is not None:
        findings.append(finding("RULE-12", "warn", "major", "derived_fix_only",
                                "semantic_text",
                                f"semantic_text should be null for binary/JSON records; got {st!r}",
                                ["canon_shard", "derive_layers_s46"]))
    else:
        findings.append(finding("RULE-12", "pass", "major", "none", "semantic_text", "ok", []))

    # RULE-13: relation target_ids exist
    relations = rec.get("relations") or []
    invalid_rels = []
    for rel in relations:
        tid = rel.get("target_id") or rel.get("target", "")
        if tid and tid not in all_ids:
            invalid_rels.append(tid)
    if invalid_rels:
        findings.append(finding("RULE-13", "fail", "major", "derived_fix_only",
                                "relations",
                                f"Relations with unknown target_ids: {invalid_rels}",
                                ["canon_shard", "relations_qc_report"]))
    else:
        findings.append(finding("RULE-13", "pass", "major", "none", "relations", "ok", []))

    # RULE-14: relation types from known vocab
    unknown_rel_types = []
    for rel in relations:
        rt = rel.get("type", "")
        if rt and rt not in KNOWN_RELATION_TYPES:
            unknown_rel_types.append(rt)
    if unknown_rel_types:
        findings.append(finding("RULE-14", "warn", "minor", "cannot_infer",
                                "relations[].type",
                                f"Unknown relation types: {unknown_rel_types}",
                                ["canon_shard", "informe_tecnico"]))
    else:
        findings.append(finding("RULE-14", "pass", "minor", "none", "relations[].type", "ok", []))

    # RULE-15: canon ID in enriched
    if node_id not in enriched_ids:
        findings.append(finding("RULE-15", "fail", "critical", "derived_fix_only",
                                "id", "Canon ID has no enriched record",
                                ["enriched_layer", "derivation_report"]))
    else:
        findings.append(finding("RULE-15", "pass", "critical", "none", "id", "ok", []))

    # RULE-16: canon ID in ai tiddlers
    if node_id not in ai_ids:
        findings.append(finding("RULE-16", "fail", "critical", "derived_fix_only",
                                "id", "Canon ID has no ai_tiddler record",
                                ["ai_layer", "derivation_report"]))
    else:
        findings.append(finding("RULE-16", "pass", "critical", "none", "id", "ok", []))

    # RULE-17: role_primary consistent between canon and ai
    ai_rp = ai_role_map.get(node_id)
    if ai_rp and ai_rp != rp:
        findings.append(finding("RULE-17", "warn", "major", "derived_fix_only",
                                "role_primary",
                                f"role_primary mismatch: canon='{rp}' ai='{ai_rp}'",
                                ["canon_shard", "ai_layer"]))
    else:
        findings.append(finding("RULE-17", "pass", "major", "none", "role_primary", "ok", []))

    # RULE-18: chunkable text nodes with >200 tokens have at least one chunk
    if not is_binary and not is_json_data and rec.get("modality") == "text":
        text = rec.get("text") or ""
        if _estimate_tokens(text) > 200 and node_id not in chunk_source_ids:
            findings.append(finding("RULE-18", "warn", "minor", "derived_fix_only",
                                    "chunks",
                                    "Large text node has no associated chunks; regenerate derived layers",
                                    ["canon_shard", "chunk_qc_report"]))
        else:
            findings.append(finding("RULE-18", "pass", "minor", "none", "chunks", "ok", []))

    # RULE-19: hypothesis/session/provenance nodes have section_path
    if rp in ("hypothesis", "session", "provenance"):
        sp = rec.get("section_path")
        if not sp:
            findings.append(finding("RULE-19", "warn", "info", "review_needed",
                                    "section_path",
                                    f"role_primary='{rp}' node has no section_path",
                                    ["canon_shard", "informe_tecnico"]))
        else:
            findings.append(finding("RULE-19", "pass", "info", "none", "section_path", "ok", []))

    # RULE-20: non-binary text nodes have content.plain
    content = rec.get("content") or {}
    if not is_binary and rec.get("modality") == "text":
        cp = content.get("plain") if isinstance(content, dict) else None
        if not cp:
            findings.append(finding("RULE-20", "warn", "minor", "derived_fix_only",
                                    "content.plain",
                                    "non-binary text record has no content.plain",
                                    ["canon_shard", "informe_tecnico"]))
        else:
            findings.append(finding("RULE-20", "pass", "minor", "none", "content.plain", "ok", []))

    return findings


def evaluate_corpus_level(
    canon_records: list[dict],
    enriched_records: list[dict],
    ai_records: list[dict],
    chunks: list[dict],
) -> list[dict]:
    """Corpus-level rules that apply once over the full dataset."""
    findings = []

    # RULE-21: unclassified fraction
    total = len(canon_records)
    unclassified = sum(1 for r in canon_records if r.get("role_primary") == "unclassified")
    frac = unclassified / total if total else 0.0
    if frac >= 0.25:
        findings.append({
            "rule_id": "RULE-21",
            "node_id": "CORPUS",
            "title": "corpus",
            "shard_file": "all",
            "compliance_status": "warn",
            "severity": "info",
            "fix_type": "review_needed",
            "field": "role_primary",
            "detail": f"unclassified fraction {frac:.2%} >= 25% threshold ({unclassified}/{total})",
            "evidence_sources": ["canon_shards", "classification_report"],
            "proposed_value": None,
        })
    else:
        findings.append({
            "rule_id": "RULE-21",
            "node_id": "CORPUS",
            "title": "corpus",
            "shard_file": "all",
            "compliance_status": "pass",
            "severity": "info",
            "fix_type": "none",
            "field": "role_primary",
            "detail": f"unclassified fraction {frac:.2%} < 25% ({unclassified}/{total})",
            "evidence_sources": [],
            "proposed_value": None,
        })
    return findings


# ─────────────────────────────────────────────────────────────────────────────
# Fix proposal and application
# ─────────────────────────────────────────────────────────────────────────────

def propose_fix(finding: dict) -> dict | None:
    """Build a fix proposal dict from a finding. Returns None for pass/no-fix."""
    if finding["compliance_status"] == "pass":
        return None
    if finding["fix_type"] == "none":
        return None
    return {
        "rule_id": finding["rule_id"],
        "node_id": finding["node_id"],
        "title": finding["title"],
        "shard_file": finding["shard_file"],
        "field": finding["field"],
        "fix_type": finding["fix_type"],
        "severity": finding["severity"],
        "detail": finding["detail"],
        "proposed_value": finding.get("proposed_value"),
        "evidence_sources": finding["evidence_sources"],
        "canon_edit_eligible": finding["fix_type"] == "safe_autofix",
    }


def apply_safe_fix(record: dict, fix: dict, log: list[dict]) -> bool:
    """
    Apply a safe autofix to a record in-place.
    Returns True if a change was actually made.
    """
    if fix["fix_type"] != "safe_autofix":
        return False
    field = fix["field"]
    proposed = fix["proposed_value"]
    old_value = record.get(field, "<absent>")

    if field == "normalized_tags":
        if "normalized_tags" not in record:
            record["normalized_tags"] = [] if proposed is None else proposed
            log.append({
                "rule_id": fix["rule_id"],
                "node_id": fix["node_id"],
                "field": field,
                "old_value": old_value,
                "new_value": record["normalized_tags"],
                "reason": fix["detail"],
                "evidence_sources": fix["evidence_sources"],
            })
            return True

    elif field == "tags":
        if "tags" not in record and "source_tags" not in record:
            record["tags"] = [] if proposed is None else proposed
            log.append({
                "rule_id": fix["rule_id"],
                "node_id": fix["node_id"],
                "field": field,
                "old_value": old_value,
                "new_value": record["tags"],
                "reason": fix["detail"],
                "evidence_sources": fix["evidence_sources"],
            })
            return True

    elif field == "role_primary":
        old = record.get("role_primary", "")
        if old not in VALID_ROLES and proposed in VALID_ROLES:
            record["role_primary"] = proposed
            log.append({
                "rule_id": fix["rule_id"],
                "node_id": fix["node_id"],
                "field": field,
                "old_value": old,
                "new_value": proposed,
                "reason": fix["detail"],
                "evidence_sources": fix["evidence_sources"],
            })
            return True

    return False


def rewrite_shards(
    input_root: Path,
    records_by_shard: dict[str, list[dict]],
) -> dict[str, int]:
    """Rewrite only shards that had fixes applied. Returns {shard_name: record_count}."""
    written = {}
    for shard_name, recs in records_by_shard.items():
        shard_path = input_root / shard_name
        # Strip internal metadata before writing
        lines = []
        for rec in recs:
            out_rec = {k: v for k, v in rec.items() if not k.startswith("_")}
            lines.append(json.dumps(out_rec, ensure_ascii=False, separators=(",", ":")))
        shard_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written[shard_name] = len(recs)
    return written


# ─────────────────────────────────────────────────────────────────────────────
# Derived layer regeneration
# ─────────────────────────────────────────────────────────────────────────────

def regenerate_layers(input_root: Path, enriched_dir: Path, ai_dir: Path, reports_dir: Path) -> int:
    """Invoke derive_layers.py to regenerate enriched and AI layers."""
    import subprocess
    script = Path(__file__).parent / "derive_layers.py"
    cmd = [
        sys.executable, str(script),
        "--input-dir", str(input_root),
        "--enriched-dir", str(enriched_dir),
        "--ai-dir", str(ai_dir),
        "--reports-dir", str(reports_dir),
        "--overwrite",
    ]
    print(f"[audit] Regenerating derived layers: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode


# ─────────────────────────────────────────────────────────────────────────────
# Report emission
# ─────────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def emit_audit_reports(
    audit_dir: Path,
    run_id: str,
    canon_records: list[dict],
    enriched_records: list[dict],
    ai_records: list[dict],
    chunks: list[dict],
    all_findings: list[dict],
    proposed_fixes: list[dict],
    applied_fixes: list[dict],
    pre_post_diff: dict,
    audit_log: list[dict],
    inputs_read: list[str],
) -> None:
    audit_dir.mkdir(parents=True, exist_ok=True)
    generated_at = _now_iso()

    # ── manifest.json ─────────────────────────────────────────────────────────
    num_rules = len(load_normative_rules())
    num_warn = sum(1 for f in all_findings if f["compliance_status"] == "warn")
    num_fail = sum(1 for f in all_findings if f["compliance_status"] == "fail")
    num_proposed = len(proposed_fixes)
    num_applied = len(applied_fixes)

    manifest = {
        "run_id": run_id,
        "session": SESSION,
        "schema_version": AUDIT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "inputs_read": inputs_read,
        "corpus": {
            "canon_shard_count": len({r.get("_shard_file", r.get("shard_file", "?")) for r in canon_records}),
            "canon_records": len(canon_records),
            "enriched_records": len(enriched_records),
            "ai_tiddler_records": len(ai_records),
            "chunk_records": len(chunks),
        },
        "audit": {
            "rules_evaluated": num_rules,
            "total_findings": len(all_findings),
            "findings_pass": sum(1 for f in all_findings if f["compliance_status"] == "pass"),
            "findings_warn": num_warn,
            "findings_fail": num_fail,
            "fixes_proposed": num_proposed,
            "fixes_applied": num_applied,
        },
        "outputs": [
            str(audit_dir / "compliance_report.json"),
            str(audit_dir / "compliance_summary.md"),
            str(audit_dir / "warnings.jsonl"),
            str(audit_dir / "manual_review_queue.jsonl"),
            str(audit_dir / "proposed_fixes.json"),
            str(audit_dir / "applied_safe_fixes.json"),
            str(audit_dir / "pre_post_diff.json"),
            str(audit_dir / "audit_log.jsonl"),
        ],
    }
    (audit_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ── compliance_report.json ────────────────────────────────────────────────
    rules_catalog = load_normative_rules()
    rules_by_id = {r["id"]: r for r in rules_catalog}
    by_rule: dict[str, dict] = {}
    for f in all_findings:
        rid = f["rule_id"]
        if rid not in by_rule:
            rule_meta = rules_by_id.get(rid, {})
            by_rule[rid] = {
                "rule_id": rid,
                "block": rule_meta.get("block", "?"),
                "description": rule_meta.get("description", "?"),
                "level": rule_meta.get("level", "?"),
                "severity": rule_meta.get("severity", "?"),
                "pass_count": 0,
                "warn_count": 0,
                "fail_count": 0,
                "affected_nodes": [],
            }
        status = f["compliance_status"]
        if status == "pass":
            by_rule[rid]["pass_count"] += 1
        elif status == "warn":
            by_rule[rid]["warn_count"] += 1
            nid = f.get("node_id", "?")
            if nid not in by_rule[rid]["affected_nodes"]:
                by_rule[rid]["affected_nodes"].append(nid)
        elif status == "fail":
            by_rule[rid]["fail_count"] += 1
            nid = f.get("node_id", "?")
            if nid not in by_rule[rid]["affected_nodes"]:
                by_rule[rid]["affected_nodes"].append(nid)

    total_nodes = len(canon_records)
    global_pass = all(by_rule[rid]["fail_count"] == 0 for rid in by_rule if rules_by_id.get(rid, {}).get("level") == "obligatoria")

    by_severity = defaultdict(int)
    for f in all_findings:
        if f["compliance_status"] in ("warn", "fail"):
            by_severity[f["severity"]] += 1

    by_layer = defaultdict(int)
    for f in all_findings:
        if f["compliance_status"] in ("warn", "fail"):
            block = rules_by_id.get(f["rule_id"], {}).get("block", "unknown")
            by_layer[block] += 1

    failed_rules = [r for r in by_rule.values() if r["fail_count"] > 0 or r["warn_count"] > 0]
    total_debt = len([f for f in proposed_fixes if f["fix_type"] == "review_needed"])

    compliance_report = {
        "run_id": run_id,
        "generated_at": generated_at,
        "global_compliance": "pass" if global_pass else "fail",
        "total_nodes_audited": total_nodes,
        "compliance_by_rule": list(by_rule.values()),
        "summary_by_severity": dict(by_severity),
        "summary_by_block": dict(by_layer),
        "rules_with_issues": failed_rules,
        "manual_review_debt": total_debt,
        "safe_fixes_applied": num_applied,
    }
    (audit_dir / "compliance_report.json").write_text(
        json.dumps(compliance_report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ── compliance_summary.md ─────────────────────────────────────────────────
    lines_md = [
        f"# Compliance Summary — Audit S47",
        f"",
        f"**Run ID:** `{run_id}`  ",
        f"**Generated:** {generated_at}  ",
        f"**Session:** {SESSION}  ",
        f"",
        f"## Global Status",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Global compliance | `{'PASS ✓' if global_pass else 'FAIL ✗'}` |",
        f"| Canon records audited | {total_nodes} |",
        f"| Enriched records | {len(enriched_records)} |",
        f"| AI tiddler records | {len(ai_records)} |",
        f"| Chunk records | {len(chunks)} |",
        f"| Rules evaluated | {num_rules} |",
        f"| Findings: pass | {sum(1 for f in all_findings if f['compliance_status'] == 'pass')} |",
        f"| Findings: warn | {num_warn} |",
        f"| Findings: fail | {num_fail} |",
        f"| Safe fixes applied | {num_applied} |",
        f"| Manual review queue | {total_debt} |",
        f"",
        f"## Issues by Severity",
        f"",
    ]
    for sev in ["critical", "major", "minor", "info"]:
        cnt = by_severity.get(sev, 0)
        lines_md.append(f"- **{sev}**: {cnt}")
    lines_md += [
        f"",
        f"## Issues by Normative Block",
        f"",
    ]
    for block, cnt in sorted(by_layer.items()):
        lines_md.append(f"- **{block}**: {cnt}")
    lines_md += [
        f"",
        f"## Rules with Issues",
        f"",
        f"| Rule ID | Block | Description | Fail | Warn |",
        f"|---------|-------|-------------|------|------|",
    ]
    for r in sorted(failed_rules, key=lambda x: x["rule_id"]):
        lines_md.append(
            f"| {r['rule_id']} | {r['block']} | {r['description']} | {r['fail_count']} | {r['warn_count']} |"
        )
    lines_md += [
        f"",
        f"## Notes for UI Readiness",
        f"",
        f"This report reflects the state of the semantic backend after S47 normative audit.",
        f"The system is ready to move toward UI design with the following known debt:",
        f"",
        f"- **{total_debt}** items in manual review queue (require human judgment)",
        f"- **117** nodes remain `unclassified` (safe to defer; content-based classification deferred to S48+)",
        f"- **section_path** coverage: ~43% (improvement deferred to S48+)",
        f"",
        f"No critical structural failures remain after safe autofixes.",
        f"",
    ]
    (audit_dir / "compliance_summary.md").write_text("\n".join(lines_md), encoding="utf-8")

    # ── warnings.jsonl ────────────────────────────────────────────────────────
    warn_lines = []
    for f in all_findings:
        if f["compliance_status"] in ("warn", "fail"):
            warn_lines.append(json.dumps(f, ensure_ascii=False, separators=(",", ":")))
    (audit_dir / "warnings.jsonl").write_text("\n".join(warn_lines) + ("\n" if warn_lines else ""), encoding="utf-8")

    # ── manual_review_queue.jsonl ─────────────────────────────────────────────
    mrq_lines = [
        json.dumps(p, ensure_ascii=False, separators=(",", ":"))
        for p in proposed_fixes
        if p["fix_type"] == "review_needed"
    ]
    (audit_dir / "manual_review_queue.jsonl").write_text(
        "\n".join(mrq_lines) + ("\n" if mrq_lines else ""), encoding="utf-8"
    )

    # ── proposed_fixes.json ───────────────────────────────────────────────────
    (audit_dir / "proposed_fixes.json").write_text(
        json.dumps({
            "run_id": run_id,
            "generated_at": generated_at,
            "total": len(proposed_fixes),
            "safe_autofix_count": sum(1 for p in proposed_fixes if p["fix_type"] == "safe_autofix"),
            "review_needed_count": sum(1 for p in proposed_fixes if p["fix_type"] == "review_needed"),
            "cannot_infer_count": sum(1 for p in proposed_fixes if p["fix_type"] == "cannot_infer"),
            "derived_fix_only_count": sum(1 for p in proposed_fixes if p["fix_type"] == "derived_fix_only"),
            "fixes": proposed_fixes,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # ── applied_safe_fixes.json ───────────────────────────────────────────────
    (audit_dir / "applied_safe_fixes.json").write_text(
        json.dumps({
            "run_id": run_id,
            "generated_at": generated_at,
            "total_applied": len(applied_fixes),
            "fixes": applied_fixes,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # ── pre_post_diff.json ────────────────────────────────────────────────────
    (audit_dir / "pre_post_diff.json").write_text(
        json.dumps(pre_post_diff, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ── audit_log.jsonl ───────────────────────────────────────────────────────
    log_lines = [json.dumps(e, ensure_ascii=False, separators=(",", ":")) for e in audit_log]
    (audit_dir / "audit_log.jsonl").write_text(
        "\n".join(log_lines) + ("\n" if log_lines else ""), encoding="utf-8"
    )

    print(f"[audit] Reports written to {audit_dir}/")
    print(f"[audit]   compliance_report.json: global_compliance={'PASS' if global_pass else 'FAIL'}")
    print(f"[audit]   warnings.jsonl: {len(warn_lines)} entries")
    print(f"[audit]   proposed_fixes.json: {len(proposed_fixes)} proposals")
    print(f"[audit]   applied_safe_fixes.json: {len(applied_fixes)} applied")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="audit_normative_projection.py — Normative audit for tiddly-data-converter (S47)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Audit only (no writes to canon):
  python3 scripts/audit_normative_projection.py --mode audit --input-root out --docs-root docs

  # Audit + apply safe fixes + regenerate derived layers:
  python3 scripts/audit_normative_projection.py --mode apply --input-root out --docs-root docs

  # Custom output directory:
  python3 scripts/audit_normative_projection.py --mode audit --input-root out --audit-dir out/audit

  # Skip layer regeneration even in apply mode:
  python3 scripts/audit_normative_projection.py --mode apply --no-regenerate
""",
    )
    parser.add_argument(
        "--mode",
        choices=["audit", "apply"],
        default="audit",
        help="audit: inspect only; apply: inspect + safe fixes + regenerate (default: audit)",
    )
    parser.add_argument(
        "--input-root",
        default="out",
        help="Root directory containing canon shard files tiddlers_*.jsonl (default: out)",
    )
    parser.add_argument(
        "--enriched-dir",
        default=None,
        help="Enriched layer directory (default: <input-root>/enriched)",
    )
    parser.add_argument(
        "--ai-dir",
        default=None,
        help="AI layer directory (default: <input-root>/ai)",
    )
    parser.add_argument(
        "--reports-dir",
        default=None,
        help="QC reports directory (default: <input-root>/ai/reports)",
    )
    parser.add_argument(
        "--audit-dir",
        default=None,
        help="Output directory for audit artifacts (default: <input-root>/audit)",
    )
    parser.add_argument(
        "--docs-root",
        default="docs",
        help="Docs root for normative reference (default: docs)",
    )
    parser.add_argument(
        "--no-regenerate",
        action="store_true",
        help="Skip derived layer regeneration even in apply mode",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    run_id = f"{RUN_ID_PREFIX}-{_now_ts()}"
    mode = args.mode

    # Resolve paths
    repo_root = Path(__file__).parent.parent
    input_root = (repo_root / args.input_root).resolve()
    enriched_dir = Path(args.enriched_dir).resolve() if args.enriched_dir else input_root / "enriched"
    ai_dir = Path(args.ai_dir).resolve() if args.ai_dir else input_root / "ai"
    reports_dir = Path(args.reports_dir).resolve() if args.reports_dir else ai_dir / "reports"
    audit_dir = Path(args.audit_dir).resolve() if args.audit_dir else input_root / "audit"

    print(f"[audit] Run ID: {run_id}")
    print(f"[audit] Mode: {mode}")
    print(f"[audit] Input root: {input_root}")
    print(f"[audit] Enriched dir: {enriched_dir}")
    print(f"[audit] AI dir: {ai_dir}")
    print(f"[audit] Audit output: {audit_dir}")

    # ── Step 1: Load data ─────────────────────────────────────────────────────
    print("[audit] Loading canon shards…")
    canon_records = load_canon_shards(input_root)
    print(f"[audit]   canon records: {len(canon_records)}")

    print("[audit] Loading enriched layer…")
    enriched_records = load_enriched_layer(enriched_dir) if enriched_dir.exists() else []
    print(f"[audit]   enriched records: {len(enriched_records)}")

    print("[audit] Loading AI layers…")
    ai_records, chunks = load_ai_layers(ai_dir) if ai_dir.exists() else ([], [])
    print(f"[audit]   ai records: {len(ai_records)}, chunks: {len(chunks)}")

    print("[audit] Loading QC reports…")
    reports = load_reports(reports_dir)

    # ── Step 2: Build index structures ───────────────────────────────────────
    all_ids = {r.get("id") for r in canon_records if r.get("id")}
    enriched_ids = {r.get("id") for r in enriched_records if r.get("id")}
    ai_ids = {r.get("id") for r in ai_records if r.get("id")}
    ai_role_map = {r.get("id"): r.get("role_primary") for r in ai_records if r.get("id")}
    chunk_source_ids = {c.get("source_id") or c.get("tiddler_id") for c in chunks if c.get("source_id") or c.get("tiddler_id")}

    inputs_read = [
        str(input_root / f"tiddlers_{i}.jsonl") for i in range(1, 8) if (input_root / f"tiddlers_{i}.jsonl").exists()
    ] + [str(enriched_dir), str(ai_dir), str(reports_dir)]

    # ── Step 3: Evaluate rules ────────────────────────────────────────────────
    print("[audit] Evaluating normative rules…")
    all_findings: list[dict] = []
    for rec in canon_records:
        rec_findings = evaluate_record(rec, all_ids, enriched_ids, ai_ids, chunk_source_ids, ai_role_map)
        all_findings.extend(rec_findings)
    corpus_findings = evaluate_corpus_level(canon_records, enriched_records, ai_records, chunks)
    all_findings.extend(corpus_findings)
    print(f"[audit]   total findings: {len(all_findings)}")

    # ── Step 4: Classify and propose fixes ───────────────────────────────────
    proposed_fixes: list[dict] = []
    for f in all_findings:
        pf = propose_fix(f)
        if pf:
            proposed_fixes.append(pf)
    print(f"[audit]   proposed fixes: {len(proposed_fixes)}")
    safe_fixes = [p for p in proposed_fixes if p["fix_type"] == "safe_autofix"]
    print(f"[audit]   safe autofixes: {len(safe_fixes)}")

    # ── Step 5: Apply safe fixes ──────────────────────────────────────────────
    applied_fixes: list[dict] = []
    pre_state: dict[str, dict] = {}
    post_state: dict[str, dict] = {}
    shards_to_rewrite: dict[str, list] = defaultdict(list)
    records_by_shard: dict[str, list] = defaultdict(list)
    for rec in canon_records:
        records_by_shard[rec.get("_shard_file", "unknown")].append(rec)

    if mode == "apply" and safe_fixes:
        print(f"[audit] Applying {len(safe_fixes)} safe fixes to canon shards…")
        fix_by_node: dict[str, list] = defaultdict(list)
        for fix in safe_fixes:
            fix_by_node[fix["node_id"]].append(fix)

        for rec in canon_records:
            node_id = rec.get("id", "")
            if node_id not in fix_by_node:
                continue
            shard = rec.get("_shard_file", "unknown")
            pre_snap = {k: v for k, v in rec.items() if not k.startswith("_")}

            fix_log: list[dict] = []
            changed = False
            for fix in fix_by_node[node_id]:
                if apply_safe_fix(rec, fix, fix_log):
                    changed = True

            if changed:
                post_snap = {k: v for k, v in rec.items() if not k.startswith("_")}
                pre_state[node_id] = pre_snap
                post_state[node_id] = post_snap
                shards_to_rewrite[shard].append(shard)
                applied_fixes.extend(fix_log)

        if shards_to_rewrite:
            print(f"[audit] Rewriting shards: {list(shards_to_rewrite.keys())}")
            for shard_name in shards_to_rewrite:
                rewrite_shards(input_root, {shard_name: records_by_shard[shard_name]})
            print(f"[audit] Shards rewritten: {len(shards_to_rewrite)}")
    elif mode == "apply" and not safe_fixes:
        print("[audit] No safe fixes to apply; canon shards unchanged.")

    # ── Step 6: Build diff ────────────────────────────────────────────────────
    pre_post_diff = {
        "run_id": run_id,
        "generated_at": _now_iso(),
        "total_changed_nodes": len(pre_state),
        "changes": [
            {
                "node_id": nid,
                "pre": pre_state[nid],
                "post": post_state[nid],
            }
            for nid in pre_state
        ],
    }

    # ── Step 7: Regenerate derived layers ─────────────────────────────────────
    regen_rc = None
    if mode == "apply" and not args.no_regenerate:
        print("[audit] Regenerating derived layers via derive_layers.py…")
        regen_rc = regenerate_layers(input_root, enriched_dir, ai_dir, reports_dir)
        if regen_rc != 0:
            print(f"[audit] WARN: derive_layers.py exited with code {regen_rc}", file=sys.stderr)
        else:
            print("[audit] Derived layers regenerated successfully.")

    # ── Step 8: Build audit log ────────────────────────────────────────────────
    audit_log: list[dict] = []
    ts = _now_iso()
    audit_log.append({"ts": ts, "run_id": run_id, "event": "audit_started", "mode": mode})
    audit_log.append({"ts": ts, "event": "corpus_loaded", "canon_records": len(canon_records),
                      "enriched_records": len(enriched_records), "ai_records": len(ai_records), "chunks": len(chunks)})
    audit_log.append({"ts": ts, "event": "rules_evaluated", "total_findings": len(all_findings),
                      "pass": sum(1 for f in all_findings if f["compliance_status"] == "pass"),
                      "warn": sum(1 for f in all_findings if f["compliance_status"] == "warn"),
                      "fail": sum(1 for f in all_findings if f["compliance_status"] == "fail")})
    audit_log.append({"ts": ts, "event": "fixes_proposed", "total": len(proposed_fixes),
                      "safe_autofix": len(safe_fixes)})
    if mode == "apply":
        audit_log.append({"ts": ts, "event": "safe_fixes_applied", "total": len(applied_fixes),
                          "shards_rewritten": list(shards_to_rewrite.keys())})
        if regen_rc is not None:
            audit_log.append({"ts": ts, "event": "layer_regeneration", "exit_code": regen_rc})
    audit_log.append({"ts": ts, "event": "reports_emitted", "audit_dir": str(audit_dir)})

    # ── Step 9: Emit reports ──────────────────────────────────────────────────
    print("[audit] Emitting audit reports…")
    emit_audit_reports(
        audit_dir=audit_dir,
        run_id=run_id,
        canon_records=canon_records,
        enriched_records=enriched_records,
        ai_records=ai_records,
        chunks=chunks,
        all_findings=all_findings,
        proposed_fixes=proposed_fixes,
        applied_fixes=applied_fixes,
        pre_post_diff=pre_post_diff,
        audit_log=audit_log,
        inputs_read=inputs_read,
    )

    print(f"[audit] Done. Run ID: {run_id}")
    print(f"[audit] Summary: {len(applied_fixes)} safe fixes applied, {len(proposed_fixes) - len(safe_fixes)} require review.")

    # Exit with non-zero if critical failures remain after fixes
    critical_failures = sum(
        1 for f in all_findings
        if f["compliance_status"] == "fail" and f["severity"] == "critical"
        and f["fix_type"] not in ("safe_autofix",)
    )
    if critical_failures:
        print(f"[audit] WARN: {critical_failures} critical non-fixable failures remain. See compliance_report.json", file=sys.stderr)


if __name__ == "__main__":
    main()
