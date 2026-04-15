package canon_test

// ---------------------------------------------------------------------------
// S32 — canon-freeze-baseline-oracle-and-first-jsonl-v0
//
// Baseline oracle tests that verify the committed golden files in
// tests/golden/baseline/v1/ match the deterministic output produced
// by FoldV1 from the frozen input fixtures.
//
// These tests are the in-process equivalent of scripts/baseline_verify.sh.
// They ensure that any change to accumulation logic, canonical JSON, UUID
// computation, or checksum rules is immediately detected as a regression.
//
// Truth respected from S29/S30 (immutable):
//   - Fold order: (start_time, run_id) ascending.
//   - Checksum: sha256(CanonicalJSON(snapshot with checksum="")).
//   - UUIDv5: deterministic from canonical payload.
//   - uuid_spec_version: "v1".
//
// Ref: S29 — truth pin.
// Ref: S30 — UUIDv5 and canonical JSON.
// Ref: S31 — replay verification.
// Ref: S32 — baseline oracle.
// ---------------------------------------------------------------------------

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/tiddly-data-converter/canon"
)

// baselineFixturesDir returns the absolute path to the baseline input fixtures.
func baselineFixturesDir(t *testing.T) string {
	t.Helper()
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot determine test file path")
	}
	return filepath.Join(filepath.Dir(thisFile), "..", "..", "tests", "fixtures", "baseline", "v1", "input")
}

// goldenDir returns the absolute path to the golden baseline outputs.
func goldenDir(t *testing.T) string {
	t.Helper()
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot determine test file path")
	}
	return filepath.Join(filepath.Dir(thisFile), "..", "..", "tests", "golden", "baseline", "v1")
}

// Deterministic parameters matching manifest.json.
const (
	baselineSnapshotID = "canon-baseline-v1"
	baselineAsOf       = "2026-04-14T00:00:00Z"
)

// TestBaselineOracleSnapshotMatch verifies that FoldV1 with the frozen
// inputs produces an identical batch_snapshot.json to the committed golden file.
func TestBaselineOracleSnapshotMatch(t *testing.T) {
	inputDir := baselineFixturesDir(t)
	goldenPath := filepath.Join(goldenDir(t), "batch_snapshot.json")

	// Load frozen inputs.
	runs, err := canon.LoadRunReports(inputDir)
	if err != nil {
		t.Fatalf("load inputs: %v", err)
	}
	if len(runs) == 0 {
		t.Fatal("no run_reports found in baseline fixtures")
	}

	// Regenerate snapshot with deterministic parameters.
	snap := canon.FoldV1(runs, baselineSnapshotID, baselineAsOf)

	// Serialize regenerated snapshot.
	regenData, err := json.MarshalIndent(snap, "", "  ")
	if err != nil {
		t.Fatalf("marshal regenerated snapshot: %v", err)
	}
	regenData = append(regenData, '\n')

	// Load committed golden snapshot.
	goldenData, err := os.ReadFile(goldenPath)
	if err != nil {
		t.Fatalf("read golden snapshot: %v", err)
	}

	// Byte-for-byte comparison.
	if string(regenData) != string(goldenData) {
		t.Errorf("batch_snapshot.json REGRESSION DETECTED\n"+
			"  regenerated checksum: %s\n"+
			"  Run scripts/baseline_regen.sh to update golden files after review",
			snap.Checksum)
	}
}

// TestBaselineOracleJSONLMatch verifies that the canonical JSONL export
// of the regenerated snapshot matches the committed golden export.jsonl.
func TestBaselineOracleJSONLMatch(t *testing.T) {
	inputDir := baselineFixturesDir(t)
	goldenPath := filepath.Join(goldenDir(t), "export.jsonl")

	// Load frozen inputs.
	runs, err := canon.LoadRunReports(inputDir)
	if err != nil {
		t.Fatalf("load inputs: %v", err)
	}

	// Regenerate snapshot with deterministic parameters.
	snap := canon.FoldV1(runs, baselineSnapshotID, baselineAsOf)

	// Serialize as canonical JSONL line.
	canonical, err := canon.CanonicalJSON(snap)
	if err != nil {
		t.Fatalf("canonical json: %v", err)
	}
	canonical = append(canonical, '\n')

	// Load committed golden JSONL.
	goldenData, err := os.ReadFile(goldenPath)
	if err != nil {
		t.Fatalf("read golden jsonl: %v", err)
	}

	// Byte-for-byte comparison.
	if string(canonical) != string(goldenData) {
		t.Error("export.jsonl REGRESSION DETECTED\n" +
			"  Run scripts/baseline_regen.sh to update golden files after review")
	}
}

