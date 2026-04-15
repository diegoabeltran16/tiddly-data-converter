package canon

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

// TestExportReadingModeIntegration_AllFieldsPresent verifies that the
// S33+S34+S35 exporter (ExportTiddlersJSONL) produces JSONL lines with
// all five reading mode fields: content_type, modality, encoding,
// is_binary, is_reference_only.
//
// Ref: S35 §19 — exporter JSONL must contain all 5 reading mode fields.
func TestExportReadingModeIntegration_AllFieldsPresent(t *testing.T) {
	text1 := "Content of Alpha"
	st1 := "text/plain"
	text2 := `{"key":"value"}`
	st2 := "application/json"
	entries := []CanonEntry{
		{Key: "Alpha", Title: "Alpha", Text: &text1, SourceType: &st1},
		{Key: "Beta Node", Title: "Beta Node", Text: &text2, SourceType: &st2},
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "rm-integration-001")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if result.Manifest.ExportedCount != 2 {
		t.Fatalf("ExportedCount = %d, want 2", result.Manifest.ExportedCount)
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 2 {
		t.Fatalf("JSONL lines = %d, want 2", len(lines))
	}

	readingModeFields := []string{"content_type", "modality", "encoding", "is_binary", "is_reference_only"}

	for i, line := range lines {
		var m map[string]interface{}
		if err := json.Unmarshal([]byte(line), &m); err != nil {
			t.Errorf("line[%d] invalid JSON: %v", i, err)
			continue
		}
		for _, f := range readingModeFields {
			if _, ok := m[f]; !ok {
				t.Errorf("line[%d] missing field %q", i, f)
			}
		}
	}
}

// TestExportReadingModeIntegration_ContentTypeValues verifies that
// specific entries produce the expected content_type values.
func TestExportReadingModeIntegration_ContentTypeValues(t *testing.T) {
	text1 := "Simple text"
	st1 := "text/plain"
	text2 := `{"a":1}`
	st2 := "application/json"
	text3 := "Wiki ''content''"
	st3 := "text/vnd.tiddlywiki"

	entries := []CanonEntry{
		{Key: "Plain", Title: "Plain", Text: &text1, SourceType: &st1},
		{Key: "JSON", Title: "JSON", Text: &text2, SourceType: &st2},
		{Key: "Wiki", Title: "Wiki", Text: &text3, SourceType: &st3},
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "ct-values-001")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Manifest.ExportedCount != 3 {
		t.Fatalf("ExportedCount = %d, want 3", result.Manifest.ExportedCount)
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	wantCT := []string{ContentTypePlain, ContentTypeJSON, ContentTypeTiddlyWiki}

	for i, line := range lines {
		var e CanonEntry
		if err := json.Unmarshal([]byte(line), &e); err != nil {
			t.Errorf("line[%d] invalid JSON: %v", i, err)
			continue
		}
		if e.ContentType != wantCT[i] {
			t.Errorf("line[%d] content_type = %q, want %q", i, e.ContentType, wantCT[i])
		}
	}
}

// TestExportReadingModeIntegration_ManifestConteos verifies that the
// export manifest includes S35 conteos.
func TestExportReadingModeIntegration_ManifestConteos(t *testing.T) {
	text1 := "Text content"
	st1 := "text/plain"
	text2 := `{"k":"v"}`
	st2 := "application/json"

	entries := []CanonEntry{
		{Key: "T1", Title: "T1", Text: &text1, SourceType: &st1},
		{Key: "T2", Title: "T2", Text: &text2, SourceType: &st2},
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "conteos-001")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	m := result.Manifest
	if m.ContentTypeCounts == nil {
		t.Fatal("ContentTypeCounts is nil")
	}
	if m.ModalityCounts == nil {
		t.Fatal("ModalityCounts is nil")
	}

	if m.ContentTypeCounts[ContentTypePlain] != 1 {
		t.Errorf("ContentTypeCounts[text/plain] = %d, want 1", m.ContentTypeCounts[ContentTypePlain])
	}
	if m.ContentTypeCounts[ContentTypeJSON] != 1 {
		t.Errorf("ContentTypeCounts[application/json] = %d, want 1", m.ContentTypeCounts[ContentTypeJSON])
	}
	if m.ModalityCounts[ModalityText] != 1 {
		t.Errorf("ModalityCounts[text] = %d, want 1", m.ModalityCounts[ModalityText])
	}
	if m.ModalityCounts[ModalityMetadata] != 1 {
		t.Errorf("ModalityCounts[metadata] = %d, want 1", m.ModalityCounts[ModalityMetadata])
	}
	if m.BinaryCount != 0 {
		t.Errorf("BinaryCount = %d, want 0", m.BinaryCount)
	}
	if m.ReferenceOnlyCount != 0 {
		t.Errorf("ReferenceOnlyCount = %d, want 0", m.ReferenceOnlyCount)
	}
}

// TestExportReadingModeIntegration_LogContainsReadingMode verifies that
// export log entries for included tiddlers contain reading mode.
func TestExportReadingModeIntegration_LogContainsReadingMode(t *testing.T) {
	text := "test content"
	st := "text/plain"
	entries := []CanonEntry{
		{Key: "LogTest", Title: "LogTest", Text: &text, SourceType: &st},
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "log-rm-001")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(result.LogEntries) != 1 {
		t.Fatalf("LogEntries = %d, want 1", len(result.LogEntries))
	}

	entry := result.LogEntries[0]
	if entry.ReadingMode == nil {
		t.Fatal("ReadingMode is nil for included entry")
	}
	if entry.ReadingMode.ContentType != ContentTypePlain {
		t.Errorf("ReadingMode.ContentType = %q, want %q", entry.ReadingMode.ContentType, ContentTypePlain)
	}
	if entry.ReadingMode.Modality != ModalityText {
		t.Errorf("ReadingMode.Modality = %q, want %q", entry.ReadingMode.Modality, ModalityText)
	}
}

// TestExportReadingModeIntegration_Determinism verifies that two
// identical runs produce the same reading mode fields.
func TestExportReadingModeIntegration_Determinism(t *testing.T) {
	text := "Determinism test"
	st := "text/markdown"
	entries := []CanonEntry{
		{Key: "Det", Title: "Det", Text: &text, SourceType: &st},
	}

	var buf1, buf2 bytes.Buffer
	_, err1 := ExportTiddlersJSONL(&buf1, entries, "det-rm-1")
	_, err2 := ExportTiddlersJSONL(&buf2, entries, "det-rm-2")
	if err1 != nil || err2 != nil {
		t.Fatalf("errors: %v, %v", err1, err2)
	}

	var e1, e2 CanonEntry
	if err := json.Unmarshal([]byte(strings.TrimSpace(buf1.String())), &e1); err != nil {
		t.Fatalf("parse run1: %v", err)
	}
	if err := json.Unmarshal([]byte(strings.TrimSpace(buf2.String())), &e2); err != nil {
		t.Fatalf("parse run2: %v", err)
	}

	if e1.ContentType != e2.ContentType {
		t.Errorf("content_type differs: %q vs %q", e1.ContentType, e2.ContentType)
	}
	if e1.Modality != e2.Modality {
		t.Errorf("modality differs: %q vs %q", e1.Modality, e2.Modality)
	}
	if e1.Encoding != e2.Encoding {
		t.Errorf("encoding differs: %q vs %q", e1.Encoding, e2.Encoding)
	}
	if e1.IsBinary != e2.IsBinary {
		t.Errorf("is_binary differs: %v vs %v", e1.IsBinary, e2.IsBinary)
	}
	if e1.IsReferenceOnly != e2.IsReferenceOnly {
		t.Errorf("is_reference_only differs: %v vs %v", e1.IsReferenceOnly, e2.IsReferenceOnly)
	}
}
