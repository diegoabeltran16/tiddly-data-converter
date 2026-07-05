package canon

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

// ---------------------------------------------------------------------------
// S25 — batch_contract_test.go
//
// Contract-level tests that verify the cross-layer invariants declared in
// batch_contract.go. These tests operate on the frozen pipeline shape and
// are designed to break if any layer silently changes its interface or
// violates a stated invariant.
//
// The tests use deterministic fixtures so that parallel sessions can run
// them without coordination.
//
// Ref: S25 — contract v1 freeze.
// ---------------------------------------------------------------------------

// --- helpers ----------------------------------------------------------------

// contractFixtureMixed returns a deterministic mixed batch (3 valid + 3 invalid).
func contractFixtureMixed() []CanonEntry {
	txt := "body"
	return []CanonEntry{
		{Key: CanonKey("alpha"), Title: "Alpha", Text: &txt},
		{Key: "", Title: "NoKey"},                              // rejected: key empty
		{Key: CanonKey("beta"), Title: "Beta", Text: &txt},
		{Key: CanonKey("bad"), Title: ""},                      // rejected: title empty
		{Key: CanonKey("gamma"), Title: "Gamma"},
		{Key: "", Title: ""},                                   // rejected: key empty
	}
}

// contractFixtureAllValid returns 3 valid entries.
func contractFixtureAllValid() []CanonEntry {
	txt := "content"
	return []CanonEntry{
		{Key: CanonKey("one"), Title: "One", Text: &txt},
		{Key: CanonKey("two"), Title: "Two"},
		{Key: CanonKey("three"), Title: "Three", Text: &txt},
	}
}

// contractFixtureEmpty returns an empty batch.
func contractFixtureEmpty() []CanonEntry {
	return []CanonEntry{}
}

// --- Section A: Contract version -------------------------------------------

func TestBatchContractVersion(t *testing.T) {
	if BatchContractVersion != "v1" {
		t.Fatalf("BatchContractVersion = %q; want %q", BatchContractVersion, "v1")
	}
}

// --- Section B: INV-1 — Total == Accepted + Rejected (all layers) ----------

func TestContractINV1_AuditTotalEqualsAcceptedPlusRejected(t *testing.T) {
	for _, entries := range [][]CanonEntry{
		contractFixtureEmpty(),
		contractFixtureAllValid(),
		contractFixtureMixed(),
		nil,
	} {
		audit := AuditBatch(entries)
		if audit.Summary.Total != audit.Summary.Accepted+audit.Summary.Rejected {
			t.Errorf("INV-1 audit: Total=%d != Accepted(%d)+Rejected(%d)",
				audit.Summary.Total, audit.Summary.Accepted, audit.Summary.Rejected)
		}
	}
}

func TestContractINV1_ReportTotalEqualsAcceptedPlusRejected(t *testing.T) {
	for _, entries := range [][]CanonEntry{
		contractFixtureEmpty(),
		contractFixtureAllValid(),
		contractFixtureMixed(),
		nil,
	} {
		audit := AuditBatch(entries)
		report := BuildBatchReport(audit)
		if report.Total != report.Accepted+report.Rejected {
			t.Errorf("INV-1 report: Total=%d != Accepted(%d)+Rejected(%d)",
				report.Total, report.Accepted, report.Rejected)
		}
	}
}

func TestContractINV1_EmitTotalEqualsAcceptedPlusRejected(t *testing.T) {
	for _, entries := range [][]CanonEntry{
		contractFixtureEmpty(),
		contractFixtureAllValid(),
		contractFixtureMixed(),
		nil,
	} {
		var buf bytes.Buffer
		result, err := EmitBatchV0(&buf, entries)
		if err != nil {
			t.Fatalf("EmitBatchV0 error: %v", err)
		}
		if result.Total != result.Accepted+result.Rejected {
			t.Errorf("INV-1 emit: Total=%d != Accepted(%d)+Rejected(%d)",
				result.Total, result.Accepted, result.Rejected)
		}
	}
}

func TestContractINV1_VerdictTotalEqualsAcceptedPlusRejected(t *testing.T) {
	for _, entries := range [][]CanonEntry{
		contractFixtureEmpty(),
		contractFixtureAllValid(),
		contractFixtureMixed(),
		nil,
	} {
		audit := AuditBatch(entries)
		verdict := DeriveVerdict(audit)
		if verdict.Total != verdict.Accepted+verdict.Rejected {
			t.Errorf("INV-1 verdict: Total=%d != Accepted(%d)+Rejected(%d)",
				verdict.Total, verdict.Accepted, verdict.Rejected)
		}
	}
}

// --- Section C: INV-2 — len(Items) == Total (audit) -----------------------

