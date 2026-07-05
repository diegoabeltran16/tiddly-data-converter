package canon

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

// ---------------------------------------------------------------------------
// Policy tests
// ---------------------------------------------------------------------------

func TestDefaultCanonPolicy(t *testing.T) {
	p := DefaultCanonPolicy()

	if p.SchemaVersion != SchemaV0 {
		t.Errorf("SchemaVersion = %q, want %q", p.SchemaVersion, SchemaV0)
	}
	if p.CanonArtifactRole != "canon_export" {
		t.Errorf("CanonArtifactRole = %q, want %q", p.CanonArtifactRole, "canon_export")
	}
	if len(p.RequiredFields) != 3 {
		t.Errorf("RequiredFields count = %d, want 3", len(p.RequiredFields))
	}
	if len(p.DerivedFields) == 0 {
		t.Error("DerivedFields should not be empty")
	}
	if len(p.AllowedTopLevel) == 0 {
		t.Error("AllowedTopLevel should not be empty")
	}
}

func TestPolicyIsAllowedField(t *testing.T) {
	p := DefaultCanonPolicy()

	if !p.IsAllowedField("title") {
		t.Error("title should be allowed")
	}
	if !p.IsAllowedField("id") {
		t.Error("id should be allowed")
	}
	if p.IsAllowedField("invented_field") {
		t.Error("invented_field should not be allowed")
	}
}

func TestPolicyIsDerivedField(t *testing.T) {
	p := DefaultCanonPolicy()

	if !p.IsDerivedField("id") {
		t.Error("id should be derived")
	}
	if !p.IsDerivedField("canonical_slug") {
		t.Error("canonical_slug should be derived")
	}
	if p.IsDerivedField("title") {
		t.Error("title should not be derived")
	}
	if p.IsDerivedField("text") {
		t.Error("text should not be derived")
	}
	if !p.IsDerivedField("content") {
		t.Error("content should be derived")
	}
	if !p.IsDerivedField("normalized_tags") {
		t.Error("normalized_tags should be derived")
	}
}

// ---------------------------------------------------------------------------
// Validator tests
// ---------------------------------------------------------------------------

func makeValidLine(t *testing.T) string {
	t.Helper()
	txt := "Hello world"
	entry := CanonEntry{
		SchemaVersion: SchemaV0,
		Key:           "Test Tiddler",
		Title:         "Test Tiddler",
		Text:          &txt,
	}
	// Compute identity so derived fields are correct.
	if err := BuildNodeIdentity(&entry); err != nil {
		t.Fatalf("BuildNodeIdentity: %v", err)
	}
	data, err := json.Marshal(entry)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	return string(data)
}

// Case A: Valid canon line passes strict validation.
func TestValidateStrict_ValidLine(t *testing.T) {
	line := makeValidLine(t)
	policy := DefaultCanonPolicy()
	report := ValidateCanonJSONL(strings.NewReader(line+"\n"), policy)

	if !report.OK() {
		t.Errorf("expected OK, got %d errors: %v", report.ErrorCount(), report.Issues)
	}
	if report.LinesRead != 1 {
		t.Errorf("LinesRead = %d, want 1", report.LinesRead)
	}
	if report.LinesValid != 1 {
		t.Errorf("LinesValid = %d, want 1", report.LinesValid)
	}
}

// Case B: Missing required field (empty key).
func TestValidateStrict_MissingKey(t *testing.T) {
	line := `{"schema_version":"v0","key":"","title":"Test"}`
	policy := DefaultCanonPolicy()
	report := ValidateCanonJSONL(strings.NewReader(line+"\n"), policy)

	if report.OK() {
		t.Error("expected failure for empty key")
	}
	found := false
	for _, issue := range report.Issues {
		if issue.RuleID == "missing-required-field" && issue.Field == "key" {
			found = true
		}
	}
	if !found {
		t.Error("expected missing-required-field issue for key")
	}
}

