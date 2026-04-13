package canon_test

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/tiddly-data-converter/canon"
)

// ---------------------------------------------------------------------------
// S23 — canon-gate-batch-report-v0
//
// Tests for the aggregate report layer over the batch audit result.
// Validates that BuildBatchReport produces correct accepted/rejected lists,
// counters, reason distribution, and formatting.
//
// Ref: S23 — batch report over Canon gate batch audit.
// Ref: S22 — BatchAuditResult contract.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// A. BuildBatchReport — core tests
// ---------------------------------------------------------------------------

// TestBuildBatchReport_EmptyAudit validates that an empty audit result
// produces a valid report with zero counters and empty lists.
//
// Ref: S23 — empty batch report case.
func TestBuildBatchReport_EmptyAudit(t *testing.T) {
	audit := canon.AuditBatch([]canon.CanonEntry{})
	report := canon.BuildBatchReport(audit)

	if report.Total != 0 {
		t.Errorf("Total: got %d, want 0", report.Total)
	}
	if report.Accepted != 0 {
		t.Errorf("Accepted: got %d, want 0", report.Accepted)
	}
	if report.Rejected != 0 {
		t.Errorf("Rejected: got %d, want 0", report.Rejected)
	}
	if len(report.AcceptedTitles) != 0 {
		t.Errorf("AcceptedTitles: got %d, want 0", len(report.AcceptedTitles))
	}
	if len(report.RejectedEntries) != 0 {
		t.Errorf("RejectedEntries: got %d, want 0", len(report.RejectedEntries))
	}
}

// TestBuildBatchReport_AllValid validates that an all-accepted audit
// produces a report with all titles in AcceptedTitles and no rejected.
//
// Ref: S23 — all-accept batch report.
func TestBuildBatchReport_AllValid(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A", Text: strPtr("body A")},
		{Key: canon.KeyOf("B"), Title: "B"},
		{Key: canon.KeyOf("C"), Title: "C", Text: strPtr("body C")},
	}
	audit := canon.AuditBatch(entries)
	report := canon.BuildBatchReport(audit)

	if report.Total != 3 {
		t.Errorf("Total: got %d, want 3", report.Total)
	}
	if report.Accepted != 3 {
		t.Errorf("Accepted: got %d, want 3", report.Accepted)
	}
	if report.Rejected != 0 {
		t.Errorf("Rejected: got %d, want 0", report.Rejected)
	}
	if len(report.AcceptedTitles) != 3 {
		t.Fatalf("AcceptedTitles: got %d, want 3", len(report.AcceptedTitles))
	}
	wantTitles := []string{"A", "B", "C"}
	for i, want := range wantTitles {
		if report.AcceptedTitles[i] != want {
			t.Errorf("AcceptedTitles[%d]: got %q, want %q", i, report.AcceptedTitles[i], want)
		}
	}
	if len(report.RejectedEntries) != 0 {
		t.Errorf("RejectedEntries: got %d, want 0", len(report.RejectedEntries))
	}
}

// TestBuildBatchReport_AllInvalid validates that an all-rejected audit
// produces a report with no accepted titles and all entries in rejected.
//
// Ref: S23 — all-reject batch report.
func TestBuildBatchReport_AllInvalid(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: "", Title: ""},
		{Key: "", Title: "NoKey"},
		{Key: canon.KeyOf("NoTitle"), Title: ""},
	}
	audit := canon.AuditBatch(entries)
	report := canon.BuildBatchReport(audit)

	if report.Total != 3 {
		t.Errorf("Total: got %d, want 3", report.Total)
	}
	if report.Accepted != 0 {
		t.Errorf("Accepted: got %d, want 0", report.Accepted)
	}
	if report.Rejected != 3 {
		t.Errorf("Rejected: got %d, want 3", report.Rejected)
	}
	if len(report.AcceptedTitles) != 0 {
		t.Errorf("AcceptedTitles: got %d, want 0", len(report.AcceptedTitles))
	}
	if len(report.RejectedEntries) != 3 {
		t.Fatalf("RejectedEntries: got %d, want 3", len(report.RejectedEntries))
	}
	for i, entry := range report.RejectedEntries {
		if entry.Reason == "" {
			t.Errorf("RejectedEntries[%d]: reason should be non-empty", i)
		}
	}
}

