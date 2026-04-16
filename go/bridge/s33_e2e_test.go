package bridge

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/tiddly-data-converter/canon"
	"github.com/tiddly-data-converter/ingesta"
)

// TestS33_E2E_ExportFromFixture runs the complete S33 pipeline end-to-end
// on the S33 fixture HTML and compares the output to the golden file.
//
// This test validates the entire Bridge→Canon costura:
//   1. HTML extraction via adapter_real_html
//   2. Filtering (exclude $:/ system tiddlers)
//   3. Ingesta transformation
//   4. Bridge conversion to CanonEntry
//   5. JSONL export with S19 gate
//   6. Golden file comparison
//
// Ref: contratos/m01-s33-single-jsonl-functional-tiddlers-from-real-html-v0.md.json
func TestS33_E2E_ExportFromFixture(t *testing.T) {
	// Locate fixture and golden relative to test file.
	fixtureHTML := filepath.Join("..", "..", "tests", "fixtures", "s33_sample", "s33_fixture.html")
	goldenPath := filepath.Join("..", "..", "tests", "golden", "s33", "export.jsonl")

	// Verify files exist.
	if _, err := os.Stat(fixtureHTML); err != nil {
		t.Skipf("fixture not found: %v", err)
	}
	if _, err := os.Stat(goldenPath); err != nil {
		t.Skipf("golden not found: %v", err)
	}

	// Step 1: Extract from HTML.
	htmlFile, err := os.Open(fixtureHTML)
	if err != nil {
		t.Fatalf("cannot open fixture: %v", err)
	}
	defer htmlFile.Close()

	raws, extractResult, err := ExtractRawTiddlersFromHTML(htmlFile)
	if err != nil {
		t.Fatalf("extraction failed: %v", err)
	}
	if extractResult.TotalExtracted != 6 {
		t.Errorf("TotalExtracted = %d, want 6", extractResult.TotalExtracted)
	}

	// Step 2: Filter.
	rules := DefaultFunctionalTiddlerRules()
	filtered, filterLog := ApplyFilterRules(raws, rules, "e2e-test-run")

	// Expect 4 user tiddlers (6 total - 2 system)
	if len(filtered) != 4 {
		t.Errorf("filtered = %d, want 4", len(filtered))
	}

	// Verify filter log has entries for all tiddlers.
	if len(filterLog) != 6 {
		t.Errorf("filterLog entries = %d, want 6", len(filterLog))
	}

	// Step 3: Ingest.
	var tiddlers []ingesta.Tiddler
	for _, raw := range filtered {
		tid, _, errs := ingesta.TransformOne(raw, ingesta.OriginHTML)
		if len(errs) > 0 {
			t.Errorf("ingest error for %q: %v", raw.Title, errs)
			continue
		}
		tiddlers = append(tiddlers, tid)
	}
	if len(tiddlers) != 4 {
		t.Fatalf("ingested tiddlers = %d, want 4", len(tiddlers))
	}

	// Step 4: Bridge.
	entries := ToCanonEntries(tiddlers)
	if len(entries) != 4 {
		t.Fatalf("canon entries = %d, want 4", len(entries))
	}

	// Step 5: Export JSONL.
	var buf bytes.Buffer
	exportResult, err := canon.ExportTiddlersJSONL(&buf, entries, "e2e-test-run")
	if err != nil {
		t.Fatalf("export failed: %v", err)
	}
	if exportResult.Manifest.ExportedCount != 4 {
		t.Errorf("ExportedCount = %d, want 4", exportResult.Manifest.ExportedCount)
	}
	if exportResult.Manifest.ExcludedCount != 0 {
		t.Errorf("ExcludedCount = %d, want 0", exportResult.Manifest.ExcludedCount)
	}

	// Step 6: Compare with golden.
	goldenData, err := os.ReadFile(goldenPath)
	if err != nil {
		t.Fatalf("cannot read golden: %v", err)
	}

	actualLines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	goldenLines := strings.Split(strings.TrimSpace(string(goldenData)), "\n")

	if len(actualLines) != len(goldenLines) {
		t.Fatalf("line count: actual=%d golden=%d", len(actualLines), len(goldenLines))
	}

	for i := range actualLines {
		// Compare as parsed JSON to handle field ordering differences.
		var actual, golden map[string]interface{}
		if err := json.Unmarshal([]byte(actualLines[i]), &actual); err != nil {
			t.Errorf("actual line[%d] invalid JSON: %v", i, err)
			continue
		}
		if err := json.Unmarshal([]byte(goldenLines[i]), &golden); err != nil {
			t.Errorf("golden line[%d] invalid JSON: %v", i, err)
			continue
		}

		// Check key fields match
		for _, field := range []string{"schema_version", "key", "title", "text", "created", "modified"} {
			if actual[field] != golden[field] {
				t.Errorf("line[%d] field %q: actual=%v golden=%v", i, field, actual[field], golden[field])
			}
		}
	}

	// Verify no duplication: all keys should be unique.
	seen := make(map[string]bool)
	for i, line := range actualLines {
		var entry map[string]interface{}
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			continue
		}
		key, _ := entry["key"].(string)
		if seen[key] {
			t.Errorf("duplicate key %q at line %d", key, i)
		}
		seen[key] = true
	}
}

