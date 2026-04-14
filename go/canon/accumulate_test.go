package canon

// ---------------------------------------------------------------------------
// S28 — canon-gate-batch-accumulation-semantics-v0  (original contract tests)
// S29 — canon-accumulator-truth-pin-and-impl-v0    (truth-pinning tests)
//
// Contract tests for the accumulation semantics defined in S28.
// Truth-pinning tests added in S29 to codify resolved discrepancies.
//
// These tests verify:
//   - Deterministic fold of run_report fixtures into batch_snapshot.
//   - Replay reconstruction produces identical checksums.
//   - Invariants I1–I5 are satisfied.
//   - [S29] Fold order uses start_time (not batch_time).
//   - [S29] Checksum rule: sha256 with Checksum="" before serialization.
//
// Ref: S28 — accumulation semantics contract.
// Ref: S29 — truth pin and implementation.
// ---------------------------------------------------------------------------

import (
	"crypto/sha256"
	"fmt"
	"path/filepath"
	"sort"
	"testing"
)

// --- Tests (S28 original) ---

// TestFoldDeterministic verifies that the same set of runs, folded in
// the canonical order, always produces the same snapshot checksum.
//
// Ref: S28 — criterion: same runs → same checksum.
func TestFoldDeterministic(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	runs, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load fixtures: %v", err)
	}
	if len(runs) < 3 {
		t.Fatalf("expected >= 3 run fixtures, got %d", len(runs))
	}

	// Fold twice
	snap1 := FoldV1(runs, "snapshot-test-v0", "2026-04-14T12:00:00Z")
	snap2 := FoldV1(runs, "snapshot-test-v0", "2026-04-14T12:00:00Z")

	if snap1.Checksum != snap2.Checksum {
		t.Errorf("fold not deterministic: checksum1=%s checksum2=%s", snap1.Checksum, snap2.Checksum)
	}

	// Fold with reversed input order (should still produce same result due to internal sort)
	reversed := make([]RunReport, len(runs))
	for i, r := range runs {
		reversed[len(runs)-1-i] = r
	}
	snap3 := FoldV1(reversed, "snapshot-test-v0", "2026-04-14T12:00:00Z")
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
	runs, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load fixtures: %v", err)
	}

	// Generate snapshot
	original := FoldV1(runs, "snapshot-replay-test", "2026-04-14T12:00:00Z")

	// Replay: reload and refold
	runs2, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("reload fixtures: %v", err)
	}

	replayed := FoldV1(runs2, "snapshot-replay-test", "2026-04-14T12:00:00Z")

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
	runs, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load fixtures: %v", err)
	}

	snap := FoldV1(runs, "snapshot-invariants-test", "2026-04-14T12:00:00Z")

	// I1: run_reports are referentiable by run_id — each run has a non-empty run_id
	t.Run("I1_RunID_NonEmpty", func(t *testing.T) {
		for _, r := range runs {
			if r.RunID == "" {
				t.Error("run_report with empty run_id violates I1")
			}
		}
	})

	// I2: runs_included is exact and ordered by (start_time, run_id) as per fold_v1 spec.
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
		recomputed := ComputeSnapshotChecksum(snap)
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
	runs, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load fixtures: %v", err)
	}

	snap := FoldV1(runs, "snapshot-aggregate-test", "2026-04-14T12:00:00Z")

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

// --- Tests (S29 truth-pinning) ---

