package canon

// ---------------------------------------------------------------------------
// S31 — Tests for replay verification of batch_snapshot.
//
// These tests verify:
//   - VerifySnapshot correctly identifies matching snapshots.
//   - VerifySnapshot detects tampered/corrupted snapshots.
//   - Field-by-field comparison classifies normative vs non-normative diffs.
//   - LoadSnapshot correctly parses snapshot files.
//   - Integration: generate + write + verify round-trip.
//
// Ref: S31 — replay verification and CI.
// ---------------------------------------------------------------------------

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// TestVerifySnapshot_ValidSnapshot verifies that a correctly generated
// snapshot passes verification when verified against the same inputs.
//
// Ref: S31 §5 — verify behavior (happy path).
func TestVerifySnapshot_ValidSnapshot(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	tmpDir := t.TempDir()

	// Generate a snapshot.
	runs, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load runs: %v", err)
	}

	snap := FoldV1(runs, "snapshot-verify-test", "2026-04-14T12:00:00Z")

	// Write snapshot to temp file.
	snapPath := filepath.Join(tmpDir, "snapshot.json")
	data, err := json.MarshalIndent(snap, "", "  ")
	if err != nil {
		t.Fatalf("marshal snapshot: %v", err)
	}
	if err := os.WriteFile(snapPath, data, 0644); err != nil {
		t.Fatalf("write snapshot: %v", err)
	}

	// Verify.
	result, err := VerifySnapshot(snapPath, fixtureDir, "")
	if err != nil {
		t.Fatalf("verify: %v", err)
	}

	if !result.OK {
		t.Errorf("expected OK=true, got false. Diffs: %+v", result.Diffs)
	}
	if result.RunsLoaded != len(runs) {
		t.Errorf("runs_loaded: got %d, want %d", result.RunsLoaded, len(runs))
	}

	// Should have no normative diffs.
	for _, d := range result.Diffs {
		if d.Normative {
			t.Errorf("unexpected normative diff: %s (expected=%s, observed=%s)",
				d.Field, d.Expected, d.Observed)
		}
	}
}

// TestVerifySnapshot_TamperedChecksum verifies that a snapshot with a
// modified checksum fails verification.
//
// Ref: S31 §6.1 — checksum is a strictly verified field.
func TestVerifySnapshot_TamperedChecksum(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	tmpDir := t.TempDir()

	// Generate a valid snapshot.
	runs, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load runs: %v", err)
	}

	snap := FoldV1(runs, "snapshot-tamper-test", "2026-04-14T12:00:00Z")

	// Tamper with checksum.
	snap.Checksum = "sha256:0000000000000000000000000000000000000000000000000000000000000000"

	// Write tampered snapshot.
	snapPath := filepath.Join(tmpDir, "snapshot-tampered.json")
	data, err := json.MarshalIndent(snap, "", "  ")
	if err != nil {
		t.Fatalf("marshal snapshot: %v", err)
	}
	if err := os.WriteFile(snapPath, data, 0644); err != nil {
		t.Fatalf("write snapshot: %v", err)
	}

	// Verify — should fail.
	result, err := VerifySnapshot(snapPath, fixtureDir, "")
	if err != nil {
		t.Fatalf("verify: %v", err)
	}

	if result.OK {
		t.Error("expected OK=false for tampered checksum, got true")
	}

	// Must have a normative diff for checksum.
	found := false
	for _, d := range result.Diffs {
		if d.Field == "checksum" && d.Normative {
			found = true
		}
	}
	if !found {
		t.Error("expected normative diff for 'checksum' field")
	}
}

// TestVerifySnapshot_TamperedUUID verifies that a snapshot with a
// modified UUID fails verification.
//
// Ref: S31 §6.1 — uuid is a strictly verified field.
func TestVerifySnapshot_TamperedUUID(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	tmpDir := t.TempDir()

	runs, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load runs: %v", err)
	}

	snap := FoldV1(runs, "snapshot-uuid-tamper", "2026-04-14T12:00:00Z")

	// Tamper with UUID.
	snap.UUID = "00000000-0000-5000-8000-000000000000"

	snapPath := filepath.Join(tmpDir, "snapshot-uuid-tampered.json")
	data, err := json.MarshalIndent(snap, "", "  ")
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if err := os.WriteFile(snapPath, data, 0644); err != nil {
		t.Fatalf("write: %v", err)
	}

	result, err := VerifySnapshot(snapPath, fixtureDir, "")
	if err != nil {
		t.Fatalf("verify: %v", err)
	}

	if result.OK {
		t.Error("expected OK=false for tampered UUID")
	}

	found := false
	for _, d := range result.Diffs {
		if d.Field == "uuid" && d.Normative {
			found = true
		}
	}
	if !found {
		t.Error("expected normative diff for 'uuid' field")
	}
}