// Case C: Derived field id is tampered.
func TestValidateStrict_InconsistentID(t *testing.T) {
	txt := "Hello"
	entry := CanonEntry{
		SchemaVersion: SchemaV0,
		Key:           "Test",
		Title:         "Test",
		Text:          &txt,
	}
	if err := BuildNodeIdentity(&entry); err != nil {
		t.Fatalf("BuildNodeIdentity: %v", err)
	}
	entry.ID = "tampered-id"
	data, _ := json.Marshal(entry)
	policy := DefaultCanonPolicy()
	report := ValidateCanonJSONL(strings.NewReader(string(data)+"\n"), policy)

	if report.OK() {
		t.Error("expected failure for tampered id")
	}
	found := false
	for _, issue := range report.Issues {
		if issue.RuleID == "inconsistent-derived-id" {
			found = true
		}
	}
	if !found {
		t.Error("expected inconsistent-derived-id issue")
	}
}

// Case D: Unknown top-level field.
func TestValidateStrict_UnknownField(t *testing.T) {
	line := `{"schema_version":"v0","key":"T","title":"T","invented_field":"bad"}`
	policy := DefaultCanonPolicy()
	report := ValidateCanonJSONL(strings.NewReader(line+"\n"), policy)

	if report.OK() {
		t.Error("expected failure for unknown field")
	}
	found := false
	for _, issue := range report.Issues {
		if issue.RuleID == "unknown-top-level-field" {
			found = true
		}
	}
	if !found {
		t.Error("expected unknown-top-level-field issue")
	}
}

// Case E: semantic_text redundant (equals text).
func TestValidateStrict_SemanticTextRedundant(t *testing.T) {
	txt := "Same content"
	entry := CanonEntry{
		SchemaVersion: SchemaV0,
		Key:           "Test",
		Title:         "Test",
		Text:          &txt,
		SemanticText:  &txt,
	}
	if err := BuildNodeIdentity(&entry); err != nil {
		t.Fatalf("BuildNodeIdentity: %v", err)
	}
	data, _ := json.Marshal(entry)
	policy := DefaultCanonPolicy()
	report := ValidateCanonJSONL(strings.NewReader(string(data)+"\n"), policy)

	// The redundancy is a warning, not an error.
	if !report.OK() {
		t.Errorf("semantic_text redundancy should be warning not error: %v", report.Issues)
	}
	found := false
	for _, issue := range report.Issues {
		if issue.RuleID == "semantic-text-redundant" && issue.Severity == "warning" {
			found = true
		}
	}
	if !found {
		t.Error("expected semantic-text-redundant warning")
	}
}

func TestValidateStrict_InconsistentContentPlain(t *testing.T) {
	txt := "Hello\nworld"
	entry := CanonEntry{
		SchemaVersion: SchemaV0,
		Key:           "Test",
		Title:         "Test",
		Text:          &txt,
		ContentType:   ContentTypePlain,
		Content: &ContentProjection{
			Plain: strPtr("tampered plain"),
		},
	}
	if err := BuildNodeIdentity(&entry); err != nil {
		t.Fatalf("BuildNodeIdentity: %v", err)
	}
	data, _ := json.Marshal(entry)
	report := ValidateCanonJSONL(strings.NewReader(string(data)+"\n"), DefaultCanonPolicy())

	if report.OK() {
		t.Fatal("expected failure for inconsistent content.plain")
	}
	found := false
	for _, issue := range report.Issues {
		if issue.RuleID == "inconsistent-derived-content-plain" {
			found = true
		}
	}
	if !found {
		t.Fatal("expected inconsistent-derived-content-plain issue")
	}
}

func TestValidateStrict_InconsistentContentAsset(t *testing.T) {
	txt := "aGVsbG8="
	entry := CanonEntry{
		SchemaVersion:  SchemaV0,
		Key:            "Asset",
		Title:          "Asset",
		Text:           &txt,
		ContentType:    ContentTypePNG,
		Modality:       ModalityImage,
		Encoding:       EncodingBase64,
		IsBinary:       true,
		RolePrimary:    RoleAsset,
		RawPayloadRef:  "node:asset",
		AssetID:        "asset:asset",
		MimeType:       ContentTypePNG,
		SourceType:     strPtr(ContentTypePNG),
		SourcePosition: strPtr("html:block0:tiddler1"),
		Content: &ContentProjection{
			Asset: &AssetContentProjection{
				AssetID:        "asset:asset",
				MimeType:       ContentTypePNG,
				Encoding:       EncodingBase64,
				PayloadRef:     "node:asset",
				PayloadPresent: true,
				PayloadSHA256:  "sha256:0000000000000000000000000000000000000000000000000000000000000000",
			},
		},
	}
	if err := BuildNodeIdentity(&entry); err != nil {
		t.Fatalf("BuildNodeIdentity: %v", err)
	}
	data, _ := json.Marshal(entry)
	report := ValidateCanonJSONL(strings.NewReader(string(data)+"\n"), DefaultCanonPolicy())

	if report.OK() {
		t.Fatal("expected failure for inconsistent content.asset")
	}
	found := false
	for _, issue := range report.Issues {
		if issue.RuleID == "inconsistent-derived-content-asset" {
			found = true
		}
	}
	if !found {
		t.Fatal("expected inconsistent-derived-content-asset issue")
	}
}

