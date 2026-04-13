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
// S23 — canon-gate-batch-report-v0
//
// Tests for the batch report layer over the Canon gate audit (S22).
// Validates:
//   - report generation from audit results;
//   - metadata population;
//   - derived observations (empty_batch, all_accepted, all_rejected,
//     high_rejection_rate);
//   - summary and items propagation;
//   - human-readable format output;
//   - JSON round-trip;
//   - fixture-backed mixed batch report;
//   - consistency between report and audit.
//
// Ref: S23 — batch report v0.
// Ref: S22 — AuditBatch, BatchAuditResult.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// A. GenerateBatchReport — metadata and structure
// ---------------------------------------------------------------------------

// TestGenerateBatchReport_Meta validates that report metadata is populated
// correctly from the function parameters.
func TestGenerateBatchReport_Meta(t *testing.T) {
	audit := canon.AuditBatch([]canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
	})

	report := canon.GenerateBatchReport(audit, "20260413212500000")

	if report.Meta.Session != "m02-s23-canon-gate-batch-report-v0" {
		t.Errorf("Meta.Session: got %q", report.Meta.Session)
	}
	if report.Meta.SchemaVersion != canon.SchemaV0 {
		t.Errorf("Meta.SchemaVersion: got %q, want %q", report.Meta.SchemaVersion, canon.SchemaV0)
	}
	if report.Meta.GateVersion != "gate-v0" {
		t.Errorf("Meta.GateVersion: got %q", report.Meta.GateVersion)
	}
	if report.Meta.Timestamp != "20260413212500000" {
		t.Errorf("Meta.Timestamp: got %q", report.Meta.Timestamp)
	}
}

// TestGenerateBatchReport_PropagatesSummary validates that the report
// summary matches the audit summary exactly.
func TestGenerateBatchReport_PropagatesSummary(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
		{Key: "", Title: ""},
		{Key: canon.KeyOf("C"), Title: "C"},
	}
	audit := canon.AuditBatch(entries)
	report := canon.GenerateBatchReport(audit, "20260413212500000")

	if report.Summary.Total != audit.Summary.Total {
		t.Errorf("Total: report=%d, audit=%d", report.Summary.Total, audit.Summary.Total)
	}
	if report.Summary.Accepted != audit.Summary.Accepted {
		t.Errorf("Accepted: report=%d, audit=%d", report.Summary.Accepted, audit.Summary.Accepted)
	}
	if report.Summary.Rejected != audit.Summary.Rejected {
		t.Errorf("Rejected: report=%d, audit=%d", report.Summary.Rejected, audit.Summary.Rejected)
	}
}

// TestGenerateBatchReport_PropagatesItems validates that the report
// items match the audit items exactly.
func TestGenerateBatchReport_PropagatesItems(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
		{Key: "", Title: "NoKey"},
		{Key: canon.KeyOf("C"), Title: "C"},
	}
	audit := canon.AuditBatch(entries)
	report := canon.GenerateBatchReport(audit, "20260413212500000")

	if len(report.Items) != len(audit.Items) {
		t.Fatalf("Items: report=%d, audit=%d", len(report.Items), len(audit.Items))
	}
	for i := range audit.Items {
		if report.Items[i].Index != audit.Items[i].Index {
			t.Errorf("Items[%d].Index: report=%d, audit=%d", i, report.Items[i].Index, audit.Items[i].Index)
		}
		if report.Items[i].Verdict != audit.Items[i].Verdict {
			t.Errorf("Items[%d].Verdict: report=%q, audit=%q", i, report.Items[i].Verdict, audit.Items[i].Verdict)
		}
		if report.Items[i].Reason != audit.Items[i].Reason {
			t.Errorf("Items[%d].Reason: report=%q, audit=%q", i, report.Items[i].Reason, audit.Items[i].Reason)
		}
	}
}

// ---------------------------------------------------------------------------
// B. Observations derivation
// ---------------------------------------------------------------------------

