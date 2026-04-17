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
	baseHTML := mustReadReverseFixture(t, "s42", "base.html")
	canonJSONL := mustReadReverseFixture(t, "s42", "canon_with_new_valid.jsonl")

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

	if first.Report.RawTiddlersEvaluated != 3 {
		t.Fatalf("RawTiddlersEvaluated = %d, want 3", first.Report.RawTiddlersEvaluated)
	}
	if first.Report.NonRawRecordsSkipped != 0 {
		t.Fatalf("NonRawRecordsSkipped = %d, want 0", first.Report.NonRawRecordsSkipped)
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
	if first.Report.SourceFieldsUsed {
		t.Fatal("SourceFieldsUsed = true, want false")
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
	baseHTML := mustReadReverseFixture(t, "s42", "base.html")
	canonJSONL := mustReadReverseFixture(t, "s42", "canon_with_collision.jsonl")

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
	if result.Report.RejectedByRule["existing-title-conflict"] != 1 {
		t.Fatalf("RejectedByRule[existing-title-conflict] = %d, want 1", result.Report.RejectedByRule["existing-title-conflict"])
	}
}

func TestReverseInsertOnlyFiles_DoesNotMutateBaseHTML(t *testing.T) {
	baseHTML := mustReadReverseFixture(t, "s42", "base.html")
	canonJSONL := mustReadReverseFixture(t, "s42", "canon_with_new_valid.jsonl")

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
	if result.Report.HTMLInputPath != basePath {
		t.Fatalf("HTMLInputPath = %q, want %q", result.Report.HTMLInputPath, basePath)
	}
	if result.Report.CanonInputPath != canonPath {
		t.Fatalf("CanonInputPath = %q, want %q", result.Report.CanonInputPath, canonPath)
	}
	if result.Report.OutputHTMLPath != outPath {
		t.Fatalf("OutputHTMLPath = %q, want %q", result.Report.OutputHTMLPath, outPath)
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

func TestReverseInsertOnlyHTML_MixedCanonInsertsMultipleRawTiddlers(t *testing.T) {
	baseHTML := mustReadReverseFixture(t, "s42", "base.html")
	canonJSONL := mustReadReverseFixture(t, "s43", "canon_mixed_multi.jsonl")

	result, err := ReverseInsertOnlyHTML(baseHTML, canonJSONL)
	if err != nil {
		t.Fatalf("ReverseInsertOnlyHTML: %v", err)
	}

	if result.Report.CanonLinesRead != 7 {
		t.Fatalf("CanonLinesRead = %d, want 7", result.Report.CanonLinesRead)
	}
	if result.Report.RawTiddlersEvaluated != 5 {
		t.Fatalf("RawTiddlersEvaluated = %d, want 5", result.Report.RawTiddlersEvaluated)
	}
	if result.Report.NonRawRecordsSkipped != 2 {
		t.Fatalf("NonRawRecordsSkipped = %d, want 2", result.Report.NonRawRecordsSkipped)
	}
	if result.Report.InsertedCount != 4 {
		t.Fatalf("InsertedCount = %d, want 4", result.Report.InsertedCount)
	}
	if result.Report.AlreadyPresentCount != 1 {
		t.Fatalf("AlreadyPresentCount = %d, want 1", result.Report.AlreadyPresentCount)
	}
	if result.Report.RejectedCount != 0 {
		t.Fatalf("RejectedCount = %d, want 0", result.Report.RejectedCount)
	}
	if !result.Report.SourceFieldsUsed {
		t.Fatal("SourceFieldsUsed = false, want true")
	}
	if result.Report.SourceFieldsUsedCount != 4 {
		t.Fatalf("SourceFieldsUsedCount = %d, want 4", result.Report.SourceFieldsUsedCount)
	}

	wantTypes := map[string]int{
		"text/vnd.tiddlywiki": 1,
		"text/markdown":       1,
		"text/plain":          1,
		"text/csv":            1,
		"application/json":    1,
	}
	if len(result.Report.ProcessedSourceTypes) != len(wantTypes) {
		t.Fatalf("ProcessedSourceTypes length = %d, want %d", len(result.Report.ProcessedSourceTypes), len(wantTypes))
	}
	for sourceType, want := range wantTypes {
		if got := result.Report.ProcessedSourceTypes[sourceType]; got != want {
			t.Fatalf("ProcessedSourceTypes[%q] = %d, want %d", sourceType, got, want)
		}
	}

	output := string(result.HTML)
	for _, needle := range []string{
		"\"title\":\"m03-s43-canon-robust-textual-reverse-v0.md\"",
		"\"title\":\"S43 Note Plain\"",
		"\"title\":\"S43 Table.csv\"",
		"\"title\":\"#### 🌀 Sesión 43 = canon-robust-textual-reverse-v0\"",
		"\"caption\":\"CSV Snapshot\"",
		"\"list\":\"Existing Alpha [[m03-s43-canon-robust-textual-reverse-v0.md]]\"",
		"\"tmap.id\":\"11111111-1111-4111-8111-111111111111\"",
	} {
		if !strings.Contains(output, needle) {
			t.Fatalf("reversed HTML does not contain %q", needle)
		}
	}

	markdownIndex := strings.Index(output, "\"title\":\"m03-s43-canon-robust-textual-reverse-v0.md\"")
	plainIndex := strings.Index(output, "\"title\":\"S43 Note Plain\"")
	csvIndex := strings.Index(output, "\"title\":\"S43 Table.csv\"")
	jsonIndex := strings.Index(output, "\"title\":\"#### 🌀 Sesión 43 = canon-robust-textual-reverse-v0\"")
	if !(markdownIndex < plainIndex && plainIndex < csvIndex && csvIndex < jsonIndex) {
		t.Fatal("inserted raw candidates were not appended in canon order")
	}
}

func TestReverseInsertOnlyHTML_RejectsInvalidRawCandidates(t *testing.T) {
	baseHTML := mustReadReverseFixture(t, "s42", "base.html")
	canonJSONL := mustReadReverseFixture(t, "s43", "invalid_raw_candidates.jsonl")

	result, err := ReverseInsertOnlyHTML(baseHTML, canonJSONL)
	if err == nil {
		t.Fatal("expected validation error for invalid raw candidates, got nil")
	}
	if result == nil {
		t.Fatal("expected a report on raw candidate rejection")
	}
	if len(result.HTML) != 0 {
		t.Fatal("result HTML should be empty when rejections stop the write")
	}
	if result.Report.RawTiddlersEvaluated != 5 {
		t.Fatalf("RawTiddlersEvaluated = %d, want 5", result.Report.RawTiddlersEvaluated)
	}
	if result.Report.AlreadyPresentCount != 1 {
		t.Fatalf("AlreadyPresentCount = %d, want 1", result.Report.AlreadyPresentCount)
	}
	if result.Report.RejectedCount != 4 {
		t.Fatalf("RejectedCount = %d, want 4", result.Report.RejectedCount)
	}

	expectedRules := []string{
		"unsupported-system-title",
		"invalid-source-tags",
		"unsupported-source-type",
		"source-fields-reserved-key",
	}
	for _, ruleID := range expectedRules {
		if result.Report.RejectedByRule[ruleID] != 1 {
			t.Fatalf("RejectedByRule[%q] = %d, want 1", ruleID, result.Report.RejectedByRule[ruleID])
		}
	}
	if len(result.Report.Decisions) != 5 {
		t.Fatalf("Decisions length = %d, want 5", len(result.Report.Decisions))
	}
}

func TestReverseInsertOnlyHTML_RoundTripThroughExport(t *testing.T) {
	baseHTML := mustReadReverseFixture(t, "s42", "base.html")
	canonJSONL := mustReadReverseFixture(t, "s42", "canon_with_new_valid.jsonl")

	result, err := ReverseInsertOnlyHTML(baseHTML, canonJSONL)
	if err != nil {
		t.Fatalf("ReverseInsertOnlyHTML: %v", err)
	}

	roundTripEntries := exportRoundTripEntries(t, result.HTML)
	found := findRoundTripEntry(t, roundTripEntries, "#### 🌀 Sesión 42 = canon-minimal-deterministic-reverse-v0")

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

func TestReverseInsertOnlyHTML_RoundTripPreservesSourceFieldsAuthority(t *testing.T) {
	baseHTML := mustReadReverseFixture(t, "s42", "base.html")
	canonJSONL := mustReadReverseFixture(t, "s43", "canon_mixed_multi.jsonl")

	result, err := ReverseInsertOnlyHTML(baseHTML, canonJSONL)
	if err != nil {
		t.Fatalf("ReverseInsertOnlyHTML: %v", err)
	}

	roundTripEntries := exportRoundTripEntries(t, result.HTML)

	markdown := findRoundTripEntry(t, roundTripEntries, "m03-s43-canon-robust-textual-reverse-v0.md")
	if markdown.SourceType == nil || *markdown.SourceType != "text/markdown" {
		t.Fatalf("markdown source_type = %v, want %q", markdown.SourceType, "text/markdown")
	}
	if markdown.SourceFields["caption"] != "S43 contract" {
		t.Fatalf("markdown source_fields[caption] = %q, want %q", markdown.SourceFields["caption"], "S43 contract")
	}

	plain := findRoundTripEntry(t, roundTripEntries, "S43 Note Plain")
	if plain.SourceType == nil || *plain.SourceType != "text/plain" {
		t.Fatalf("plain source_type = %v, want %q", plain.SourceType, "text/plain")
	}
	if plain.SourceFields["caption"] != "Plain note" {
		t.Fatalf("plain source_fields[caption] = %q, want %q", plain.SourceFields["caption"], "Plain note")
	}
	if plain.SourceFields["list"] != "Existing Alpha [[m03-s43-canon-robust-textual-reverse-v0.md]]" {
		t.Fatalf("plain source_fields[list] = %q, want %q", plain.SourceFields["list"], "Existing Alpha [[m03-s43-canon-robust-textual-reverse-v0.md]]")
	}

	csv := findRoundTripEntry(t, roundTripEntries, "S43 Table.csv")
	if csv.SourceType == nil || *csv.SourceType != "text/csv" {
		t.Fatalf("csv source_type = %v, want %q", csv.SourceType, "text/csv")
	}
	if csv.SourceFields["caption"] != "CSV Snapshot" {
		t.Fatalf("csv source_fields[caption] = %q, want %q", csv.SourceFields["caption"], "CSV Snapshot")
	}

	session := findRoundTripEntry(t, roundTripEntries, "#### 🌀 Sesión 43 = canon-robust-textual-reverse-v0")
	if session.SourceType == nil || *session.SourceType != "application/json" {
		t.Fatalf("session source_type = %v, want %q", session.SourceType, "application/json")
	}
	if session.SourceFields["caption"] != "Session 43" {
		t.Fatalf("session source_fields[caption] = %q, want %q", session.SourceFields["caption"], "Session 43")
	}
	if session.SourceFields["tmap.id"] != "11111111-1111-4111-8111-111111111111" {
		t.Fatalf("session source_fields[tmap.id] = %q, want %q", session.SourceFields["tmap.id"], "11111111-1111-4111-8111-111111111111")
	}
	wantTags := []string{"session:m03-s43", "milestone:m03", "topic:reverse"}
	if !slices.Equal(session.SourceTags, wantTags) {
		t.Fatalf("session source_tags = %v, want %v", session.SourceTags, wantTags)
	}
}

func exportRoundTripEntries(t *testing.T, html []byte) []canon.CanonEntry {
	t.Helper()

	raws, _, err := ExtractRawTiddlersFromHTML(bytes.NewReader(html))
	if err != nil {
		t.Fatalf("ExtractRawTiddlersFromHTML: %v", err)
	}

	filtered, _ := ApplyFilterRules(raws, DefaultFunctionalTiddlerRules(), "reverse-roundtrip")

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
	exportResult, err := canon.ExportTiddlersJSONL(&exported, entries, "reverse-roundtrip")
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
	return roundTripEntries
}

func findRoundTripEntry(t *testing.T, entries []canon.CanonEntry, title string) canon.CanonEntry {
	t.Helper()

	for _, entry := range entries {
		if entry.Title == title {
			return entry
		}
	}

	t.Fatalf("round-trip export did not recover %q", title)
	return canon.CanonEntry{}
}

func mustReadReverseFixture(t *testing.T, session, name string) []byte {
	t.Helper()

	path := filepath.Join("..", "..", "tests", "fixtures", session, name)
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read fixture %s: %v", path, err)
	}
	return data
}
