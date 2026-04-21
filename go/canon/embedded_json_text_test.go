package canon

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func TestNormalizeEmbeddedJSONText_CompactsAndResolvesPendingID(t *testing.T) {
	title := "#### 🌀 Sesión 99 = embedded-json-normalization"
	raw := "{\n  \"id\": \"urn:uuid:PENDIENTE-GENERACION-CONVERTIDOR\",\n  \"title\": \"#### 🌀 Sesión 99 = embedded-json-normalization\",\n  \"content\": {\n    \"plain\": \"Resumen\",\n    \"markdown\": \"# Head\\n\\nBody\"\n  }\n}"

	entry := CanonEntry{
		Key:        KeyOf(title),
		Title:      title,
		Text:       strPtr(raw),
		SourceType: strPtr(ContentTypeJSON),
	}

	actions, err := NormalizeEmbeddedJSONText(&entry)
	if err != nil {
		t.Fatalf("NormalizeEmbeddedJSONText: %v", err)
	}
	if len(actions) == 0 {
		t.Fatal("expected normalization actions, got none")
	}

	wantID, err := ComputeNodeUUID(string(KeyOf(title)))
	if err != nil {
		t.Fatalf("ComputeNodeUUID: %v", err)
	}

	want := `{"id":"` + wantID + `","title":"#### 🌀 Sesión 99 = embedded-json-normalization","content":{"plain":"Resumen","markdown":"# Head\n\nBody"}}`
	if entry.Text == nil || *entry.Text != want {
		t.Fatalf("normalized text = %q, want %q", deref(entry.Text), want)
	}
}

func TestNormalizeEmbeddedJSONText_RepairsInvalidEscapesWithoutLosingContent(t *testing.T) {
	title := "#### 🌀🧾 Procedencia de sesión 24"
	raw := "{\n  \"id\": \"urn:uuid:PENDIENTE-GENERACION-CONVERTIDOR\",\n  \"title\": \"#### 🌀🧾 Procedencia de sesión 24\",\n  \"content\": {\n    \"markdown\": \"Linea 1\\n\\3. item\\n\\---\"\n  }\n}"

	entry := CanonEntry{
		Key:        KeyOf(title),
		Title:      title,
		Text:       strPtr(raw),
		SourceType: strPtr(ContentTypeJSON),
	}

	actions, err := NormalizeEmbeddedJSONText(&entry)
	if err != nil {
		t.Fatalf("NormalizeEmbeddedJSONText: %v", err)
	}
	if len(actions) == 0 {
		t.Fatal("expected repair actions, got none")
	}
	if entry.Text == nil {
		t.Fatal("expected normalized text")
	}
	if !json.Valid([]byte(*entry.Text)) {
		t.Fatalf("normalized embedded JSON is still invalid: %s", *entry.Text)
	}
	if !strings.Contains(*entry.Text, `\\3. item`) {
		t.Fatalf("expected escaped literal backslash before list marker, got %q", *entry.Text)
	}
	if !strings.Contains(*entry.Text, `\\---`) {
		t.Fatalf("expected escaped literal backslash before separator, got %q", *entry.Text)
	}
}

func TestNormalizeEmbeddedJSONText_RepairsMissingCommasBetweenArrayValues(t *testing.T) {
	title := "### 🎯 5. Arquitectura 🌀"
	raw := "{\n  \"id\": \"urn:uuid:PENDIENTE-GENERACION-CONVERTIDOR\",\n  \"title\": \"### 🎯 5. Arquitectura 🌀\",\n  \"provenance\": [\n    {\n      \"actor\": \"human\",\n      \"origin\": \"human\",\n      \"method\": \"compiled\"\n    }\n    {\n      \"actor\": \"ai\",\n      \"origin\": \"ai\",\n      \"method\": \"generated\"\n    }\n  ]\n}"

	entry := CanonEntry{
		Key:        KeyOf(title),
		Title:      title,
		Text:       strPtr(raw),
		SourceType: strPtr(ContentTypeJSON),
	}

	actions, err := NormalizeEmbeddedJSONText(&entry)
	if err != nil {
		t.Fatalf("NormalizeEmbeddedJSONText: %v", err)
	}
	if len(actions) == 0 {
		t.Fatal("expected repair actions, got none")
	}
	if entry.Text == nil {
		t.Fatal("expected normalized text")
	}
	if !json.Valid([]byte(*entry.Text)) {
		t.Fatalf("normalized embedded JSON is still invalid: %s", *entry.Text)
	}
	if !strings.Contains(*entry.Text, `},{"actor":"ai"`) {
		t.Fatalf("expected repaired comma between array objects, got %q", *entry.Text)
	}
}

