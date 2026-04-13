package canon_test

import (
	"bufio"
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/tiddly-data-converter/canon"
)

// ---------------------------------------------------------------------------
// S24 — canon-gate-batch-emit-v0
//
// Integration tests for the minimal batch emission seam (EmitBatchV0).
// Validates that the full pipeline — audit → report → filter → write —
// produces correct, observable, deterministic results.
//
// Ref: S24 — costura mínima de emisión por lote.
// Ref: S22 — AuditBatch.
// Ref: S23 — BuildBatchReport.
// Ref: S16 — WriteJSONL.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// A. EmitBatchV0 — core cases
// ---------------------------------------------------------------------------

// TestEmitBatchV0_EmptyBatch validates that an empty batch produces a valid
// result with all counters at zero and no output written.
//
// Ref: S24 — empty batch emission.
func TestEmitBatchV0_EmptyBatch(t *testing.T) {
	var buf bytes.Buffer
	result, err := canon.EmitBatchV0(&buf, []canon.CanonEntry{})
	if err != nil {
		t.Fatalf("EmitBatchV0: unexpected error: %v", err)
	}

	if result.Total != 0 {
		t.Errorf("Total: got %d, want 0", result.Total)
	}
	if result.Accepted != 0 {
		t.Errorf("Accepted: got %d, want 0", result.Accepted)
	}
	if result.Rejected != 0 {
		t.Errorf("Rejected: got %d, want 0", result.Rejected)
	}
	if result.Written != 0 {
		t.Errorf("Written: got %d, want 0", result.Written)
	}
	if buf.Len() != 0 {
		t.Errorf("expected empty output, got %q", buf.String())
	}
}

// TestEmitBatchV0_NilBatch validates that a nil slice is handled as an
// empty batch.
//
// Ref: S24 — defensive handling.
func TestEmitBatchV0_NilBatch(t *testing.T) {
	var buf bytes.Buffer
	result, err := canon.EmitBatchV0(&buf, nil)
	if err != nil {
		t.Fatalf("EmitBatchV0: unexpected error: %v", err)
	}

	if result.Total != 0 {
		t.Errorf("Total: got %d, want 0", result.Total)
	}
	if result.Written != 0 {
		t.Errorf("Written: got %d, want 0", result.Written)
	}
	if buf.Len() != 0 {
		t.Errorf("expected empty output, got %q", buf.String())
	}
}

// TestEmitBatchV0_AllValid validates that a batch with all valid entries
// produces output for every entry.
//
// Ref: S24 — all-accept batch emission.
func TestEmitBatchV0_AllValid(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A", Text: strPtr("body A")},
		{Key: canon.KeyOf("B"), Title: "B"},
		{Key: canon.KeyOf("C"), Title: "C", Text: strPtr("body C")},
	}

	var buf bytes.Buffer
	result, err := canon.EmitBatchV0(&buf, entries)
	if err != nil {
		t.Fatalf("EmitBatchV0: unexpected error: %v", err)
	}

	if result.Total != 3 {
		t.Errorf("Total: got %d, want 3", result.Total)
	}
	if result.Accepted != 3 {
		t.Errorf("Accepted: got %d, want 3", result.Accepted)
	}
	if result.Rejected != 0 {
		t.Errorf("Rejected: got %d, want 0", result.Rejected)
	}
	if result.Written != 3 {
		t.Errorf("Written: got %d, want 3", result.Written)
	}

	// Verify 3 JSONL lines written.
	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 3 {
		t.Fatalf("expected 3 JSONL lines, got %d", len(lines))
	}

	// Verify titles in order.
	wantTitles := []string{"A", "B", "C"}
	for i, line := range lines {
		var ce canon.CanonEntry
		if err := json.Unmarshal([]byte(line), &ce); err != nil {
			t.Errorf("line %d: invalid JSON: %v", i, err)
			continue
		}
		if ce.Title != wantTitles[i] {
			t.Errorf("line %d: title = %q, want %q", i, ce.Title, wantTitles[i])
		}
		if ce.SchemaVersion != canon.SchemaV0 {
			t.Errorf("line %d: schema_version = %q, want %q", i, ce.SchemaVersion, canon.SchemaV0)
		}
	}
}

