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
// S22 — canon-gate-batch-audit-v0
//
// This file contains the tests for the batch audit layer over the Canon
// gate v0 (AuditBatch). It validates:
//
//   - per-item audit detail (index, verdict, reason);
//   - aggregate summary (total, accepted, rejected);
//   - distribution by rejection reason;
//   - deterministic output order;
//   - empty batch handling;
//   - fixture-backed mixed batch;
//   - consistency between AuditBatch and WriteJSONL counters;
//   - FormatBatchSummary observability.
//
// Ref: S22 — batch audit over Canon gate v0.
// Ref: S19 — ValidateEntryV0 contract.
// Ref: S21 — acceptance matrix.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// A. AuditBatch — table-driven core tests
// ---------------------------------------------------------------------------

// TestAuditBatch_EmptyBatch validates that an empty batch produces a valid
// result with Total=0, Accepted=0, Rejected=0 and no items.
//
// Ref: S22 — empty batch case.
func TestAuditBatch_EmptyBatch(t *testing.T) {
	result := canon.AuditBatch([]canon.CanonEntry{})

	if result.Summary.Total != 0 {
		t.Errorf("Total: got %d, want 0", result.Summary.Total)
	}
	if result.Summary.Accepted != 0 {
		t.Errorf("Accepted: got %d, want 0", result.Summary.Accepted)
	}
	if result.Summary.Rejected != 0 {
		t.Errorf("Rejected: got %d, want 0", result.Summary.Rejected)
	}
	if len(result.Items) != 0 {
		t.Errorf("Items: got %d, want 0", len(result.Items))
	}
	if len(result.Summary.RejectsByReason) != 0 {
		t.Errorf("RejectsByReason: got %d, want 0", len(result.Summary.RejectsByReason))
	}
}

// TestAuditBatch_AllValid validates that a batch with all valid entries
// produces Total=N, Accepted=N, Rejected=0.
//
// Ref: S22 — all-accept batch.
func TestAuditBatch_AllValid(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A", Text: strPtr("body A")},
		{Key: canon.KeyOf("B"), Title: "B"},
		{Key: canon.KeyOf("C"), Title: "C", Text: strPtr("body C")},
	}

	result := canon.AuditBatch(entries)

	if result.Summary.Total != 3 {
		t.Errorf("Total: got %d, want 3", result.Summary.Total)
	}
	if result.Summary.Accepted != 3 {
		t.Errorf("Accepted: got %d, want 3", result.Summary.Accepted)
	}
	if result.Summary.Rejected != 0 {
		t.Errorf("Rejected: got %d, want 0", result.Summary.Rejected)
	}
	for i, item := range result.Items {
		if item.Verdict != canon.VerdictAccepted {
			t.Errorf("Items[%d]: verdict = %q, want %q", i, item.Verdict, canon.VerdictAccepted)
		}
		if item.Index != i {
			t.Errorf("Items[%d]: index = %d, want %d", i, item.Index, i)
		}
		if item.Reason != "" {
			t.Errorf("Items[%d]: reason should be empty for accepted, got %q", i, item.Reason)
		}
	}
}

// TestAuditBatch_AllInvalid validates that a batch with all invalid entries
// produces Total=N, Accepted=0, Rejected=N.
//
// Ref: S22 — all-reject batch.
func TestAuditBatch_AllInvalid(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: "", Title: ""},
		{Key: "", Title: "NoKey"},
		{Key: canon.KeyOf("NoTitle"), Title: ""},
	}

	result := canon.AuditBatch(entries)

	if result.Summary.Total != 3 {
		t.Errorf("Total: got %d, want 3", result.Summary.Total)
	}
	if result.Summary.Accepted != 0 {
		t.Errorf("Accepted: got %d, want 0", result.Summary.Accepted)
	}
	if result.Summary.Rejected != 3 {
		t.Errorf("Rejected: got %d, want 3", result.Summary.Rejected)
	}
	for i, item := range result.Items {
		if item.Verdict != canon.VerdictRejected {
			t.Errorf("Items[%d]: verdict = %q, want %q", i, item.Verdict, canon.VerdictRejected)
		}
		if item.Reason == "" {
			t.Errorf("Items[%d]: reason should be non-empty for rejected", i)
		}
	}
}

