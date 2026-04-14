package canon

// ---------------------------------------------------------------------------
// S28 — canon-gate-batch-accumulation-semantics-v0
//
// Contract tests for the accumulation semantics defined in S28.
// These tests verify:
//   - Deterministic fold of run_report fixtures into batch_snapshot.
//   - Replay reconstruction produces identical checksums.
//   - Invariants I1–I5 are satisfied.
//
// The tests use a minimal stub implementation of fold_v1 that operates
// on the run_report shape defined in S28. The stub is intentionally
// simple: it demonstrates the contract, not a production implementation.
//
// Ref: S28 — accumulation semantics contract.
// Ref: S25–S27 — batch contract, report, persist.
// ---------------------------------------------------------------------------

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"testing"
)

// --- Accumulation shapes (S28 contract) ---

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
// Shape defined in S28 contract.
type BatchSnapshot struct {
	SnapshotID       string            `json:"snapshot_id"`
	AsOf             string            `json:"as_of"`
	BatchesIncluded  []string          `json:"batches_included"`
	RunsIncluded     []string          `json:"runs_included"`
	MetricsAggregate AggregateMetrics  `json:"metrics_aggregate"`
	RejectedAggregate map[string]int   `json:"rejected_by_reason_aggregate"`
	TopErrors        [][2]interface{}  `json:"top_errors"`
	FirstSeen        string            `json:"first_seen"`
	LastSeen         string            `json:"last_seen"`
	Provenance       SnapshotProvenance `json:"provenance"`
	Checksum         string            `json:"checksum"`
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

// --- Stub implementation of fold_v1 ---

// foldV1 applies the deterministic fold algorithm over a sorted slice of
// RunReport values and returns a BatchSnapshot.
//
// This is a contract-level stub: it demonstrates the fold semantics
// required by S28 without optimizations.
func foldV1(runs []RunReport, snapshotID, asOf string) BatchSnapshot {
	// Sort by (start_time, run_id) for deterministic order.
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
	snap.TopErrors = topKFromMap(snap.RejectedAggregate)

	// I4: compute checksum over canonical serialization
	snap.Checksum = computeSnapshotChecksum(snap)

	return snap
}

// topKFromMap derives a sorted error list from the rejection map.
func topKFromMap(m map[string]int) [][2]interface{} {
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

// computeSnapshotChecksum serializes a snapshot (without its checksum
// field) to canonical JSON and returns "sha256:<hex>".
// The snapshot is received by value, so the caller's copy is NOT mutated.
func computeSnapshotChecksum(snap BatchSnapshot) string {
	// Zero out checksum before serializing
	snap.Checksum = ""
	data, err := json.Marshal(snap)
	if err != nil {
		panic(fmt.Sprintf("accumulate: marshal snapshot: %v", err))
	}
	h := sha256.Sum256(data)
	return fmt.Sprintf("sha256:%x", h)
}

// loadRunReports reads all JSON files from a directory and parses them
// as RunReport values.
func loadRunReports(dir string) ([]RunReport, error) {
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

// --- Tests ---

// TestFoldDeterministic verifies that the same set of runs, folded in
// the canonical order, always produces the same snapshot checksum.
//
// Ref: S28 — criterion: same runs → same checksum.
func TestFoldDeterministic(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	runs, err := loadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load fixtures: %v", err)
	}
	if len(runs) < 3 {
		t.Fatalf("expected >= 3 run fixtures, got %d", len(runs))
	}

	// Fold twice
	snap1 := foldV1(runs, "snapshot-test-v0", "2026-04-14T12:00:00Z")
	snap2 := foldV1(runs, "snapshot-test-v0", "2026-04-14T12:00:00Z")

	if snap1.Checksum != snap2.Checksum {
		t.Errorf("fold not deterministic: checksum1=%s checksum2=%s", snap1.Checksum, snap2.Checksum)
	}

	// Fold with reversed input order (should still produce same result due to internal sort)
	reversed := make([]RunReport, len(runs))
	for i, r := range runs {
		reversed[len(runs)-1-i] = r
	}
	snap3 := foldV1(reversed, "snapshot-test-v0", "2026-04-14T12:00:00Z")
	if snap1.Checksum != snap3.Checksum {
		t.Errorf("fold not order-independent after sort: checksum1=%s checksum3=%s", snap1.Checksum, snap3.Checksum)
	}
}

// TestReplayReconstruction verifies that a snapshot can be reconstructed
// from its source runs and the recomputed checksum matches.
//
// Ref: S28 — criterion: replay == snapshot.
func TestReplayReconstruction(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	runs, err := loadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load fixtures: %v", err)
	}

	// Generate snapshot
	original := foldV1(runs, "snapshot-replay-test", "2026-04-14T12:00:00Z")

	// Replay: reload and refold
	runs2, err := loadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("reload fixtures: %v", err)
	}

	replayed := foldV1(runs2, "snapshot-replay-test", "2026-04-14T12:00:00Z")

	if original.Checksum != replayed.Checksum {
		t.Errorf("replay mismatch: original=%s replayed=%s", original.Checksum, replayed.Checksum)
	}

	// Verify runs_included matches
	if len(original.RunsIncluded) != len(replayed.RunsIncluded) {
		t.Fatalf("runs_included length mismatch: %d vs %d",
			len(original.RunsIncluded), len(replayed.RunsIncluded))
	}
	for i := range original.RunsIncluded {
		if original.RunsIncluded[i] != replayed.RunsIncluded[i] {
			t.Errorf("runs_included[%d]: %s vs %s",
				i, original.RunsIncluded[i], replayed.RunsIncluded[i])
		}
	}
}