func TestValidateStrict_ContentCodeBlocksRequireText(t *testing.T) {
	entry := CanonEntry{
		SchemaVersion: SchemaV0,
		Key:           "Code",
		Title:         "Code",
		ContentType:   ContentTypeMarkdown,
		Content: &ContentProjection{
			CodeBlocks: []CodeBlockProjection{{
				Language:  "go",
				Text:      "fmt.Println(\"ok\")",
				LineCount: 1,
				ByteCount: 17,
				Source:    "fenced_code_block:1",
			}},
		},
	}
	if err := BuildNodeIdentity(&entry); err != nil {
		t.Fatalf("BuildNodeIdentity: %v", err)
	}
	data, _ := json.Marshal(entry)
	report := ValidateCanonJSONL(strings.NewReader(string(data)+"\n"), DefaultCanonPolicy())

	if report.OK() {
		t.Fatal("expected failure for code projection without source text")
	}
	found := false
	for _, issue := range report.Issues {
		if issue.RuleID == "inconsistent-derived-content-code-blocks" {
			found = true
		}
	}
	if !found {
		t.Fatal("expected inconsistent-derived-content-code-blocks issue")
	}
}

func TestValidateStrict_InconsistentContentProjectionKind(t *testing.T) {
	txt := "Hello world"
	plain := "Hello world"
	entry := CanonEntry{
		SchemaVersion: SchemaV0,
		Key:           "Text",
		Title:         "Text",
		Text:          &txt,
		ContentType:   ContentTypePlain,
		Content: &ContentProjection{
			ProjectionKind: RoleAsset,
			Modalities:     []string{RoleAsset},
			Plain:          &plain,
		},
	}
	if err := BuildNodeIdentity(&entry); err != nil {
		t.Fatalf("BuildNodeIdentity: %v", err)
	}
	data, _ := json.Marshal(entry)
	report := ValidateCanonJSONL(strings.NewReader(string(data)+"\n"), DefaultCanonPolicy())

	if report.OK() {
		t.Fatal("expected failure for inconsistent projection kind")
	}
	foundKind := false
	foundModalities := false
	for _, issue := range report.Issues {
		if issue.RuleID == "inconsistent-derived-content-projection-kind" {
			foundKind = true
		}
		if issue.RuleID == "inconsistent-derived-content-modalities" {
			foundModalities = true
		}
	}
	if !foundKind || !foundModalities {
		t.Fatalf("expected projection kind and modalities issues, got %+v", report.Issues)
	}
}

func TestValidateStrict_InconsistentNormalizedTags(t *testing.T) {
	txt := "Hello"
	entry := CanonEntry{
		SchemaVersion:  SchemaV0,
		Key:            "Test",
		Title:          "Test",
		Text:           &txt,
		ContentType:    ContentTypePlain,
		Tags:           []string{"Árbol", "🚀 Launch"},
		NormalizedTags: []string{"wrong"},
	}
	if err := BuildNodeIdentity(&entry); err != nil {
		t.Fatalf("BuildNodeIdentity: %v", err)
	}
	data, _ := json.Marshal(entry)
	report := ValidateCanonJSONL(strings.NewReader(string(data)+"\n"), DefaultCanonPolicy())

	if report.OK() {
		t.Fatal("expected failure for inconsistent normalized_tags")
	}
	found := false
	for _, issue := range report.Issues {
		if issue.RuleID == "inconsistent-derived-normalized-tags" {
			found = true
		}
	}
	if !found {
		t.Fatal("expected inconsistent-derived-normalized-tags issue")
	}
}