// TestAuditBatch_MixedBatch validates a batch with both valid and invalid
// entries, verifying counters, per-item detail, and rejection reasons.
//
// Ref: S22 — mixed batch core test.
func TestAuditBatch_MixedBatch(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Good1"), Title: "Good1", Text: strPtr("ok")},               // 0: accept
		{Key: "", Title: ""},                                                            // 1: reject (key)
		{Key: canon.KeyOf("Good2"), Title: "Good2"},                                    // 2: accept
		{Key: canon.KeyOf("BadTitle"), Title: ""},                                      // 3: reject (title)
		{SchemaVersion: "v99", Key: canon.KeyOf("BadVer"), Title: "BadVer"},            // 4: reject (schema_version)
		{Key: canon.KeyOf("Good3"), Title: "Good3", Text: strPtr("also ok")},           // 5: accept
	}

	result := canon.AuditBatch(entries)

	if result.Summary.Total != 6 {
		t.Errorf("Total: got %d, want 6", result.Summary.Total)
	}
	if result.Summary.Accepted != 3 {
		t.Errorf("Accepted: got %d, want 3", result.Summary.Accepted)
	}
	if result.Summary.Rejected != 3 {
		t.Errorf("Rejected: got %d, want 3", result.Summary.Rejected)
	}

	// Verify counters are consistent.
	if result.Summary.Total != result.Summary.Accepted+result.Summary.Rejected {
		t.Errorf("Total (%d) != Accepted (%d) + Rejected (%d)",
			result.Summary.Total, result.Summary.Accepted, result.Summary.Rejected)
	}

	// Verify item count matches total.
	if len(result.Items) != result.Summary.Total {
		t.Errorf("Items length (%d) != Total (%d)", len(result.Items), result.Summary.Total)
	}

	// Verify per-item verdicts and order.
	expectedVerdicts := []canon.ItemVerdict{
		canon.VerdictAccepted,
		canon.VerdictRejected,
		canon.VerdictAccepted,
		canon.VerdictRejected,
		canon.VerdictRejected,
		canon.VerdictAccepted,
	}
	for i, want := range expectedVerdicts {
		if result.Items[i].Verdict != want {
			t.Errorf("Items[%d].Verdict: got %q, want %q", i, result.Items[i].Verdict, want)
		}
		if result.Items[i].Index != i {
			t.Errorf("Items[%d].Index: got %d, want %d", i, result.Items[i].Index, i)
		}
	}

	// Verify rejection reasons contain the expected field names.
	if !strings.Contains(result.Items[1].Reason, "key") {
		t.Errorf("Items[1].Reason should contain 'key': %q", result.Items[1].Reason)
	}
	if !strings.Contains(result.Items[3].Reason, "title") {
		t.Errorf("Items[3].Reason should contain 'title': %q", result.Items[3].Reason)
	}
	if !strings.Contains(result.Items[4].Reason, "schema_version") {
		t.Errorf("Items[4].Reason should contain 'schema_version': %q", result.Items[4].Reason)
	}
}

// ---------------------------------------------------------------------------
// B. Rejection reason distribution
// ---------------------------------------------------------------------------