// TestEmitBatchV0_AllInvalid validates that a batch where all entries are
// invalid produces zero output and correct rejection counters.
//
// Ref: S24 — all-reject batch emission.
func TestEmitBatchV0_AllInvalid(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: "", Title: ""},
		{Key: "", Title: "NoKey"},
		{Key: canon.KeyOf("NoTitle"), Title: ""},
	}

	var buf bytes.Buffer
	result, err := canon.EmitBatchV0(&buf, entries)
	if err != nil {
		t.Fatalf("EmitBatchV0: unexpected error: %v", err)
	}

	if result.Total != 3 {
		t.Errorf("Total: got %d, want 3", result.Total)
	}
	if result.Accepted != 0 {
		t.Errorf("Accepted: got %d, want 0", result.Accepted)
	}
	if result.Rejected != 3 {
		t.Errorf("Rejected: got %d, want 3", result.Rejected)
	}
	if result.Written != 0 {
		t.Errorf("Written: got %d, want 0", result.Written)
	}
	if buf.Len() != 0 {
		t.Errorf("expected empty output for all-invalid batch, got %q", buf.String())
	}
}

// TestEmitBatchV0_MixedBatch validates the core mixed-batch scenario:
// only accepted entries are written; rejected entries produce no output.
//
// Ref: S24 — mixed batch emission.
func TestEmitBatchV0_MixedBatch(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Good1"), Title: "Good1", Text: strPtr("ok")},              // 0: accept
		{Key: "", Title: ""},                                                          // 1: reject (key)
		{Key: canon.KeyOf("Good2"), Title: "Good2"},                                  // 2: accept
		{Key: canon.KeyOf("BadTitle"), Title: ""},                                    // 3: reject (title)
		{SchemaVersion: "v99", Key: canon.KeyOf("BadVer"), Title: "BadVer"},          // 4: reject (version)
		{Key: canon.KeyOf("Good3"), Title: "Good3", Text: strPtr("also ok")},         // 5: accept
	}

	var buf bytes.Buffer
	result, err := canon.EmitBatchV0(&buf, entries)
	if err != nil {
		t.Fatalf("EmitBatchV0: unexpected error: %v", err)
	}

	// Counter checks.
	if result.Total != 6 {
		t.Errorf("Total: got %d, want 6", result.Total)
	}
	if result.Accepted != 3 {
		t.Errorf("Accepted: got %d, want 3", result.Accepted)
	}
	if result.Rejected != 3 {
		t.Errorf("Rejected: got %d, want 3", result.Rejected)
	}
	if result.Written != 3 {
		t.Errorf("Written: got %d, want 3", result.Written)
	}

	// Verify written == accepted.
	if result.Written != result.Accepted {
		t.Errorf("Written (%d) != Accepted (%d)", result.Written, result.Accepted)
	}

	// Verify only accepted entries were emitted, in order.
	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 3 {
		t.Fatalf("expected 3 JSONL lines, got %d", len(lines))
	}
	wantTitles := []string{"Good1", "Good2", "Good3"}
	for i, line := range lines {
		var ce canon.CanonEntry
		if err := json.Unmarshal([]byte(line), &ce); err != nil {
			t.Errorf("line %d: invalid JSON: %v", i, err)
			continue
		}
		if ce.Title != wantTitles[i] {
			t.Errorf("line %d: title = %q, want %q", i, ce.Title, wantTitles[i])
		}
	}
}

// ---------------------------------------------------------------------------
// B. Written == Accepted invariant
// ---------------------------------------------------------------------------

