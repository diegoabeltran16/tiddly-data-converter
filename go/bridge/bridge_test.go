package bridge_test

import (
	"testing"

	"github.com/tiddly-data-converter/bridge"
	"github.com/tiddly-data-converter/canon"
	"github.com/tiddly-data-converter/ingesta"
)

// strPtr is a test helper to create a *string from a literal.
func strPtr(s string) *string { return &s }

// ---------------------------------------------------------------------------
// Conversion tests — ToCanonEntry
// ---------------------------------------------------------------------------

// TestToCanonEntry_MinimalFields validates the bridge conversion of a
// minimal ingesta.Tiddler into a canon.CanonEntry.
//
// Ref: S14 §A — bridge mínimo.
func TestToCanonEntry_MinimalFields(t *testing.T) {
	it := ingesta.Tiddler{
		Title: "LICENSE",
		Text:  strPtr("Apache License 2.0"),
	}

	ce := bridge.ToCanonEntry(it)

	if ce.Key != canon.CanonKey("LICENSE") {
		t.Errorf("Key: got %q, want %q", ce.Key, "LICENSE")
	}
	if ce.Title != "LICENSE" {
		t.Errorf("Title: got %q, want %q", ce.Title, "LICENSE")
	}
	if ce.Text == nil || *ce.Text != "Apache License 2.0" {
		t.Errorf("Text: got %v, want %q", ce.Text, "Apache License 2.0")
	}
	if ce.SourcePosition != nil {
		t.Errorf("SourcePosition: got %v, want nil", ce.SourcePosition)
	}
}

// TestToCanonEntry_AllFields validates that Title, Text, and SourcePosition
// are all correctly carried from ingesta.Tiddler to canon.CanonEntry.
//
// Ref: S14 §A — bridge mínimo.
func TestToCanonEntry_AllFields(t *testing.T) {
	it := ingesta.Tiddler{
		Title:          "estructura.txt",
		Text:           strPtr("├── .gitignore\n├── contratos"),
		SourcePosition: strPtr("tiddler-store:144"),
		Tags:           []string{"tag1", "tag2"},
		OriginFormat:   ingesta.OriginHTML,
		Fields:         map[string]string{"custom": "value"},
	}

	ce := bridge.ToCanonEntry(it)

	if ce.Key != canon.CanonKey("estructura.txt") {
		t.Errorf("Key: got %q, want %q", ce.Key, "estructura.txt")
	}
	if ce.Title != "estructura.txt" {
		t.Errorf("Title: got %q", ce.Title)
	}
	if ce.Text == nil || *ce.Text != "├── .gitignore\n├── contratos" {
		t.Errorf("Text: got %v", ce.Text)
	}
	if ce.SourcePosition == nil || *ce.SourcePosition != "tiddler-store:144" {
		t.Errorf("SourcePosition: got %v", ce.SourcePosition)
	}
}

// TestToCanonEntry_NilText validates that a tiddler with no text is
// converted to a CanonEntry with nil text.
func TestToCanonEntry_NilText(t *testing.T) {
	it := ingesta.Tiddler{
		Title: "$:/StoryList",
	}

	ce := bridge.ToCanonEntry(it)

	if ce.Text != nil {
		t.Errorf("Text: got %v, want nil", ce.Text)
	}
}

// TestToCanonEntries_BatchConversion validates batch conversion preserves
// order and count.
//
// Ref: S14 §A — bridge mínimo batch.
func TestToCanonEntries_BatchConversion(t *testing.T) {
	tiddlers := []ingesta.Tiddler{
		{Title: "Alpha", Text: strPtr("content A")},
		{Title: "Beta", Text: strPtr("content B")},
		{Title: "Gamma"},
	}

	entries := bridge.ToCanonEntries(tiddlers)

	if len(entries) != 3 {
		t.Fatalf("expected 3 entries, got %d", len(entries))
	}
	for i, tt := range tiddlers {
		if entries[i].Title != tt.Title {
			t.Errorf("[%d] Title: got %q, want %q", i, entries[i].Title, tt.Title)
		}
	}
}

