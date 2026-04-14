package canon

// ---------------------------------------------------------------------------
// S29 — canon-accumulator-truth-pin-and-impl-v0
//
// Production implementation of the accumulator, promoted from the S28
// contract-test stubs in accumulate_test.go.
//
// Truth pinned in S29:
//   - Fold order: (start_time, run_id) ascending.
//   - Checksum: sha256(canonical JSON with checksum field set to "").
//
// Discrepancies resolved:
//   - D1: S28 contract §D said "(batch_time, run_id)" but batch_time does
//     not exist in the run_report shape. Implementation uses start_time.
//   - D2: S28 contract §E said "sha256(serialized_snapshot)" which is
//     ambiguous. Implementation zeros Checksum before hashing to avoid
//     circular dependency.
//
// Ref: S28 — accumulation semantics contract.
// Ref: S29 — truth pin and implementation.
// ---------------------------------------------------------------------------

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
)

// --- Accumulation shapes (S28 contract, promoted S29) ---

// RunReport represents a single pipeline run's observable output.
// Shape defined in S28 — canon-gate-batch-accumulation-semantics-v0.
type RunReport struct {
	RunID    string     `json:"run_id"`
	BatchID  string     `json:"batch_id"`
	Start    string     `json:"start_time"`
	End      string     `json:"end_time"`
	Metrics  RunMetrics `json:"metrics"`
	Rejected map[string]int `json:"rejected_by_reason"`
	Emitted  struct {
		CanonLines int      `json:"canon_lines"`
		Files      []string `json:"files"`
	} `json:"emitted"`
	Provenance struct {
		ToolVersion string `json:"tool_version"`
		Commit      string `json:"commit"`
	} `json:"provenance"`
	Checksums struct {
		CanonSHA256 string `json:"canon_sha256"`
	} `json:"checksums"`
}

// RunMetrics holds the counters for a single run.
type RunMetrics struct {
	Processed       int     `json:"processed"`
	Admitted        int     `json:"admitted"`
	Rejected        int     `json:"rejected"`
	Warnings        int     `json:"warnings"`
	DurationSeconds float64 `json:"duration_seconds"`
}

// BatchSnapshot is the accumulated state across runs.
// Shape defined in S28 contract, promoted to production in S29.
//
// S30 enrichment: UUID (UUIDv5 deterministic identity) and UUIDSpecVersion
// fields added. UUID is computed from a canonical payload that includes
// the sorted runs_included, algorithm_id, accumulation_version, and
// uuid_spec_version. Checksum now uses Canonical JSON serialization.
//
// Ref: S30 — UUIDv5 and canonical JSON for batch_snapshot identity.
type BatchSnapshot struct {
	SnapshotID        string             `json:"snapshot_id"`
	UUID              string             `json:"uuid"`
	UUIDSpecVersion   string             `json:"uuid_spec_version"`
	AsOf              string             `json:"as_of"`
	BatchesIncluded   []string           `json:"batches_included"`
	RunsIncluded      []string           `json:"runs_included"`
	MetricsAggregate  AggregateMetrics   `json:"metrics_aggregate"`
	RejectedAggregate map[string]int     `json:"rejected_by_reason_aggregate"`
	TopErrors         [][2]interface{}   `json:"top_errors"`
	FirstSeen         string             `json:"first_seen"`
	LastSeen          string             `json:"last_seen"`
	Provenance        SnapshotProvenance `json:"provenance"`
	Checksum          string             `json:"checksum"`
}

// AggregateMetrics holds the accumulated counters.
type AggregateMetrics struct {
	Processed       int     `json:"processed"`
	Admitted        int     `json:"admitted"`
	Rejected        int     `json:"rejected"`
	Warnings        int     `json:"warnings"`
	DurationSeconds float64 `json:"duration_seconds"`
	CanonLines      int     `json:"canon_lines"`
}

// SnapshotProvenance records how the snapshot was computed.
type SnapshotProvenance struct {
	AccumulationAlgo    string   `json:"accumulation_algo"`
	AccumulationVersion string   `json:"accumulation_version"`
	ReconstructedFrom   []string `json:"reconstructed_from_runs"`
}

// --- Production implementation of fold_v1 ---

