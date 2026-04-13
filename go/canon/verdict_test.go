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
// S24 — canon-gate-verdict-v0
//
// Tests for the batch verdict layer over the Canon gate audit (S22).
// Validates:
//
//   - deterministic verdict derivation from audit summary counters;
//   - empty batch → "empty";
//   - all accepted → "accept";
//   - all rejected → "reject";
//   - mixed batch → "mixed";
//   - consistency with AuditBatch;
//   - consistency with BuildBatchReport;
//   - consistency with WriteJSONL;
//   - FormatVerdict observability;
//   - JSON round-trip;
//   - nil batch handling;
//   - single-entry edge cases;
//   - fixture-backed mixed batch.
//
// Ref: S24 — gate verdict over Canon gate batch audit.
// Ref: S22 — BatchAuditResult contract.
// Ref: S23 — BatchReport contract.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// A. DeriveVerdict — core verdict derivation
// ---------------------------------------------------------------------------

// TestDeriveVerdict_EmptyBatch validates that an empty batch produces
// verdict "empty" with all counters at zero.
//
// Ref: S24 — empty batch verdict.
func TestDeriveVerdict_EmptyBatch(t *testing.T) {
	audit := canon.AuditBatch([]canon.CanonEntry{})
	v := canon.DeriveVerdict(audit)

	if v.Verdict != canon.VerdictEmpty {
		t.Errorf("Verdict: got %q, want %q", v.Verdict, canon.VerdictEmpty)
	}
	if v.Total != 0 {
		t.Errorf("Total: got %d, want 0", v.Total)
	}
	if v.Accepted != 0 {
		t.Errorf("Accepted: got %d, want 0", v.Accepted)
	}
	if v.Rejected != 0 {
		t.Errorf("Rejected: got %d, want 0", v.Rejected)
	}
}

// TestDeriveVerdict_NilBatch validates that a nil batch is handled
// as empty (same semantics as empty slice).
//
// Ref: S24 — defensive handling.
func TestDeriveVerdict_NilBatch(t *testing.T) {
	audit := canon.AuditBatch(nil)
	v := canon.DeriveVerdict(audit)

	if v.Verdict != canon.VerdictEmpty {
		t.Errorf("Verdict: got %q, want %q", v.Verdict, canon.VerdictEmpty)
	}
	if v.Total != 0 {
		t.Errorf("Total: got %d, want 0", v.Total)
	}
}

// TestDeriveVerdict_AllAccepted validates that a batch where all entries
// pass the gate produces verdict "accept".
//
// Ref: S24 — all-accept verdict.
func TestDeriveVerdict_AllAccepted(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A", Text: strPtr("body A")},
		{Key: canon.KeyOf("B"), Title: "B"},
		{Key: canon.KeyOf("C"), Title: "C", Text: strPtr("body C")},
	}
	audit := canon.AuditBatch(entries)
	v := canon.DeriveVerdict(audit)

	if v.Verdict != canon.VerdictAccept {
		t.Errorf("Verdict: got %q, want %q", v.Verdict, canon.VerdictAccept)
	}
	if v.Total != 3 {
		t.Errorf("Total: got %d, want 3", v.Total)
	}
	if v.Accepted != 3 {
		t.Errorf("Accepted: got %d, want 3", v.Accepted)
	}
	if v.Rejected != 0 {
		t.Errorf("Rejected: got %d, want 0", v.Rejected)
	}
}

// TestDeriveVerdict_AllRejected validates that a batch where all entries
// fail the gate produces verdict "reject".
//
// Ref: S24 — all-reject verdict.
func TestDeriveVerdict_AllRejected(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: "", Title: ""},
		{Key: "", Title: "NoKey"},
		{Key: canon.KeyOf("NoTitle"), Title: ""},
	}
	audit := canon.AuditBatch(entries)
	v := canon.DeriveVerdict(audit)

	if v.Verdict != canon.VerdictReject {
		t.Errorf("Verdict: got %q, want %q", v.Verdict, canon.VerdictReject)
	}
	if v.Total != 3 {
		t.Errorf("Total: got %d, want 3", v.Total)
	}
	if v.Accepted != 0 {
		t.Errorf("Accepted: got %d, want 0", v.Accepted)
	}
	if v.Rejected != 3 {
		t.Errorf("Rejected: got %d, want 3", v.Rejected)
	}
}