func TestContractINV2_AuditItemCountEqualsTotal(t *testing.T) {
	for _, entries := range [][]CanonEntry{
		contractFixtureEmpty(),
		contractFixtureAllValid(),
		contractFixtureMixed(),
		nil,
	} {
		audit := AuditBatch(entries)
		if len(audit.Items) != audit.Summary.Total {
			t.Errorf("INV-2: len(Items)=%d != Total=%d",
				len(audit.Items), audit.Summary.Total)
		}
	}
}

// --- Section D: INV-3 — Items preserve input order (audit) -----------------

func TestContractINV3_AuditItemsPreserveOrder(t *testing.T) {
	entries := contractFixtureMixed()
	audit := AuditBatch(entries)
	for i, item := range audit.Items {
		if item.Index != i {
			t.Errorf("INV-3: item[%d].Index=%d; want %d", i, item.Index, i)
		}
		if item.Title != entries[i].Title {
			t.Errorf("INV-3: item[%d].Title=%q; want %q", i, item.Title, entries[i].Title)
		}
	}
}

// --- Section E: INV-4 — Written == Accepted (emit) -------------------------

func TestContractINV4_EmitWrittenEqualsAccepted(t *testing.T) {
	for _, entries := range [][]CanonEntry{
		contractFixtureEmpty(),
		contractFixtureAllValid(),
		contractFixtureMixed(),
		nil,
	} {
		var buf bytes.Buffer
		result, err := EmitBatchV0(&buf, entries)
		if err != nil {
			t.Fatalf("EmitBatchV0 error: %v", err)
		}
		if result.Written != result.Accepted {
			t.Errorf("INV-4: Written=%d != Accepted=%d",
				result.Written, result.Accepted)
		}
	}
}

// --- Section F: INV-5 and INV-6 — Report list lengths ----------------------

func TestContractINV5_AcceptedTitlesLengthEqualsAccepted(t *testing.T) {
	for _, entries := range [][]CanonEntry{
		contractFixtureEmpty(),
		contractFixtureAllValid(),
		contractFixtureMixed(),
		nil,
	} {
		audit := AuditBatch(entries)
		report := BuildBatchReport(audit)
		if len(report.AcceptedTitles) != report.Accepted {
			t.Errorf("INV-5: len(AcceptedTitles)=%d != Accepted=%d",
				len(report.AcceptedTitles), report.Accepted)
		}
	}
}

func TestContractINV6_RejectedEntriesLengthEqualsRejected(t *testing.T) {
	for _, entries := range [][]CanonEntry{
		contractFixtureEmpty(),
		contractFixtureAllValid(),
		contractFixtureMixed(),
		nil,
	} {
		audit := AuditBatch(entries)
		report := BuildBatchReport(audit)
		if len(report.RejectedEntries) != report.Rejected {
			t.Errorf("INV-6: len(RejectedEntries)=%d != Rejected=%d",
				len(report.RejectedEntries), report.Rejected)
		}
	}
}

// --- Section G: INV-7 — sum(RejectsByReason[].Count) == Rejected -----------

func TestContractINV7_RejectTallySumEqualsRejected(t *testing.T) {
	for _, entries := range [][]CanonEntry{
		contractFixtureEmpty(),
		contractFixtureAllValid(),
		contractFixtureMixed(),
		nil,
	} {
		audit := AuditBatch(entries)
		sum := 0
		for _, rt := range audit.Summary.RejectsByReason {
			sum += rt.Count
		}
		if sum != audit.Summary.Rejected {
			t.Errorf("INV-7: sum(RejectsByReason)=%d != Rejected=%d",
				sum, audit.Summary.Rejected)
		}
	}
}

// --- Section H: INV-8, INV-9, INV-10 — Cross-layer counter consistency ----

func TestContractINV8_ReportCountersEqualAudit(t *testing.T) {
	entries := contractFixtureMixed()
	audit := AuditBatch(entries)
	report := BuildBatchReport(audit)

	if report.Total != audit.Summary.Total {
		t.Errorf("INV-8: report.Total=%d != audit.Total=%d",
			report.Total, audit.Summary.Total)
	}
	if report.Accepted != audit.Summary.Accepted {
		t.Errorf("INV-8: report.Accepted=%d != audit.Accepted=%d",
			report.Accepted, audit.Summary.Accepted)
	}
	if report.Rejected != audit.Summary.Rejected {
		t.Errorf("INV-8: report.Rejected=%d != audit.Rejected=%d",
			report.Rejected, audit.Summary.Rejected)
	}
}

