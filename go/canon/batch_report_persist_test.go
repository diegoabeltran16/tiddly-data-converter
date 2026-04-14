package canon_test

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"github.com/tiddly-data-converter/canon"
)

// ---------------------------------------------------------------------------
// S26 — canon-gate-batch-report-persist-v0
//
// Tests for the minimal persistence seam of BatchReport as JSON artifact.
//
// Coverage:
//   A. WriteBatchReportJSON — valid report serializes to parseable JSON
//   B. Round-trip JSON → struct preserves content
//   C. Empty report is serializable
//   D. Writer failure propagates error
//   E. WriteBatchReportFile writes valid artifact
//   F. File artifact can be read and parsed
//   G. No mutation of original struct during write
//   H. File wrapper error on invalid path
//   I. Trailing newline convention
//   J. Mixed batch round-trip
//
// Ref: S26 — batch report persist tests.
// Ref: S23 — BatchReport shape.
// Ref: S25 — batch contract freeze v1.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// buildMixedReport creates a representative BatchReport with both accepted
// and rejected entries for testing.
func buildMixedReport() canon.BatchReport {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Good1"), Title: "Good1", Text: strPtr("ok")},
		{Key: "", Title: ""},
		{Key: canon.KeyOf("Good2"), Title: "Good2"},
		{Key: canon.KeyOf("NoTitle"), Title: ""},
	}
	audit := canon.AuditBatch(entries)
	return canon.BuildBatchReport(audit)
}

// errWriter is a writer that always returns an error.
type errWriter struct{}

func (errWriter) Write([]byte) (int, error) {
	return 0, errors.New("simulated write failure")
}

// ---------------------------------------------------------------------------
// A. Valid report serializes to parseable JSON
// ---------------------------------------------------------------------------

// TestWriteBatchReportJSON_ValidReport validates that a non-trivial
// BatchReport serializes to valid, parseable JSON.
//
// Ref: S26 — test case 1.
func TestWriteBatchReportJSON_ValidReport(t *testing.T) {
	report := buildMixedReport()
	var buf bytes.Buffer

	err := canon.WriteBatchReportJSON(&buf, report)
	if err != nil {
		t.Fatalf("WriteBatchReportJSON: unexpected error: %v", err)
	}

	// Output must be valid JSON.
	if !json.Valid(buf.Bytes()) {
		t.Fatalf("output is not valid JSON:\n%s", buf.String())
	}
}

// ---------------------------------------------------------------------------
// B. Round-trip JSON → struct preserves content
// ---------------------------------------------------------------------------

// TestWriteBatchReportJSON_RoundTrip validates that serializing and then
// deserializing a BatchReport preserves all relevant fields.
//
// Ref: S26 — test case 2.
func TestWriteBatchReportJSON_RoundTrip(t *testing.T) {
	original := buildMixedReport()
	var buf bytes.Buffer

	if err := canon.WriteBatchReportJSON(&buf, original); err != nil {
		t.Fatalf("WriteBatchReportJSON: %v", err)
	}

	var restored canon.BatchReport
	if err := json.Unmarshal(buf.Bytes(), &restored); err != nil {
		t.Fatalf("json.Unmarshal: %v", err)
	}

	if restored.Total != original.Total {
		t.Errorf("Total: got %d, want %d", restored.Total, original.Total)
	}
	if restored.Accepted != original.Accepted {
		t.Errorf("Accepted: got %d, want %d", restored.Accepted, original.Accepted)
	}
	if restored.Rejected != original.Rejected {
		t.Errorf("Rejected: got %d, want %d", restored.Rejected, original.Rejected)
	}
	if !reflect.DeepEqual(restored.AcceptedTitles, original.AcceptedTitles) {
		t.Errorf("AcceptedTitles: got %v, want %v", restored.AcceptedTitles, original.AcceptedTitles)
	}
	if !reflect.DeepEqual(restored.RejectedEntries, original.RejectedEntries) {
		t.Errorf("RejectedEntries: got %v, want %v", restored.RejectedEntries, original.RejectedEntries)
	}
	if !reflect.DeepEqual(restored.RejectsByReason, original.RejectsByReason) {
		t.Errorf("RejectsByReason: got %v, want %v", restored.RejectsByReason, original.RejectsByReason)
	}
}

// ---------------------------------------------------------------------------
// C. Empty report is serializable
// ---------------------------------------------------------------------------