// TestDeriveVerdict_MixedBatch validates that a batch with both accepted
// and rejected entries produces verdict "mixed".
//
// Ref: S24 — mixed verdict.
func TestDeriveVerdict_MixedBatch(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Good1"), Title: "Good1", Text: strPtr("ok")},
		{Key: "", Title: ""},
		{Key: canon.KeyOf("Good2"), Title: "Good2"},
		{Key: canon.KeyOf("BadTitle"), Title: ""},
		{SchemaVersion: "v99", Key: canon.KeyOf("BadVer"), Title: "BadVer"},
		{Key: canon.KeyOf("Good3"), Title: "Good3", Text: strPtr("also ok")},
	}
	audit := canon.AuditBatch(entries)
	v := canon.DeriveVerdict(audit)

	if v.Verdict != canon.VerdictMixed {
		t.Errorf("Verdict: got %q, want %q", v.Verdict, canon.VerdictMixed)
	}
	if v.Total != 6 {
		t.Errorf("Total: got %d, want 6", v.Total)
	}
	if v.Accepted != 3 {
		t.Errorf("Accepted: got %d, want 3", v.Accepted)
	}
	if v.Rejected != 3 {
		t.Errorf("Rejected: got %d, want 3", v.Rejected)
	}
}

// ---------------------------------------------------------------------------
// B. Single-entry edge cases
// ---------------------------------------------------------------------------

// TestDeriveVerdict_SingleAccepted validates verdict for a batch with
// exactly one valid entry.
//
// Ref: S24 — single-entry edge case.
func TestDeriveVerdict_SingleAccepted(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Solo"), Title: "Solo", Text: strPtr("body")},
	}
	audit := canon.AuditBatch(entries)
	v := canon.DeriveVerdict(audit)

	if v.Verdict != canon.VerdictAccept {
		t.Errorf("Verdict: got %q, want %q", v.Verdict, canon.VerdictAccept)
	}
	if v.Total != 1 || v.Accepted != 1 || v.Rejected != 0 {
		t.Errorf("unexpected counters: total=%d accepted=%d rejected=%d",
			v.Total, v.Accepted, v.Rejected)
	}
}

// TestDeriveVerdict_SingleRejected validates verdict for a batch with
// exactly one invalid entry.
//
// Ref: S24 — single-entry edge case.
func TestDeriveVerdict_SingleRejected(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: "", Title: ""},
	}
	audit := canon.AuditBatch(entries)
	v := canon.DeriveVerdict(audit)

	if v.Verdict != canon.VerdictReject {
		t.Errorf("Verdict: got %q, want %q", v.Verdict, canon.VerdictReject)
	}
	if v.Total != 1 || v.Accepted != 0 || v.Rejected != 1 {
		t.Errorf("unexpected counters: total=%d accepted=%d rejected=%d",
			v.Total, v.Accepted, v.Rejected)
	}
}

// ---------------------------------------------------------------------------
// C. Consistency with audit and report
// ---------------------------------------------------------------------------

// TestDeriveVerdict_ConsistentWithAudit validates that the verdict counters
// match the audit summary counters exactly.
//
// Ref: S24 — consistency with S22 audit.
func TestDeriveVerdict_ConsistentWithAudit(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
		{Key: "", Title: "NoKey"},
		{Key: canon.KeyOf("C"), Title: "C"},
	}
	audit := canon.AuditBatch(entries)
	v := canon.DeriveVerdict(audit)

	if v.Total != audit.Summary.Total {
		t.Errorf("Total: verdict=%d, audit=%d", v.Total, audit.Summary.Total)
	}
	if v.Accepted != audit.Summary.Accepted {
		t.Errorf("Accepted: verdict=%d, audit=%d", v.Accepted, audit.Summary.Accepted)
	}
	if v.Rejected != audit.Summary.Rejected {
		t.Errorf("Rejected: verdict=%d, audit=%d", v.Rejected, audit.Summary.Rejected)
	}
}

// TestDeriveVerdict_ConsistentWithBatchReport validates that verdict counters
// match the batch report counters exactly.
//
// Ref: S24 — consistency with S23 report.
func TestDeriveVerdict_ConsistentWithBatchReport(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
		{Key: "", Title: "NoKey"},
		{Key: canon.KeyOf("C"), Title: "C"},
		{Key: canon.KeyOf("D"), Title: ""},
	}
	audit := canon.AuditBatch(entries)
	report := canon.BuildBatchReport(audit)
	v := canon.DeriveVerdict(audit)

	if v.Total != report.Total {
		t.Errorf("Total: verdict=%d, report=%d", v.Total, report.Total)
	}
	if v.Accepted != report.Accepted {
		t.Errorf("Accepted: verdict=%d, report=%d", v.Accepted, report.Accepted)
	}
	if v.Rejected != report.Rejected {
		t.Errorf("Rejected: verdict=%d, report=%d", v.Rejected, report.Rejected)
	}
}