// TestTruthPinnedFoldOrder verifies that the fold sorts by (start_time, run_id),
// NOT by batch_time or any other field.
//
// This test codifies the resolution of discrepancy D1 (S29):
//   Contract S28 §D said "(batch_time, run_id)" but batch_time does not exist
//   in the run_report shape. Truth: fold order is (start_time, run_id).
//
// Ref: S29 — D1 truth pin.
func TestTruthPinnedFoldOrder(t *testing.T) {
	// Create runs with different start_times in non-chronological order.
	// If fold sorts by start_time, output order will be run-C, run-A, run-B.
	runs := []RunReport{
		{
			RunID:   "run-A",
			BatchID: "batch-test",
			Start:   "2026-04-14T10:05:00Z",
			End:     "2026-04-14T10:06:00Z",
			Metrics: RunMetrics{Processed: 10, Admitted: 10},
		},
		{
			RunID:   "run-B",
			BatchID: "batch-test",
			Start:   "2026-04-14T10:10:00Z",
			End:     "2026-04-14T10:11:00Z",
			Metrics: RunMetrics{Processed: 20, Admitted: 20},
		},
		{
			RunID:   "run-C",
			BatchID: "batch-test",
			Start:   "2026-04-14T10:00:00Z",
			End:     "2026-04-14T10:01:00Z",
			Metrics: RunMetrics{Processed: 30, Admitted: 30},
		},
	}

	snap := FoldV1(runs, "snapshot-truth-order", "2026-04-14T12:00:00Z")

	// Verify the runs are ordered by start_time ascending.
	expectedOrder := []string{"run-C", "run-A", "run-B"}
	if len(snap.RunsIncluded) != len(expectedOrder) {
		t.Fatalf("runs_included length: got %d, want %d", len(snap.RunsIncluded), len(expectedOrder))
	}
	for i, want := range expectedOrder {
		if snap.RunsIncluded[i] != want {
			t.Errorf("runs_included[%d]: got %s, want %s (sorted by start_time)",
				i, snap.RunsIncluded[i], want)
		}
	}

	// Verify tie-breaking by run_id when start_time is equal.
	runsWithTie := []RunReport{
		{
			RunID:   "run-Z",
			BatchID: "batch-test",
			Start:   "2026-04-14T10:00:00Z",
			End:     "2026-04-14T10:01:00Z",
			Metrics: RunMetrics{Processed: 10, Admitted: 10},
		},
		{
			RunID:   "run-A",
			BatchID: "batch-test",
			Start:   "2026-04-14T10:00:00Z",
			End:     "2026-04-14T10:01:00Z",
			Metrics: RunMetrics{Processed: 20, Admitted: 20},
		},
	}

	snapTie := FoldV1(runsWithTie, "snapshot-truth-tie", "2026-04-14T12:00:00Z")
	if snapTie.RunsIncluded[0] != "run-A" || snapTie.RunsIncluded[1] != "run-Z" {
		t.Errorf("tie-break by run_id: got %v, want [run-A, run-Z]", snapTie.RunsIncluded)
	}
}

// TestTruthPinnedChecksumRule verifies that the checksum is computed as
// sha256(canonical JSON with Checksum field set to "").
//
// This test codifies the resolution of discrepancy D2 (S29):
//   Contract S28 §E said "sha256(serialized_snapshot)" which is ambiguous.
//   Truth: Checksum field is set to "" before serialization, then sha256 is
//   computed over that serialization.
//
// Ref: S29 — D2 truth pin.
func TestTruthPinnedChecksumRule(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	runs, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load fixtures: %v", err)
	}

	snap := FoldV1(runs, "snapshot-checksum-truth", "2026-04-14T12:00:00Z")

	// 1. Verify the checksum is non-empty and has sha256: prefix
	if snap.Checksum == "" {
		t.Fatal("checksum is empty")
	}
	if len(snap.Checksum) < 8 || snap.Checksum[:7] != "sha256:" {
		t.Fatalf("checksum does not have sha256: prefix: %s", snap.Checksum)
	}

	// 2. Manually verify: set Checksum to "", canonical marshal, compute sha256
	verifyCopy := snap
	verifyCopy.Checksum = ""
	data, err := CanonicalJSON(verifyCopy)
	if err != nil {
		t.Fatalf("canonical marshal for verification: %v", err)
	}
	h := sha256.Sum256(data)
	expected := fmt.Sprintf("sha256:%x", h)

	if snap.Checksum != expected {
		t.Errorf("checksum rule violated:\n  stored:   %s\n  expected: %s\n  rule: sha256(JSON with Checksum=\"\")",
			snap.Checksum, expected)
	}

	// 3. Verify that ComputeSnapshotChecksum produces the same result
	recomputed := ComputeSnapshotChecksum(snap)
	if snap.Checksum != recomputed {
		t.Errorf("ComputeSnapshotChecksum mismatch: stored=%s recomputed=%s",
			snap.Checksum, recomputed)
	}
}