// TestAuditBatch_RejectsByReason validates that the rejection reason
// distribution is correct and deterministic (ordered by first occurrence).
//
// Ref: S22 — aggregated view by rejection motive.
func TestAuditBatch_RejectsByReason(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Ok"), Title: "Ok"},
		{Key: "", Title: "NoKey1"},                                              // key error
		{Key: "", Title: "NoKey2"},                                              // key error (same reason)
		{Key: canon.KeyOf("NoTitle"), Title: ""},                                // title error
		{SchemaVersion: "v99", Key: canon.KeyOf("BadVer"), Title: "BadVer"},     // schema_version error
		{Key: "", Title: "NoKey3"},                                              // key error again
	}

	result := canon.AuditBatch(entries)

	if result.Summary.Rejected != 5 {
		t.Fatalf("Rejected: got %d, want 5", result.Summary.Rejected)
	}

	if len(result.Summary.RejectsByReason) != 3 {
		t.Fatalf("RejectsByReason: got %d distinct reasons, want 3", len(result.Summary.RejectsByReason))
	}

	// First occurrence order: key, title, schema_version.
	wantReasons := []struct {
		contains string
		count    int
	}{
		{"key", 3},
		{"title", 1},
		{"schema_version", 1},
	}

	for i, want := range wantReasons {
		got := result.Summary.RejectsByReason[i]
		if !strings.Contains(got.Reason, want.contains) {
			t.Errorf("RejectsByReason[%d].Reason: got %q, want substring %q", i, got.Reason, want.contains)
		}
		if got.Count != want.count {
			t.Errorf("RejectsByReason[%d].Count: got %d, want %d", i, got.Count, want.count)
		}
	}

	// Verify tally sums to total rejected.
	tallySum := 0
	for _, rt := range result.Summary.RejectsByReason {
		tallySum += rt.Count
	}
	if tallySum != result.Summary.Rejected {
		t.Errorf("tally sum (%d) != Rejected (%d)", tallySum, result.Summary.Rejected)
	}
}

// ---------------------------------------------------------------------------
// C. Order preservation and index integrity
// ---------------------------------------------------------------------------

// TestAuditBatch_PreservesOrder validates that Items appear in the exact
// order of the input batch, and each item's Index matches its position.
//
// Ref: S22 — deterministic order for audit traceability.
func TestAuditBatch_PreservesOrder(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("First"), Title: "First"},
		{Key: "", Title: "Invalid"},
		{Key: canon.KeyOf("Third"), Title: "Third"},
		{Key: canon.KeyOf("Fourth"), Title: "Fourth"},
	}

	result := canon.AuditBatch(entries)

	if len(result.Items) != len(entries) {
		t.Fatalf("Items: got %d, want %d", len(result.Items), len(entries))
	}

	expectedTitles := []string{"First", "Invalid", "Third", "Fourth"}
	for i, item := range result.Items {
		if item.Index != i {
			t.Errorf("Items[%d].Index: got %d, want %d", i, item.Index, i)
		}
		if item.Title != expectedTitles[i] {
			t.Errorf("Items[%d].Title: got %q, want %q", i, item.Title, expectedTitles[i])
		}
	}
}

// ---------------------------------------------------------------------------
// D. Consistency with WriteJSONL
// ---------------------------------------------------------------------------

// TestAuditBatch_ConsistentWithWriteJSONL validates that AuditBatch
// accepted/rejected counts match WriteJSONL written/skipped counts
// for the same input batch.
//
// This is a critical structural invariant: the audit layer and the
// writer gate must agree on what passes and what fails.
//
// Ref: S22 — consistency between audit and gate.
// Ref: S19 — WriteJSONL gate.
func TestAuditBatch_ConsistentWithWriteJSONL(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A", Text: strPtr("ok")},
		{Key: "", Title: ""},
		{Key: canon.KeyOf("C"), Title: "C"},
		{Key: canon.KeyOf("D"), Title: ""},
		{SchemaVersion: "v99", Key: canon.KeyOf("E"), Title: "E"},
		{Key: canon.KeyOf("F"), Title: "F", Text: strPtr("also ok")},
	}

	audit := canon.AuditBatch(entries)

	var buf bytes.Buffer
	writeResult, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}

	if audit.Summary.Accepted != writeResult.Written {
		t.Errorf("Audit.Accepted (%d) != WriteJSONL.Written (%d)",
			audit.Summary.Accepted, writeResult.Written)
	}
	if audit.Summary.Rejected != writeResult.Skipped {
		t.Errorf("Audit.Rejected (%d) != WriteJSONL.Skipped (%d)",
			audit.Summary.Rejected, writeResult.Skipped)
	}
}

// ---------------------------------------------------------------------------
// E. Fixture-backed mixed batch audit
// ---------------------------------------------------------------------------