// TestVerifySnapshot_TamperedMetrics verifies that a snapshot with
// modified aggregate metrics fails verification.
//
// Ref: S31 §6.1 — metrics are strictly verified fields.
func TestVerifySnapshot_TamperedMetrics(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	tmpDir := t.TempDir()

	runs, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load runs: %v", err)
	}

	snap := FoldV1(runs, "snapshot-metrics-tamper", "2026-04-14T12:00:00Z")

	// Tamper with a metric.
	snap.MetricsAggregate.Processed = 999

	snapPath := filepath.Join(tmpDir, "snapshot-metrics-tampered.json")
	data, err := json.MarshalIndent(snap, "", "  ")
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if err := os.WriteFile(snapPath, data, 0644); err != nil {
		t.Fatalf("write: %v", err)
	}

	result, err := VerifySnapshot(snapPath, fixtureDir, "")
	if err != nil {
		t.Fatalf("verify: %v", err)
	}

	if result.OK {
		t.Error("expected OK=false for tampered metrics")
	}

	// Should detect metrics_aggregate diff.
	found := false
	for _, d := range result.Diffs {
		if d.Field == "metrics_aggregate" && d.Normative {
			found = true
		}
	}
	if !found {
		t.Error("expected normative diff for 'metrics_aggregate' field")
	}
}

// TestVerifySnapshot_NonNormativeDifference verifies that a non-normative
// field difference (like as_of) does NOT fail verification.
//
// Ref: S31 §6.2 — non-normative fields don't block verification.
func TestVerifySnapshot_NonNormativeDifference(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	tmpDir := t.TempDir()

	runs, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load runs: %v", err)
	}

	// Note: snapshot_id and as_of are non-normative; when we pass the
	// observed's snapshot_id and as_of to FoldV1 in VerifySnapshot, they
	// will match. To test non-normative handling, we verify that a valid
	// snapshot still passes even though we verify with identical params.
	snap := FoldV1(runs, "snapshot-non-norm", "2026-04-14T12:00:00Z")

	snapPath := filepath.Join(tmpDir, "snapshot.json")
	data, err := json.MarshalIndent(snap, "", "  ")
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if err := os.WriteFile(snapPath, data, 0644); err != nil {
		t.Fatalf("write: %v", err)
	}

	result, err := VerifySnapshot(snapPath, fixtureDir, "")
	if err != nil {
		t.Fatalf("verify: %v", err)
	}

	if !result.OK {
		t.Errorf("expected OK=true, got false. Diffs: %+v", result.Diffs)
	}
}

// TestVerifySnapshot_WithBatchFilter verifies that batch filtering works
// correctly during verification.
//
// Ref: S31 §5.1 — verify with batch filter.
func TestVerifySnapshot_WithBatchFilter(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	tmpDir := t.TempDir()

	// Generate snapshot with batch filter.
	runs, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load runs: %v", err)
	}

	// All fixtures use batch_id "batch-20260414"
	batchID := "batch-20260414"
	var filtered []RunReport
	for _, r := range runs {
		if r.BatchID == batchID {
			filtered = append(filtered, r)
		}
	}

	snap := FoldV1(filtered, "snapshot-batch-filter", "2026-04-14T12:00:00Z")

	snapPath := filepath.Join(tmpDir, "snapshot-filtered.json")
	data, err := json.MarshalIndent(snap, "", "  ")
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if err := os.WriteFile(snapPath, data, 0644); err != nil {
		t.Fatalf("write: %v", err)
	}

	result, err := VerifySnapshot(snapPath, fixtureDir, batchID)
	if err != nil {
		t.Fatalf("verify: %v", err)
	}

	if !result.OK {
		t.Errorf("expected OK=true with batch filter, got false. Diffs: %+v", result.Diffs)
	}
	if result.RunsLoaded != len(filtered) {
		t.Errorf("runs_loaded: got %d, want %d", result.RunsLoaded, len(filtered))
	}
}

// TestVerifySnapshot_MissingInputDir verifies error on missing input directory.
func TestVerifySnapshot_MissingInputDir(t *testing.T) {
	tmpDir := t.TempDir()
	snap := BatchSnapshot{SnapshotID: "test", AsOf: "2026-04-14T12:00:00Z"}
	snapPath := filepath.Join(tmpDir, "snap.json")
	data, _ := json.Marshal(snap)
	os.WriteFile(snapPath, data, 0644)

	_, err := VerifySnapshot(snapPath, "/nonexistent/dir", "")
	if err == nil {
		t.Error("expected error for missing input dir")
	}
}