// TestDeriveVerdict_ConsistentWithWriteJSONL validates that verdict counters
// match the WriteJSONL written/skipped counts.
//
// Ref: S24 — consistency with S19 gate.
func TestDeriveVerdict_ConsistentWithWriteJSONL(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A", Text: strPtr("ok")},
		{Key: "", Title: ""},
		{Key: canon.KeyOf("C"), Title: "C"},
		{Key: canon.KeyOf("D"), Title: ""},
		{Key: canon.KeyOf("E"), Title: "E", Text: strPtr("also ok")},
	}

	audit := canon.AuditBatch(entries)
	v := canon.DeriveVerdict(audit)

	var buf bytes.Buffer
	writeResult, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}

	if v.Accepted != writeResult.Written {
		t.Errorf("Verdict.Accepted (%d) != WriteJSONL.Written (%d)",
			v.Accepted, writeResult.Written)
	}
	if v.Rejected != writeResult.Skipped {
		t.Errorf("Verdict.Rejected (%d) != WriteJSONL.Skipped (%d)",
			v.Rejected, writeResult.Skipped)
	}
}

// ---------------------------------------------------------------------------
// D. Determinism — same input produces same verdict
// ---------------------------------------------------------------------------

// TestDeriveVerdict_Deterministic validates that calling DeriveVerdict
// twice on the same audit result produces the same verdict.
//
// Ref: S24 — deterministic verdict requirement.
func TestDeriveVerdict_Deterministic(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
		{Key: "", Title: "NoKey"},
		{Key: canon.KeyOf("C"), Title: "C"},
	}
	audit := canon.AuditBatch(entries)

	v1 := canon.DeriveVerdict(audit)
	v2 := canon.DeriveVerdict(audit)

	if v1.Verdict != v2.Verdict {
		t.Errorf("Verdict not deterministic: %q vs %q", v1.Verdict, v2.Verdict)
	}
	if v1.Total != v2.Total || v1.Accepted != v2.Accepted || v1.Rejected != v2.Rejected {
		t.Errorf("Counters not deterministic: %+v vs %+v", v1, v2)
	}
}

// ---------------------------------------------------------------------------
// E. FormatVerdict observability
// ---------------------------------------------------------------------------

// TestFormatVerdict_Empty validates the verdict format for empty batch.
//
// Ref: S24 — observability.
func TestFormatVerdict_Empty(t *testing.T) {
	v := canon.GateVerdict{Verdict: canon.VerdictEmpty, Total: 0, Accepted: 0, Rejected: 0}
	got := canon.FormatVerdict(v)
	want := "gate_verdict: verdict=empty total=0 accepted=0 rejected=0"
	if got != want {
		t.Errorf("FormatVerdict: got %q, want %q", got, want)
	}
}

// TestFormatVerdict_Accept validates the verdict format for all-accept.
//
// Ref: S24 — observability.
func TestFormatVerdict_Accept(t *testing.T) {
	v := canon.GateVerdict{Verdict: canon.VerdictAccept, Total: 5, Accepted: 5, Rejected: 0}
	got := canon.FormatVerdict(v)
	want := "gate_verdict: verdict=accept total=5 accepted=5 rejected=0"
	if got != want {
		t.Errorf("FormatVerdict: got %q, want %q", got, want)
	}
}

// TestFormatVerdict_Reject validates the verdict format for all-reject.
//
// Ref: S24 — observability.
func TestFormatVerdict_Reject(t *testing.T) {
	v := canon.GateVerdict{Verdict: canon.VerdictReject, Total: 3, Accepted: 0, Rejected: 3}
	got := canon.FormatVerdict(v)
	want := "gate_verdict: verdict=reject total=3 accepted=0 rejected=3"
	if got != want {
		t.Errorf("FormatVerdict: got %q, want %q", got, want)
	}
}

// TestFormatVerdict_Mixed validates the verdict format for mixed batch.
//
// Ref: S24 — observability.
func TestFormatVerdict_Mixed(t *testing.T) {
	v := canon.GateVerdict{Verdict: canon.VerdictMixed, Total: 10, Accepted: 7, Rejected: 3}
	got := canon.FormatVerdict(v)
	want := "gate_verdict: verdict=mixed total=10 accepted=7 rejected=3"
	if got != want {
		t.Errorf("FormatVerdict: got %q, want %q", got, want)
	}
}