// TestGenerateBatchReport_Obs_EmptyBatch validates that an empty batch
// produces the "empty_batch" observation.
func TestGenerateBatchReport_Obs_EmptyBatch(t *testing.T) {
	audit := canon.AuditBatch([]canon.CanonEntry{})
	report := canon.GenerateBatchReport(audit, "20260413212500000")

	if len(report.Observations) != 1 {
		t.Fatalf("Observations: got %d, want 1", len(report.Observations))
	}
	if report.Observations[0].Code != canon.ObsEmptyBatch {
		t.Errorf("Observation code: got %q, want %q", report.Observations[0].Code, canon.ObsEmptyBatch)
	}
}

// TestGenerateBatchReport_Obs_AllAccepted validates that a fully accepted
// batch produces the "all_accepted" observation.
func TestGenerateBatchReport_Obs_AllAccepted(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
		{Key: canon.KeyOf("B"), Title: "B"},
	}
	audit := canon.AuditBatch(entries)
	report := canon.GenerateBatchReport(audit, "20260413212500000")

	found := false
	for _, obs := range report.Observations {
		if obs.Code == canon.ObsAllAccepted {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("expected %q observation, got %v", canon.ObsAllAccepted, report.Observations)
	}
}

// TestGenerateBatchReport_Obs_AllRejected validates that a fully rejected
// batch produces the "all_rejected" observation.
func TestGenerateBatchReport_Obs_AllRejected(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: "", Title: ""},
		{Key: "", Title: "NoKey"},
	}
	audit := canon.AuditBatch(entries)
	report := canon.GenerateBatchReport(audit, "20260413212500000")

	found := false
	for _, obs := range report.Observations {
		if obs.Code == canon.ObsAllRejected {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("expected %q observation, got %v", canon.ObsAllRejected, report.Observations)
	}
}

// TestGenerateBatchReport_Obs_HighRejectionRate validates that a batch
// where rejected > accepted produces the "high_rejection_rate" observation.
func TestGenerateBatchReport_Obs_HighRejectionRate(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},          // accept
		{Key: "", Title: ""},                          // reject
		{Key: "", Title: "NoKey"},                     // reject
		{Key: canon.KeyOf("D"), Title: ""},            // reject
	}
	audit := canon.AuditBatch(entries)
	report := canon.GenerateBatchReport(audit, "20260413212500000")

	found := false
	for _, obs := range report.Observations {
		if obs.Code == canon.ObsHighRejectionRate {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("expected %q observation, got %v", canon.ObsHighRejectionRate, report.Observations)
	}
}

// TestGenerateBatchReport_Obs_MixedNoSpecialObs validates that a balanced
// mixed batch (accepted >= rejected) has no special observations.
func TestGenerateBatchReport_Obs_MixedNoSpecialObs(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
		{Key: canon.KeyOf("B"), Title: "B"},
		{Key: "", Title: ""},
	}
	audit := canon.AuditBatch(entries)
	report := canon.GenerateBatchReport(audit, "20260413212500000")

	for _, obs := range report.Observations {
		switch obs.Code {
		case canon.ObsEmptyBatch, canon.ObsAllAccepted, canon.ObsAllRejected, canon.ObsHighRejectionRate:
			t.Errorf("unexpected observation %q in balanced mixed batch", obs.Code)
		}
	}
}

// TestGenerateBatchReport_Obs_NilBatch validates nil batch = empty batch observation.
func TestGenerateBatchReport_Obs_NilBatch(t *testing.T) {
	audit := canon.AuditBatch(nil)
	report := canon.GenerateBatchReport(audit, "20260413212500000")

	if len(report.Observations) != 1 {
		t.Fatalf("Observations: got %d, want 1", len(report.Observations))
	}
	if report.Observations[0].Code != canon.ObsEmptyBatch {
		t.Errorf("Observation code: got %q, want %q", report.Observations[0].Code, canon.ObsEmptyBatch)
	}
}

// ---------------------------------------------------------------------------
// C. FormatBatchReport — human-readable output
// ---------------------------------------------------------------------------