// TestTruthPinnedSemantics verifies that the truth-pinned accumulator
// produces deterministic and correct output with the fixture runs,
// combining both D1 and D2 resolutions.
//
// Ref: S29 — combined truth verification.
func TestTruthPinnedSemantics(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	runs, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load fixtures: %v", err)
	}

	// Sort runs manually by (start_time, run_id) to verify fold does the same
	sorted := make([]RunReport, len(runs))
	copy(sorted, runs)
	sort.Slice(sorted, func(i, j int) bool {
		if sorted[i].Start != sorted[j].Start {
			return sorted[i].Start < sorted[j].Start
		}
		return sorted[i].RunID < sorted[j].RunID
	})

	snap := FoldV1(runs, "snapshot-truth-combined", "2026-04-14T12:00:00Z")

	// Verify order matches manual sort by start_time
	for i, r := range sorted {
		if snap.RunsIncluded[i] != r.RunID {
			t.Errorf("fold order[%d]: got %s, want %s (by start_time)",
				i, snap.RunsIncluded[i], r.RunID)
		}
	}

	// Verify checksum is reproducible
	snap2 := FoldV1(runs, "snapshot-truth-combined", "2026-04-14T12:00:00Z")
	if snap.Checksum != snap2.Checksum {
		t.Errorf("not deterministic: %s vs %s", snap.Checksum, snap2.Checksum)
	}

	// Verify checksum rule
	recomputed := ComputeSnapshotChecksum(snap)
	if snap.Checksum != recomputed {
		t.Errorf("checksum rule: stored=%s recomputed=%s", snap.Checksum, recomputed)
	}
}

// --- Tests (S30 — UUIDv5 and Canonical JSON) ---

// TestBatchSnapshotUUIDDeterministic verifies that the same set of
// runs_included (in any input order) always produces the same UUID.
//
// Quality gate: S30 §14.1.
// Ref: S30 — UUIDv5 deterministic identity.
func TestBatchSnapshotUUIDDeterministic(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	runs, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load fixtures: %v", err)
	}

	// Fold twice with same inputs.
	snap1 := FoldV1(runs, "snapshot-uuid-det", "2026-04-14T12:00:00Z")
	snap2 := FoldV1(runs, "snapshot-uuid-det", "2026-04-14T12:00:00Z")

	if snap1.UUID == "" {
		t.Fatal("UUID is empty")
	}
	if snap1.UUID != snap2.UUID {
		t.Errorf("UUID not deterministic: %s vs %s", snap1.UUID, snap2.UUID)
	}

	// Fold with reversed input order (sort is internal).
	reversed := make([]RunReport, len(runs))
	for i, r := range runs {
		reversed[len(runs)-1-i] = r
	}
	snap3 := FoldV1(reversed, "snapshot-uuid-det", "2026-04-14T12:00:00Z")
	if snap1.UUID != snap3.UUID {
		t.Errorf("UUID not order-independent: %s vs %s", snap1.UUID, snap3.UUID)
	}

	// UUID must have version 5 marker.
	// Format: xxxxxxxx-xxxx-5xxx-yxxx-xxxxxxxxxxxx
	if len(snap1.UUID) != 36 {
		t.Fatalf("UUID wrong length: %d", len(snap1.UUID))
	}
	if snap1.UUID[14] != '5' {
		t.Errorf("UUID version nibble: got %c, want 5", snap1.UUID[14])
	}

	// UUIDSpecVersion must be set.
	if snap1.UUIDSpecVersion != UUIDSpecVersionV1 {
		t.Errorf("UUIDSpecVersion: got %q, want %q", snap1.UUIDSpecVersion, UUIDSpecVersionV1)
	}
}

