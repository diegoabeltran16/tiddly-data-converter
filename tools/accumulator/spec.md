# Accumulator — Specification

> **Session:** m02-s28-canon-gate-batch-accumulation-semantics-v0
> **Status:** specification (implementation deferred)
> **Milestone:** M02

---

## 1. Purpose

The `accumulator` is a deterministic tool that computes `batch_snapshot` from a set of `run_report` artifacts using the `fold_v1` algorithm. It provides both accumulation and verification capabilities.

---

## 2. CLI Interface

```
accumulate [flags]

Flags:
  --input <dir>       Directory containing run_report JSON files (required)
  --batch <id>        Filter runs by batch_id (optional; if omitted, all runs)
  --out <path>        Output path for the generated batch_snapshot JSON (required)
  --verify            After generating, replay from runs and verify checksum
  --version           Print accumulation algorithm version (fold_v1)
```

---

## 3. Input: `run_report`

Each file in `--input` must be a valid JSON object conforming to the `run_report` shape defined in the S28 contract:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `run_id` | string | yes | Unique identifier for the run |
| `batch_id` | string | yes | Logical batch grouping |
| `start_time` | RFC3339 | yes | Run start timestamp |
| `end_time` | RFC3339 | yes | Run end timestamp |
| `metrics.processed` | int | yes | Total entries processed |
| `metrics.admitted` | int | yes | Entries admitted |
| `metrics.rejected` | int | yes | Entries rejected |
| `metrics.warnings` | int | yes | Warnings emitted |
| `metrics.duration_seconds` | float | yes | Run duration |
| `rejected_by_reason` | map[string]int | yes | Rejection counts by reason |
| `emitted.canon_lines` | int | yes | Lines written to canon |
| `emitted.files` | []string | yes | Output file paths |
| `provenance.tool_version` | string | yes | Tool version string |
| `provenance.commit` | string | yes | Source commit hash |
| `checksums.canon_sha256` | string | yes | SHA256 of output canon file |

---

## 4. Output: `batch_snapshot`

| Field | Type | Description |
|-------|------|-------------|
| `snapshot_id` | string | `snapshot-<batch_id>-<timestamp>` |
| `as_of` | RFC3339 | Generation timestamp |
| `batches_included` | []string | Distinct batch_ids in this snapshot |
| `runs_included` | []string | Ordered list of run_ids used |
| `metrics_aggregate.processed` | int | Sum of all `metrics.processed` |
| `metrics_aggregate.admitted` | int | Sum of all `metrics.admitted` |
| `metrics_aggregate.rejected` | int | Sum of all `metrics.rejected` |
| `metrics_aggregate.warnings` | int | Sum of all `metrics.warnings` |
| `metrics_aggregate.duration_seconds` | float | Sum of all durations |
| `metrics_aggregate.canon_lines` | int | Sum of all `emitted.canon_lines` |
| `rejected_by_reason_aggregate` | map[string]int | Merged rejection map |
| `top_errors` | [][]any | Top-K errors `[[reason, count], ...]` sorted desc by count, ties broken lexicographically |
| `first_seen` | RFC3339 | `min(start_time)` across all runs |
| `last_seen` | RFC3339 | `max(end_time)` across all runs |
| `provenance.accumulation_algo` | string | `"fold_v1"` |
| `provenance.accumulation_version` | string | `"v0.1"` |
| `provenance.reconstructed_from_runs` | []string | Same as `runs_included` |
| `checksum` | string | `sha256:<hex>` of the canonical JSON serialization |

---

## 5. Fold Algorithm — `fold_v1`

### 5.1 Ordering

Runs are sorted by `(start_time, run_id)` in ascending order. Fold is applied sequentially in this order.

### 5.2 Fold Rules

| Data type | Rule | Properties |
|-----------|------|-----------|
| Counters (`int`) | Sum | Associative, commutative |
| Maps of counts | Sum per key | Associative, commutative |
| Unique sets (run_ids, batch_ids) | Union | Idempotent |
| Timestamps | `min()` for first-seen, `max()` for last-seen | Commutative |
| Histograms | Merge by bucket boundaries (stable per `accumulation_version`) | Associative |
| Top-K | Derive from merged counts map; break ties lexicographically | Deterministic |

### 5.3 Checksum Computation

1. Serialize snapshot to canonical JSON (sorted keys, no trailing whitespace).
2. Compute `sha256(canonical_json)`.
3. Store as `"sha256:<hex>"`.

---

## 6. Verification (`--verify`)

1. Read the generated snapshot.
2. Re-read all `run_report` files listed in `runs_included`.
3. Re-apply `fold_v1` from scratch.
4. Compare the recomputed checksum with the stored checksum.
5. If mismatch: exit with error code 1, print diagnostic showing which field diverges.

---

## 7. Invariants

| ID | Invariant |
|----|-----------|
| I1 | `run_report` values are immutable once persisted |
| I2 | `runs_included` is exact and ordered |
| I3 | Snapshot includes `accumulation_version` and `accumulation_algo` |
| I4 | `checksum` = `sha256(canonical_serialization)` and is verifiable by replay |
| I5 | No silent rewrite: changed runs invalidate snapshot; new snapshot carries `replaces` field |

---

## 8. Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (and verification passed if `--verify`) |
| 1 | Verification failed (checksum mismatch) |
| 2 | Input error (missing files, invalid JSON, missing required fields) |

---

## 9. Implementation Notes (deferred to post-S28)

- The accumulator will be implemented as a Go package in `go/canon/` with a CLI wrapper in `tools/accumulator/`.
- S28 provides contract tests (`go/canon/accumulate_test.go`) that can be satisfied by a stub or a full implementation.
- The stub must demonstrate that the fold is deterministic and that replay produces identical checksums.