// TestFormatBatchReport_ContainsHeader validates that the formatted report
// contains the expected header lines.
func TestFormatBatchReport_ContainsHeader(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
	}
	audit := canon.AuditBatch(entries)
	report := canon.GenerateBatchReport(audit, "20260413212500000")
	output := canon.FormatBatchReport(report)

	mustContain := []string{
		"=== Canon Gate Batch Report ===",
		"Session:",
		"SchemaVersion:",
		"GateVersion:",
		"Timestamp:",
	}
	for _, s := range mustContain {
		if !strings.Contains(output, s) {
			t.Errorf("FormatBatchReport missing %q", s)
		}
	}
}

// TestFormatBatchReport_ContainsSummary validates that the formatted report
// contains summary counters.
func TestFormatBatchReport_ContainsSummary(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
		{Key: "", Title: ""},
	}
	audit := canon.AuditBatch(entries)
	report := canon.GenerateBatchReport(audit, "20260413212500000")
	output := canon.FormatBatchReport(report)

	if !strings.Contains(output, "Total:    2") {
		t.Errorf("FormatBatchReport missing Total counter")
	}
	if !strings.Contains(output, "Accepted: 1") {
		t.Errorf("FormatBatchReport missing Accepted counter")
	}
	if !strings.Contains(output, "Rejected: 1") {
		t.Errorf("FormatBatchReport missing Rejected counter")
	}
}

// TestFormatBatchReport_ContainsItems validates that the formatted report
// lists individual items.
func TestFormatBatchReport_ContainsItems(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Alpha"), Title: "Alpha"},
		{Key: "", Title: "BadEntry"},
	}
	audit := canon.AuditBatch(entries)
	report := canon.GenerateBatchReport(audit, "20260413212500000")
	output := canon.FormatBatchReport(report)

	if !strings.Contains(output, "Alpha") {
		t.Error("FormatBatchReport missing accepted entry title")
	}
	if !strings.Contains(output, "BadEntry") {
		t.Error("FormatBatchReport missing rejected entry title")
	}
	if !strings.Contains(output, "--- Items ---") {
		t.Error("FormatBatchReport missing Items section")
	}
}

// TestFormatBatchReport_ContainsObservations validates that observations
// appear in the formatted output.
func TestFormatBatchReport_ContainsObservations(t *testing.T) {
	audit := canon.AuditBatch([]canon.CanonEntry{})
	report := canon.GenerateBatchReport(audit, "20260413212500000")
	output := canon.FormatBatchReport(report)

	if !strings.Contains(output, "--- Observations ---") {
		t.Error("FormatBatchReport missing Observations section")
	}
	if !strings.Contains(output, canon.ObsEmptyBatch) {
		t.Errorf("FormatBatchReport missing %q observation", canon.ObsEmptyBatch)
	}
}

// TestFormatBatchReport_EmptyBatch validates the complete output for an
// empty batch (minimal report).
func TestFormatBatchReport_EmptyBatch(t *testing.T) {
	audit := canon.AuditBatch([]canon.CanonEntry{})
	report := canon.GenerateBatchReport(audit, "20260413212500000")
	output := canon.FormatBatchReport(report)

	if !strings.Contains(output, "Total:    0") {
		t.Error("FormatBatchReport: empty batch should show Total: 0")
	}
	// Should NOT contain Items section for empty batch
	if strings.Contains(output, "--- Items ---") {
		t.Error("FormatBatchReport: empty batch should not have Items section")
	}
}

// ---------------------------------------------------------------------------
// D. JSON round-trip
// ---------------------------------------------------------------------------

