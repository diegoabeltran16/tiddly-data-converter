package bridge

import (
	"bytes"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/tiddly-data-converter/canon"
	"github.com/tiddly-data-converter/ingesta"
)

func TestReverseInsertOnlyHTML_SuccessAndDeterminism(t *testing.T) {
	baseHTML := mustReadFixture(t, "base.html")
	canonJSONL := mustReadFixture(t, "canon_with_new_valid.jsonl")

	first, err := ReverseInsertOnlyHTML(baseHTML, canonJSONL)
	if err != nil {
		t.Fatalf("ReverseInsertOnlyHTML first run: %v", err)
	}
	second, err := ReverseInsertOnlyHTML(baseHTML, canonJSONL)
	if err != nil {
		t.Fatalf("ReverseInsertOnlyHTML second run: %v", err)
	}

	if !bytes.Equal(first.HTML, second.HTML) {
		t.Fatal("reverse output is not deterministic across identical inputs")
	}

	if first.Report.InsertedCount != 1 {
		t.Fatalf("InsertedCount = %d, want 1", first.Report.InsertedCount)
	}
	if first.Report.AlreadyPresentCount != 2 {
		t.Fatalf("AlreadyPresentCount = %d, want 2", first.Report.AlreadyPresentCount)
	}
	if first.Report.RejectedCount != 0 {
		t.Fatalf("RejectedCount = %d, want 0", first.Report.RejectedCount)
	}

	output := string(first.HTML)
	if !strings.Contains(output, "\"title\":\"#### 🌀 Sesión 42 = canon-minimal-deterministic-reverse-v0\"") {
		t.Fatal("reversed HTML does not contain the inserted S42 tiddler")
	}
	if !strings.Contains(output, "\"custom\":\"preserve-me\"") {
		t.Fatal("existing base tiddler content was not preserved in the output store")
	}

	insertedIndex := strings.Index(output, "\"title\":\"#### 🌀 Sesión 42 = canon-minimal-deterministic-reverse-v0\"")
	betaIndex := strings.Index(output, "\"title\":\"Existing Beta\"")
	if insertedIndex <= betaIndex {
		t.Fatal("inserted tiddler should be appended after the existing store content")
	}
}

func TestReverseInsertOnlyHTML_RejectsCollision(t *testing.T) {
	baseHTML := mustReadFixture(t, "base.html")
	canonJSONL := mustReadFixture(t, "canon_with_collision.jsonl")

	result, err := ReverseInsertOnlyHTML(baseHTML, canonJSONL)
	if err == nil {
		t.Fatal("expected collision error, got nil")
	}
	if result == nil {
		t.Fatal("expected a report on collision failure")
	}
	if result.Report.RejectedCount != 1 {
		t.Fatalf("RejectedCount = %d, want 1", result.Report.RejectedCount)
	}
	if len(result.Report.Decisions) == 0 {
		t.Fatal("expected at least one decision in the collision report")
	}
	if result.Report.Decisions[0].RuleID != "existing-title-conflict" {
		t.Fatalf("RuleID = %q, want %q", result.Report.Decisions[0].RuleID, "existing-title-conflict")
	}
}

func TestReverseInsertOnlyFiles_DoesNotMutateBaseHTML(t *testing.T) {
	baseHTML := mustReadFixture(t, "base.html")
	canonJSONL := mustReadFixture(t, "canon_with_new_valid.jsonl")

	tmpDir := t.TempDir()
	basePath := filepath.Join(tmpDir, "base.html")
	canonPath := filepath.Join(tmpDir, "canon.jsonl")
	outPath := filepath.Join(tmpDir, "reversed.html")

	if err := os.WriteFile(basePath, baseHTML, 0o644); err != nil {
		t.Fatalf("write base fixture: %v", err)
	}
	if err := os.WriteFile(canonPath, canonJSONL, 0o644); err != nil {
		t.Fatalf("write canon fixture: %v", err)
	}

	before, err := os.ReadFile(basePath)
	if err != nil {
		t.Fatalf("read base before reverse: %v", err)
	}

	result, err := ReverseInsertOnlyFiles(basePath, canonPath, outPath)
	if err != nil {
		t.Fatalf("ReverseInsertOnlyFiles: %v", err)
	}
	if result.Report.InsertedCount != 1 {
		t.Fatalf("InsertedCount = %d, want 1", result.Report.InsertedCount)
	}

	after, err := os.ReadFile(basePath)
	if err != nil {
		t.Fatalf("read base after reverse: %v", err)
	}
	if !bytes.Equal(before, after) {
		t.Fatal("base HTML file was mutated in place")
	}

	if _, err := os.Stat(outPath); err != nil {
		t.Fatalf("expected output HTML to be written: %v", err)
	}
}

