# Accumulator

> Deterministic batch accumulation tool for Canon Gate run reports.

## Overview

The `accumulator` reads `run_report` JSON files produced by the Canon Gate pipeline and computes a `batch_snapshot` — a deterministic, verifiable summary of accumulated metrics across runs.

## Status

**Specified** in session `m02-s28-canon-gate-batch-accumulation-semantics-v0`.
Implementation is deferred to a post-S28 sprint. Contract tests exist in `go/canon/accumulate_test.go`.

## Quick Reference

```bash
# Accumulate all runs in a directory into a snapshot
accumulate --input out/reports/ --out out/snapshot.json

# Accumulate only runs for a specific batch
accumulate --input out/reports/ --batch batch-20260414 --out out/snapshot.json

# Accumulate and verify (replay + checksum comparison)
accumulate --input out/reports/ --batch batch-20260414 --out out/snapshot.json --verify
```

## Documentation

- **Full specification:** [`spec.md`](spec.md)
- **Contract:** `contratos/m02-s28-canon-gate-batch-accumulation-semantics-v0.md.json`
- **Test fixtures:** `tests/fixtures/runs_for_accumulation/run-001.json` ... `run-003.json`
- **Contract tests:** `go/canon/accumulate_test.go`

## Key Concepts

| Concept | Description |
|---------|-------------|
| `run_report` | Atomic, immutable record of a single pipeline run |
| `batch_report` | Ordered aggregation of runs within a logical batch |
| `batch_snapshot` | Deterministic, verifiable summary across batches |
| `fold_v1` | Deterministic fold algorithm (sum counters, merge maps, union sets) |

## Invariants

1. **I1:** `run_report` values are immutable and referentiable by `run_id`.
2. **I2:** `runs_included` in snapshots is exact and ordered.
3. **I3:** Snapshots carry `accumulation_version` and `accumulation_algo`.
4. **I4:** Snapshot `checksum` is verifiable by replay from source runs.
5. **I5:** No silent rewrite — changed runs invalidate existing snapshots.

## Session Reference

- Session: `m02-s28-canon-gate-batch-accumulation-semantics-v0`
- Milestone: M02
- Prerequisites: S16 (writer), S17–S21 (gate), S22–S27 (batch audit/report/persist)
