package canon

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type s38FixtureItem struct {
	Title        string            `json:"title"`
	Text         string            `json:"text"`
	Tags         []string          `json:"tags"`
	SourceFields map[string]string `json:"source_fields"`
	SourceType   string            `json:"source_type,omitempty"`
}

func loadS38Fixture(t *testing.T) []CanonEntry {
	t.Helper()
	path := filepath.Join("..", "..", "tests", "fixtures", "s38", "export_contract", "contract_hardening_fixture.json")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read fixture: %v", err)
	}
	var items []s38FixtureItem
	if err := json.Unmarshal(raw, &items); err != nil {
		t.Fatalf("parse fixture: %v", err)
	}
	entries := make([]CanonEntry, 0, len(items))
	for _, it := range items {
		text := it.Text
		e := CanonEntry{
			Key:          KeyOf(it.Title),
			Title:        it.Title,
			Text:         &text,
			SourceTags:   append([]string(nil), it.Tags...),
			SourceFields: it.SourceFields,
		}
		if it.SourceType != "" {
			st := it.SourceType
			e.SourceType = &st
		}
		entries = append(entries, e)
	}
	return entries
}

// TestExportContractIntegration_ManifestInvariant verifies S38 §9.3:
// source_candidate_count == excluded_count + exported_count.
func TestExportContractIntegration_ManifestInvariant(t *testing.T) {
	entries := loadS38Fixture(t)
	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "s38-manifest-001")
	if err != nil {
		t.Fatalf("ExportTiddlersJSONL: %v", err)
	}
	m := result.Manifest
	if m.SourceCandidateCount != m.ExcludedCount+m.ExportedCount {
		t.Fatalf("manifest invariant violated: source_candidate_count(%d) != excluded_count(%d) + exported_count(%d)",
			m.SourceCandidateCount, m.ExcludedCount, m.ExportedCount)
	}
	if m.ArtifactRole != "canon_export" {
		t.Fatalf("artifact_role = %q, want %q", m.ArtifactRole, "canon_export")
	}
	if m.SchemaVersion != SchemaV0 {
		t.Fatalf("schema_version = %q, want %q", m.SchemaVersion, SchemaV0)
	}
}

// TestExportContractIntegration_SemanticTextSuppression verifies S38 §9.1:
// semantic_text is null when it would be identical to text.
func TestExportContractIntegration_SemanticTextSuppression(t *testing.T) {
	entries := loadS38Fixture(t)
	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "s38-semtext-001")
	if err != nil {
		t.Fatalf("ExportTiddlersJSONL: %v", err)
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	for i, line := range lines {
		var m map[string]interface{}
		if err := json.Unmarshal([]byte(line), &m); err != nil {
			t.Fatalf("line[%d] invalid JSON: %v", i, err)
		}

		text, hasText := m["text"]
		semText := m["semantic_text"]

		// If text is present and semantic_text is non-null, they must differ.
		if hasText && text != nil && semText != nil {
			if text.(string) == semText.(string) {
				t.Errorf("line[%d]: semantic_text must be null when equal to text (title=%v)", i, m["title"])
			}
		}
	}

	// Verify manifest semantic counters are consistent.
	m := result.Manifest
	if m.SemanticTextDistinctCount+m.SemanticTextNullCount != m.ExportedCount {
		t.Errorf("semantic counters: distinct(%d) + null(%d) != exported(%d)",
			m.SemanticTextDistinctCount, m.SemanticTextNullCount, m.ExportedCount)
	}
}

// TestExportContractIntegration_ExportLogTerminalDecision verifies S38 §9.5:
// every candidate has exactly one terminal decision in the export log.
func TestExportContractIntegration_ExportLogTerminalDecision(t *testing.T) {
	text := "valid content"
	entries := []CanonEntry{
		{Key: "valid1", Title: "Valid1", Text: &text},
		{Key: "valid2", Title: "Valid2", Text: &text},
		{Key: "", Title: "Rejected", Text: &text}, // gate rejected
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "s38-log-001")
	if err != nil {
		t.Fatalf("ExportTiddlersJSONL: %v", err)
	}

	if len(result.LogEntries) != 3 {
		t.Fatalf("LogEntries = %d, want 3", len(result.LogEntries))
	}

	exportedCount := 0
	excludedCount := 0
	for _, entry := range result.LogEntries {
		switch entry.Decision {
		case "exported":
			exportedCount++
			if entry.ID == "" {
				t.Error("exported entry missing id")
			}
			if entry.CanonicalSlug == "" {
				t.Error("exported entry missing canonical_slug")
			}
			if entry.SemanticTextStrategy == "" {
				t.Error("exported entry missing semantic_text_strategy")
			}
		case "excluded":
			excludedCount++
			if entry.RuleID == "" {
				t.Error("excluded entry missing rule_id")
			}
		default:
			t.Errorf("unknown decision: %q", entry.Decision)
		}
		if entry.RunID != "s38-log-001" {
			t.Errorf("run_id = %q, want %q", entry.RunID, "s38-log-001")
		}
		if entry.SourceRef == "" {
			t.Error("source_ref is empty")
		}
	}

	if exportedCount != 2 {
		t.Errorf("exported = %d, want 2", exportedCount)
	}
	if excludedCount != 1 {
		t.Errorf("excluded = %d, want 1", excludedCount)
	}
}