// TestS33_E2E_TextPreservation verifies that the pipeline preserves
// textual content faithfully, including Unicode characters and newlines.
func TestS33_E2E_TextPreservation(t *testing.T) {
	fixtureHTML := filepath.Join("..", "..", "tests", "fixtures", "s33_sample", "s33_fixture.html")
	if _, err := os.Stat(fixtureHTML); err != nil {
		t.Skipf("fixture not found: %v", err)
	}

	htmlFile, err := os.Open(fixtureHTML)
	if err != nil {
		t.Fatalf("cannot open fixture: %v", err)
	}
	defer htmlFile.Close()

	raws, _, err := ExtractRawTiddlersFromHTML(htmlFile)
	if err != nil {
		t.Fatalf("extraction failed: %v", err)
	}

	rules := DefaultFunctionalTiddlerRules()
	filtered, _ := ApplyFilterRules(raws, rules, "text-preservation-run")

	var tiddlers []ingesta.Tiddler
	for _, raw := range filtered {
		tid, _, errs := ingesta.TransformOne(raw, ingesta.OriginHTML)
		if len(errs) > 0 {
			continue
		}
		tiddlers = append(tiddlers, tid)
	}

	entries := ToCanonEntries(tiddlers)

	var buf bytes.Buffer
	_, err = canon.ExportTiddlersJSONL(&buf, entries, "text-preservation-run")
	if err != nil {
		t.Fatalf("export failed: %v", err)
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")

	// Verify specific text content preservation
	expectedTexts := map[string]string{
		"Tiddler Alpha":    "Contenido del tiddler Alpha.\n\nUna segunda línea.",
		"Sesión de prueba": "Contenido de sesión de prueba con caracteres especiales: áéíóú ñ.",
	}

	for _, line := range lines {
		var entry canon.CanonEntry
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			continue
		}
		if expected, ok := expectedTexts[entry.Title]; ok {
			if entry.Text == nil {
				t.Errorf("tiddler %q: text is nil, want %q", entry.Title, expected)
			} else if *entry.Text != expected {
				t.Errorf("tiddler %q: text = %q, want %q", entry.Title, *entry.Text, expected)
			}
		}
	}

	// Verify nil text for "Tiddler Sin Texto"
	for _, line := range lines {
		var entry canon.CanonEntry
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			continue
		}
		if entry.Title == "Tiddler Sin Texto" && entry.Text != nil {
			t.Errorf("Tiddler Sin Texto should have nil text, got %q", *entry.Text)
		}
	}
}
