package ingesta_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/tiddly-data-converter/ingesta"
)

// fixtureDir returns the absolute path to the shared fixtures directory.
func fixtureDir(t *testing.T) string {
	t.Helper()
	// go/ingesta/ → ../../tests/fixtures/
	dir, err := filepath.Abs(filepath.Join("..", "..", "tests", "fixtures"))
	if err != nil {
		t.Fatalf("cannot resolve fixtures dir: %v", err)
	}
	if _, err := os.Stat(dir); err != nil {
		t.Fatalf("fixtures dir not found: %s", dir)
	}
	return dir
}

// TestIngest_MinimalFixture validates the happy-path ingestion using
// the shared fixture raw_tiddlers_minimal.json.
func TestIngest_MinimalFixture(t *testing.T) {
	path := filepath.Join(fixtureDir(t), "raw_tiddlers_minimal.json")

	tiddlers, report, err := ingesta.Ingest(path, ingesta.OriginHTML)
	if err != nil {
		t.Fatalf("unexpected IngestError: %v", err)
	}
	if report == nil {
		t.Fatal("report must not be nil")
	}

	// Fixture has 4 tiddlers; all should be ingested (BadCreated produces warning, not error).
	if report.TiddlerCount != 4 {
		t.Errorf("expected TiddlerCount=4, got %d", report.TiddlerCount)
	}
	if report.IngestedCount != 4 {
		t.Errorf("expected IngestedCount=4, got %d", report.IngestedCount)
	}
	if report.SkippedCount != 0 {
		t.Errorf("expected SkippedCount=0, got %d", report.SkippedCount)
	}
	if len(tiddlers) != 4 {
		t.Errorf("expected 4 tiddlers, got %d", len(tiddlers))
	}

	// BadCreated should produce a warning → verdict warning.
	if report.Verdict != ingesta.VerdictWarning {
		t.Errorf("expected verdict=%q, got %q", ingesta.VerdictWarning, report.Verdict)
	}
	if len(report.Warnings) == 0 {
		t.Error("expected at least one warning for BadCreated timestamp")
	}
}

// TestIngest_EmptyArray validates S05 §9.1: empty array produces ok.
func TestIngest_EmptyArray(t *testing.T) {
	tmp := t.TempDir()
	path := filepath.Join(tmp, "empty.json")
	if err := os.WriteFile(path, []byte("[]"), 0644); err != nil {
		t.Fatal(err)
	}

	tiddlers, report, err := ingesta.Ingest(path, ingesta.OriginHTML)
	if err != nil {
		t.Fatalf("unexpected IngestError: %v", err)
	}
	if report.Verdict != ingesta.VerdictOk {
		t.Errorf("expected verdict=ok for empty array, got %q", report.Verdict)
	}
	if report.TiddlerCount != 0 {
		t.Errorf("expected TiddlerCount=0, got %d", report.TiddlerCount)
	}
	if len(tiddlers) != 0 {
		t.Errorf("expected 0 tiddlers, got %d", len(tiddlers))
	}
}

// TestIngest_FileNotFound validates S05 §8: ERR_INGEST_FILE_NOT_FOUND.
func TestIngest_FileNotFound(t *testing.T) {
	_, _, err := ingesta.Ingest("/nonexistent/path.json", ingesta.OriginHTML)
	if err == nil {
		t.Fatal("expected IngestError for nonexistent file")
	}
	ie, ok := err.(*ingesta.IngestError)
	if !ok {
		t.Fatalf("expected *IngestError, got %T", err)
	}
	if ie.Code != ingesta.ErrFileNotFound {
		t.Errorf("expected code=%s, got %s", ingesta.ErrFileNotFound, ie.Code)
	}
}

// TestIngest_InvalidJSON validates S05 §8: ERR_INGEST_NOT_VALID_JSON.
func TestIngest_InvalidJSON(t *testing.T) {
	tmp := t.TempDir()
	path := filepath.Join(tmp, "bad.json")
	if err := os.WriteFile(path, []byte("{not json}"), 0644); err != nil {
		t.Fatal(err)
	}

	_, _, err := ingesta.Ingest(path, ingesta.OriginHTML)
	if err == nil {
		t.Fatal("expected IngestError for invalid JSON")
	}
	ie, ok := err.(*ingesta.IngestError)
	if !ok {
		t.Fatalf("expected *IngestError, got %T", err)
	}
	if ie.Code != ingesta.ErrNotValidJSON {
		t.Errorf("expected code=%s, got %s", ingesta.ErrNotValidJSON, ie.Code)
	}
}