// TestEmitBatchV0_WrittenEqualsAccepted validates the critical invariant:
// Written count must equal Accepted count (unless I/O error interrupts).
//
// Ref: S24 — written == accepted invariant.
func TestEmitBatchV0_WrittenEqualsAccepted(t *testing.T) {
	cases := []struct {
		name    string
		entries []canon.CanonEntry
	}{
		{
			name:    "all_valid",
			entries: []canon.CanonEntry{
				{Key: canon.KeyOf("A"), Title: "A"},
				{Key: canon.KeyOf("B"), Title: "B"},
			},
		},
		{
			name:    "all_invalid",
			entries: []canon.CanonEntry{
				{Key: "", Title: ""},
				{Key: "", Title: "x"},
			},
		},
		{
			name:    "mixed",
			entries: []canon.CanonEntry{
				{Key: canon.KeyOf("A"), Title: "A"},
				{Key: "", Title: ""},
				{Key: canon.KeyOf("C"), Title: "C"},
			},
		},
		{
			name:    "empty",
			entries: []canon.CanonEntry{},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var buf bytes.Buffer
			result, err := canon.EmitBatchV0(&buf, tc.entries)
			if err != nil {
				t.Fatalf("EmitBatchV0: unexpected error: %v", err)
			}
			if result.Written != result.Accepted {
				t.Errorf("Written (%d) != Accepted (%d)", result.Written, result.Accepted)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// C. Order preservation
// ---------------------------------------------------------------------------

// TestEmitBatchV0_PreservesAcceptedOrder validates that accepted entries
// appear in the output in the same relative order as in the input batch.
//
// Ref: S24 — stable order for accepted entries.
func TestEmitBatchV0_PreservesAcceptedOrder(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("First"), Title: "First"},
		{Key: "", Title: "Invalid"},
		{Key: canon.KeyOf("Second"), Title: "Second"},
		{Key: canon.KeyOf("Third"), Title: "Third"},
		{Key: "", Title: "AlsoInvalid"},
		{Key: canon.KeyOf("Fourth"), Title: "Fourth"},
	}

	var buf bytes.Buffer
	result, err := canon.EmitBatchV0(&buf, entries)
	if err != nil {
		t.Fatalf("EmitBatchV0: unexpected error: %v", err)
	}

	if result.Written != 4 {
		t.Fatalf("Written: got %d, want 4", result.Written)
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	wantOrder := []string{"First", "Second", "Third", "Fourth"}
	for i, line := range lines {
		var ce canon.CanonEntry
		if err := json.Unmarshal([]byte(line), &ce); err != nil {
			t.Errorf("line %d: invalid JSON: %v", i, err)
			continue
		}
		if ce.Title != wantOrder[i] {
			t.Errorf("line %d: title = %q, want %q", i, ce.Title, wantOrder[i])
		}
	}
}

// ---------------------------------------------------------------------------
// D. Rejected entries do not contaminate output
// ---------------------------------------------------------------------------

// TestEmitBatchV0_RejectedNotWritten validates that no rejected entry
// appears in the output.
//
// Ref: S24 — rejected entries never written.
func TestEmitBatchV0_RejectedNotWritten(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Good"), Title: "Good"},
		{Key: "", Title: "BadNoKey"},
		{Key: canon.KeyOf("BadNoTitle"), Title: ""},
		{SchemaVersion: "v99", Key: canon.KeyOf("BadVer"), Title: "BadVer"},
	}

	var buf bytes.Buffer
	_, err := canon.EmitBatchV0(&buf, entries)
	if err != nil {
		t.Fatalf("EmitBatchV0: unexpected error: %v", err)
	}

	output := buf.String()
	// "BadNoKey" appears as a title in rejected entries; must not appear in output.
	if strings.Contains(output, "BadNoKey") {
		t.Error("rejected entry 'BadNoKey' found in output")
	}
	if strings.Contains(output, "BadNoTitle") {
		t.Error("rejected entry 'BadNoTitle' found in output")
	}
	if strings.Contains(output, "BadVer") {
		t.Error("rejected entry 'BadVer' found in output")
	}
}

// ---------------------------------------------------------------------------
// E. Report consistency with emission result
// ---------------------------------------------------------------------------

// TestEmitBatchV0_ReportConsistentWithResult validates that the embedded
// report counters match the top-level emission counters.
//
// Ref: S24 — consistency between report and emission result.
func TestEmitBatchV0_ReportConsistentWithResult(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
		{Key: "", Title: "B"},
		{Key: canon.KeyOf("C"), Title: "C"},
	}

	var buf bytes.Buffer
	result, err := canon.EmitBatchV0(&buf, entries)
	if err != nil {
		t.Fatalf("EmitBatchV0: unexpected error: %v", err)
	}

	if result.Report.Total != result.Total {
		t.Errorf("Report.Total (%d) != Result.Total (%d)", result.Report.Total, result.Total)
	}
	if result.Report.Accepted != result.Accepted {
		t.Errorf("Report.Accepted (%d) != Result.Accepted (%d)", result.Report.Accepted, result.Accepted)
	}
	if result.Report.Rejected != result.Rejected {
		t.Errorf("Report.Rejected (%d) != Result.Rejected (%d)", result.Report.Rejected, result.Rejected)
	}
	if len(result.Report.AcceptedTitles) != result.Written {
		t.Errorf("Report.AcceptedTitles (%d) != Written (%d)",
			len(result.Report.AcceptedTitles), result.Written)
	}
}

// TestEmitBatchV0_AuditConsistentWithResult validates that the embedded
// audit counters match the top-level emission counters.
//
// Ref: S24 — consistency between audit and emission result.
func TestEmitBatchV0_AuditConsistentWithResult(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
		{Key: "", Title: "B"},
		{Key: canon.KeyOf("C"), Title: "C"},
		{Key: canon.KeyOf("D"), Title: ""},
	}

	var buf bytes.Buffer
	result, err := canon.EmitBatchV0(&buf, entries)
	if err != nil {
		t.Fatalf("EmitBatchV0: unexpected error: %v", err)
	}

	if result.Audit.Summary.Total != result.Total {
		t.Errorf("Audit.Total (%d) != Result.Total (%d)", result.Audit.Summary.Total, result.Total)
	}
	if result.Audit.Summary.Accepted != result.Accepted {
		t.Errorf("Audit.Accepted (%d) != Result.Accepted (%d)", result.Audit.Summary.Accepted, result.Accepted)
	}
	if result.Audit.Summary.Rejected != result.Rejected {
		t.Errorf("Audit.Rejected (%d) != Result.Rejected (%d)", result.Audit.Summary.Rejected, result.Rejected)
	}
}