func TestContractINV9_VerdictCountersEqualAudit(t *testing.T) {
	entries := contractFixtureMixed()
	audit := AuditBatch(entries)
	verdict := DeriveVerdict(audit)

	if verdict.Total != audit.Summary.Total {
		t.Errorf("INV-9: verdict.Total=%d != audit.Total=%d",
			verdict.Total, audit.Summary.Total)
	}
	if verdict.Accepted != audit.Summary.Accepted {
		t.Errorf("INV-9: verdict.Accepted=%d != audit.Accepted=%d",
			verdict.Accepted, audit.Summary.Accepted)
	}
	if verdict.Rejected != audit.Summary.Rejected {
		t.Errorf("INV-9: verdict.Rejected=%d != audit.Rejected=%d",
			verdict.Rejected, audit.Summary.Rejected)
	}
}

func TestContractINV10_EmitCountersEqualAudit(t *testing.T) {
	entries := contractFixtureMixed()
	var buf bytes.Buffer
	result, err := EmitBatchV0(&buf, entries)
	if err != nil {
		t.Fatalf("EmitBatchV0 error: %v", err)
	}

	if result.Total != result.Audit.Summary.Total {
		t.Errorf("INV-10: result.Total=%d != audit.Total=%d",
			result.Total, result.Audit.Summary.Total)
	}
	if result.Accepted != result.Audit.Summary.Accepted {
		t.Errorf("INV-10: result.Accepted=%d != audit.Accepted=%d",
			result.Accepted, result.Audit.Summary.Accepted)
	}
	if result.Rejected != result.Audit.Summary.Rejected {
		t.Errorf("INV-10: result.Rejected=%d != audit.Rejected=%d",
			result.Rejected, result.Audit.Summary.Rejected)
	}
}

// --- Section I: Shape stability (JSON round-trip) --------------------------

func TestContractShapeStability_BatchAuditResult(t *testing.T) {
	entries := contractFixtureMixed()
	audit := AuditBatch(entries)

	data, err := json.Marshal(audit)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var restored BatchAuditResult
	if err := json.Unmarshal(data, &restored); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if restored.Summary.Total != audit.Summary.Total {
		t.Errorf("shape: audit Total mismatch after round-trip")
	}
	if len(restored.Items) != len(audit.Items) {
		t.Errorf("shape: audit Items length mismatch after round-trip")
	}
}

func TestContractShapeStability_BatchReport(t *testing.T) {
	audit := AuditBatch(contractFixtureMixed())
	report := BuildBatchReport(audit)

	data, err := json.Marshal(report)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var restored BatchReport
	if err := json.Unmarshal(data, &restored); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if restored.Total != report.Total {
		t.Errorf("shape: report Total mismatch after round-trip")
	}
	if len(restored.AcceptedTitles) != len(report.AcceptedTitles) {
		t.Errorf("shape: report AcceptedTitles length mismatch")
	}
	if len(restored.RejectedEntries) != len(report.RejectedEntries) {
		t.Errorf("shape: report RejectedEntries length mismatch")
	}
}

func TestContractShapeStability_EmitBatchResult(t *testing.T) {
	var buf bytes.Buffer
	result, err := EmitBatchV0(&buf, contractFixtureMixed())
	if err != nil {
		t.Fatalf("emit: %v", err)
	}

	data, err := json.Marshal(result)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var restored EmitBatchResult
	if err := json.Unmarshal(data, &restored); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if restored.Total != result.Total {
		t.Errorf("shape: emit Total mismatch after round-trip")
	}
	if restored.Written != result.Written {
		t.Errorf("shape: emit Written mismatch after round-trip")
	}
}

func TestContractShapeStability_GateVerdict(t *testing.T) {
	audit := AuditBatch(contractFixtureMixed())
	verdict := DeriveVerdict(audit)

	data, err := json.Marshal(verdict)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var restored GateVerdict
	if err := json.Unmarshal(data, &restored); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if restored.Verdict != verdict.Verdict {
		t.Errorf("shape: verdict mismatch after round-trip")
	}
	if restored.Total != verdict.Total {
		t.Errorf("shape: verdict Total mismatch after round-trip")
	}
}

// --- Section J: Emit output consistency ------------------------------------

func TestContractEmitOutputContainsOnlyAccepted(t *testing.T) {
	entries := contractFixtureMixed()
	var buf bytes.Buffer
	result, err := EmitBatchV0(&buf, entries)
	if err != nil {
		t.Fatalf("emit: %v", err)
	}

	// Count lines in output.
	output := buf.String()
	if output == "" {
		if result.Written != 0 {
			t.Errorf("output empty but Written=%d", result.Written)
		}
		return
	}
	lines := strings.Split(strings.TrimSuffix(output, "\n"), "\n")
	if len(lines) != result.Written {
		t.Errorf("output lines=%d != Written=%d", len(lines), result.Written)
	}

	// Verify every written line is an accepted entry.
	for i, line := range lines {
		var entry map[string]interface{}
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			t.Fatalf("line[%d] unmarshal: %v", i, err)
		}
		title, _ := entry["title"].(string)
		// Must be in AcceptedTitles.
		found := false
		for _, at := range result.Report.AcceptedTitles {
			if at == title {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("line[%d] title=%q not in AcceptedTitles", i, title)
		}
	}
}