// TestIngest_TagsParsing validates S05 §9.2: TW5 tag parsing.
func TestIngest_TagsParsing(t *testing.T) {
	tmp := t.TempDir()
	path := filepath.Join(tmp, "tags.json")
	raw := `[{"title":"T","raw_fields":{"tags":"[[multi word]] simple [[another tag]]"},"raw_text":null,"source_position":null}]`
	if err := os.WriteFile(path, []byte(raw), 0644); err != nil {
		t.Fatal(err)
	}

	tiddlers, report, err := ingesta.Ingest(path, ingesta.OriginJSON)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if report.Verdict != ingesta.VerdictOk {
		t.Errorf("expected verdict=ok, got %q", report.Verdict)
	}
	if len(tiddlers) != 1 {
		t.Fatalf("expected 1 tiddler, got %d", len(tiddlers))
	}
	tags := tiddlers[0].Tags
	expected := []string{"multi word", "simple", "another tag"}
	if len(tags) != len(expected) {
		t.Fatalf("expected %d tags, got %d: %v", len(expected), len(tags), tags)
	}
	for i, e := range expected {
		if tags[i] != e {
			t.Errorf("tag[%d]: expected %q, got %q", i, e, tags[i])
		}
	}
}

// TestIngest_SystemTiddler validates S05 §9.6: $:/ tiddlers are ingested normally.
func TestIngest_SystemTiddler(t *testing.T) {
	tmp := t.TempDir()
	path := filepath.Join(tmp, "sys.json")
	raw := `[{"title":"$:/core/modules/foo","raw_fields":{},"raw_text":"code","source_position":"0"}]`
	if err := os.WriteFile(path, []byte(raw), 0644); err != nil {
		t.Fatal(err)
	}

	tiddlers, report, err := ingesta.Ingest(path, ingesta.OriginHTML)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if report.IngestedCount != 1 {
		t.Errorf("expected IngestedCount=1, got %d", report.IngestedCount)
	}
	if tiddlers[0].Title != "$:/core/modules/foo" {
		t.Errorf("expected title=$:/core/modules/foo, got %q", tiddlers[0].Title)
	}
}

// TestIngest_OriginFormatPreserved validates that OriginFormat is set correctly.
func TestIngest_OriginFormatPreserved(t *testing.T) {
	tmp := t.TempDir()
	path := filepath.Join(tmp, "o.json")
	raw := `[{"title":"X","raw_fields":{},"raw_text":null,"source_position":null}]`
	if err := os.WriteFile(path, []byte(raw), 0644); err != nil {
		t.Fatal(err)
	}

	for _, origin := range []ingesta.OriginFormat{ingesta.OriginHTML, ingesta.OriginJSON} {
		tiddlers, _, err := ingesta.Ingest(path, origin)
		if err != nil {
			t.Fatalf("unexpected error for origin %s: %v", origin, err)
		}
		if tiddlers[0].OriginFormat != origin {
			t.Errorf("expected OriginFormat=%s, got %s", origin, tiddlers[0].OriginFormat)
		}
	}
}

// TestIngest_Determinism validates S05 §7.4: same input → same output.
func TestIngest_Determinism(t *testing.T) {
	path := filepath.Join(fixtureDir(t), "raw_tiddlers_minimal.json")

	t1, r1, err1 := ingesta.Ingest(path, ingesta.OriginHTML)
	t2, r2, err2 := ingesta.Ingest(path, ingesta.OriginHTML)

	if err1 != nil || err2 != nil {
		t.Fatalf("unexpected errors: %v, %v", err1, err2)
	}
	if r1.Verdict != r2.Verdict {
		t.Errorf("verdicts differ: %s vs %s", r1.Verdict, r2.Verdict)
	}
	if r1.IngestedCount != r2.IngestedCount {
		t.Errorf("ingested counts differ: %d vs %d", r1.IngestedCount, r2.IngestedCount)
	}
	if len(t1) != len(t2) {
		t.Errorf("tiddler counts differ: %d vs %d", len(t1), len(t2))
	}
	for i := range t1 {
		if t1[i].Title != t2[i].Title {
			t.Errorf("tiddler[%d] titles differ: %q vs %q", i, t1[i].Title, t2[i].Title)
		}
	}
}

