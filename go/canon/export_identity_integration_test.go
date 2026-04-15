package canon

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

// TestExportIdentityIntegration_AllFieldsPresent verifies that the S33
// exporter (ExportTiddlersJSONL) now produces JSONL lines with all five
// structural identity fields: id, key, title, canonical_slug, version_id.
//
// Ref: S34 §16 — exporter JSONL must contain all 5 identity fields.
func TestExportIdentityIntegration_AllFieldsPresent(t *testing.T) {
	text1 := "Content of Alpha"
	text2 := "Content of Beta"
	entries := []CanonEntry{
		{Key: "Alpha", Title: "Alpha", Text: &text1},
		{Key: "Beta Node", Title: "Beta Node", Text: &text2},
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "integration-run-001")
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

	requiredFields := []string{"id", "key", "title", "canonical_slug", "version_id"}

	for i, line := range lines {
		// Parse as generic map to verify field presence.
		var m map[string]interface{}
		if err := json.Unmarshal([]byte(line), &m); err != nil {
			t.Errorf("line[%d] invalid JSON: %v", i, err)
			continue
		}
		for _, f := range requiredFields {
			val, ok := m[f]
			if !ok {
				t.Errorf("line[%d] missing field %q", i, f)
				continue
			}
			s, isStr := val.(string)
			if !isStr || s == "" {
				t.Errorf("line[%d] field %q is empty or not a string: %v", i, f, val)
			}
		}
	}
}

// TestExportIdentityIntegration_Determinism verifies that two identical
// export runs produce identical JSONL output (same identity fields).
//
// Ref: S34 §18.B — determinism quality gate.
func TestExportIdentityIntegration_Determinism(t *testing.T) {
	text := "Determinism test content"
	entries := []CanonEntry{
		{Key: "Det", Title: "Det", Text: &text},
	}

	var buf1, buf2 bytes.Buffer
	_, err1 := ExportTiddlersJSONL(&buf1, entries, "det-run-1")
	_, err2 := ExportTiddlersJSONL(&buf2, entries, "det-run-2")
	if err1 != nil || err2 != nil {
		t.Fatalf("errors: %v, %v", err1, err2)
	}

	// Parse both lines and compare identity fields (exclude run-dependent metadata).
	var e1, e2 CanonEntry
	if err := json.Unmarshal([]byte(strings.TrimSpace(buf1.String())), &e1); err != nil {
		t.Fatalf("parse run1: %v", err)
	}
	if err := json.Unmarshal([]byte(strings.TrimSpace(buf2.String())), &e2); err != nil {
		t.Fatalf("parse run2: %v", err)
	}

	if e1.ID != e2.ID {
		t.Errorf("id differs between runs: %q vs %q", e1.ID, e2.ID)
	}
	if e1.Key != e2.Key {
		t.Errorf("key differs between runs: %q vs %q", e1.Key, e2.Key)
	}
	if e1.CanonicalSlug != e2.CanonicalSlug {
		t.Errorf("canonical_slug differs: %q vs %q", e1.CanonicalSlug, e2.CanonicalSlug)
	}
	if e1.VersionID != e2.VersionID {
		t.Errorf("version_id differs: %q vs %q", e1.VersionID, e2.VersionID)
	}
}

// TestExportIdentityIntegration_LogContainsIdentity verifies that the
// export log entries for included tiddlers contain the identity reference.
//
// Ref: S34 §17.1 — export log shape.
func TestExportIdentityIntegration_LogContainsIdentity(t *testing.T) {
	text := "log test content"
	entries := []CanonEntry{
		{Key: "LogTest", Title: "LogTest", Text: &text},
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "log-run-001")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(result.LogEntries) != 1 {
		t.Fatalf("LogEntries = %d, want 1", len(result.LogEntries))
	}

	entry := result.LogEntries[0]
	if entry.Action != "included" {
		t.Fatalf("action = %q, want included", entry.Action)
	}
	if entry.ExportIdentity == nil {
		t.Fatal("ExportIdentity is nil for included entry")
	}
	if entry.ExportIdentity.ID == "" {
		t.Error("ExportIdentity.ID is empty")
	}
	if entry.ExportIdentity.CanonicalSlug == "" {
		t.Error("ExportIdentity.CanonicalSlug is empty")
	}
	if entry.ExportIdentity.VersionID == "" {
		t.Error("ExportIdentity.VersionID is empty")
	}
}

// TestExportIdentityIntegration_GateRejection verifies that entries
// failing the gate have nil ExportIdentity in the log.
func TestExportIdentityIntegration_GateRejection(t *testing.T) {
	text := "valid"
	entries := []CanonEntry{
		{Key: "valid", Title: "Valid", Text: &text},
		{Key: "", Title: "EmptyKey", Text: &text}, // rejected
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "reject-run-001")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if result.Manifest.ExportedCount != 1 {
		t.Errorf("ExportedCount = %d, want 1", result.Manifest.ExportedCount)
	}

	for _, entry := range result.LogEntries {
		if entry.Action == "excluded" && entry.ExportIdentity != nil {
			t.Error("excluded entry should have nil ExportIdentity")
		}
		if entry.Action == "included" && entry.ExportIdentity == nil {
			t.Error("included entry should have non-nil ExportIdentity")
		}
	}
}

// TestExportIdentityIntegration_SpecialCharsInTitle verifies that
// titles with diacritics, emojis, and symbols produce valid identity.
//
// Ref: S34 §19 Case D — special characters.
func TestExportIdentityIntegration_SpecialCharsInTitle(t *testing.T) {
	text := "content"
	entries := []CanonEntry{
		{Key: "🌀 Sesión 34", Title: "🌀 Sesión 34", Text: &text},
		{Key: "Résumé", Title: "Résumé", Text: &text},
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "special-chars-run")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if result.Manifest.ExportedCount != 2 {
		t.Fatalf("ExportedCount = %d, want 2", result.Manifest.ExportedCount)
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	for i, line := range lines {
		var e CanonEntry
		if err := json.Unmarshal([]byte(line), &e); err != nil {
			t.Errorf("line[%d] invalid JSON: %v", i, err)
			continue
		}
		if e.ID == "" || e.CanonicalSlug == "" || e.VersionID == "" {
			t.Errorf("line[%d] missing identity fields: id=%q slug=%q vid=%q",
				i, e.ID, e.CanonicalSlug, e.VersionID)
		}
	}
}