// TestAuditBatch_Fixture_MixedBatch loads the batch audit fixture
// (canon_gate_batch_audit_mixed.jsonl), runs AuditBatch over it,
// and verifies the expected accept/reject distribution.
//
// The fixture contains 10 lines:
//   - 5 valid entries (Alpha, Beta, Delta, Unicode, Epsilon)
//   - 5 invalid entries (NoKey, NoTitle, BadVer, BothEmpty, CaseBadV0)
//
// Ref: S22 — fixture-backed mixed batch audit.
func TestAuditBatch_Fixture_MixedBatch(t *testing.T) {
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

	result := canon.AuditBatch(entries)

	// Summary checks.
	if result.Summary.Total != 10 {
		t.Errorf("Total: got %d, want 10", result.Summary.Total)
	}
	if result.Summary.Accepted != 5 {
		t.Errorf("Accepted: got %d, want 5", result.Summary.Accepted)
	}
	if result.Summary.Rejected != 5 {
		t.Errorf("Rejected: got %d, want 5", result.Summary.Rejected)
	}

	// Verify accepted entries are the expected ones.
	wantAccepted := map[string]bool{
		"Alpha":                                      true,
		"Beta":                                       true,
		"Delta":                                      true,
		"#### 🌀 Sesión 08 = ingesta-data-triage": true,
		"Epsilon":                                    true,
	}
	for _, item := range result.Items {
		if item.Verdict == canon.VerdictAccepted {
			if !wantAccepted[item.Title] {
				t.Errorf("unexpected accepted title: %q", item.Title)
			}
		}
	}

	// Verify rejected entries have non-empty reasons.
	for _, item := range result.Items {
		if item.Verdict == canon.VerdictRejected && item.Reason == "" {
			t.Errorf("Items[%d] (%q): rejected but reason is empty", item.Index, item.Title)
		}
	}

	// Counters consistency.
	if result.Summary.Total != result.Summary.Accepted+result.Summary.Rejected {
		t.Errorf("Total (%d) != Accepted (%d) + Rejected (%d)",
			result.Summary.Total, result.Summary.Accepted, result.Summary.Rejected)
	}

	// Item count consistency.
	if len(result.Items) != result.Summary.Total {
		t.Errorf("Items length (%d) != Total (%d)", len(result.Items), result.Summary.Total)
	}

	// RejectsByReason tally consistency.
	tallySum := 0
	for _, rt := range result.Summary.RejectsByReason {
		tallySum += rt.Count
	}
	if tallySum != result.Summary.Rejected {
		t.Errorf("tally sum (%d) != Rejected (%d)", tallySum, result.Summary.Rejected)
	}

	t.Logf("Fixture audit: total=%d accepted=%d rejected=%d reasons=%d",
		result.Summary.Total, result.Summary.Accepted, result.Summary.Rejected,
		len(result.Summary.RejectsByReason))
}

// ---------------------------------------------------------------------------
// F. FormatBatchSummary observability
// ---------------------------------------------------------------------------

// TestFormatBatchSummary_NoRejections validates the summary format
// when all entries are accepted.
//
// Ref: S22 — observability.
func TestFormatBatchSummary_NoRejections(t *testing.T) {
	result := canon.BatchAuditResult{
		Summary: canon.BatchAuditSummary{Total: 3, Accepted: 3, Rejected: 0},
	}
	got := canon.FormatBatchSummary(result)
	want := "batch_audit: total=3 accepted=3 rejected=0"
	if got != want {
		t.Errorf("FormatBatchSummary: got %q, want %q", got, want)
	}
}

// TestFormatBatchSummary_WithRejections validates the summary format
// when rejections are present.
//
// Ref: S22 — observability.
func TestFormatBatchSummary_WithRejections(t *testing.T) {
	result := canon.BatchAuditResult{
		Summary: canon.BatchAuditSummary{
			Total:    6,
			Accepted: 3,
			Rejected: 3,
			RejectsByReason: []canon.RejectTally{
				{Reason: "key: required field is empty", Count: 2},
				{Reason: "title: required field is empty", Count: 1},
			},
		},
	}
	got := canon.FormatBatchSummary(result)
	want := "batch_audit: total=6 accepted=3 rejected=3 reject_reasons=2"
	if got != want {
		t.Errorf("FormatBatchSummary: got %q, want %q", got, want)
	}
}

// ---------------------------------------------------------------------------
// G. Nil batch
// ---------------------------------------------------------------------------