// TestToCanonEntries_EmptySlice validates that converting an empty slice
// produces an empty (non-nil) result.
func TestToCanonEntries_EmptySlice(t *testing.T) {
	entries := bridge.ToCanonEntries([]ingesta.Tiddler{})
	if entries == nil {
		t.Fatal("expected non-nil empty slice")
	}
	if len(entries) != 0 {
		t.Errorf("expected 0 entries, got %d", len(entries))
	}
}

// ---------------------------------------------------------------------------
// Admission tests — Admit
// ---------------------------------------------------------------------------

// TestAdmit_AllDistinct validates that a batch with no collisions reports
// all entries as distinct.
//
// Ref: S14 §B — admission smoke.
func TestAdmit_AllDistinct(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Alpha"), Title: "Alpha", Text: strPtr("unique content A")},
		{Key: canon.KeyOf("Beta"), Title: "Beta", Text: strPtr("unique content B")},
		{Key: canon.KeyOf("Gamma"), Title: "Gamma", Text: strPtr("unique content C")},
	}

	report := bridge.Admit(entries)

	if report.InputCount != 3 {
		t.Errorf("InputCount: got %d, want 3", report.InputCount)
	}
	if report.DistinctCount != 3 {
		t.Errorf("DistinctCount: got %d, want 3", report.DistinctCount)
	}
	if report.D1Count != 0 {
		t.Errorf("D1Count: got %d, want 0", report.D1Count)
	}
	if len(report.Collisions) != 0 {
		t.Errorf("Collisions: got %d, want 0", len(report.Collisions))
	}
}

// TestAdmit_D1Collision validates that D1 (exact duplicate) is detected
// by the admission process.
//
// Ref: S14 §B — admission smoke.
// Ref: S13 §C — D1 classification.
func TestAdmit_D1Collision(t *testing.T) {
	body := "Apache License 2.0"
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("LICENSE"), Title: "LICENSE", Text: strPtr(body), SourcePosition: strPtr("pos:1")},
		{Key: canon.KeyOf("LICENSE"), Title: "LICENSE", Text: strPtr(body), SourcePosition: strPtr("pos:2")},
	}

	report := bridge.Admit(entries)

	if report.InputCount != 2 {
		t.Errorf("InputCount: got %d, want 2", report.InputCount)
	}
	if report.D1Count != 1 {
		t.Errorf("D1Count: got %d, want 1", report.D1Count)
	}
	if report.DistinctCount != 0 {
		t.Errorf("DistinctCount: got %d, want 0", report.DistinctCount)
	}
	if len(report.Collisions) != 1 {
		t.Fatalf("Collisions: got %d, want 1", len(report.Collisions))
	}
	if report.Collisions[0].Result.Class != canon.CollisionD1 {
		t.Errorf("Collision class: got %q, want D1", report.Collisions[0].Result.Class)
	}
}

// TestAdmit_D2Collision validates that D2 (same key, different content) is
// detected by the admission process.
//
// Ref: S14 §B — admission smoke.
// Ref: S13 §C — D2 classification.
func TestAdmit_D2Collision(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("estructura.txt"), Title: "estructura.txt", Text: strPtr("version 1")},
		{Key: canon.KeyOf("estructura.txt"), Title: "estructura.txt", Text: strPtr("version 2")},
	}

	report := bridge.Admit(entries)

	if report.D2Count != 1 {
		t.Errorf("D2Count: got %d, want 1", report.D2Count)
	}
	if len(report.Collisions) != 1 {
		t.Fatalf("Collisions: got %d, want 1", len(report.Collisions))
	}
	if report.Collisions[0].Result.Class != canon.CollisionD2 {
		t.Errorf("Collision class: got %q, want D2", report.Collisions[0].Result.Class)
	}
}