// ---------------------------------------------------------------------------
// F. Fixture-backed emission
// ---------------------------------------------------------------------------

// TestEmitBatchV0_Fixture_MixedBatch loads the batch audit fixture
// and runs EmitBatchV0, verifying correct emission behavior.
//
// The fixture contains 10 lines:
//   - 5 valid entries → should be written
//   - 5 invalid entries → should be rejected
//
// Ref: S24 — fixture-backed emission evidence.
func TestEmitBatchV0_Fixture_MixedBatch(t *testing.T) {
	path := filepath.Join("..", "..", "tests", "fixtures", "canon_gate_batch_audit_mixed.jsonl")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("failed to read fixture %q: %v", path, err)
	}

	var entries []canon.CanonEntry
	scanner := bufio.NewScanner(bytes.NewReader(data))
	lineNum := 0
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		lineNum++
		var entry canon.CanonEntry
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			t.Fatalf("line %d: JSON parse error: %v", lineNum, err)
		}
		entries = append(entries, entry)
	}
	if err := scanner.Err(); err != nil {
		t.Fatalf("scanner error: %v", err)
	}
	if len(entries) != 10 {
		t.Fatalf("expected 10 entries in fixture, got %d", len(entries))
	}

	var buf bytes.Buffer
	result, err := canon.EmitBatchV0(&buf, entries)
	if err != nil {
		t.Fatalf("EmitBatchV0: unexpected error: %v", err)
	}

	// Summary checks.
	if result.Total != 10 {
		t.Errorf("Total: got %d, want 10", result.Total)
	}
	if result.Accepted != 5 {
		t.Errorf("Accepted: got %d, want 5", result.Accepted)
	}
	if result.Rejected != 5 {
		t.Errorf("Rejected: got %d, want 5", result.Rejected)
	}
	if result.Written != 5 {
		t.Errorf("Written: got %d, want 5", result.Written)
	}

	// Written == Accepted.
	if result.Written != result.Accepted {
		t.Errorf("Written (%d) != Accepted (%d)", result.Written, result.Accepted)
	}

	// Verify output lines.
	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 5 {
		t.Fatalf("expected 5 JSONL output lines, got %d", len(lines))
	}

	// Each line must be valid JSON with schema_version stamped.
	for i, line := range lines {
		var parsed canon.CanonEntry
		if err := json.Unmarshal([]byte(line), &parsed); err != nil {
			t.Errorf("line %d: invalid JSON: %v", i, err)
			continue
		}
		if parsed.SchemaVersion != canon.SchemaV0 {
			t.Errorf("line %d: schema_version = %q, want %q", i, parsed.SchemaVersion, canon.SchemaV0)
		}
		if err := canon.ValidateEntryV0(parsed); err != nil {
			t.Errorf("line %d: emitted entry fails ValidateEntryV0: %v", i, err)
		}
	}

	// Report consistency.
	if result.Report.Total != 10 {
		t.Errorf("Report.Total: got %d, want 10", result.Report.Total)
	}
	if len(result.Report.AcceptedTitles) != 5 {
		t.Errorf("Report.AcceptedTitles: got %d, want 5", len(result.Report.AcceptedTitles))
	}
	if len(result.Report.RejectedEntries) != 5 {
		t.Errorf("Report.RejectedEntries: got %d, want 5", len(result.Report.RejectedEntries))
	}

	t.Logf("Fixture emit: %s", canon.FormatEmitBatchResult(result))
}