// TestIngest_TimestampPrecisionFromRealCorpus validates S09 policy:
// TW5 timestamps with milliseconds are preserved with full precision.
//
// This test uses the fixture derived from real corpus in S08, which
// demonstrated that 337/338 timestamps had non-zero milliseconds that
// were being silently truncated before the S09 fix.
func TestIngest_TimestampPrecisionFromRealCorpus(t *testing.T) {
	path := filepath.Join(fixtureDir(t), "raw_tiddlers_timestamp_ms_from_data.json")

	tiddlers, report, err := ingesta.Ingest(path, ingesta.OriginHTML)
	if err != nil {
		t.Fatalf("unexpected IngestError: %v", err)
	}
	if report == nil {
		t.Fatal("report must not be nil")
	}

	// Fixture has 1 tiddler with created=20260409180825708 and modified=20260409180825708
	if report.TiddlerCount != 1 {
		t.Fatalf("expected TiddlerCount=1, got %d", report.TiddlerCount)
	}
	if report.IngestedCount != 1 {
		t.Fatalf("expected IngestedCount=1, got %d", report.IngestedCount)
	}
	if report.Verdict != ingesta.VerdictOk {
		t.Errorf("expected verdict=ok, got %q (warnings: %v)", report.Verdict, report.Warnings)
	}
	if len(tiddlers) != 1 {
		t.Fatalf("expected 1 tiddler, got %d", len(tiddlers))
	}

	// Verify the tiddler
	tiddler := tiddlers[0]
	if tiddler.Title != "LICENSE" {
		t.Errorf("expected title=LICENSE, got %q", tiddler.Title)
	}

	// Verify Created timestamp preserves milliseconds (708ms)
	if tiddler.Created == nil {
		t.Fatal("Created timestamp should not be nil")
	}
	expectedCreatedMs := 708 * 1000000 // 708ms in nanoseconds
	actualCreatedNs := tiddler.Created.Nanosecond()
	if actualCreatedNs != expectedCreatedMs {
		t.Errorf("Created milliseconds not preserved: expected %dns (708ms), got %dns",
			expectedCreatedMs, actualCreatedNs)
	}

	// Verify Modified timestamp preserves milliseconds (708ms)
	if tiddler.Modified == nil {
		t.Fatal("Modified timestamp should not be nil")
	}
	expectedModifiedMs := 708 * 1000000
	actualModifiedNs := tiddler.Modified.Nanosecond()
	if actualModifiedNs != expectedModifiedMs {
		t.Errorf("Modified milliseconds not preserved: expected %dns (708ms), got %dns",
			expectedModifiedMs, actualModifiedNs)
	}

	// Verify base timestamp values
	if tiddler.Created.Year() != 2026 || tiddler.Created.Month() != 4 || tiddler.Created.Day() != 9 {
		t.Errorf("unexpected Created date: %v", tiddler.Created)
	}
	if tiddler.Created.Hour() != 18 || tiddler.Created.Minute() != 8 || tiddler.Created.Second() != 25 {
		t.Errorf("unexpected Created time: %v", tiddler.Created)
	}
}

// TestIngest_D1ExactDuplicatePassthrough validates S11 observation:
// Ingesta (pre-canonical) passes D1 duplicates through without deduplication.
// D1: same title + same content — both tiddlers are ingested; deduplication
// is deferred to the Canon layer (S05 §9.8).
func TestIngest_D1ExactDuplicatePassthrough(t *testing.T) {
	path := filepath.Join(fixtureDir(t), "raw_tiddlers_d1_exact_duplicate.json")

	tiddlers, report, err := ingesta.Ingest(path, ingesta.OriginHTML)
	if err != nil {
		t.Fatalf("unexpected IngestError: %v", err)
	}
	if report == nil {
		t.Fatal("report must not be nil")
	}

	// Fixture has 2 tiddlers with identical title and content.
	// Ingesta MUST pass both through — deduplication is not its responsibility.
	if report.TiddlerCount != 2 {
		t.Errorf("expected TiddlerCount=2, got %d", report.TiddlerCount)
	}
	if report.IngestedCount != 2 {
		t.Errorf("expected IngestedCount=2 (both duplicates pass through), got %d", report.IngestedCount)
	}
	if report.SkippedCount != 0 {
		t.Errorf("expected SkippedCount=0 (no deduplication at this layer), got %d", report.SkippedCount)
	}
	if len(tiddlers) != 2 {
		t.Errorf("expected 2 tiddlers in output, got %d", len(tiddlers))
	}
	// Both should have the same title.
	if tiddlers[0].Title != "LICENSE" || tiddlers[1].Title != "LICENSE" {
		t.Errorf("expected both tiddlers titled LICENSE, got %q and %q", tiddlers[0].Title, tiddlers[1].Title)
	}
}