// TestBuildBatchReport_MixedBatch validates a mixed batch report with
// both accepted and rejected entries, verifying lists, counters, and order.
//
// Ref: S23 — mixed batch report.
func TestBuildBatchReport_MixedBatch(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Good1"), Title: "Good1", Text: strPtr("ok")},    // 0: accept
		{Key: "", Title: ""},                                                // 1: reject
		{Key: canon.KeyOf("Good2"), Title: "Good2"},                        // 2: accept
		{Key: canon.KeyOf("BadTitle"), Title: ""},                          // 3: reject
		{SchemaVersion: "v99", Key: canon.KeyOf("BadVer"), Title: "BadVer"},// 4: reject
		{Key: canon.KeyOf("Good3"), Title: "Good3", Text: strPtr("ok2")},  // 5: accept
	}
	audit := canon.AuditBatch(entries)
	report := canon.BuildBatchReport(audit)

	if report.Total != 6 {
		t.Errorf("Total: got %d, want 6", report.Total)
	}
	if report.Accepted != 3 {
		t.Errorf("Accepted: got %d, want 3", report.Accepted)
	}
	if report.Rejected != 3 {
		t.Errorf("Rejected: got %d, want 3", report.Rejected)
	}

	// Accepted titles in input order.
	if len(report.AcceptedTitles) != 3 {
		t.Fatalf("AcceptedTitles: got %d, want 3", len(report.AcceptedTitles))
	}
	wantAccepted := []string{"Good1", "Good2", "Good3"}
	for i, want := range wantAccepted {
		if report.AcceptedTitles[i] != want {
			t.Errorf("AcceptedTitles[%d]: got %q, want %q", i, report.AcceptedTitles[i], want)
		}
	}

	// Rejected entries with correct indices.
	if len(report.RejectedEntries) != 3 {
		t.Fatalf("RejectedEntries: got %d, want 3", len(report.RejectedEntries))
	}
	wantRejectedIdx := []int{1, 3, 4}
	for i, wantIdx := range wantRejectedIdx {
		if report.RejectedEntries[i].Index != wantIdx {
			t.Errorf("RejectedEntries[%d].Index: got %d, want %d", i, report.RejectedEntries[i].Index, wantIdx)
		}
		if report.RejectedEntries[i].Reason == "" {
			t.Errorf("RejectedEntries[%d].Reason: should be non-empty", i)
		}
	}

	// Counter consistency.
	if report.Total != report.Accepted+report.Rejected {
		t.Errorf("Total (%d) != Accepted (%d) + Rejected (%d)",
			report.Total, report.Accepted, report.Rejected)
	}
}

// TestBuildBatchReport_ConsistentWithAudit validates that report counters
// match audit counters exactly.
//
// Ref: S23 — consistency between report and audit.
func TestBuildBatchReport_ConsistentWithAudit(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
		{Key: "", Title: "NoKey"},
		{Key: canon.KeyOf("C"), Title: "C"},
	}
	audit := canon.AuditBatch(entries)
	report := canon.BuildBatchReport(audit)

	if report.Total != audit.Summary.Total {
		t.Errorf("Total: report=%d, audit=%d", report.Total, audit.Summary.Total)
	}
	if report.Accepted != audit.Summary.Accepted {
		t.Errorf("Accepted: report=%d, audit=%d", report.Accepted, audit.Summary.Accepted)
	}
	if report.Rejected != audit.Summary.Rejected {
		t.Errorf("Rejected: report=%d, audit=%d", report.Rejected, audit.Summary.Rejected)
	}
	if len(report.AcceptedTitles) != audit.Summary.Accepted {
		t.Errorf("AcceptedTitles length (%d) != Accepted (%d)",
			len(report.AcceptedTitles), audit.Summary.Accepted)
	}
	if len(report.RejectedEntries) != audit.Summary.Rejected {
		t.Errorf("RejectedEntries length (%d) != Rejected (%d)",
			len(report.RejectedEntries), audit.Summary.Rejected)
	}
}

// TestBuildBatchReport_PreservesRejectsByReason validates that the
// report carries the same RejectsByReason distribution from the audit.
//
// Ref: S23 — reason distribution passthrough.
func TestBuildBatchReport_PreservesRejectsByReason(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: "", Title: "NoKey1"},
		{Key: "", Title: "NoKey2"},
		{Key: canon.KeyOf("NoTitle"), Title: ""},
	}
	audit := canon.AuditBatch(entries)
	report := canon.BuildBatchReport(audit)

	if len(report.RejectsByReason) != len(audit.Summary.RejectsByReason) {
		t.Fatalf("RejectsByReason: report has %d, audit has %d",
			len(report.RejectsByReason), len(audit.Summary.RejectsByReason))
	}
	for i := range audit.Summary.RejectsByReason {
		if report.RejectsByReason[i].Reason != audit.Summary.RejectsByReason[i].Reason {
			t.Errorf("RejectsByReason[%d].Reason: report=%q, audit=%q",
				i, report.RejectsByReason[i].Reason, audit.Summary.RejectsByReason[i].Reason)
		}
		if report.RejectsByReason[i].Count != audit.Summary.RejectsByReason[i].Count {
			t.Errorf("RejectsByReason[%d].Count: report=%d, audit=%d",
				i, report.RejectsByReason[i].Count, audit.Summary.RejectsByReason[i].Count)
		}
	}
}