// ---------------------------------------------------------------------------
// G. FormatEmitBatchResult observability
// ---------------------------------------------------------------------------

// TestFormatEmitBatchResult validates the one-line summary format.
//
// Ref: S24 — observability.
func TestFormatEmitBatchResult_AllValid(t *testing.T) {
	result := canon.EmitBatchResult{
		Total: 3, Accepted: 3, Rejected: 0, Written: 3,
	}
	got := canon.FormatEmitBatchResult(result)
	want := "emit_batch: total=3 accepted=3 rejected=0 written=3"
	if got != want {
		t.Errorf("FormatEmitBatchResult: got %q, want %q", got, want)
	}
}

// TestFormatEmitBatchResult_Mixed validates the summary with mixed results.
func TestFormatEmitBatchResult_Mixed(t *testing.T) {
	result := canon.EmitBatchResult{
		Total: 6, Accepted: 3, Rejected: 3, Written: 3,
	}
	got := canon.FormatEmitBatchResult(result)
	want := "emit_batch: total=6 accepted=3 rejected=3 written=3"
	if got != want {
		t.Errorf("FormatEmitBatchResult: got %q, want %q", got, want)
	}
}

// ---------------------------------------------------------------------------
// H. JSON serialization of EmitBatchResult
// ---------------------------------------------------------------------------

// TestEmitBatchResult_JSONRoundTrip validates that EmitBatchResult
// serializes to JSON and deserializes back correctly.
//
// Ref: S24 — auditability via JSON serialization.
func TestEmitBatchResult_JSONRoundTrip(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
		{Key: "", Title: "NoKey"},
		{Key: canon.KeyOf("C"), Title: "C"},
	}

	var buf bytes.Buffer
	original, err := canon.EmitBatchV0(&buf, entries)
	if err != nil {
		t.Fatalf("EmitBatchV0: %v", err)
	}

	data, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("json.Marshal: %v", err)
	}

	var restored canon.EmitBatchResult
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
	if restored.Written != original.Written {
		t.Errorf("Written: got %d, want %d", restored.Written, original.Written)
	}
}

// ---------------------------------------------------------------------------
// I. Counter arithmetic invariant
// ---------------------------------------------------------------------------

// TestEmitBatchV0_CounterArithmetic validates that Total == Accepted + Rejected
// for all batch configurations.
//
// Ref: S24 — counter consistency.
func TestEmitBatchV0_CounterArithmetic(t *testing.T) {
	cases := []struct {
		name    string
		entries []canon.CanonEntry
	}{
		{"empty", []canon.CanonEntry{}},
		{"all_valid", []canon.CanonEntry{
			{Key: canon.KeyOf("A"), Title: "A"},
		}},
		{"all_invalid", []canon.CanonEntry{
			{Key: "", Title: ""},
		}},
		{"mixed", []canon.CanonEntry{
			{Key: canon.KeyOf("A"), Title: "A"},
			{Key: "", Title: ""},
			{Key: canon.KeyOf("C"), Title: "C"},
		}},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var buf bytes.Buffer
			result, err := canon.EmitBatchV0(&buf, tc.entries)
			if err != nil {
				t.Fatalf("EmitBatchV0: %v", err)
			}
			if result.Total != result.Accepted+result.Rejected {
				t.Errorf("Total (%d) != Accepted (%d) + Rejected (%d)",
					result.Total, result.Accepted, result.Rejected)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// J. Schema version stamping on emitted entries
// ---------------------------------------------------------------------------

// TestEmitBatchV0_SchemaVersionStamped validates that every emitted line
// carries schema_version = "v0".
//
// Ref: S24 — schema v0 stamping via WriteJSONL.
func TestEmitBatchV0_SchemaVersionStamped(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A", Text: strPtr("body")},
		{Key: canon.KeyOf("B"), Title: "B"},
	}

	var buf bytes.Buffer
	_, err := canon.EmitBatchV0(&buf, entries)
	if err != nil {
		t.Fatalf("EmitBatchV0: unexpected error: %v", err)
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	for i, line := range lines {
		var parsed map[string]interface{}
		if err := json.Unmarshal([]byte(line), &parsed); err != nil {
			t.Fatalf("line %d: invalid JSON: %v", i, err)
		}
		v, ok := parsed["schema_version"]
		if !ok {
			t.Errorf("line %d: missing schema_version", i)
			continue
		}
		if v != canon.SchemaV0 {
			t.Errorf("line %d: schema_version = %v, want %q", i, v, canon.SchemaV0)
		}
	}
}