// TestWriteBatchReportJSON_EmptyReport validates that an empty BatchReport
// (Total=0, no entries) produces valid JSON.
//
// Ref: S26 — test case 3.
func TestWriteBatchReportJSON_EmptyReport(t *testing.T) {
	audit := canon.AuditBatch([]canon.CanonEntry{})
	report := canon.BuildBatchReport(audit)
	var buf bytes.Buffer

	if err := canon.WriteBatchReportJSON(&buf, report); err != nil {
		t.Fatalf("WriteBatchReportJSON: %v", err)
	}
	if !json.Valid(buf.Bytes()) {
		t.Fatalf("empty report output is not valid JSON:\n%s", buf.String())
	}

	var restored canon.BatchReport
	if err := json.Unmarshal(buf.Bytes(), &restored); err != nil {
		t.Fatalf("json.Unmarshal: %v", err)
	}
	if restored.Total != 0 {
		t.Errorf("Total: got %d, want 0", restored.Total)
	}
}

// ---------------------------------------------------------------------------
// D. Writer failure propagates error
// ---------------------------------------------------------------------------

// TestWriteBatchReportJSON_WriterError validates that an error from the
// underlying writer is propagated.
//
// Ref: S26 — test case 4.
func TestWriteBatchReportJSON_WriterError(t *testing.T) {
	report := buildMixedReport()
	err := canon.WriteBatchReportJSON(errWriter{}, report)
	if err == nil {
		t.Fatal("expected error from failing writer, got nil")
	}
}

// ---------------------------------------------------------------------------
// E. WriteBatchReportFile writes valid artifact
// ---------------------------------------------------------------------------