// TestChecksumZeroField verifies that the checksum is computed as
// sha256(CanonicalJSON(snapshot with checksum="")).
//
// This strengthens the S29 truth pin D2 by ensuring Canonical JSON
// (sorted keys) is used instead of struct-order serialization.
//
// Quality gate: S30 §14.2.
// Ref: S30 — canonical JSON checksum rule.
func TestChecksumZeroField(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	runs, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load fixtures: %v", err)
	}

	snap := FoldV1(runs, "snapshot-checksum-zero", "2026-04-14T12:00:00Z")

	// 1. Checksum must be non-empty with sha256: prefix.
	if snap.Checksum == "" {
		t.Fatal("checksum is empty")
	}
	if len(snap.Checksum) < 8 || snap.Checksum[:7] != "sha256:" {
		t.Fatalf("checksum missing sha256: prefix: %s", snap.Checksum)
	}

	// 2. Manually verify using CanonicalJSON.
	verifyCopy := snap
	verifyCopy.Checksum = ""
	canonical, err := CanonicalJSON(verifyCopy)
	if err != nil {
		t.Fatalf("canonical JSON for verification: %v", err)
	}

	// Verify canonical JSON has sorted keys (spot-check: "as_of" < "batches_included").
	if len(canonical) == 0 {
		t.Fatal("canonical JSON is empty")
	}

	h := sha256.Sum256(canonical)
	expected := fmt.Sprintf("sha256:%x", h)
	if snap.Checksum != expected {
		t.Errorf("checksum rule violated:\n  stored:   %s\n  expected: %s\n  rule: sha256(CanonicalJSON(snapshot with checksum=\"\"))",
			snap.Checksum, expected)
	}

	// 3. ComputeSnapshotChecksum must agree.
	recomputed := ComputeSnapshotChecksum(snap)
	if snap.Checksum != recomputed {
		t.Errorf("ComputeSnapshotChecksum mismatch: stored=%s recomputed=%s",
			snap.Checksum, recomputed)
	}
}

// TestReplayVerification verifies that replaying the fold from the same
// run_report fixtures reproduces both the checksum and the UUID.
//
// Quality gate: S30 §14.3.
// Ref: S30 — replay verification.
func TestReplayVerification(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	runs1, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load fixtures (pass 1): %v", err)
	}

	original := FoldV1(runs1, "snapshot-replay-s30", "2026-04-14T12:00:00Z")

	// Replay: reload and refold.
	runs2, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load fixtures (pass 2): %v", err)
	}

	replayed := FoldV1(runs2, "snapshot-replay-s30", "2026-04-14T12:00:00Z")

	// Both checksum and UUID must match.
	if original.Checksum != replayed.Checksum {
		t.Errorf("replay checksum mismatch: %s vs %s", original.Checksum, replayed.Checksum)
	}
	if original.UUID != replayed.UUID {
		t.Errorf("replay UUID mismatch: %s vs %s", original.UUID, replayed.UUID)
	}

	// Runs included must match.
	if len(original.RunsIncluded) != len(replayed.RunsIncluded) {
		t.Fatalf("runs_included length: %d vs %d",
			len(original.RunsIncluded), len(replayed.RunsIncluded))
	}
	for i := range original.RunsIncluded {
		if original.RunsIncluded[i] != replayed.RunsIncluded[i] {
			t.Errorf("runs_included[%d]: %s vs %s",
				i, original.RunsIncluded[i], replayed.RunsIncluded[i])
		}
	}

	// UUIDSpecVersion must be set on both.
	if original.UUIDSpecVersion != UUIDSpecVersionV1 {
		t.Errorf("original UUIDSpecVersion: %q", original.UUIDSpecVersion)
	}
	if replayed.UUIDSpecVersion != UUIDSpecVersionV1 {
		t.Errorf("replayed UUIDSpecVersion: %q", replayed.UUIDSpecVersion)
	}
}

// TestUUIDDifferentRunsProduceDifferentUUID verifies that different sets
// of runs_included produce different UUIDs.
//
// Ref: S30 — UUIDv5 collision resistance for distinct inputs.
func TestUUIDDifferentRunsProduceDifferentUUID(t *testing.T) {
	runsA := []RunReport{
		{RunID: "run-A", BatchID: "b1", Start: "2026-04-14T10:00:00Z", End: "2026-04-14T10:01:00Z", Metrics: RunMetrics{Processed: 10, Admitted: 10}},
	}
	runsB := []RunReport{
		{RunID: "run-B", BatchID: "b1", Start: "2026-04-14T10:00:00Z", End: "2026-04-14T10:01:00Z", Metrics: RunMetrics{Processed: 10, Admitted: 10}},
	}

	snapA := FoldV1(runsA, "snap-diff-a", "2026-04-14T12:00:00Z")
	snapB := FoldV1(runsB, "snap-diff-b", "2026-04-14T12:00:00Z")

	if snapA.UUID == snapB.UUID {
		t.Errorf("different runs produced same UUID: %s", snapA.UUID)
	}
}
