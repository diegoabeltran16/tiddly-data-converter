#!/usr/bin/env python3
"""Read-only S0154 coverage audit grouped by explicit artifact_family."""
from __future__ import annotations
import argparse, json
from collections import Counter, defaultdict
from pathlib import Path
from layer_authority_policy import coverage_state, observed_metadata
from path_governance import DEFAULT_CANON_DIR, sorted_canon_shards


def _rows(canon_dir: Path):
    for path in sorted_canon_shards(canon_dir):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield json.loads(line)


def audit(canon_dir: Path = DEFAULT_CANON_DIR) -> dict:
    groups = defaultdict(list)
    for row in _rows(canon_dir):
        sf = row.get("source_fields") if isinstance(row.get("source_fields"), dict) else {}
        groups[str(sf.get("artifact_family") or "not_inferible")].append(row)
    families = []
    for family, rows in sorted(groups.items()):
        authority = sum(bool(observed_metadata(row)["authority"]) for row in rows)
        lifecycle = sum(bool(observed_metadata(row)["repo_lifecycle"]) for row in rows)
        source_path = sum(bool((row.get("source_fields") or {}).get("source_path")) for row in rows)
        sessions = sum(bool((row.get("source_fields") or {}).get("session_origin")) for row in rows)
        applicable_lifecycle = family == "repo_artifact" or lifecycle > 0
        families.append({"artifact_family": family, "records": len(rows),
            "authority_level": {"present": authority, "state": coverage_state(authority, len(rows))},
            "repo_lifecycle_state": {"applicable": applicable_lifecycle, "present": lifecycle,
                "state": coverage_state(lifecycle, len(rows)) if applicable_lifecycle else "not_applicable"},
            "source_path": {"present": source_path, "state": coverage_state(source_path, len(rows))},
            "session_origin": {"present": sessions, "state": coverage_state(sessions, len(rows))}})
    return {"schema": "artifact-family-coverage-audit/v1", "read_only": True,
            "canon_records": sum(item["records"] for item in families), "families": families}


def render_human(report: dict) -> str:
    lines=["familia | registros | authority | lifecycle | source_path | session_origin"]
    for row in report["families"]:
        lines.append(" | ".join((row["artifact_family"], str(row["records"]), row["authority_level"]["state"], row["repo_lifecycle_state"]["state"], row["source_path"]["state"], row["session_origin"]["state"])))
    return "\n".join(lines)


def main():
    p=argparse.ArgumentParser(description="Audit canon coverage by explicit artifact family without writes.")
    p.add_argument("--canon-dir", type=Path, default=DEFAULT_CANON_DIR); p.add_argument("--format", choices=("human","json"), default="human")
    args=p.parse_args(); report=audit(args.canon_dir)
    print(json.dumps(report,ensure_ascii=False,indent=2) if args.format=="json" else render_human(report))
if __name__ == "__main__": main()