// TestBatchReport_JSONRoundTrip validates that a BatchReport survives
// JSON serialization and deserialization intact.
func TestBatchReport_JSONRoundTrip(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A", Text: strPtr("body")},
		{Key: "", Title: "NoKey"},
		{Key: canon.KeyOf("C"), Title: "C"},
	}
	audit := canon.AuditBatch(entries)
	original := canon.GenerateBatchReport(audit, "20260413212500000")

	data, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("json.Marshal: %v", err)
	}

	var restored canon.BatchReport
	if err := json.Unmarshal(data, &restored); err != nil {
		t.Fatalf("json.Unmarshal: %v", err)
	}

	// Meta
	if restored.Meta.Session != original.Meta.Session {
		t.Errorf("Meta.Session: got %q, want %q", restored.Meta.Session, original.Meta.Session)
	}
	if restored.Meta.SchemaVersion != original.Meta.SchemaVersion {
		t.Errorf("Meta.SchemaVersion: got %q, want %q", restored.Meta.SchemaVersion, original.Meta.SchemaVersion)
	}
	if restored.Meta.GateVersion != original.Meta.GateVersion {
		t.Errorf("Meta.GateVersion: got %q, want %q", restored.Meta.GateVersion, original.Meta.GateVersion)
	}
	if restored.Meta.Timestamp != original.Meta.Timestamp {
		t.Errorf("Meta.Timestamp: got %q, want %q", restored.Meta.Timestamp, original.Meta.Timestamp)
	}

	// Summary
	if restored.Summary.Total != original.Summary.Total {
		t.Errorf("Summary.Total: got %d, want %d", restored.Summary.Total, original.Summary.Total)
	}
	if restored.Summary.Accepted != original.Summary.Accepted {
		t.Errorf("Summary.Accepted: got %d, want %d", restored.Summary.Accepted, original.Summary.Accepted)
	}
	if restored.Summary.Rejected != original.Summary.Rejected {
		t.Errorf("Summary.Rejected: got %d, want %d", restored.Summary.Rejected, original.Summary.Rejected)
	}

	// Items
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
	}

	// Observations
	if len(restored.Observations) != len(original.Observations) {
		t.Fatalf("Observations: got %d, want %d", len(restored.Observations), len(original.Observations))
	}
	for i := range original.Observations {
		if restored.Observations[i].Code != original.Observations[i].Code {
			t.Errorf("Observations[%d].Code: got %q, want %q",
				i, restored.Observations[i].Code, original.Observations[i].Code)
		}
	}
}

// ---------------------------------------------------------------------------
// E. Fixture-backed mixed batch report
// ---------------------------------------------------------------------------

// TestGenerateBatchReport_Fixture_MixedBatch loads the S22 batch audit
// fixture (canon_gate_batch_audit_mixed.jsonl), generates a report, and
// validates the expected structure.
//
// The fixture contains 10 lines: 5 valid + 5 invalid.
//
// Ref: S23 — fixture-backed batch report.
// Ref: S22 — mixed fixture definition.
func TestGenerateBatchReport_Fixture_MixedBatch(t *testing.T) {
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
	report := canon.GenerateBatchReport(audit, "20260413212500000")

	// Summary checks.
	if report.Summary.Total != 10 {
		t.Errorf("Total: got %d, want 10", report.Summary.Total)
	}
	if report.Summary.Accepted != 5 {
		t.Errorf("Accepted: got %d, want 5", report.Summary.Accepted)
	}
	if report.Summary.Rejected != 5 {
		t.Errorf("Rejected: got %d, want 5", report.Summary.Rejected)
	}

	// Items count.
	if len(report.Items) != 10 {
		t.Errorf("Items: got %d, want 10", len(report.Items))
	}

	// Meta is populated.
	if report.Meta.Session == "" {
		t.Error("Meta.Session should be populated")
	}
	if report.Meta.Timestamp != "20260413212500000" {
		t.Errorf("Meta.Timestamp: got %q", report.Meta.Timestamp)
	}

	// RejectsByReason is populated.
	if len(report.Summary.RejectsByReason) == 0 {
		t.Error("RejectsByReason should be populated for mixed batch")
	}

	// Tally consistency.
	tallySum := 0
	for _, rt := range report.Summary.RejectsByReason {
		tallySum += rt.Count
	}
	if tallySum != report.Summary.Rejected {
		t.Errorf("tally sum (%d) != Rejected (%d)", tallySum, report.Summary.Rejected)
	}

	// Observations: balanced batch (5 vs 5) — rejected == accepted, so no high_rejection_rate.
	// But since rejected > accepted is false (5 == 5), no high_rejection_rate.
	for _, obs := range report.Observations {
		if obs.Code == canon.ObsAllAccepted || obs.Code == canon.ObsAllRejected || obs.Code == canon.ObsEmptyBatch {
			t.Errorf("unexpected observation %q for 5/5 mixed batch", obs.Code)
		}
	}

	// Format check — ensure it produces non-empty output.
	output := canon.FormatBatchReport(report)
	if len(output) < 100 {
		t.Errorf("FormatBatchReport output too short (%d chars)", len(output))
	}

	t.Logf("Fixture report: total=%d accepted=%d rejected=%d observations=%d",
		report.Summary.Total, report.Summary.Accepted, report.Summary.Rejected,
		len(report.Observations))
}