// TestInvariants verifies invariants I1–I5 defined in the S28 contract.
//
// Ref: S28 — invariants I1–I5.
func TestInvariants(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	runs, err := loadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load fixtures: %v", err)
	}

	snap := foldV1(runs, "snapshot-invariants-test", "2026-04-14T12:00:00Z")

	// I1: run_reports are referentiable by run_id — each run has a non-empty run_id
	t.Run("I1_RunID_NonEmpty", func(t *testing.T) {
		for _, r := range runs {
			if r.RunID == "" {
				t.Error("run_report with empty run_id violates I1")
			}
		}
	})

	// I2: runs_included is exact and ordered by (start_time, run_id) as per fold_v1 spec.
	// In our fixtures, run_ids are co-monotonic with start_times, so checking
	// run_id ordering suffices. The canonical ordering is verified end-to-end
	// by TestFoldDeterministic (reversed input → same output).
	t.Run("I2_RunsIncluded_Exact_Ordered", func(t *testing.T) {
		if len(snap.RunsIncluded) != len(runs) {
			t.Errorf("runs_included has %d entries, expected %d",
				len(snap.RunsIncluded), len(runs))
		}
		for i := 1; i < len(snap.RunsIncluded); i++ {
			if snap.RunsIncluded[i] < snap.RunsIncluded[i-1] {
				t.Errorf("runs_included not ordered at index %d: %s < %s",
					i, snap.RunsIncluded[i], snap.RunsIncluded[i-1])
			}
		}
	})

	// I3: snapshot includes accumulation_version and algorithm_id
	t.Run("I3_AccumulationMetadata", func(t *testing.T) {
		if snap.Provenance.AccumulationAlgo == "" {
			t.Error("missing accumulation_algo")
		}
		if snap.Provenance.AccumulationVersion == "" {
			t.Error("missing accumulation_version")
		}
	})

	// I4: checksum is verifiable
	t.Run("I4_Checksum_Verifiable", func(t *testing.T) {
		recomputed := computeSnapshotChecksum(snap)
		if snap.Checksum != recomputed {
			t.Errorf("checksum mismatch: stored=%s recomputed=%s",
				snap.Checksum, recomputed)
		}
	})

	// I5: provenance.reconstructed_from_runs matches runs_included
	t.Run("I5_Provenance_Matches_RunsIncluded", func(t *testing.T) {
		if len(snap.Provenance.ReconstructedFrom) != len(snap.RunsIncluded) {
			t.Fatalf("reconstructed_from_runs length (%d) != runs_included length (%d)",
				len(snap.Provenance.ReconstructedFrom), len(snap.RunsIncluded))
		}
		for i := range snap.RunsIncluded {
			if snap.RunsIncluded[i] != snap.Provenance.ReconstructedFrom[i] {
				t.Errorf("mismatch at %d: runs_included=%s reconstructed=%s",
					i, snap.RunsIncluded[i], snap.Provenance.ReconstructedFrom[i])
			}
		}
	})
}

// TestFoldAggregateValues verifies the accumulated counters match the
// expected sums from the fixture runs.
//
// Ref: S28 — fold_v1 counter rules: sum.
func TestFoldAggregateValues(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	runs, err := loadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load fixtures: %v", err)
	}

	snap := foldV1(runs, "snapshot-aggregate-test", "2026-04-14T12:00:00Z")

	// Expected sums from run-001 + run-002 + run-003:
	// processed: 50 + 80 + 30 = 160
	// admitted:  45 + 70 + 28 = 143
	// rejected:   5 + 10 +  2 =  17
	// warnings:   1 +  3 +  0 =   4
	// duration: 120 + 180 + 90 = 390
	// canon_lines: 45 + 70 + 28 = 143

	if snap.MetricsAggregate.Processed != 160 {
		t.Errorf("processed: got %d, want 160", snap.MetricsAggregate.Processed)
	}
	if snap.MetricsAggregate.Admitted != 143 {
		t.Errorf("admitted: got %d, want 143", snap.MetricsAggregate.Admitted)
	}
	if snap.MetricsAggregate.Rejected != 17 {
		t.Errorf("rejected: got %d, want 17", snap.MetricsAggregate.Rejected)
	}
	if snap.MetricsAggregate.Warnings != 4 {
		t.Errorf("warnings: got %d, want 4", snap.MetricsAggregate.Warnings)
	}
	if snap.MetricsAggregate.DurationSeconds != 390 {
		t.Errorf("duration_seconds: got %v, want 390", snap.MetricsAggregate.DurationSeconds)
	}
	if snap.MetricsAggregate.CanonLines != 143 {
		t.Errorf("canon_lines: got %d, want 143", snap.MetricsAggregate.CanonLines)
	}

	// Rejected by reason:
	// schema_error: 3 + 4 = 7
	// empty_title:  2 + 1 = 3
	// duplicate:    6 + 1 = 7
	if snap.RejectedAggregate["schema_error"] != 7 {
		t.Errorf("schema_error: got %d, want 7", snap.RejectedAggregate["schema_error"])
	}
	if snap.RejectedAggregate["empty_title"] != 3 {
		t.Errorf("empty_title: got %d, want 3", snap.RejectedAggregate["empty_title"])
	}
	if snap.RejectedAggregate["duplicate"] != 7 {
		t.Errorf("duplicate: got %d, want 7", snap.RejectedAggregate["duplicate"])
	}

	// Timestamps
	if snap.FirstSeen != "2026-04-14T10:00:00Z" {
		t.Errorf("first_seen: got %s, want 2026-04-14T10:00:00Z", snap.FirstSeen)
	}
	if snap.LastSeen != "2026-04-14T10:11:30Z" {
		t.Errorf("last_seen: got %s, want 2026-04-14T10:11:30Z", snap.LastSeen)
	}
}