// TestAuditBatch_NilBatch validates that a nil slice is handled as an
// empty batch (same as empty slice).
//
// Ref: S22 — defensive handling.
func TestAuditBatch_NilBatch(t *testing.T) {
	result := canon.AuditBatch(nil)

	if result.Summary.Total != 0 {
		t.Errorf("Total: got %d, want 0", result.Summary.Total)
	}
	if result.Summary.Accepted != 0 {
		t.Errorf("Accepted: got %d, want 0", result.Summary.Accepted)
	}
	if result.Summary.Rejected != 0 {
		t.Errorf("Rejected: got %d, want 0", result.Summary.Rejected)
	}
	if len(result.Items) != 0 {
		t.Errorf("Items: got %d, want 0", len(result.Items))
	}
}

// ---------------------------------------------------------------------------
// H. Single-entry batches
// ---------------------------------------------------------------------------

// TestAuditBatch_SingleValid validates a batch with exactly one valid entry.
func TestAuditBatch_SingleValid(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Solo"), Title: "Solo", Text: strPtr("body")},
	}
	result := canon.AuditBatch(entries)

	if result.Summary.Total != 1 || result.Summary.Accepted != 1 || result.Summary.Rejected != 0 {
		t.Errorf("unexpected summary: %+v", result.Summary)
	}
	if result.Items[0].Verdict != canon.VerdictAccepted {
		t.Errorf("single valid entry should be accepted")
	}
}

// TestAuditBatch_SingleInvalid validates a batch with exactly one invalid entry.
func TestAuditBatch_SingleInvalid(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: "", Title: ""},
	}
	result := canon.AuditBatch(entries)

	if result.Summary.Total != 1 || result.Summary.Accepted != 0 || result.Summary.Rejected != 1 {
		t.Errorf("unexpected summary: %+v", result.Summary)
	}
	if result.Items[0].Verdict != canon.VerdictRejected {
		t.Errorf("single invalid entry should be rejected")
	}
	if result.Items[0].Reason == "" {
		t.Error("single invalid entry should have a reason")
	}
}

// ---------------------------------------------------------------------------
// I. JSON serialization of BatchAuditResult
// ---------------------------------------------------------------------------

// TestBatchAuditResult_JSONRoundTrip validates that BatchAuditResult
// serializes to JSON and deserializes back correctly.
//
// Ref: S22 — auditability via JSON serialization.
func TestBatchAuditResult_JSONRoundTrip(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
		{Key: "", Title: "NoKey"},
		{Key: canon.KeyOf("C"), Title: "C"},
	}

	original := canon.AuditBatch(entries)

	data, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("json.Marshal: %v", err)
	}

	var restored canon.BatchAuditResult
	if err := json.Unmarshal(data, &restored); err != nil {
		t.Fatalf("json.Unmarshal: %v", err)
	}

	if restored.Summary.Total != original.Summary.Total {
		t.Errorf("Total: got %d, want %d", restored.Summary.Total, original.Summary.Total)
	}
	if restored.Summary.Accepted != original.Summary.Accepted {
		t.Errorf("Accepted: got %d, want %d", restored.Summary.Accepted, original.Summary.Accepted)
	}
	if restored.Summary.Rejected != original.Summary.Rejected {
		t.Errorf("Rejected: got %d, want %d", restored.Summary.Rejected, original.Summary.Rejected)
	}
	if len(restored.Items) != len(original.Items) {
		t.Fatalf("Items: got %d, want %d", len(restored.Items), len(original.Items))
	}
	for i := range original.Items {
		if restored.Items[i].Index != original.Items[i].Index {
			t.Errorf("Items[%d].Index: got %d, want %d", i, restored.Items[i].Index, original.Items[i].Index)
		}
		if restored.Items[i].Verdict != original.Items[i].Verdict {
			t.Errorf("Items[%d].Verdict: got %q, want %q", i, restored.Items[i].Verdict, original.Items[i].Verdict)
		}
		if restored.Items[i].Reason != original.Items[i].Reason {
			t.Errorf("Items[%d].Reason: got %q, want %q", i, restored.Items[i].Reason, original.Items[i].Reason)
		}
	}
}
