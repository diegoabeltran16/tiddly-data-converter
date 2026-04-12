package bridge_test

import (
	"testing"
	"time"

	"github.com/tiddly-data-converter/bridge"
	"github.com/tiddly-data-converter/canon"
	"github.com/tiddly-data-converter/ingesta"
)

// strPtr is a test helper to create a *string from a literal.
func strPtr(s string) *string { return &s }

// timePtr is a test helper to create a *time.Time from a value.
func timePtr(t time.Time) *time.Time { return &t }

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
	want := "input=5 distinct=3 d1=1 d2=1 d3=0 d4=0 collisions=0"
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

// ---------------------------------------------------------------------------
// S17 — D3 admission test
// ---------------------------------------------------------------------------

// TestAdmit_D3Collision validates that D3 (different key, exact same content)
// is detected and counted by the admission process.
//
// Ref: S15 — D3 explicit operational class.
// Ref: S17 — alignment with full D1/D2/D3/D4 grammar.
func TestAdmit_D3Collision(t *testing.T) {
	body := "shared body content across different titles"
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Alpha"), Title: "Alpha", Text: strPtr(body)},
		{Key: canon.KeyOf("Beta"), Title: "Beta", Text: strPtr(body)},
	}

	report := bridge.Admit(entries)

	if report.D3Count != 1 {
		t.Errorf("D3Count: got %d, want 1", report.D3Count)
	}
	if report.DistinctCount != 0 {
		t.Errorf("DistinctCount: got %d, want 0", report.DistinctCount)
	}
	if len(report.Collisions) != 1 {
		t.Fatalf("Collisions: got %d, want 1", len(report.Collisions))
	}
	if report.Collisions[0].Result.Class != canon.CollisionD3 {
		t.Errorf("Collision class: got %q, want D3", report.Collisions[0].Result.Class)
	}
}

// TestAdmitReport_Summary_WithD3 validates the summary output with D3 counter.
//
// Ref: S17 — observable D3 counters in admission report.
func TestAdmitReport_Summary_WithD3(t *testing.T) {
	report := &bridge.AdmitReport{
		InputCount:    6,
		DistinctCount: 2,
		D1Count:       1,
		D2Count:       1,
		D3Count:       1,
		D4Count:       0,
	}
	want := "input=6 distinct=2 d1=1 d2=1 d3=1 d4=0 collisions=0"
	if got := report.Summary(); got != want {
		t.Errorf("Summary: got %q, want %q", got, want)
	}
}

// ---------------------------------------------------------------------------
// S17 — Timestamp carriage tests
// ---------------------------------------------------------------------------

// TestToCanonEntry_WithTimestamps validates that created and modified
// timestamps are carried from ingesta.Tiddler to canon.CanonEntry via
// the bridge, formatted as TW5 17-digit strings.
//
// Ref: S09 — timestamp preservation policy.
// Ref: S17 — shape enrichment with created/modified.
func TestToCanonEntry_WithTimestamps(t *testing.T) {
	// 20230615143052123 → 2023-06-15 14:30:52.123
	created := time.Date(2023, 6, 15, 14, 30, 52, 123*int(time.Millisecond), time.UTC)
	modified := time.Date(2023, 6, 15, 15, 0, 0, 456*int(time.Millisecond), time.UTC)

	it := ingesta.Tiddler{
		Title:    "TestTiddler",
		Text:     strPtr("body content"),
		Created:  timePtr(created),
		Modified: timePtr(modified),
	}

	ce := bridge.ToCanonEntry(it)

	if ce.Created == nil {
		t.Fatal("Created: got nil, want non-nil")
	}
	wantCreated := "20230615143052123"
	if *ce.Created != wantCreated {
		t.Errorf("Created: got %q, want %q", *ce.Created, wantCreated)
	}

	if ce.Modified == nil {
		t.Fatal("Modified: got nil, want non-nil")
	}
	wantModified := "20230615150000456"
	if *ce.Modified != wantModified {
		t.Errorf("Modified: got %q, want %q", *ce.Modified, wantModified)
	}
}

// TestToCanonEntry_NilTimestamps validates that nil timestamps in the
// ingesta Tiddler result in nil timestamps in the CanonEntry.
//
// Ref: S17 — timestamps are optional, carried only when present.
func TestToCanonEntry_NilTimestamps(t *testing.T) {
	it := ingesta.Tiddler{
		Title: "NoTimestamps",
		Text:  strPtr("body"),
	}

	ce := bridge.ToCanonEntry(it)

	if ce.Created != nil {
		t.Errorf("Created: got %q, want nil", *ce.Created)
	}
	if ce.Modified != nil {
		t.Errorf("Modified: got %q, want nil", *ce.Modified)
	}
}

