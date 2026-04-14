package canon

// ---------------------------------------------------------------------------
// S31 — canon-accumulate-replay-verify-and-ci-v0
//
// Structured replay verification for batch_snapshot values.
//
// Given a snapshot file and the source run_report inputs, VerifySnapshot
// reconstructs the expected snapshot via FoldV1 and performs a field-by-field
// comparison against the observed snapshot. Fields are classified as
// normative (must match exactly) or informational (differences reported
// but do not fail verification).
//
// Truth respected from S29/S30:
//   - Fold order: (start_time, run_id) ascending.
//   - Checksum: sha256(CanonicalJSON(snapshot with checksum="")).
//   - UUIDv5: deterministic from canonical payload (S30).
//   - uuid_spec_version: "v1".
//
// Ref: S29 — truth pin (fold order, checksum rule).
// Ref: S30 — UUIDv5 and canonical JSON.
// Ref: S31 — replay verification and CI.
// ---------------------------------------------------------------------------

import (
	"encoding/json"
	"fmt"
	"os"
	"reflect"
)

// FieldDiff records a difference between expected and observed values
// for a single field in a batch_snapshot.
type FieldDiff struct {
	Field    string `json:"field"`
	Expected string `json:"expected"`
	Observed string `json:"observed"`
	// Normative indicates whether this field is normatively required to match.
	// If true, a mismatch constitutes a verification failure.
	Normative bool `json:"normative"`
}

// VerifyResult holds the structured outcome of a replay verification.
type VerifyResult struct {
	OK         bool        `json:"ok"`
	Diffs      []FieldDiff `json:"diffs,omitempty"`
	RunsLoaded int         `json:"runs_loaded"`
	Message    string      `json:"message"`
}

// VerifySnapshot loads an observed snapshot from snapshotPath, loads
// run_report inputs from inputDir, reconstructs the expected snapshot
// via FoldV1 using the observed snapshot's snapshot_id and as_of, and
// performs a field-by-field comparison.
//
// The function uses the observed snapshot's snapshot_id and as_of to
// ensure the replay produces identical non-normative fields too, making
// the comparison maximally strict.
//
// Ref: S31 §5.1 — verify behavior specification.
func VerifySnapshot(snapshotPath, inputDir, batchID string) (*VerifyResult, error) {
	// Step 1: load observed snapshot.
	observed, err := LoadSnapshot(snapshotPath)
	if err != nil {
		return nil, fmt.Errorf("verify: load snapshot: %w", err)
	}

	// Step 2: load source inputs.
	runs, err := LoadRunReports(inputDir)
	if err != nil {
		return nil, fmt.Errorf("verify: load inputs: %w", err)
	}

	// Step 2b: filter by batch_id if specified.
	if batchID != "" {
		var filtered []RunReport
		for _, r := range runs {
			if r.BatchID == batchID {
				filtered = append(filtered, r)
			}
		}
		runs = filtered
	}

	if len(runs) == 0 {
		return nil, fmt.Errorf("verify: no run_reports found after filtering")
	}

	// Step 3-6: reconstruct expected snapshot using observed's snapshot_id
	// and as_of to eliminate trivial differences.
	expected := FoldV1(runs, observed.SnapshotID, observed.AsOf)

	// Step 7: compare expected vs observed.
	result := compareSnapshots(expected, observed, len(runs))

	return result, nil
}

// LoadSnapshot reads and parses a BatchSnapshot from a JSON file.
func LoadSnapshot(path string) (BatchSnapshot, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return BatchSnapshot{}, fmt.Errorf("load snapshot %q: %w", path, err)
	}
	var snap BatchSnapshot
	if err := json.Unmarshal(data, &snap); err != nil {
		return BatchSnapshot{}, fmt.Errorf("parse snapshot %q: %w", path, err)
	}
	return snap, nil
}