// TestBaselineOracleReplayVerify uses the S31 VerifySnapshot function
// to verify the committed golden snapshot via structured replay.
func TestBaselineOracleReplayVerify(t *testing.T) {
	inputDir := baselineFixturesDir(t)
	goldenPath := filepath.Join(goldenDir(t), "batch_snapshot.json")

	result, err := canon.VerifySnapshot(goldenPath, inputDir, "")
	if err != nil {
		t.Fatalf("verify: %v", err)
	}

	if !result.OK {
		t.Errorf("replay verification failed: %s", result.Message)
		for _, d := range result.Diffs {
			if d.Normative {
				t.Errorf("  normative diff in %s: expected=%s observed=%s",
					d.Field, d.Expected, d.Observed)
			}
		}
	}

	if result.RunsLoaded != 3 {
		t.Errorf("expected 3 runs loaded, got %d", result.RunsLoaded)
	}
}

// TestBaselineOracleManifestConsistency verifies that the manifest.json
// metadata is consistent with the golden snapshot.
func TestBaselineOracleManifestConsistency(t *testing.T) {
	golden := goldenDir(t)
	goldenPath := filepath.Join(golden, "batch_snapshot.json")

	// Load manifest.
	manifestPath := filepath.Join(golden, "..", "..", "..", "fixtures", "baseline", "v1", "manifest.json")
	manifestData, err := os.ReadFile(manifestPath)
	if err != nil {
		t.Fatalf("read manifest: %v", err)
	}

	var manifest struct {
		BaselineVersion     string `json:"baseline_version"`
		SnapshotID          string `json:"snapshot_id"`
		AsOf                string `json:"as_of"`
		AccumulationVersion string `json:"accumulation_version"`
		AccumulationAlgo    string `json:"accumulation_algo"`
		RunsCount           int    `json:"runs_count"`
		UUIDSpecVersion     string `json:"uuid_spec_version"`
	}
	if err := json.Unmarshal(manifestData, &manifest); err != nil {
		t.Fatalf("parse manifest: %v", err)
	}

	// Load golden snapshot.
	snap, err := canon.LoadSnapshot(goldenPath)
	if err != nil {
		t.Fatalf("load golden snapshot: %v", err)
	}

	// Verify consistency.
	if manifest.SnapshotID != snap.SnapshotID {
		t.Errorf("manifest.snapshot_id=%q != snapshot.snapshot_id=%q", manifest.SnapshotID, snap.SnapshotID)
	}
	if manifest.AsOf != snap.AsOf {
		t.Errorf("manifest.as_of=%q != snapshot.as_of=%q", manifest.AsOf, snap.AsOf)
	}
	if manifest.AccumulationVersion != snap.Provenance.AccumulationVersion {
		t.Errorf("manifest.accumulation_version=%q != snapshot.provenance.accumulation_version=%q",
			manifest.AccumulationVersion, snap.Provenance.AccumulationVersion)
	}
	if manifest.AccumulationAlgo != snap.Provenance.AccumulationAlgo {
		t.Errorf("manifest.accumulation_algo=%q != snapshot.provenance.accumulation_algo=%q",
			manifest.AccumulationAlgo, snap.Provenance.AccumulationAlgo)
	}
	if manifest.RunsCount != len(snap.RunsIncluded) {
		t.Errorf("manifest.runs_count=%d != len(snapshot.runs_included)=%d",
			manifest.RunsCount, len(snap.RunsIncluded))
	}
	if manifest.UUIDSpecVersion != snap.UUIDSpecVersion {
		t.Errorf("manifest.uuid_spec_version=%q != snapshot.uuid_spec_version=%q",
			manifest.UUIDSpecVersion, snap.UUIDSpecVersion)
	}
}

// TestBaselineOracleDeterminism verifies that running FoldV1 twice
// with the same inputs and parameters produces byte-identical output.
func TestBaselineOracleDeterminism(t *testing.T) {
	inputDir := baselineFixturesDir(t)

	runs, err := canon.LoadRunReports(inputDir)
	if err != nil {
		t.Fatalf("load inputs: %v", err)
	}

	snap1 := canon.FoldV1(runs, baselineSnapshotID, baselineAsOf)
	snap2 := canon.FoldV1(runs, baselineSnapshotID, baselineAsOf)

	data1, _ := json.Marshal(snap1)
	data2, _ := json.Marshal(snap2)

	if string(data1) != string(data2) {
		t.Error("FoldV1 is not deterministic: two runs with identical inputs produced different output")
	}

	if snap1.Checksum != snap2.Checksum {
		t.Errorf("checksum mismatch: %s vs %s", snap1.Checksum, snap2.Checksum)
	}

	if snap1.UUID != snap2.UUID {
		t.Errorf("UUID mismatch: %s vs %s", snap1.UUID, snap2.UUID)
	}
}