// TestToCanonEntry_OnlyCreated validates that only created is carried
// when modified is absent.
//
// Ref: S17 — each timestamp is independent.
func TestToCanonEntry_OnlyCreated(t *testing.T) {
	created := time.Date(2023, 1, 1, 0, 0, 0, 0, time.UTC)
	it := ingesta.Tiddler{
		Title:   "OnlyCreated",
		Created: timePtr(created),
	}

	ce := bridge.ToCanonEntry(it)

	if ce.Created == nil {
		t.Fatal("Created: got nil, want non-nil")
	}
	if *ce.Created != "20230101000000000" {
		t.Errorf("Created: got %q, want %q", *ce.Created, "20230101000000000")
	}
	if ce.Modified != nil {
		t.Errorf("Modified: got %q, want nil", *ce.Modified)
	}
}

// ---------------------------------------------------------------------------
// S17 — FormatTW5Timestamp tests
// ---------------------------------------------------------------------------

// TestFormatTW5Timestamp_WithMilliseconds validates the TW5 timestamp
// formatting with millisecond precision.
//
// Ref: S09 — TW5 timestamps are 17-digit strings.
// Ref: S17 — bridge carries timestamps in TW5 format.
func TestFormatTW5Timestamp_WithMilliseconds(t *testing.T) {
	ts := time.Date(2026, 4, 12, 0, 16, 0, 123*int(time.Millisecond), time.UTC)
	got := bridge.FormatTW5Timestamp(ts)
	want := "20260412001600123"
	if got != want {
		t.Errorf("FormatTW5Timestamp: got %q, want %q", got, want)
	}
}

// TestFormatTW5Timestamp_ZeroMilliseconds validates formatting when
// milliseconds are zero.
func TestFormatTW5Timestamp_ZeroMilliseconds(t *testing.T) {
	ts := time.Date(2023, 6, 15, 14, 30, 52, 0, time.UTC)
	got := bridge.FormatTW5Timestamp(ts)
	want := "20230615143052000"
	if got != want {
		t.Errorf("FormatTW5Timestamp: got %q, want %q", got, want)
	}
}

// TestEndToEnd_WithTimestamps validates the full flow including timestamps:
// ingesta.Tiddler (with created/modified) → bridge → canon.CanonEntry → Admit.
//
// Ref: S17 — end-to-end admission with timestamp enrichment.
func TestEndToEnd_WithTimestamps(t *testing.T) {
	created := time.Date(2023, 6, 15, 14, 30, 52, 123*int(time.Millisecond), time.UTC)
	modified := time.Date(2023, 6, 15, 15, 0, 0, 0, time.UTC)

	tiddlers := []ingesta.Tiddler{
		{
			Title:        "WithTimestamps",
			Text:         strPtr("body A"),
			Created:      timePtr(created),
			Modified:     timePtr(modified),
			OriginFormat: ingesta.OriginHTML,
		},
		{
			Title:        "NoTimestamps",
			Text:         strPtr("body B"),
			OriginFormat: ingesta.OriginHTML,
		},
	}

	entries := bridge.ToCanonEntries(tiddlers)
	if len(entries) != 2 {
		t.Fatalf("ToCanonEntries: got %d, want 2", len(entries))
	}

	// First entry has timestamps.
	if entries[0].Created == nil {
		t.Error("entries[0].Created: got nil, want non-nil")
	}
	if entries[0].Modified == nil {
		t.Error("entries[0].Modified: got nil, want non-nil")
	}

	// Second entry has no timestamps.
	if entries[1].Created != nil {
		t.Errorf("entries[1].Created: got %q, want nil", *entries[1].Created)
	}
	if entries[1].Modified != nil {
		t.Errorf("entries[1].Modified: got %q, want nil", *entries[1].Modified)
	}

	// Admission should work normally with timestamps present.
	report := bridge.Admit(entries)
	if report.InputCount != 2 {
		t.Errorf("InputCount: got %d, want 2", report.InputCount)
	}
	if report.DistinctCount != 2 {
		t.Errorf("DistinctCount: got %d, want 2", report.DistinctCount)
	}

	t.Logf("admission with timestamps: %s", report.Summary())
}