func TestReverseInsertOnlyHTML_RoundTripThroughExport(t *testing.T) {
	baseHTML := mustReadFixture(t, "base.html")
	canonJSONL := mustReadFixture(t, "canon_with_new_valid.jsonl")

	result, err := ReverseInsertOnlyHTML(baseHTML, canonJSONL)
	if err != nil {
		t.Fatalf("ReverseInsertOnlyHTML: %v", err)
	}

	raws, _, err := ExtractRawTiddlersFromHTML(bytes.NewReader(result.HTML))
	if err != nil {
		t.Fatalf("ExtractRawTiddlersFromHTML: %v", err)
	}

	filtered, _ := ApplyFilterRules(raws, DefaultFunctionalTiddlerRules(), "s42-roundtrip")

	tiddlers := make([]ingesta.Tiddler, 0, len(filtered))
	for _, raw := range filtered {
		tiddler, _, errs := ingesta.TransformOne(raw, ingesta.OriginHTML)
		if len(errs) > 0 {
			t.Fatalf("TransformOne(%q) errors: %v", raw.Title, errs)
		}
		tiddlers = append(tiddlers, tiddler)
	}

	entries := ToCanonEntries(tiddlers)
	var exported bytes.Buffer
	exportResult, err := canon.ExportTiddlersJSONL(&exported, entries, "s42-roundtrip")
	if err != nil {
		t.Fatalf("ExportTiddlersJSONL: %v", err)
	}
	if exportResult.Manifest.ExportedCount != len(entries) {
		t.Fatalf("ExportedCount = %d, want %d", exportResult.Manifest.ExportedCount, len(entries))
	}

	roundTripEntries, err := canon.ParseCanonJSONL(bytes.NewReader(exported.Bytes()))
	if err != nil {
		t.Fatalf("ParseCanonJSONL(roundtrip): %v", err)
	}

	var found canon.CanonEntry
	foundOK := false
	for _, entry := range roundTripEntries {
		if entry.Title == "#### 🌀 Sesión 42 = canon-minimal-deterministic-reverse-v0" {
			found = entry
			foundOK = true
			break
		}
	}
	if !foundOK {
		t.Fatal("round-trip export did not recover the inserted S42 tiddler")
	}

	if found.Text == nil || *found.Text != "## S42\n\nReverse mínimo controlado." {
		t.Fatalf("round-trip text = %v, want %q", found.Text, "## S42\n\nReverse mínimo controlado.")
	}
	if found.Created == nil || *found.Created != "20260416010101000" {
		t.Fatalf("round-trip created = %v, want %q", found.Created, "20260416010101000")
	}
	if found.Modified == nil || *found.Modified != "20260416010202000" {
		t.Fatalf("round-trip modified = %v, want %q", found.Modified, "20260416010202000")
	}
	if found.SourceType == nil || *found.SourceType != "text/vnd.tiddlywiki" {
		t.Fatalf("round-trip source_type = %v, want %q", found.SourceType, "text/vnd.tiddlywiki")
	}
	wantTags := []string{"session:m02-s42", "milestone:m02", "topic:reverse"}
	if !slices.Equal(found.SourceTags, wantTags) {
		t.Fatalf("round-trip source_tags = %v, want %v", found.SourceTags, wantTags)
	}
}

func mustReadFixture(t *testing.T, name string) []byte {
	t.Helper()

	path := filepath.Join("..", "..", "tests", "fixtures", "s42", name)
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read fixture %s: %v", path, err)
	}
	return data
}