// Case: Wrong schema version.
func TestValidateStrict_WrongSchemaVersion(t *testing.T) {
	line := `{"schema_version":"v99","key":"T","title":"T"}`
	policy := DefaultCanonPolicy()
	report := ValidateCanonJSONL(strings.NewReader(line+"\n"), policy)

	if report.OK() {
		t.Error("expected failure for wrong schema version")
	}
}

// Case: Invalid JSON.
func TestValidateStrict_InvalidJSON(t *testing.T) {
	line := `{this is not json}`
	policy := DefaultCanonPolicy()
	report := ValidateCanonJSONL(strings.NewReader(line+"\n"), policy)

	if report.OK() {
		t.Error("expected failure for invalid JSON")
	}
}

// ---------------------------------------------------------------------------
// Normalizer tests
// ---------------------------------------------------------------------------

// Case B: New tiddler with only source fields, no derived fields.
func TestNormalize_NewTiddlerNoDeriveds(t *testing.T) {
	txt := "New content"
	entry := CanonEntry{
		Key:   "New Tiddler",
		Title: "New Tiddler",
		Text:  &txt,
	}
	data, _ := json.Marshal(entry)
	input := string(data) + "\n"

	var out bytes.Buffer
	report := NormalizeCanonJSONL(strings.NewReader(input), &out)

	if !report.OK() {
		t.Errorf("expected OK, got rejected=%d", report.LinesRejected)
	}
	if report.LinesNormalized != 1 {
		t.Errorf("LinesNormalized = %d, want 1", report.LinesNormalized)
	}

	// Parse output and verify derived fields were computed.
	var normalized CanonEntry
	if err := json.Unmarshal(bytes.TrimSpace(out.Bytes()), &normalized); err != nil {
		t.Fatalf("parse normalized: %v", err)
	}
	if normalized.SchemaVersion != SchemaV0 {
		t.Errorf("schema_version = %q, want %q", normalized.SchemaVersion, SchemaV0)
	}
	if normalized.ID == "" {
		t.Error("id should be computed")
	}
	if normalized.CanonicalSlug == "" {
		t.Error("canonical_slug should be computed")
	}
	if normalized.VersionID == "" {
		t.Error("version_id should be computed")
	}
}

// Normalizer idempotency: running twice produces same output.
func TestNormalize_Idempotent(t *testing.T) {
	txt := "Idempotent test"
	entry := CanonEntry{
		SchemaVersion: SchemaV0,
		Key:           "Idem",
		Title:         "Idem",
		Text:          &txt,
	}
	if err := BuildNodeIdentity(&entry); err != nil {
		t.Fatalf("BuildNodeIdentity: %v", err)
	}
	data, _ := json.Marshal(entry)
	input := string(data) + "\n"

	// First pass.
	var out1 bytes.Buffer
	NormalizeCanonJSONL(strings.NewReader(input), &out1)

	// Second pass on output of first.
	var out2 bytes.Buffer
	NormalizeCanonJSONL(strings.NewReader(out1.String()), &out2)

	if out1.String() != out2.String() {
		t.Errorf("normalizer not idempotent:\n  pass1: %s\n  pass2: %s", out1.String(), out2.String())
	}
}

// Case E: semantic_text redundant is suppressed by normalizer.
func TestNormalize_SemanticTextSuppressed(t *testing.T) {
	txt := "Same"
	sameTxt := "Same"
	entry := CanonEntry{
		Key:          "ST",
		Title:        "ST",
		Text:         &txt,
		SemanticText: &sameTxt,
	}
	data, _ := json.Marshal(entry)

	var out bytes.Buffer
	report := NormalizeCanonJSONL(strings.NewReader(string(data)+"\n"), &out)

	if !report.OK() {
		t.Errorf("expected OK: %v", report.Actions)
	}

	var normalized CanonEntry
	if err := json.Unmarshal(bytes.TrimSpace(out.Bytes()), &normalized); err != nil {
		t.Fatalf("parse: %v", err)
	}
	if normalized.SemanticText != nil {
		t.Error("semantic_text should be null after normalization")
	}

	// Verify action was reported.
	found := false
	for _, a := range report.Actions {
		for _, act := range a.Actions {
			if strings.Contains(act, "suppressed") {
				found = true
			}
		}
	}
	if !found {
		t.Error("expected suppression action in report")
	}
}