// FoldV1 applies the deterministic fold algorithm over a slice of RunReport
// values and returns a BatchSnapshot.
//
// Truth pinned in S29:
//   - Sort order: (start_time, run_id) ascending.
//   - Checksum: sha256(canonical JSON with Checksum="").
//
// The function internally sorts the input (by copy) so callers need not
// pre-sort. Any input order produces the same deterministic output.
//
// Ref: S28 fold_v1 semantics.
// Ref: S29 truth pin D1 (start_time), D2 (checksum rule).
func FoldV1(runs []RunReport, snapshotID, asOf string) BatchSnapshot {
	// Sort by (start_time, run_id) for deterministic order.
	// Truth pin D1: start_time is the canonical sort key.
	sorted := make([]RunReport, len(runs))
	copy(sorted, runs)
	sort.Slice(sorted, func(i, j int) bool {
		if sorted[i].Start != sorted[j].Start {
			return sorted[i].Start < sorted[j].Start
		}
		return sorted[i].RunID < sorted[j].RunID
	})

	snap := BatchSnapshot{
		SnapshotID:        snapshotID,
		AsOf:              asOf,
		RejectedAggregate: make(map[string]int),
		Provenance: SnapshotProvenance{
			AccumulationAlgo:    "fold_v1",
			AccumulationVersion: "v0.1",
		},
	}

	batchSet := make(map[string]bool)
	var firstSeen, lastSeen string

	for _, r := range sorted {
		// I2: record run_id in order
		snap.RunsIncluded = append(snap.RunsIncluded, r.RunID)
		snap.Provenance.ReconstructedFrom = append(snap.Provenance.ReconstructedFrom, r.RunID)

		// Batches: union
		if !batchSet[r.BatchID] {
			batchSet[r.BatchID] = true
			snap.BatchesIncluded = append(snap.BatchesIncluded, r.BatchID)
		}

		// Counters: sum
		snap.MetricsAggregate.Processed += r.Metrics.Processed
		snap.MetricsAggregate.Admitted += r.Metrics.Admitted
		snap.MetricsAggregate.Rejected += r.Metrics.Rejected
		snap.MetricsAggregate.Warnings += r.Metrics.Warnings
		snap.MetricsAggregate.DurationSeconds += r.Metrics.DurationSeconds
		snap.MetricsAggregate.CanonLines += r.Emitted.CanonLines

		// Maps of counts: sum per key
		for reason, count := range r.Rejected {
			snap.RejectedAggregate[reason] += count
		}

		// Timestamps: min/max
		if firstSeen == "" || r.Start < firstSeen {
			firstSeen = r.Start
		}
		if lastSeen == "" || r.End > lastSeen {
			lastSeen = r.End
		}
	}

	snap.FirstSeen = firstSeen
	snap.LastSeen = lastSeen

	// Top-K: derive from map, sorted desc by count, ties by key asc
	snap.TopErrors = TopKFromMap(snap.RejectedAggregate)

	// S30: set UUID spec version.
	snap.UUIDSpecVersion = UUIDSpecVersionV1

	// S30: compute deterministic UUIDv5 from canonical payload.
	// The UUID depends on (accumulation_version, algorithm_id, runs_included, uuid_spec_version).
	uuid, err := ComputeSnapshotUUID(
		snap.Provenance.AccumulationVersion,
		snap.Provenance.AccumulationAlgo,
		snap.RunsIncluded,
	)
	if err != nil {
		// Should not happen with well-formed inputs; panic matches
		// the existing convention in ComputeSnapshotChecksum.
		panic(fmt.Sprintf("accumulate: compute uuid: %v", err))
	}
	snap.UUID = uuid

	// I4: compute checksum over canonical serialization.
	// Truth pin D2 (S29): checksum field set to "" before hashing.
	// S30: uses Canonical JSON (sorted keys) for deterministic serialization.
	snap.Checksum = ComputeSnapshotChecksum(snap)

	return snap
}

// TopKFromMap derives a sorted error list from the rejection map.
// Sorted descending by count; ties broken by key ascending (lexicographic).
func TopKFromMap(m map[string]int) [][2]interface{} {
	type kv struct {
		Key   string
		Count int
	}
	var items []kv
	for k, v := range m {
		items = append(items, kv{k, v})
	}
	sort.Slice(items, func(i, j int) bool {
		if items[i].Count != items[j].Count {
			return items[i].Count > items[j].Count
		}
		return items[i].Key < items[j].Key
	})
	result := make([][2]interface{}, len(items))
	for i, item := range items {
		result[i] = [2]interface{}{item.Key, item.Count}
	}
	return result
}

// ComputeSnapshotChecksum serializes a snapshot (with its checksum field
// set to "") to Canonical JSON and returns "sha256:<hex>".
//
// Truth pin D2 (S29): the checksum is computed over the JSON serialization
// with the Checksum field set to empty string, avoiding circular dependency.
// The snapshot is received by value, so the caller's copy is NOT mutated.
//
// S30: uses Canonical JSON (sorted keys, preserved number precision) instead
// of Go's default struct-order json.Marshal, ensuring the checksum is
// independent of Go struct field declaration order.
//
// This function panics if JSON marshaling fails, which should not happen for
// well-formed BatchSnapshot values. If called with untrusted data, callers
// should recover from panics or pre-validate the input.
//
// Ref: S28 I4 — checksum verification.
// Ref: S29 D2 — checksum rule resolution.
// Ref: S30 — canonical JSON for deterministic checksum.
func ComputeSnapshotChecksum(snap BatchSnapshot) string {
	// Zero out checksum before serializing.
	snap.Checksum = ""
	data, err := CanonicalJSON(snap)
	if err != nil {
		panic(fmt.Sprintf("accumulate: canonical marshal snapshot: %v", err))
	}
	h := sha256.Sum256(data)
	return fmt.Sprintf("sha256:%x", h)
}

// LoadRunReports reads all JSON files from a directory and parses them
// as RunReport values.
func LoadRunReports(dir string) ([]RunReport, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, fmt.Errorf("accumulate: read dir %q: %w", dir, err)
	}
	var runs []RunReport
	for _, e := range entries {
		if e.IsDir() || filepath.Ext(e.Name()) != ".json" {
			continue
		}
		data, err := os.ReadFile(filepath.Join(dir, e.Name()))
		if err != nil {
			return nil, fmt.Errorf("accumulate: read %q: %w", e.Name(), err)
		}
		var r RunReport
		if err := json.Unmarshal(data, &r); err != nil {
			return nil, fmt.Errorf("accumulate: parse %q: %w", e.Name(), err)
		}
		runs = append(runs, r)
	}
	return runs, nil
}