// TestWriteBatchReportFile_Success validates that WriteBatchReportFile
// creates a file with valid JSON content.
//
// Ref: S26 — test case 5.
func TestWriteBatchReportFile_Success(t *testing.T) {
	report := buildMixedReport()
	dir := t.TempDir()
	path := filepath.Join(dir, "report.json")

	if err := canon.WriteBatchReportFile(path, report); err != nil {
		t.Fatalf("WriteBatchReportFile: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	if !json.Valid(data) {
		t.Fatalf("file content is not valid JSON:\n%s", string(data))
	}
}

// ---------------------------------------------------------------------------
// F. File artifact can be read and parsed
// ---------------------------------------------------------------------------

// TestWriteBatchReportFile_RoundTrip validates that the file written by
// WriteBatchReportFile can be read back and deserialized to the original.
//
// Ref: S26 — test case 6.
func TestWriteBatchReportFile_RoundTrip(t *testing.T) {
	original := buildMixedReport()
	dir := t.TempDir()
	path := filepath.Join(dir, "report.json")

	if err := canon.WriteBatchReportFile(path, original); err != nil {
		t.Fatalf("WriteBatchReportFile: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}

	var restored canon.BatchReport
	if err := json.Unmarshal(data, &restored); err != nil {
		t.Fatalf("json.Unmarshal: %v", err)
	}

	if restored.Total != original.Total {
		t.Errorf("Total: got %d, want %d", restored.Total, original.Total)
	}
	if restored.Accepted != original.Accepted {
		t.Errorf("Accepted: got %d, want %d", restored.Accepted, original.Accepted)
	}
	if restored.Rejected != original.Rejected {
		t.Errorf("Rejected: got %d, want %d", restored.Rejected, original.Rejected)
	}
	if !reflect.DeepEqual(restored.AcceptedTitles, original.AcceptedTitles) {
		t.Errorf("AcceptedTitles mismatch")
	}
	if !reflect.DeepEqual(restored.RejectedEntries, original.RejectedEntries) {
		t.Errorf("RejectedEntries mismatch")
	}
}

// ---------------------------------------------------------------------------
// G. No mutation of original struct during write
// ---------------------------------------------------------------------------

// TestWriteBatchReportJSON_NoMutation validates that the original
// BatchReport struct is not mutated during serialization.
//
// Ref: S26 — test case 7.
func TestWriteBatchReportJSON_NoMutation(t *testing.T) {
	original := buildMixedReport()

	// Deep-copy via JSON for comparison baseline.
	baseline, _ := json.Marshal(original)

	var buf bytes.Buffer
	if err := canon.WriteBatchReportJSON(&buf, original); err != nil {
		t.Fatalf("WriteBatchReportJSON: %v", err)
	}

	after, _ := json.Marshal(original)
	if !bytes.Equal(baseline, after) {
		t.Errorf("struct was mutated during write:\nbefore: %s\nafter:  %s",
			string(baseline), string(after))
	}
}

// ---------------------------------------------------------------------------
// H. File wrapper error on invalid path
// ---------------------------------------------------------------------------

// TestWriteBatchReportFile_InvalidPath validates that WriteBatchReportFile
// returns an error when the path is invalid or the directory does not exist.
//
// Ref: S26 — test case 8.
func TestWriteBatchReportFile_InvalidPath(t *testing.T) {
	report := buildMixedReport()
	err := canon.WriteBatchReportFile("/nonexistent/dir/report.json", report)
	if err == nil {
		t.Fatal("expected error for invalid path, got nil")
	}
}

// ---------------------------------------------------------------------------
// I. Trailing newline convention
// ---------------------------------------------------------------------------

// TestWriteBatchReportJSON_TrailingNewline validates that the output ends
// with a single newline character.
//
// Ref: S26 — trailing newline convention.
func TestWriteBatchReportJSON_TrailingNewline(t *testing.T) {
	report := buildMixedReport()
	var buf bytes.Buffer

	if err := canon.WriteBatchReportJSON(&buf, report); err != nil {
		t.Fatalf("WriteBatchReportJSON: %v", err)
	}

	data := buf.Bytes()
	if len(data) == 0 {
		t.Fatal("output is empty")
	}
	if data[len(data)-1] != '\n' {
		t.Errorf("output does not end with newline; last byte: %q", data[len(data)-1])
	}
}

// ---------------------------------------------------------------------------
// J. Mixed batch round-trip preserves reject reasons
// ---------------------------------------------------------------------------

// TestWriteBatchReportJSON_RoundTrip_RejectsByReason validates that the
// reason distribution survives a write/read cycle.
//
// Ref: S26 — reason distribution persistence.
func TestWriteBatchReportJSON_RoundTrip_RejectsByReason(t *testing.T) {
	original := buildMixedReport()
	if len(original.RejectsByReason) == 0 {
		t.Skip("test requires a report with rejections")
	}

	var buf bytes.Buffer
	if err := canon.WriteBatchReportJSON(&buf, original); err != nil {
		t.Fatalf("WriteBatchReportJSON: %v", err)
	}

	var restored canon.BatchReport
	if err := json.Unmarshal(buf.Bytes(), &restored); err != nil {
		t.Fatalf("json.Unmarshal: %v", err)
	}

	if len(restored.RejectsByReason) != len(original.RejectsByReason) {
		t.Fatalf("RejectsByReason length: got %d, want %d",
			len(restored.RejectsByReason), len(original.RejectsByReason))
	}
	for i := range original.RejectsByReason {
		if restored.RejectsByReason[i].Reason != original.RejectsByReason[i].Reason {
			t.Errorf("RejectsByReason[%d].Reason: got %q, want %q",
				i, restored.RejectsByReason[i].Reason, original.RejectsByReason[i].Reason)
		}
		if restored.RejectsByReason[i].Count != original.RejectsByReason[i].Count {
			t.Errorf("RejectsByReason[%d].Count: got %d, want %d",
				i, restored.RejectsByReason[i].Count, original.RejectsByReason[i].Count)
		}
	}
}

// ---------------------------------------------------------------------------
// K. Nil batch audit produces serializable report
// ---------------------------------------------------------------------------

// TestWriteBatchReportJSON_NilAuditReport validates that a report built
// from a nil audit can be serialized and deserialized.
//
// Ref: S26 — defensive nil handling.
func TestWriteBatchReportJSON_NilAuditReport(t *testing.T) {
	audit := canon.AuditBatch(nil)
	report := canon.BuildBatchReport(audit)
	var buf bytes.Buffer

	if err := canon.WriteBatchReportJSON(&buf, report); err != nil {
		t.Fatalf("WriteBatchReportJSON: %v", err)
	}

	var restored canon.BatchReport
	if err := json.Unmarshal(buf.Bytes(), &restored); err != nil {
		t.Fatalf("json.Unmarshal: %v", err)
	}
	if restored.Total != 0 {
		t.Errorf("Total: got %d, want 0", restored.Total)
	}
}