// ---------------------------------------------------------------------------
// B. FormatBatchReport observability
// ---------------------------------------------------------------------------

// TestFormatBatchReport_NoRejections validates format with no rejections.
//
// Ref: S23 — observability.
func TestFormatBatchReport_NoRejections(t *testing.T) {
	report := canon.BatchReport{Total: 3, Accepted: 3, Rejected: 0}
	got := canon.FormatBatchReport(report)
	want := "batch_report: total=3 accepted=3 rejected=0"
	if got != want {
		t.Errorf("FormatBatchReport: got %q, want %q", got, want)
	}
}

// TestFormatBatchReport_WithRejections validates format with rejections.
//
// Ref: S23 — observability.
func TestFormatBatchReport_WithRejections(t *testing.T) {
	report := canon.BatchReport{
		Total:    6,
		Accepted: 3,
		Rejected: 3,
		RejectsByReason: []canon.RejectTally{
			{Reason: "key: required field is empty", Count: 2},
			{Reason: "title: required field is empty", Count: 1},
		},
	}
	got := canon.FormatBatchReport(report)
	want := "batch_report: total=6 accepted=3 rejected=3 reject_reasons=2"
	if got != want {
		t.Errorf("FormatBatchReport: got %q, want %q", got, want)
	}
}

// ---------------------------------------------------------------------------
// C. JSON serialization of BatchReport
// ---------------------------------------------------------------------------

// TestBatchReport_JSONRoundTrip validates that BatchReport serializes to
// JSON and deserializes back correctly.
//
// Ref: S23 — auditability via JSON serialization.
func TestBatchReport_JSONRoundTrip(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
		{Key: "", Title: "NoKey"},
		{Key: canon.KeyOf("C"), Title: "C"},
	}
	audit := canon.AuditBatch(entries)
	original := canon.BuildBatchReport(audit)

	data, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("json.Marshal: %v", err)
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
	if len(restored.AcceptedTitles) != len(original.AcceptedTitles) {
		t.Fatalf("AcceptedTitles: got %d, want %d", len(restored.AcceptedTitles), len(original.AcceptedTitles))
	}
	for i := range original.AcceptedTitles {
		if restored.AcceptedTitles[i] != original.AcceptedTitles[i] {
			t.Errorf("AcceptedTitles[%d]: got %q, want %q", i, restored.AcceptedTitles[i], original.AcceptedTitles[i])
		}
	}
}

// ---------------------------------------------------------------------------
// D. Nil audit
// ---------------------------------------------------------------------------

// TestBuildBatchReport_NilAudit validates that a nil-batch audit produces
// a valid report (same behavior as empty batch).
//
// Ref: S23 — defensive handling.
func TestBuildBatchReport_NilAudit(t *testing.T) {
	audit := canon.AuditBatch(nil)
	report := canon.BuildBatchReport(audit)

	if report.Total != 0 {
		t.Errorf("Total: got %d, want 0", report.Total)
	}
	if len(report.AcceptedTitles) != 0 {
		t.Errorf("AcceptedTitles: got %d, want 0", len(report.AcceptedTitles))
	}
	if len(report.RejectedEntries) != 0 {
		t.Errorf("RejectedEntries: got %d, want 0", len(report.RejectedEntries))
	}
}

// ---------------------------------------------------------------------------
// E. Rejected entry context quality
// ---------------------------------------------------------------------------

// TestBuildBatchReport_RejectedEntryContext validates that each rejected
// entry in the report contains sufficient context for identification.
//
// Ref: S23 — observability of rejections.
func TestBuildBatchReport_RejectedEntryContext(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Good"), Title: "Good"},
		{Key: "", Title: "NoKey"},
		{Key: canon.KeyOf("NoTitle"), Title: ""},
	}
	audit := canon.AuditBatch(entries)
	report := canon.BuildBatchReport(audit)

	if len(report.RejectedEntries) != 2 {
		t.Fatalf("RejectedEntries: got %d, want 2", len(report.RejectedEntries))
	}

	// First rejection: index 1, reason contains "key".
	if report.RejectedEntries[0].Index != 1 {
		t.Errorf("RejectedEntries[0].Index: got %d, want 1", report.RejectedEntries[0].Index)
	}
	if !strings.Contains(report.RejectedEntries[0].Reason, "key") {
		t.Errorf("RejectedEntries[0].Reason should contain 'key': %q", report.RejectedEntries[0].Reason)
	}

	// Second rejection: index 2, reason contains "title".
	if report.RejectedEntries[1].Index != 2 {
		t.Errorf("RejectedEntries[1].Index: got %d, want 2", report.RejectedEntries[1].Index)
	}
	if !strings.Contains(report.RejectedEntries[1].Reason, "title") {
		t.Errorf("RejectedEntries[1].Reason should contain 'title': %q", report.RejectedEntries[1].Reason)
	}
}