// TestAdmit_MixedCollisions validates admission with a realistic mix of
// distinct entries and various collision types.
//
// Ref: S14 §B — admission smoke.
func TestAdmit_MixedCollisions(t *testing.T) {
	body := "Apache License 2.0 — minimal representative body."
	entries := []canon.CanonEntry{
		// D1 pair: same key + same content
		{Key: canon.KeyOf("LICENSE"), Title: "LICENSE", Text: strPtr(body)},
		{Key: canon.KeyOf("LICENSE"), Title: "LICENSE", Text: strPtr(body)},
		// Distinct entry
		{Key: canon.KeyOf("README"), Title: "README", Text: strPtr("project readme")},
		// D2 pair: same key + different content
		{Key: canon.KeyOf("estructura.txt"), Title: "estructura.txt", Text: strPtr("v1")},
		{Key: canon.KeyOf("estructura.txt"), Title: "estructura.txt", Text: strPtr("v2")},
	}

	report := bridge.Admit(entries)

	if report.InputCount != 5 {
		t.Errorf("InputCount: got %d, want 5", report.InputCount)
	}
	if report.D1Count != 1 {
		t.Errorf("D1Count: got %d, want 1", report.D1Count)
	}
	if report.D2Count != 1 {
		t.Errorf("D2Count: got %d, want 1", report.D2Count)
	}
	if report.DistinctCount != 1 {
		t.Errorf("DistinctCount: got %d, want 1 (README)", report.DistinctCount)
	}
}

// TestAdmit_EmptyBatch validates that an empty batch produces a valid
// report with zero counters.
func TestAdmit_EmptyBatch(t *testing.T) {
	report := bridge.Admit([]canon.CanonEntry{})

	if report.InputCount != 0 {
		t.Errorf("InputCount: got %d, want 0", report.InputCount)
	}
	if report.DistinctCount != 0 {
		t.Errorf("DistinctCount: got %d, want 0", report.DistinctCount)
	}
	if len(report.Collisions) != 0 {
		t.Errorf("Collisions: got %d, want 0", len(report.Collisions))
	}
}

// TestAdmitReport_Summary validates the human-readable summary output.
func TestAdmitReport_Summary(t *testing.T) {
	report := &bridge.AdmitReport{
		InputCount:    5,
		DistinctCount: 3,
		D1Count:       1,
		D2Count:       1,
	}
	want := "input=5 distinct=3 d1=1 d2=1 d4=0 collisions=0"
	if got := report.Summary(); got != want {
		t.Errorf("Summary: got %q, want %q", got, want)
	}
}

// ---------------------------------------------------------------------------
// Integration test — end-to-end Ingesta → Bridge → Canon
// ---------------------------------------------------------------------------

// TestEndToEnd_IngestaToBridgeToCanon validates the full flow:
// ingesta.Tiddler → bridge.ToCanonEntries → bridge.Admit.
//
// This is the minimal integration evidence for S14.
// Ref: S14 §C — evidencia observable.
func TestEndToEnd_IngestaToBridgeToCanon(t *testing.T) {
	// Simulate ingesta output: 3 tiddlers with 1 D1 duplicate pair.
	body := "shared body content"
	tiddlers := []ingesta.Tiddler{
		{Title: "LICENSE", Text: strPtr(body), SourcePosition: strPtr("pos:1"), OriginFormat: ingesta.OriginHTML},
		{Title: "LICENSE", Text: strPtr(body), SourcePosition: strPtr("pos:2"), OriginFormat: ingesta.OriginHTML},
		{Title: "README", Text: strPtr("project description"), OriginFormat: ingesta.OriginHTML},
	}

	// Step 1: bridge conversion
	entries := bridge.ToCanonEntries(tiddlers)
	if len(entries) != 3 {
		t.Fatalf("ToCanonEntries: got %d, want 3", len(entries))
	}

	// Step 2: canon admission
	report := bridge.Admit(entries)

	// Step 3: verify observable evidence
	if report.InputCount != 3 {
		t.Errorf("InputCount: got %d, want 3", report.InputCount)
	}
	if report.D1Count != 1 {
		t.Errorf("D1Count: got %d, want 1 (LICENSE pair)", report.D1Count)
	}
	if report.DistinctCount != 1 {
		t.Errorf("DistinctCount: got %d, want 1 (README)", report.DistinctCount)
	}

	t.Logf("admission: %s", report.Summary())
}