// compareSnapshots performs field-by-field comparison between expected
// and observed snapshots, classifying each difference as normative or
// informational.
func compareSnapshots(expected, observed BatchSnapshot, runsLoaded int) *VerifyResult {
	result := &VerifyResult{
		OK:         true,
		RunsLoaded: runsLoaded,
	}

	// Compare normative scalar fields.
	compareField(result, "uuid", expected.UUID, observed.UUID, true)
	compareField(result, "uuid_spec_version", expected.UUIDSpecVersion, observed.UUIDSpecVersion, true)
	compareField(result, "checksum", expected.Checksum, observed.Checksum, true)
	compareField(result, "first_seen", expected.FirstSeen, observed.FirstSeen, true)
	compareField(result, "last_seen", expected.LastSeen, observed.LastSeen, true)

	// Compare normative structured fields.
	compareSlice(result, "runs_included", expected.RunsIncluded, observed.RunsIncluded, true)
	compareSlice(result, "batches_included", expected.BatchesIncluded, observed.BatchesIncluded, true)

	// Compare metrics aggregate (normative).
	compareJSON(result, "metrics_aggregate", expected.MetricsAggregate, observed.MetricsAggregate, true)

	// Compare rejected aggregate (normative).
	compareJSON(result, "rejected_by_reason_aggregate", expected.RejectedAggregate, observed.RejectedAggregate, true)

	// Compare top_errors (normative — derived from rejected aggregate).
	compareJSON(result, "top_errors", expected.TopErrors, observed.TopErrors, true)

	// Compare provenance (normative).
	compareJSON(result, "provenance", expected.Provenance, observed.Provenance, true)

	// Compare non-normative fields (differences reported but don't fail).
	compareField(result, "snapshot_id", expected.SnapshotID, observed.SnapshotID, false)
	compareField(result, "as_of", expected.AsOf, observed.AsOf, false)

	// Set summary message.
	normDiffs := 0
	infoDiffs := 0
	for _, d := range result.Diffs {
		if d.Normative {
			normDiffs++
		} else {
			infoDiffs++
		}
	}

	if result.OK {
		result.Message = fmt.Sprintf("VERIFY OK — all normative fields match (%d runs replayed)", runsLoaded)
		if infoDiffs > 0 {
			result.Message += fmt.Sprintf(", %d non-normative differences noted", infoDiffs)
		}
	} else {
		result.Message = fmt.Sprintf("VERIFY FAILED — %d normative field(s) differ, %d non-normative", normDiffs, infoDiffs)
	}

	return result
}

// compareField compares two string values and records a diff if they differ.
func compareField(result *VerifyResult, field, expected, observed string, normative bool) {
	if expected != observed {
		result.Diffs = append(result.Diffs, FieldDiff{
			Field:     field,
			Expected:  expected,
			Observed:  observed,
			Normative: normative,
		})
		if normative {
			result.OK = false
		}
	}
}

// compareSlice compares two string slices and records a diff if they differ.
func compareSlice(result *VerifyResult, field string, expected, observed []string, normative bool) {
	if !reflect.DeepEqual(expected, observed) {
		expJSON, err1 := json.Marshal(expected)
		obsJSON, err2 := json.Marshal(observed)
		if err1 != nil || err2 != nil {
			expJSON = []byte(fmt.Sprintf("%v", expected))
			obsJSON = []byte(fmt.Sprintf("%v", observed))
		}
		result.Diffs = append(result.Diffs, FieldDiff{
			Field:     field,
			Expected:  string(expJSON),
			Observed:  string(obsJSON),
			Normative: normative,
		})
		if normative {
			result.OK = false
		}
	}
}

// compareJSON compares two values by their JSON serialization.
func compareJSON(result *VerifyResult, field string, expected, observed interface{}, normative bool) {
	expJSON, err1 := json.Marshal(expected)
	obsJSON, err2 := json.Marshal(observed)
	if err1 != nil || err2 != nil {
		expJSON = []byte(fmt.Sprintf("%v", expected))
		obsJSON = []byte(fmt.Sprintf("%v", observed))
	}
	if string(expJSON) != string(obsJSON) {
		result.Diffs = append(result.Diffs, FieldDiff{
			Field:     field,
			Expected:  string(expJSON),
			Observed:  string(obsJSON),
			Normative: normative,
		})
		if normative {
			result.OK = false
		}
	}
}