// Normalizer rejects line with empty title.
func TestNormalize_RejectsEmptyTitle(t *testing.T) {
	line := `{"key":"K","title":""}`
	var out bytes.Buffer
	report := NormalizeCanonJSONL(strings.NewReader(line+"\n"), &out)

	if report.LinesRejected != 1 {
		t.Errorf("LinesRejected = %d, want 1", report.LinesRejected)
	}
	if out.Len() != 0 {
		t.Error("should not emit any output for rejected line")
	}
}

// Case C: Tampered version_id gets corrected by normalizer.
func TestNormalize_CorrectedVersionID(t *testing.T) {
	txt := "Original"
	entry := CanonEntry{
		SchemaVersion: SchemaV0,
		Key:           "VID",
		Title:         "VID",
		Text:          &txt,
		VersionID:     "sha256:tampered",
	}
	data, _ := json.Marshal(entry)

	var out bytes.Buffer
	report := NormalizeCanonJSONL(strings.NewReader(string(data)+"\n"), &out)

	if !report.OK() {
		t.Errorf("expected OK")
	}

	var normalized CanonEntry
	if err := json.Unmarshal(bytes.TrimSpace(out.Bytes()), &normalized); err != nil {
		t.Fatalf("parse: %v", err)
	}
	if normalized.VersionID == "sha256:tampered" {
		t.Error("version_id should be corrected, not kept as tampered")
	}
	if normalized.VersionID == "" {
		t.Error("version_id should be recomputed")
	}

	// Verify the corrected value passes strict validation.
	policy := DefaultCanonPolicy()
	vReport := ValidateCanonJSONL(strings.NewReader(out.String()), policy)
	if !vReport.OK() {
		t.Errorf("normalized output should pass strict: %v", vReport.Issues)
	}
}

// Case A: Valid canon passes strict after normalization (no drift).
func TestNormalize_NoDrift(t *testing.T) {
	txt := "Content"
	entry := CanonEntry{
		SchemaVersion: SchemaV0,
		Key:           "NoDrift",
		Title:         "NoDrift",
		Text:          &txt,
	}
	if err := BuildNodeIdentity(&entry); err != nil {
		t.Fatalf("BuildNodeIdentity: %v", err)
	}
	data, _ := json.Marshal(entry)

	var out bytes.Buffer
	NormalizeCanonJSONL(strings.NewReader(string(data)+"\n"), &out)

	// Strict validation on normalized output.
	policy := DefaultCanonPolicy()
	report := ValidateCanonJSONL(strings.NewReader(out.String()), policy)
	if !report.OK() {
		t.Errorf("normalized valid canon should pass strict: %v", report.Issues)
	}
}

// ---------------------------------------------------------------------------
// Reverse readiness tests
// ---------------------------------------------------------------------------

// Case A: Valid reverse-ready node.
func TestReversePreflight_Ready(t *testing.T) {
	line := makeValidLine(t)
	report := ReversePreflightCanonJSONL(strings.NewReader(line + "\n"))

	if !report.OK() {
		t.Errorf("expected reverse-ready: %v", report.Issues)
	}
	if report.ReverseReady != 1 {
		t.Errorf("ReverseReady = %d, want 1", report.ReverseReady)
	}
}

// Case F: Node without title is not reverse-ready.
func TestReversePreflight_MissingTitle(t *testing.T) {
	line := `{"schema_version":"v0","key":"K","title":""}`
	report := ReversePreflightCanonJSONL(strings.NewReader(line + "\n"))

	if report.OK() {
		t.Error("expected not ready for missing title")
	}
	if report.NotReady != 1 {
		t.Errorf("NotReady = %d, want 1", report.NotReady)
	}
}

// Case F: Node without key is not reverse-ready.
func TestReversePreflight_MissingKey(t *testing.T) {
	line := `{"schema_version":"v0","key":"","title":"T"}`
	report := ReversePreflightCanonJSONL(strings.NewReader(line + "\n"))

	if report.OK() {
		t.Error("expected not ready for missing key")
	}
}