// TestIngest_D2SameTitleDiffContentPassthrough validates S11 observation:
// Ingesta (pre-canonical) passes D2 duplicates through without resolving the collision.
// D2: same title + different content — both versions are ingested; the Canon
// layer is responsible for deciding which version is authoritative (S05 §9.8).
func TestIngest_D2SameTitleDiffContentPassthrough(t *testing.T) {
	path := filepath.Join(fixtureDir(t), "raw_tiddlers_d2_same_title_diff_content.json")

	tiddlers, report, err := ingesta.Ingest(path, ingesta.OriginHTML)
	if err != nil {
		t.Fatalf("unexpected IngestError: %v", err)
	}
	if report == nil {
		t.Fatal("report must not be nil")
	}

	// Fixture has 2 tiddlers with the same title but different content/timestamps.
	// Both must pass through; the D2 collision is not resolved at Ingesta level.
	if report.TiddlerCount != 2 {
		t.Errorf("expected TiddlerCount=2, got %d", report.TiddlerCount)
	}
	if report.IngestedCount != 2 {
		t.Errorf("expected IngestedCount=2 (both D2 versions pass through), got %d", report.IngestedCount)
	}
	if len(tiddlers) != 2 {
		t.Errorf("expected 2 tiddlers in output, got %d", len(tiddlers))
	}
	// Both should share the same title.
	if tiddlers[0].Title != "estructura.txt" || tiddlers[1].Title != "estructura.txt" {
		t.Errorf("expected both tiddlers titled 'estructura.txt', got %q and %q",
			tiddlers[0].Title, tiddlers[1].Title)
	}
	// Content must differ to confirm this is a D2 case.
	text0 := ""
	if tiddlers[0].Text != nil {
		text0 = *tiddlers[0].Text
	}
	text1 := ""
	if tiddlers[1].Text != nil {
		text1 = *tiddlers[1].Text
	}
	if text0 == text1 {
		t.Error("D2 fixture: expected different text content between the two tiddlers")
	}
}

// TestIngest_D4NearDuplicatePassthrough validates S11 observation:
// Ingesta (pre-canonical) passes D4 near-duplicates through without semantic comparison.
// D4: different title + highly similar content — both tiddlers are ingested as-is.
// Near-duplicate resolution requires semantic analysis at Canon layer.
func TestIngest_D4NearDuplicatePassthrough(t *testing.T) {
	path := filepath.Join(fixtureDir(t), "raw_tiddlers_d4_near_duplicate.json")

	tiddlers, report, err := ingesta.Ingest(path, ingesta.OriginHTML)
	if err != nil {
		t.Fatalf("unexpected IngestError: %v", err)
	}
	if report == nil {
		t.Fatal("report must not be nil")
	}

	// Fixture has 2 tiddlers with different titles but highly similar text content.
	// Both must pass through; near-duplicate detection is out of scope for Ingesta.
	if report.TiddlerCount != 2 {
		t.Errorf("expected TiddlerCount=2, got %d", report.TiddlerCount)
	}
	if report.IngestedCount != 2 {
		t.Errorf("expected IngestedCount=2 (both D4 near-duplicates pass through), got %d", report.IngestedCount)
	}
	if len(tiddlers) != 2 {
		t.Errorf("expected 2 tiddlers in output, got %d", len(tiddlers))
	}
	// Titles must differ (distinguishing D4 from D1/D2).
	if tiddlers[0].Title == tiddlers[1].Title {
		t.Errorf("D4 fixture: expected different titles, both got %q", tiddlers[0].Title)
	}
}