// ---------------------------------------------------------------------------
// F. JSON round-trip
// ---------------------------------------------------------------------------

// TestGateVerdict_JSONRoundTrip validates that GateVerdict serializes to
// JSON and deserializes back correctly.
//
// Ref: S24 — auditability via JSON serialization.
func TestGateVerdict_JSONRoundTrip(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
		{Key: "", Title: "NoKey"},
		{Key: canon.KeyOf("C"), Title: "C"},
	}
	audit := canon.AuditBatch(entries)
	original := canon.DeriveVerdict(audit)

	data, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("json.Marshal: %v", err)
	}

	var restored canon.GateVerdict
	if err := json.Unmarshal(data, &restored); err != nil {
		t.Fatalf("json.Unmarshal: %v", err)
	}

	if restored.Verdict != original.Verdict {
		t.Errorf("Verdict: got %q, want %q", restored.Verdict, original.Verdict)
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
}

// ---------------------------------------------------------------------------
// G. Fixture-backed mixed batch verdict
// ---------------------------------------------------------------------------

// TestDeriveVerdict_Fixture_MixedBatch loads the batch audit fixture
// (canon_gate_batch_audit_mixed.jsonl), runs AuditBatch + DeriveVerdict,
// and verifies the expected "mixed" verdict.
//
// The fixture contains 10 lines: 5 valid + 5 invalid.
//
// Ref: S24 — fixture-backed mixed verdict.
// Ref: S22 — fixture definition.
func TestDeriveVerdict_Fixture_MixedBatch(t *testing.T) {
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

	audit := canon.AuditBatch(entries)
	v := canon.DeriveVerdict(audit)

	if v.Verdict != canon.VerdictMixed {
		t.Errorf("Verdict: got %q, want %q", v.Verdict, canon.VerdictMixed)
	}
	if v.Total != 10 {
		t.Errorf("Total: got %d, want 10", v.Total)
	}
	if v.Accepted != 5 {
		t.Errorf("Accepted: got %d, want 5", v.Accepted)
	}
	if v.Rejected != 5 {
		t.Errorf("Rejected: got %d, want 5", v.Rejected)
	}

	// Verify verdict counters match audit.
	if v.Total != audit.Summary.Total {
		t.Errorf("Total: verdict=%d, audit=%d", v.Total, audit.Summary.Total)
	}
	if v.Accepted != audit.Summary.Accepted {
		t.Errorf("Accepted: verdict=%d, audit=%d", v.Accepted, audit.Summary.Accepted)
	}
	if v.Rejected != audit.Summary.Rejected {
		t.Errorf("Rejected: verdict=%d, audit=%d", v.Rejected, audit.Summary.Rejected)
	}

	t.Logf("Fixture verdict: %s (total=%d accepted=%d rejected=%d)",
		v.Verdict, v.Total, v.Accepted, v.Rejected)
}

// ---------------------------------------------------------------------------
// H. Counter integrity invariant
// ---------------------------------------------------------------------------

// TestDeriveVerdict_CounterIntegrity validates that Total == Accepted + Rejected
// holds for all verdict categories.
//
// Ref: S24 — structural invariant.
func TestDeriveVerdict_CounterIntegrity(t *testing.T) {
	cases := []struct {
		name    string
		entries []canon.CanonEntry
	}{
		{"empty", []canon.CanonEntry{}},
		{"nil", nil},
		{"all_accepted", []canon.CanonEntry{
			{Key: canon.KeyOf("A"), Title: "A"},
			{Key: canon.KeyOf("B"), Title: "B"},
		}},
		{"all_rejected", []canon.CanonEntry{
			{Key: "", Title: ""},
			{Key: "", Title: "NoKey"},
		}},
		{"mixed", []canon.CanonEntry{
			{Key: canon.KeyOf("A"), Title: "A"},
			{Key: "", Title: ""},
			{Key: canon.KeyOf("C"), Title: "C"},
		}},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			audit := canon.AuditBatch(tc.entries)
			v := canon.DeriveVerdict(audit)

			if v.Total != v.Accepted+v.Rejected {
				t.Errorf("Total (%d) != Accepted (%d) + Rejected (%d)",
					v.Total, v.Accepted, v.Rejected)
			}
		})
	}
}