// Case F: Node with wrong schema version is not reverse-ready.
func TestReversePreflight_WrongSchema(t *testing.T) {
	line := `{"schema_version":"v99","key":"K","title":"T"}`
	report := ReversePreflightCanonJSONL(strings.NewReader(line + "\n"))

	if report.OK() {
		t.Error("expected not ready for wrong schema version")
	}
}

// Reverse preflight with null text is still ready (empty body).
func TestReversePreflight_NullText(t *testing.T) {
	line := `{"schema_version":"v0","key":"K","title":"T"}`
	report := ReversePreflightCanonJSONL(strings.NewReader(line + "\n"))

	if !report.OK() {
		t.Errorf("null text should still be reverse-ready: %v", report.Issues)
	}
}

// Case: Invalid JSON.
func TestReversePreflight_InvalidJSON(t *testing.T) {
	line := `{not json}`
	report := ReversePreflightCanonJSONL(strings.NewReader(line + "\n"))

	if report.OK() {
		t.Error("expected not ready for invalid JSON")
	}
}

// ---------------------------------------------------------------------------
// Derived layers registry test (Case G)
// ---------------------------------------------------------------------------

func TestDerivedLayersRegistryNotCanonical(t *testing.T) {
	// This test reads the registry JSON and verifies no layer is marked canonical.
	registryJSON := `{
		"layers": [
			{"artifact": "tiddlers.ai.jsonl", "is_canonical": false},
			{"artifact": "chunks.ai.jsonl", "is_canonical": false},
			{"artifact": "*.parquet", "is_canonical": false},
			{"artifact": "*.arrow", "is_canonical": false},
			{"artifact": "embeddings", "is_canonical": false},
			{"artifact": "reverse_html_output", "is_canonical": false}
		]
	}`
	var registry struct {
		Layers []struct {
			Artifact    string `json:"artifact"`
			IsCanonical bool   `json:"is_canonical"`
		} `json:"layers"`
	}
	if err := json.Unmarshal([]byte(registryJSON), &registry); err != nil {
		t.Fatalf("parse registry: %v", err)
	}
	for _, layer := range registry.Layers {
		if layer.IsCanonical {
			t.Errorf("derived layer %q must not be canonical", layer.Artifact)
		}
	}
}

// ---------------------------------------------------------------------------
// Integration: full flow — validate → normalize → strict → reverse-preflight
// ---------------------------------------------------------------------------

func TestFullFlow_NewTiddlerAdded(t *testing.T) {
	txt := "Brand new tiddler from AI"
	entry := CanonEntry{
		Title: "AI Generated Tiddler",
		Text:  &txt,
	}
	data, _ := json.Marshal(entry)
	input := string(data) + "\n"

	// Step 1: normalize.
	var normalized bytes.Buffer
	normReport := NormalizeCanonJSONL(strings.NewReader(input), &normalized)
	if !normReport.OK() {
		t.Fatalf("normalize failed: %v", normReport.Actions)
	}

	// Step 2: strict validation on normalized.
	policy := DefaultCanonPolicy()
	valReport := ValidateCanonJSONL(strings.NewReader(normalized.String()), policy)
	if !valReport.OK() {
		t.Fatalf("strict validation after normalize failed: %v", valReport.Issues)
	}

	// Step 3: reverse preflight.
	revReport := ReversePreflightCanonJSONL(strings.NewReader(normalized.String()))
	if !revReport.OK() {
		t.Errorf("reverse preflight after normalize failed: %v", revReport.Issues)
	}
}

// ---------------------------------------------------------------------------
// Integration: mixed valid and invalid lines
// ---------------------------------------------------------------------------

func TestValidate_MultipleLines(t *testing.T) {
	valid := makeValidLine(t)
	invalid := `{"schema_version":"v0","key":"","title":"NoKey"}`
	input := valid + "\n" + invalid + "\n"

	policy := DefaultCanonPolicy()
	report := ValidateCanonJSONL(strings.NewReader(input), policy)

	if report.LinesRead != 2 {
		t.Errorf("LinesRead = %d, want 2", report.LinesRead)
	}
	if report.LinesValid != 1 {
		t.Errorf("LinesValid = %d, want 1", report.LinesValid)
	}
	if report.ErrorCount() == 0 {
		t.Error("expected at least one error")
	}
}