// ---------------------------------------------------------------------------
// F. Consistency: report vs audit
// ---------------------------------------------------------------------------

// TestGenerateBatchReport_ConsistentWithAudit validates that the report
// summary and items are structurally identical to the source audit result.
func TestGenerateBatchReport_ConsistentWithAudit(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A", Text: strPtr("ok")},
		{Key: "", Title: ""},
		{Key: canon.KeyOf("C"), Title: "C"},
		{Key: canon.KeyOf("D"), Title: ""},
		{SchemaVersion: "v99", Key: canon.KeyOf("E"), Title: "E"},
		{Key: canon.KeyOf("F"), Title: "F"},
	}

	audit := canon.AuditBatch(entries)
	report := canon.GenerateBatchReport(audit, "20260413212500000")

	// Summary counters.
	if report.Summary.Total != audit.Summary.Total {
		t.Errorf("Total: report=%d, audit=%d", report.Summary.Total, audit.Summary.Total)
	}
	if report.Summary.Accepted != audit.Summary.Accepted {
		t.Errorf("Accepted: report=%d, audit=%d", report.Summary.Accepted, audit.Summary.Accepted)
	}
	if report.Summary.Rejected != audit.Summary.Rejected {
		t.Errorf("Rejected: report=%d, audit=%d", report.Summary.Rejected, audit.Summary.Rejected)
	}

	// RejectsByReason.
	if len(report.Summary.RejectsByReason) != len(audit.Summary.RejectsByReason) {
		t.Errorf("RejectsByReason: report=%d, audit=%d",
			len(report.Summary.RejectsByReason), len(audit.Summary.RejectsByReason))
	}

	// Items.
	if len(report.Items) != len(audit.Items) {
		t.Fatalf("Items: report=%d, audit=%d", len(report.Items), len(audit.Items))
	}
	for i := range audit.Items {
		if report.Items[i] != audit.Items[i] {
			t.Errorf("Items[%d]: report=%+v, audit=%+v", i, report.Items[i], audit.Items[i])
		}
	}
}

// ---------------------------------------------------------------------------
// G. Consistency with WriteJSONL through report
// ---------------------------------------------------------------------------

// TestGenerateBatchReport_ConsistentWithWriteJSONL validates that the
// report's accepted/rejected counts match WriteJSONL's written/skipped.
//
// This extends S22's consistency test through the report layer.
func TestGenerateBatchReport_ConsistentWithWriteJSONL(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
		{Key: "", Title: ""},
		{Key: canon.KeyOf("C"), Title: "C"},
	}

	audit := canon.AuditBatch(entries)
	report := canon.GenerateBatchReport(audit, "20260413212500000")

	var buf bytes.Buffer
	writeResult, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}

	if report.Summary.Accepted != writeResult.Written {
		t.Errorf("Report.Accepted (%d) != WriteJSONL.Written (%d)",
			report.Summary.Accepted, writeResult.Written)
	}
	if report.Summary.Rejected != writeResult.Skipped {
		t.Errorf("Report.Rejected (%d) != WriteJSONL.Skipped (%d)",
			report.Summary.Rejected, writeResult.Skipped)
	}
}