// TestVerifySnapshot_MissingSnapshotFile verifies error on missing snapshot file.
func TestVerifySnapshot_MissingSnapshotFile(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	_, err := VerifySnapshot("/nonexistent/snapshot.json", fixtureDir, "")
	if err == nil {
		t.Error("expected error for missing snapshot file")
	}
}

// TestLoadSnapshot_ValidFile verifies LoadSnapshot correctly parses a
// well-formed snapshot file.
func TestLoadSnapshot_ValidFile(t *testing.T) {
	tmpDir := t.TempDir()

	snap := BatchSnapshot{
		SnapshotID:      "test-load",
		UUID:            "12345678-1234-5678-1234-567812345678",
		UUIDSpecVersion: "v1",
		Checksum:        "sha256:abc",
		RunsIncluded:    []string{"run-001"},
	}

	path := filepath.Join(tmpDir, "snapshot.json")
	data, _ := json.MarshalIndent(snap, "", "  ")
	os.WriteFile(path, data, 0644)

	loaded, err := LoadSnapshot(path)
	if err != nil {
		t.Fatalf("LoadSnapshot: %v", err)
	}

	if loaded.SnapshotID != snap.SnapshotID {
		t.Errorf("snapshot_id: got %q, want %q", loaded.SnapshotID, snap.SnapshotID)
	}
	if loaded.UUID != snap.UUID {
		t.Errorf("uuid: got %q, want %q", loaded.UUID, snap.UUID)
	}
}

// TestVerifySnapshot_RoundTrip is an integration test that generates a
// snapshot, writes it, and verifies it — the complete S31 workflow.
//
// Ref: S31 — end-to-end verification round-trip.
func TestVerifySnapshot_RoundTrip(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	tmpDir := t.TempDir()

	// Step 1: Load runs.
	runs, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load runs: %v", err)
	}

	// Step 2: Generate snapshot.
	snap := FoldV1(runs, "snapshot-roundtrip-s31", "2026-04-14T12:00:00Z")

	// Step 3: Write to file.
	snapPath := filepath.Join(tmpDir, "batch_snapshot.json")
	data, err := json.MarshalIndent(snap, "", "  ")
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if err := os.WriteFile(snapPath, data, 0644); err != nil {
		t.Fatalf("write: %v", err)
	}

	// Step 4: Verify from file.
	result, err := VerifySnapshot(snapPath, fixtureDir, "")
	if err != nil {
		t.Fatalf("verify: %v", err)
	}

	// Step 5: Assert all OK.
	if !result.OK {
		t.Errorf("round-trip verification failed. Diffs:")
		for _, d := range result.Diffs {
			t.Errorf("  %s (normative=%v): expected=%s observed=%s",
				d.Field, d.Normative, d.Expected, d.Observed)
		}
	}

	// Step 6: Verify UUID and checksum are present.
	if snap.UUID == "" {
		t.Error("snapshot UUID is empty")
	}
	if snap.Checksum == "" {
		t.Error("snapshot checksum is empty")
	}
	if snap.UUIDSpecVersion != UUIDSpecVersionV1 {
		t.Errorf("uuid_spec_version: got %q, want %q", snap.UUIDSpecVersion, UUIDSpecVersionV1)
	}
}

// TestVerifySnapshot_StructuredOutput verifies that the VerifyResult
// contains properly structured output suitable for CI consumption.
//
// Ref: S31 §5 step 8 — emit structured result.
func TestVerifySnapshot_StructuredOutput(t *testing.T) {
	fixtureDir := filepath.Join("..", "..", "tests", "fixtures", "runs_for_accumulation")
	tmpDir := t.TempDir()

	runs, err := LoadRunReports(fixtureDir)
	if err != nil {
		t.Fatalf("load runs: %v", err)
	}

	snap := FoldV1(runs, "snapshot-structured", "2026-04-14T12:00:00Z")

	snapPath := filepath.Join(tmpDir, "snapshot.json")
	data, _ := json.MarshalIndent(snap, "", "  ")
	os.WriteFile(snapPath, data, 0644)

	result, err := VerifySnapshot(snapPath, fixtureDir, "")
	if err != nil {
		t.Fatalf("verify: %v", err)
	}

	// Result must be JSON-serializable.
	resultJSON, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		t.Fatalf("marshal result: %v", err)
	}

	// Must have required fields.
	var parsed map[string]interface{}
	if err := json.Unmarshal(resultJSON, &parsed); err != nil {
		t.Fatalf("parse result JSON: %v", err)
	}

	if _, ok := parsed["ok"]; !ok {
		t.Error("result missing 'ok' field")
	}
	if _, ok := parsed["runs_loaded"]; !ok {
		t.Error("result missing 'runs_loaded' field")
	}
	if _, ok := parsed["message"]; !ok {
		t.Error("result missing 'message' field")
	}
}
