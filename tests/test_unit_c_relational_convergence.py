"""S0186 Unit C — relational convergence coverage.

Investigation for Unit C found that the already-admitted suppression path in
``reconcile_current_relation_candidates.disposition_for`` (the
``already_canonically_admitted`` disposition, keyed off relations tagged
``schema_version == "canonical-relation/v1"`` in the runtime canon) has no
existing regression coverage: every fixture in
``tests/test_reconcile_current_relation_candidates.py`` builds canon
``relations`` without that tag, so ``canonical_v1_signatures`` is always
empty and the suppression branch is never exercised.

This file closes that coverage gap. It does not modify
``reconcile_current_relation_candidates.py``, ``relation_admission_gate.py``,
or any other production module: reconstruction showed the existing logic is
already correct for Unit C's required invariants (already-admitted
suppressed, material/new relations stay reviewable, legacy vs v1 handled
deliberately and conservatively). Only test evidence was missing.

It also locks in, as an explicit regression, an architectural fact
discovered during investigation: ``reconcile_current_relation_candidates``
(review-queue stage) and ``relation_admission_gate`` (final admission-gate
stage) use two different, both intentional, "already exists" policies:

- reconcile only trusts ``canonical-relation/v1``-tagged edges (legacy
  matches stay ``ready_for_review`` -- S0180 fixed a prior bug where mere
  historical/legacy occurrence was wrongly used as a terminal veto);
- the gate (``GATE-013: blocked_duplicate_existing``) blocks on ANY existing
  edge, legacy or v1, because admitting a duplicate edge into canon is
  undesirable regardless of how the existing edge is tagged.

That is not a contradiction to fix; it is two stages of the same pipeline
with different jobs (review-worthiness vs. final anti-duplication). This
file demonstrates both sides on the same fixture so a future session does
not mistake the divergence for a bug.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "src" / "python_scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import reconcile_current_relation_candidates as reconcile  # noqa: E402
from relation_admission_gate import evaluate_gate  # noqa: E402


# ── reconcile-layer fixtures (mirrors tests/test_reconcile_current_relation_candidates.py) ──

def _record(identifier: str, repo_path: str, relations: list[dict] | None = None) -> dict:
    return {
        "id": identifier,
        "title": repo_path,
        "key": repo_path,
        "version_id": f"sha256:{identifier}",
        "source_fields": {"repo_path": repo_path},
        "relations": relations or [],
    }


def _candidate(identifier: str, source: str, target: str, predicate: str = "references") -> dict:
    return {
        "candidate_id": identifier,
        "candidate_schema_version": "technical-relation-candidates/v1",
        "session_origin": "CURRENT",
        "relation_type": predicate,
        "source": {"repo_path": source},
        "target": {"repo_path": target},
        "evidence": {
            "evidence_kind": "content_embedded",
            "raw_observation": f"{identifier} evidence",
            "file": source,
            "line": 1,
        },
        "policy": {"canonical_admission_allowed": False, "derivation_allowed": False, "human_review_required": True},
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _setup(tmp_path: Path, rows: list[dict], canon_rows: list[dict]) -> tuple[Path, Path, Path]:
    local = tmp_path / "data" / "out" / "local"
    canon = local
    _write_jsonl(canon / "tiddlers_1.jsonl", canon_rows)
    current = local / "pipeline" / "relation_candidates" / "current"
    _write_jsonl(current / "relation_candidates.jsonl", rows)
    productive = local / "audit" / "rag_admission" / "productive_rag_manifest.json"
    productive.parent.mkdir(parents=True, exist_ok=True)
    productive.write_text(json.dumps({"technical_gate": "PASS", "governance_gate": "PASS"}), encoding="utf-8")
    return canon, current, productive


def _run(canon: Path, current: Path, productive: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    baseline = out / "pre_relational_rag_baseline_manifest.json"
    if not baseline.exists():
        baseline.write_text(
            json.dumps({"schema_version": "pre-relational-rag-baseline/v1", "fixture": True}) + "\n",
            encoding="utf-8",
        )
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "reconcile_current_relation_candidates.py"),
            "--canon-root", str(canon),
            "--current-dir", str(current),
            "--out-dir", str(out),
            "--productive-manifest", str(productive),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _matrix(out: Path) -> dict[str, dict]:
    rows = [json.loads(line) for line in (out / "candidate_reconciliation_matrix.jsonl").read_text().splitlines()]
    return {row["candidate_id"]: row for row in rows}


# ── Caso 1 + Caso 4: already-admitted is suppressed, genuinely-new stays reviewable ──

_ADMITTED_CANON_ROWS = [
    _record("source", "src/source.py", [
        {"type": "references", "target_id": "target", "schema_version": "canonical-relation/v1"},
    ]),
    _record("target", "src/target.py"),
    _record("other", "src/other.py"),
]


def test_already_admitted_canonical_v1_signature_is_suppressed_not_material(tmp_path: Path) -> None:
    rows = [
        # H-C1: exact signature match against an existing canonical-relation/v1 edge.
        _candidate("admitted", "src/source.py", "src/target.py", "references"),
        # H-C3-analog: same endpoints, a different predicate is a distinct semantic
        # claim (this data model has no revisable "content" on an edge beyond its
        # (source, target, predicate) identity) -- it must stay reviewable, not be
        # folded into the admitted signature.
        _candidate("distinct-predicate", "src/source.py", "src/target.py", "depende_de"),
        # H-C4: genuinely new relation, unrelated to any existing edge.
        _candidate("new", "src/source.py", "src/other.py", "references"),
    ]
    canon, current, productive = _setup(tmp_path, rows, _ADMITTED_CANON_ROWS)
    _run(canon, current, productive, tmp_path / "audit")
    matrix = _matrix(tmp_path / "audit")

    assert matrix["admitted"]["disposition"] == "already_canonically_admitted"
    assert matrix["admitted"]["canon_admitted"] is True
    assert matrix["admitted"]["canonical_authority_granted"] is False  # disposition != authority

    assert matrix["distinct-predicate"]["disposition"] == "ready_for_review"
    assert matrix["distinct-predicate"]["canon_admitted"] is False

    assert matrix["new"]["disposition"] == "ready_for_review"
    assert matrix["new"]["canon_admitted"] is False


def test_already_admitted_rerun_is_deterministic_and_preserves_novelty(tmp_path: Path) -> None:
    """Section 18.7 / 20: rerun on unchanged inputs must not reopen the admitted
    relation as material, and must not lose the genuinely-new one either."""
    rows = [
        _candidate("admitted", "src/source.py", "src/target.py", "references"),
        _candidate("new", "src/source.py", "src/other.py", "references"),
    ]
    run_a_root = tmp_path / "run-a"
    run_b_root = tmp_path / "run-b"
    canon_a, current_a, productive_a = _setup(run_a_root, rows, _ADMITTED_CANON_ROWS)
    canon_b, current_b, productive_b = _setup(run_b_root, rows, _ADMITTED_CANON_ROWS)

    audit_a = run_a_root / "audit"
    audit_b = run_b_root / "audit"
    result_a = _run(canon_a, current_a, productive_a, audit_a)
    result_b = _run(canon_b, current_b, productive_b, audit_b)

    matrix_a = _matrix(audit_a)
    matrix_b = _matrix(audit_b)

    already_admitted_first_run = sum(1 for row in matrix_a.values() if row["disposition"] == "already_canonically_admitted")
    already_admitted_rerun = sum(1 for row in matrix_b.values() if row["disposition"] == "already_canonically_admitted")
    material_first_run = sum(1 for row in matrix_a.values() if row["disposition"] == "ready_for_review")
    material_rerun = sum(1 for row in matrix_b.values() if row["disposition"] == "ready_for_review")

    # Central property required by Unit C: an already-admitted equivalent relation
    # does not reappear as a material (ready_for_review) candidate on rerun --
    # its material delta between runs is zero -- while genuinely-new candidates
    # are neither gained nor lost.
    assert already_admitted_first_run == already_admitted_rerun == 1
    assert material_first_run == material_rerun == 1
    assert matrix_a["admitted"]["disposition"] == matrix_b["admitted"]["disposition"] == "already_canonically_admitted"
    assert matrix_a["new"]["disposition"] == matrix_b["new"]["disposition"] == "ready_for_review"

    # Reconciliation-manifest-level dispositions and canon binding must match too.
    manifest_a = json.loads((current_a / "reconciliation_manifest.json").read_text())
    manifest_b = json.loads((current_b / "reconciliation_manifest.json").read_text())
    assert manifest_a["dispositions"] == manifest_b["dispositions"]
    assert manifest_a["canon_hash"] == manifest_b["canon_hash"]

    assert result_a["canon_modified"] is False
    assert result_b["canon_modified"] is False


# ── Cross-layer architecture check: reconcile permissive vs gate strict ──

def test_reconcile_permissive_vs_gate_strict_duplicate_policy_is_intentional(tmp_path: Path) -> None:
    """Locks in the two-stage design found during Unit C investigation.

    Same (source, target, predicate) triple already present in canon as a
    LEGACY relation (no ``schema_version`` tag):

    - at the reconcile/review-queue stage, it stays ``ready_for_review``
      (S0180 policy: legacy occurrence alone must never silently veto review);
    - at the final admission-gate stage, it is blocked as
      ``blocked_duplicate_existing`` (admitting it would duplicate an edge
      already in canon, regardless of how that edge is tagged).

    Neither stage is wrong; they answer different questions. A future change
    that makes these two dispositions agree on this fixture is a material
    change to relational-convergence policy and must go through a new
    contract, not a silent "fix".
    """
    legacy_canon_rows = [
        _record("source", "src/source.py", [{"type": "references", "target_id": "target"}]),
        _record("target", "src/target.py"),
    ]
    rows = [_candidate("legacy-match", "src/source.py", "src/target.py", "references")]
    canon, current, productive = _setup(tmp_path, rows, legacy_canon_rows)
    _run(canon, current, productive, tmp_path / "audit")
    matrix = _matrix(tmp_path / "audit")

    assert matrix["legacy-match"]["disposition"] == "ready_for_review"
    assert matrix["legacy-match"]["canon_admitted"] is False

    gate_canon = {
        "src-001": {"id": "src-001", "title": "Source", "text": "source text",
                    "relations": [{"type": "references", "target_id": "tgt-002"}]},
        "tgt-002": {"id": "tgt-002", "title": "Target", "text": "target text", "relations": []},
    }
    gate_candidate = {
        "candidate_id": "rc1_c1c2c3c4c5c6c7c8",
        "candidate_schema_version": "technical-relation-candidates/v1",
        "status": "resolved_for_human_review",
        "artifact_family": "relation_candidate",
        "relation_type": "references",
        "human_review_decision": "approved_for_admission",
        "human_review_reason_code": "EXPLICIT_REFERENCE_CONFIRMED",
        "approval_scope": "canonical_admission",
        "human_review_actor": "operator",
        "human_review_timestamp": "2026-07-08T00:00:00Z",
        "reviewed_evidence_paths": ["data/out/local/pipeline/relation_candidates/current/review_queue.jsonl"],
        "source": {
            "canonical_id": "src-001",
            "canonical_title": "Source",
            "repo_path": "tests/test_unit_c_relational_convergence.py",
            "lifecycle_state": "current_repo_artifact",
        },
        "target": {
            "canonical_id": "tgt-002",
            "canonical_title": "Target",
            "repo_path": "src/python_scripts/relation_admission_gate.py",
            "lifecycle_state": "current_repo_artifact",
        },
        "evidence": {
            "evidence_kind": "content_embedded",
            "excerpt": "source text",
            "confidence": {"score": 0.95},
        },
    }
    gate_result = evaluate_gate(gate_candidate, gate_canon)
    assert gate_result["decision"] == "blocked_duplicate_existing"