func TestValidateStrict_EmbeddedJSONTextMustBeNormalized(t *testing.T) {
	title := "#### 🌀 Sesión 48 = canonical-enrichment-target-scope-v0"
	text := "{\n  \"id\": \"urn:uuid:PENDIENTE-GENERACION-CONVERTIDOR\",\n  \"title\": \"#### 🌀 Sesión 48 = canonical-enrichment-target-scope-v0\",\n  \"content\": {\n    \"plain\": \"Resumen corto\"\n  }\n}"

	entry := CanonEntry{
		SchemaVersion: SchemaV0,
		Key:           KeyOf(title),
		Title:         title,
		Text:          &text,
		SourceType:    strPtr(ContentTypeJSON),
	}
	if err := BuildNodeIdentity(&entry); err != nil {
		t.Fatalf("BuildNodeIdentity: %v", err)
	}
	entry.ContentType = ContentTypeJSON
	ApplyDerivedProjections(&entry)

	data, err := json.Marshal(entry)
	if err != nil {
		t.Fatalf("json.Marshal: %v", err)
	}

	report := ValidateCanonJSONL(strings.NewReader(string(data)+"\n"), DefaultCanonPolicy())
	if report.OK() {
		t.Fatal("expected strict validation to reject non-normalized embedded JSON text")
	}

	found := false
	for _, issue := range report.Issues {
		if issue.RuleID == "non-normalized-embedded-json-text" {
			found = true
			break
		}
	}
	if !found {
		t.Fatalf("expected non-normalized-embedded-json-text issue, got %+v", report.Issues)
	}
}

func TestExportTiddlersJSONL_NormalizesEmbeddedJSONText(t *testing.T) {
	title := "#### 🌀 Sesión 77 = exporter-normalizes-embedded-json"
	text := "{\n  \"id\": \"urn:uuid:PENDIENTE-GENERACION-CONVERTIDOR\",\n  \"title\": \"#### 🌀 Sesión 77 = exporter-normalizes-embedded-json\",\n  \"content\": {\n    \"plain\": \"Resumen\",\n    \"markdown\": \"## Demo\\n\\nTexto\"\n  }\n}"

	entries := []CanonEntry{{
		Key:        KeyOf(title),
		Title:      title,
		Text:       &text,
		SourceType: strPtr(ContentTypeJSON),
	}}

	var out bytes.Buffer
	result, err := ExportTiddlersJSONL(&out, entries, "embedded-json-export")
	if err != nil {
		t.Fatalf("ExportTiddlersJSONL: %v", err)
	}
	if result.Manifest.ExportedCount != 1 {
		t.Fatalf("ExportedCount = %d, want 1", result.Manifest.ExportedCount)
	}

	var exported CanonEntry
	if err := json.Unmarshal(bytes.TrimSpace(out.Bytes()), &exported); err != nil {
		t.Fatalf("unmarshal exported line: %v", err)
	}
	if exported.Text == nil {
		t.Fatal("exported text should not be nil")
	}
	if strings.Contains(*exported.Text, pendingGeneratedConverterToken) {
		t.Fatalf("exported text still contains pending placeholder: %s", *exported.Text)
	}
	if strings.Contains(*exported.Text, "\n") {
		t.Fatalf("exported embedded JSON text should be compact, got %q", *exported.Text)
	}

	var inner map[string]any
	if err := json.Unmarshal([]byte(*exported.Text), &inner); err != nil {
		t.Fatalf("embedded JSON parse: %v", err)
	}
	if got := inner["id"]; got != exported.ID {
		t.Fatalf("embedded id = %v, want %q", got, exported.ID)
	}
}

func deref(v *string) string {
	if v == nil {
		return ""
	}
	return *v
}
