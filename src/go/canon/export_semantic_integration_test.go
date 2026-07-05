package canon

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

// TestExportSemanticIntegration_AllFieldsPresent verifies that the
// S33+S34+S35+S36 exporter (ExportTiddlersJSONL) produces JSONL lines with
// all semantic fields: role_primary, mime_type, semantic_text, raw_payload_ref.
//
// Ref: S36 §19 — exporter JSONL must contain semantic fields.
func TestExportSemanticIntegration_AllFieldsPresent(t *testing.T) {
	text1 := "Content of Alpha"
	st1 := "text/plain"
	text2 := "Content of Beta"
	st2 := "text/vnd.tiddlywiki"
	entries := []CanonEntry{
		{Key: "Alpha", Title: "Alpha", Text: &text1, SourceType: &st1},
		{Key: "Beta", Title: "Beta", Text: &text2, SourceType: &st2},
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "sem-integration-001")
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

	semanticFields := []string{"role_primary", "mime_type", "raw_payload_ref"}

	for i, line := range lines {
		var m map[string]interface{}
		if err := json.Unmarshal([]byte(line), &m); err != nil {
			t.Errorf("line[%d] invalid JSON: %v", i, err)
			continue
		}
		for _, f := range semanticFields {
			if _, ok := m[f]; !ok {
				t.Errorf("line[%d] missing field %q", i, f)
			}
		}
	}
}

// TestExportSemanticIntegration_RolePrimaryValues verifies role assignment.
func TestExportSemanticIntegration_RolePrimaryValues(t *testing.T) {
	text1 := "Policy content"
	st1 := "text/vnd.tiddlywiki"
	role1 := "policy"
	text2 := `{"config": true}`
	st2 := "application/json"

	entries := []CanonEntry{
		{Key: "PolicyNode", Title: "PolicyNode", Text: &text1, SourceType: &st1, SourceRole: &role1},
		{Key: "ConfigJSON", Title: "ConfigJSON", Text: &text2, SourceType: &st2},
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "role-values-001")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Manifest.ExportedCount != 2 {
		t.Fatalf("ExportedCount = %d, want 2", result.Manifest.ExportedCount)
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	wantRoles := []string{RolePolicy, RoleConfig}

	for i, line := range lines {
		var e CanonEntry
		if err := json.Unmarshal([]byte(line), &e); err != nil {
			t.Errorf("line[%d] invalid JSON: %v", i, err)
			continue
		}
		if e.RolePrimary != wantRoles[i] {
			t.Errorf("line[%d] role_primary = %q, want %q", i, e.RolePrimary, wantRoles[i])
		}
	}
}

// TestExportSemanticIntegration_ManifestConteos verifies S36 manifest conteos.
func TestExportSemanticIntegration_ManifestConteos(t *testing.T) {
	text1 := "Text content"
	st1 := "text/plain"
	text2 := "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAA"
	st2 := "image/png"

	entries := []CanonEntry{
		{Key: "T1", Title: "T1", Text: &text1, SourceType: &st1},
		{Key: "I1", Title: "I1", Text: &text2, SourceType: &st2},
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "conteos-sem-001")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	m := result.Manifest
	if m.RolePrimaryCounts == nil {
		t.Fatal("RolePrimaryCounts is nil")
	}
	// S38: with semantic_text suppression, textual nodes with text==semantic_text
	// get null semantic_text. The image node also gets null. So check total counts.
	totalDistinct := m.SemanticTextDistinctCount
	totalNull := m.SemanticTextNullCount
	if totalDistinct+totalNull != m.ExportedCount {
		t.Errorf("SemanticTextDistinctCount(%d) + SemanticTextNullCount(%d) != ExportedCount(%d)",
			totalDistinct, totalNull, m.ExportedCount)
	}
	if m.AssetCount < 1 {
		t.Errorf("AssetCount = %d, want >= 1 (from image)", m.AssetCount)
	}
}

// TestExportSemanticIntegration_LogContainsSemantic verifies export log entries.
func TestExportSemanticIntegration_LogContainsSemantic(t *testing.T) {
	text := "test content"
	st := "text/plain"
	entries := []CanonEntry{
		{Key: "LogTest", Title: "LogTest", Text: &text, SourceType: &st},
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "log-sem-001")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(result.LogEntries) != 1 {
		t.Fatalf("LogEntries = %d, want 1", len(result.LogEntries))
	}

	entry := result.LogEntries[0]
	if entry.SemanticInfo == nil {
		t.Fatal("SemanticInfo is nil for included entry")
	}
	if entry.SemanticInfo.RolePrimary == "" {
		t.Error("SemanticInfo.RolePrimary is empty")
	}
	if entry.SemanticInfo.RoleSource == "" {
		t.Error("SemanticInfo.RoleSource is empty")
	}
}

// TestExportSemanticIntegration_Determinism verifies semantic determinism.
func TestExportSemanticIntegration_Determinism(t *testing.T) {
	text := "Determinism test"
	st := "text/markdown"
	role := "note"
	entries := []CanonEntry{
		{Key: "Det", Title: "Det", Text: &text, SourceType: &st, SourceRole: &role},
	}

	var buf1, buf2 bytes.Buffer
	_, err1 := ExportTiddlersJSONL(&buf1, entries, "det-sem-1")
	_, err2 := ExportTiddlersJSONL(&buf2, entries, "det-sem-2")
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

	if e1.RolePrimary != e2.RolePrimary {
		t.Errorf("role_primary differs: %q vs %q", e1.RolePrimary, e2.RolePrimary)
	}
	if e1.MimeType != e2.MimeType {
		t.Errorf("mime_type differs: %q vs %q", e1.MimeType, e2.MimeType)
	}
	if e1.SemanticText != e2.SemanticText {
		t.Errorf("semantic_text differs")
	}
	if e1.RawPayloadRef != e2.RawPayloadRef {
		t.Errorf("raw_payload_ref differs")
	}
	if e1.AssetID != e2.AssetID {
		t.Errorf("asset_id differs")
	}
}