// --- Section K: Schema version stamped on every written line ---------------

func TestContractSchemaVersionStamped(t *testing.T) {
	entries := contractFixtureAllValid()
	var buf bytes.Buffer
	_, err := EmitBatchV0(&buf, entries)
	if err != nil {
		t.Fatalf("emit: %v", err)
	}

	lines := strings.Split(strings.TrimSuffix(buf.String(), "\n"), "\n")
	for i, line := range lines {
		var entry map[string]interface{}
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			t.Fatalf("line[%d] unmarshal: %v", i, err)
		}
		sv, _ := entry["schema_version"].(string)
		if sv != SchemaV0 {
			t.Errorf("line[%d] schema_version=%q; want %q", i, sv, SchemaV0)
		}
	}
}

// --- Section L: Determinism ------------------------------------------------

func TestContractDeterminism_AuditBatch(t *testing.T) {
	entries := contractFixtureMixed()
	a1 := AuditBatch(entries)
	a2 := AuditBatch(entries)

	d1, _ := json.Marshal(a1)
	d2, _ := json.Marshal(a2)
	if string(d1) != string(d2) {
		t.Errorf("INV-determinism: two AuditBatch calls produce different JSON")
	}
}

func TestContractDeterminism_BuildBatchReport(t *testing.T) {
	audit := AuditBatch(contractFixtureMixed())
	r1 := BuildBatchReport(audit)
	r2 := BuildBatchReport(audit)

	d1, _ := json.Marshal(r1)
	d2, _ := json.Marshal(r2)
	if string(d1) != string(d2) {
		t.Errorf("INV-determinism: two BuildBatchReport calls produce different JSON")
	}
}

func TestContractDeterminism_DeriveVerdict(t *testing.T) {
	audit := AuditBatch(contractFixtureMixed())
	v1 := DeriveVerdict(audit)
	v2 := DeriveVerdict(audit)

	d1, _ := json.Marshal(v1)
	d2, _ := json.Marshal(v2)
	if string(d1) != string(d2) {
		t.Errorf("INV-determinism: two DeriveVerdict calls produce different JSON")
	}
}

func TestContractDeterminism_EmitBatchV0(t *testing.T) {
	entries := contractFixtureMixed()

	var buf1, buf2 bytes.Buffer
	r1, _ := EmitBatchV0(&buf1, entries)
	r2, _ := EmitBatchV0(&buf2, entries)

	if buf1.String() != buf2.String() {
		t.Errorf("INV-determinism: two EmitBatchV0 calls produce different output")
	}
	d1, _ := json.Marshal(r1)
	d2, _ := json.Marshal(r2)
	if string(d1) != string(d2) {
		t.Errorf("INV-determinism: two EmitBatchV0 results produce different JSON")
	}
}

// --- Section M: Report accepted titles match input order -------------------

func TestContractReportAcceptedTitlesPreserveInputOrder(t *testing.T) {
	entries := contractFixtureMixed()
	audit := AuditBatch(entries)
	report := BuildBatchReport(audit)

	// Collect expected accepted titles in input order.
	var expected []string
	for _, item := range audit.Items {
		if item.Verdict == VerdictAccepted {
			expected = append(expected, item.Title)
		}
	}

	if len(report.AcceptedTitles) != len(expected) {
		t.Fatalf("AcceptedTitles len=%d; want %d", len(report.AcceptedTitles), len(expected))
	}
	for i := range expected {
		if report.AcceptedTitles[i] != expected[i] {
			t.Errorf("AcceptedTitles[%d]=%q; want %q", i, report.AcceptedTitles[i], expected[i])
		}
	}
}

// --- Section N: Verdict values exhaustive ----------------------------------

func TestContractVerdictExhaustive(t *testing.T) {
	cases := []struct {
		name    string
		entries []CanonEntry
		want    BatchVerdict
	}{
		{"empty", contractFixtureEmpty(), VerdictEmpty},
		{"nil", nil, VerdictEmpty},
		{"all_valid", contractFixtureAllValid(), VerdictAccept},
		{"all_invalid", []CanonEntry{{Key: "", Title: ""}}, VerdictReject},
		{"mixed", contractFixtureMixed(), VerdictMixed},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			audit := AuditBatch(tc.entries)
			verdict := DeriveVerdict(audit)
			if verdict.Verdict != tc.want {
				t.Errorf("verdict=%q; want %q", verdict.Verdict, tc.want)
			}
		})
	}
}