// TestExportContractIntegration_SemanticTextStrategy verifies S38 §9.6:
// semantic_text_strategy values are from the controlled vocabulary.
func TestExportContractIntegration_SemanticTextStrategy(t *testing.T) {
	entries := loadS38Fixture(t)
	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "s38-strategy-001")
	if err != nil {
		t.Fatalf("ExportTiddlersJSONL: %v", err)
	}

	validStrategies := map[string]bool{
		"distinct":                  true,
		"suppressed_equal_to_text":  true,
		"not_applicable":            true,
	}

	for i, entry := range result.LogEntries {
		if entry.Decision != "exported" {
			continue
		}
		if !validStrategies[entry.SemanticTextStrategy] {
			t.Errorf("log[%d] semantic_text_strategy = %q, not in controlled vocabulary",
				i, entry.SemanticTextStrategy)
		}
	}
}

// TestExportContractIntegration_ExcludedByRule verifies S38 §9.3:
// excluded_by_rule tracks per-rule exclusion counts.
func TestExportContractIntegration_ExcludedByRule(t *testing.T) {
	text := "content"
	entries := []CanonEntry{
		{Key: "good", Title: "Good", Text: &text},
		{Key: "", Title: "BadKey", Text: &text},
		{Key: "noTitle", Title: "", Text: &text},
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "s38-rule-001")
	if err != nil {
		t.Fatalf("ExportTiddlersJSONL: %v", err)
	}

	m := result.Manifest
	if m.ExcludedByRule == nil {
		t.Fatal("excluded_by_rule is nil")
	}

	totalByRule := 0
	for _, count := range m.ExcludedByRule {
		totalByRule += count
	}
	if totalByRule != m.ExcludedCount {
		t.Errorf("sum(excluded_by_rule) = %d, want %d (excluded_count)", totalByRule, m.ExcludedCount)
	}
}

// TestExportContractIntegration_NoRegressionS37 verifies S38 §13.5:
// document_id, section_path, order_in_document, relations are stable.
func TestExportContractIntegration_NoRegressionS37(t *testing.T) {
	entries := loadS38Fixture(t)

	// Run twice with same input.
	var buf1, buf2 bytes.Buffer
	_, err1 := ExportTiddlersJSONL(&buf1, entries, "s38-noreg-001")
	_, err2 := ExportTiddlersJSONL(&buf2, entries, "s38-noreg-002")
	if err1 != nil || err2 != nil {
		t.Fatalf("errors: %v, %v", err1, err2)
	}

	lines1 := strings.Split(strings.TrimSpace(buf1.String()), "\n")
	lines2 := strings.Split(strings.TrimSpace(buf2.String()), "\n")
	if len(lines1) != len(lines2) {
		t.Fatalf("line count differs: %d vs %d", len(lines1), len(lines2))
	}

	for i := range lines1 {
		var e1, e2 map[string]interface{}
		json.Unmarshal([]byte(lines1[i]), &e1)
		json.Unmarshal([]byte(lines2[i]), &e2)

		for _, field := range []string{"document_id", "section_path", "order_in_document", "relations"} {
			v1, _ := json.Marshal(e1[field])
			v2, _ := json.Marshal(e2[field])
			if string(v1) != string(v2) {
				t.Errorf("line[%d] field %q differs between runs: %s vs %s", i, field, v1, v2)
			}
		}
	}
}

// TestExportContractIntegration_EquationNode verifies S38 §14 Case F:
// equation content preserved in text, semantic_text null.
func TestExportContractIntegration_EquationNode(t *testing.T) {
	text := "The energy equation: $$E = mc^2$$"
	entries := []CanonEntry{
		{Key: "Equation", Title: "Equation", Text: &text},
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "s38-eq-001")
	if err != nil {
		t.Fatalf("ExportTiddlersJSONL: %v", err)
	}

	if result.Manifest.ExportedCount != 1 {
		t.Fatalf("ExportedCount = %d, want 1", result.Manifest.ExportedCount)
	}

	var m map[string]interface{}
	json.Unmarshal([]byte(strings.TrimSpace(buf.String())), &m)

	// text must be preserved.
	if m["text"] != text {
		t.Errorf("text not preserved: got %v", m["text"])
	}

	// semantic_text should be null (suppressed because equal to text).
	if m["semantic_text"] != nil {
		t.Errorf("semantic_text should be null for equation with no distinct transform: got %v", m["semantic_text"])
	}
}
