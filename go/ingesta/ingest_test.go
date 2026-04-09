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
