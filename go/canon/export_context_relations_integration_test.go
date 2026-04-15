package canon

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type s37FixtureItem struct {
	Title        string            `json:"title"`
	Text         string            `json:"text"`
	Tags         []string          `json:"tags"`
	SourceFields map[string]string `json:"source_fields"`
}

func loadS37Fixture(t *testing.T) []CanonEntry {
	t.Helper()
	path := filepath.Join("..", "..", "tests", "fixtures", "s37", "context_relations_fixture.json")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read fixture: %v", err)
	}
	var items []s37FixtureItem
	if err := json.Unmarshal(raw, &items); err != nil {
		t.Fatalf("parse fixture: %v", err)
	}
	entries := make([]CanonEntry, 0, len(items))
	for _, it := range items {
		text := it.Text
		entries = append(entries, CanonEntry{
			Key:          KeyOf(it.Title),
			Title:        it.Title,
			Text:         &text,
			SourceTags:   append([]string(nil), it.Tags...),
			SourceFields: it.SourceFields,
		})
	}
	return entries
}

func TestExportContextRelationsIntegration_FieldsPresent(t *testing.T) {
	entries := loadS37Fixture(t)
	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "s37-int-001")
	if err != nil {
		t.Fatalf("ExportTiddlersJSONL: %v", err)
	}
	if result.Manifest.ExportedCount != len(entries) {
		t.Fatalf("ExportedCount = %d, want %d", result.Manifest.ExportedCount, len(entries))
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != len(entries) {
		t.Fatalf("JSONL lines = %d, want %d", len(lines), len(entries))
	}
	for i, line := range lines {
		var m map[string]interface{}
		if err := json.Unmarshal([]byte(line), &m); err != nil {
			t.Fatalf("line[%d] invalid JSON: %v", i, err)
		}
		for _, field := range []string{"document_id", "section_path", "order_in_document", "relations"} {
			if _, ok := m[field]; !ok {
				t.Fatalf("line[%d] missing field %q", i, field)
			}
		}
	}
}

func TestExportContextRelationsIntegration_ManifestCounts(t *testing.T) {
	entries := loadS37Fixture(t)
	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "s37-int-002")
	if err != nil {
		t.Fatalf("ExportTiddlersJSONL: %v", err)
	}
	m := result.Manifest
	if m.DocumentCount != 1 {
		t.Fatalf("DocumentCount = %d, want 1", m.DocumentCount)
	}
	if m.NodesWithSectionPathCount < 2 {
		t.Fatalf("NodesWithSectionPathCount = %d, want >= 2", m.NodesWithSectionPathCount)
	}
	if m.NodesWithRelationsCount < 2 {
		t.Fatalf("NodesWithRelationsCount = %d, want >= 2", m.NodesWithRelationsCount)
	}
	if m.RelationCounts.References < 1 {
		t.Fatalf("RelationCounts.References = %d, want >= 1", m.RelationCounts.References)
	}
}

func TestExportContextRelationsIntegration_LogContextInfo(t *testing.T) {
	entries := loadS37Fixture(t)
	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "s37-int-003")
	if err != nil {
		t.Fatalf("ExportTiddlersJSONL: %v", err)
	}
	for i, logEntry := range result.LogEntries {
		if logEntry.Action != "included" {
			continue
		}
		if logEntry.ContextInfo == nil {
			t.Fatalf("log[%d] ContextInfo is nil", i)
		}
		if logEntry.ContextInfo.DocumentID == "" {
			t.Fatalf("log[%d] ContextInfo.DocumentID is empty", i)
		}
		if logEntry.ContextInfo.RelationResolutionStatus == "" {
			t.Fatalf("log[%d] ContextInfo.RelationResolutionStatus is empty", i)
		}
	}
}
