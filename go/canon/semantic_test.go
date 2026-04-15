package canon

import (
	"testing"
)

// ---------------------------------------------------------------------------
// Case A — Node with explicit role already integrated
// S36 §18.A: explicit role is not replaced by inference; role_primary comes
// from the explicit layer; roles_secondary preserves remaining semantics.
// ---------------------------------------------------------------------------

func TestResolvePrimaryRole_ExplicitRole(t *testing.T) {
	role := "policy"
	e := CanonEntry{
		Key:        "test",
		Title:      "Test",
		SourceRole: &role,
		SourceTags: []string{"arquitectura", "sesión"},
	}
	got, source := ResolvePrimaryRole(e)
	if got != RolePolicy {
		t.Errorf("role_primary = %q, want %q", got, RolePolicy)
	}
	if source != "explicit_role" {
		t.Errorf("role_source = %q, want %q", source, "explicit_role")
	}
}

func TestResolveSecondaryRoles_ExplicitRolePreservation(t *testing.T) {
	role := "policy"
	e := CanonEntry{
		Key:        "test",
		Title:      "Test",
		SourceRole: &role,
		SourceTags: []string{"arquitectura", "sesión"},
	}
	secondary := ResolveSecondaryRoles(e, RolePolicy)
	// Tags "arquitectura" → concept, "sesión" → log should appear
	found := make(map[string]bool)
	for _, r := range secondary {
		found[r] = true
	}
	if !found[RoleConcept] {
		t.Errorf("roles_secondary missing %q derived from 'arquitectura'", RoleConcept)
	}
	if !found[RoleLog] {
		t.Errorf("roles_secondary missing %q derived from 'sesión'", RoleLog)
	}
}

// ---------------------------------------------------------------------------
// Case B — Node with explicit roles + tags
// S36 §18.B: explicit role prevails; tags complement, not dominate.
// ---------------------------------------------------------------------------

func TestResolvePrimaryRole_ExplicitOverTags(t *testing.T) {
	role := "concept"
	e := CanonEntry{
		Key:        "test",
		Title:      "Test",
		SourceRole: &role,
		SourceTags: []string{"hipótesis", "procedencia", "glosario"},
	}
	got, source := ResolvePrimaryRole(e)
	if got != RoleConcept {
		t.Errorf("role_primary = %q, want %q", got, RoleConcept)
	}
	if source != "explicit_role" {
		t.Errorf("role_source = %q, want %q", source, "explicit_role")
	}
}

func TestResolveSecondaryRoles_TagsComplement(t *testing.T) {
	role := "concept"
	e := CanonEntry{
		Key:        "test",
		Title:      "Test",
		SourceRole: &role,
		SourceTags: []string{"hipótesis", "procedencia", "glosario"},
	}
	secondary := ResolveSecondaryRoles(e, RoleConcept)
	// Should contain evidence (from hipótesis & procedencia) and glossary (from glosario)
	found := make(map[string]bool)
	for _, r := range secondary {
		found[r] = true
	}
	if !found[RoleEvidence] {
		t.Errorf("roles_secondary missing %q", RoleEvidence)
	}
	if !found[RoleGlossary] {
		t.Errorf("roles_secondary missing %q", RoleGlossary)
	}
}

// ---------------------------------------------------------------------------
// Case C — Node without explicit role, with tags
// S36 §18.C: inference permitted; priority for internal tags.
// ---------------------------------------------------------------------------

func TestResolvePrimaryRole_TagInference(t *testing.T) {
	e := CanonEntry{
		Key:        "test",
		Title:      "Test",
		SourceTags: []string{"glosario", "definición"},
	}
	got, source := ResolvePrimaryRole(e)
	if got != RoleGlossary {
		t.Errorf("role_primary = %q, want %q", got, RoleGlossary)
	}
	if source != "declared_tags" {
		t.Errorf("role_source = %q, want %q", source, "declared_tags")
	}
}

// ---------------------------------------------------------------------------
// Case D — Code tiddler without explicit role
// S36 §18.D: classification by tags permitted.
// ---------------------------------------------------------------------------

func TestResolvePrimaryRole_CodeByTag(t *testing.T) {
	e := CanonEntry{
		Key:        "test",
		Title:      "Test",
		SourceTags: []string{"código"},
	}
	got, source := ResolvePrimaryRole(e)
	if got != RoleCode {
		t.Errorf("role_primary = %q, want %q", got, RoleCode)
	}
	if source != "declared_tags" {
		t.Errorf("role_source = %q, want %q", source, "declared_tags")
	}
}

// ---------------------------------------------------------------------------
// Case E — Conflict between explicit role and tags
// S36 §18.E: explicit role wins; conflict is traceable.
// ---------------------------------------------------------------------------

func TestResolvePrimaryRole_ExplicitWinsConflict(t *testing.T) {
	role := "evidence"
	e := CanonEntry{
		Key:        "test",
		Title:      "Test",
		SourceRole: &role,
		SourceTags: []string{"glosario", "warning", "política"},
	}
	got, source := ResolvePrimaryRole(e)
	if got != RoleEvidence {
		t.Errorf("role_primary = %q, want %q", got, RoleEvidence)
	}
	if source != "explicit_role" {
		t.Errorf("role_source = %q, want %q", source, "explicit_role")
	}
}

func TestResolveSecondaryRoles_ConflictPreserved(t *testing.T) {
	role := "evidence"
	e := CanonEntry{
		Key:        "test",
		Title:      "Test",
		SourceRole: &role,
		SourceTags: []string{"glosario", "warning", "política"},
	}
	secondary := ResolveSecondaryRoles(e, RoleEvidence)
	found := make(map[string]bool)
	for _, r := range secondary {
		found[r] = true
	}
	if !found[RoleGlossary] {
		t.Errorf("roles_secondary missing %q from conflicting tags", RoleGlossary)
	}
	if !found[RoleWarning] {
		t.Errorf("roles_secondary missing %q from conflicting tags", RoleWarning)
	}
	if !found[RolePolicy] {
		t.Errorf("roles_secondary missing %q from conflicting tags", RolePolicy)
	}
}

// ---------------------------------------------------------------------------
// Case F — Textual tiddler (text/plain)
// S36 §18.F: semantic_text present, asset_id absent, mime_type textual.
// ---------------------------------------------------------------------------

func TestBuildNodeSemantics_TextualNode(t *testing.T) {
	text := "This is a normal textual tiddler."
	e := CanonEntry{
		Key:         "test",
		Title:       "Test",
		ID:          "test-uuid-001",
		Text:        &text,
		ContentType: ContentTypePlain,
		Modality:    ModalityText,
		Encoding:    EncodingUTF8,
	}
	sem := BuildNodeSemantics(e)

	if sem.SemanticText != text {
		t.Errorf("semantic_text = %q, want %q", sem.SemanticText, text)
	}
	if sem.AssetID != "" {
		t.Errorf("asset_id = %q, want empty for textual node", sem.AssetID)
	}
	if sem.MimeType != ContentTypePlain {
		t.Errorf("mime_type = %q, want %q", sem.MimeType, ContentTypePlain)
	}
	if sem.SemanticTextMode != "direct_text" {
		t.Errorf("semantic_text_mode = %q, want %q", sem.SemanticTextMode, "direct_text")
	}
	if sem.AssetMode != "none" {
		t.Errorf("asset_mode = %q, want %q", sem.AssetMode, "none")
	}
}

// ---------------------------------------------------------------------------
// Case G — TiddlyWiki content (text/vnd.tiddlywiki)
// S36 §18.G: mime_type correct, semantic_text preserved, not degraded.
// ---------------------------------------------------------------------------

func TestBuildNodeSemantics_TiddlyWikiContent(t *testing.T) {
	text := "This is ''wikitext'' with [[links]]."
	e := CanonEntry{
		Key:         "wiki",
		Title:       "Wiki",
		ID:          "wiki-uuid-001",
		Text:        &text,
		ContentType: ContentTypeTiddlyWiki,
		Modality:    ModalityText,
		Encoding:    EncodingUTF8,
	}
	sem := BuildNodeSemantics(e)

	if sem.MimeType != ContentTypeTiddlyWiki {
		t.Errorf("mime_type = %q, want %q", sem.MimeType, ContentTypeTiddlyWiki)
	}
	if sem.SemanticText != text {
		t.Errorf("semantic_text not preserved: got %q", sem.SemanticText)
	}
	if sem.AssetID != "" {
		t.Errorf("asset_id = %q, want empty for text/vnd.tiddlywiki", sem.AssetID)
	}
}

// ---------------------------------------------------------------------------
// Case H — Tiddler with equations in text
// S36 §18.H: equations preserved inside semantic_text; not converted to asset.
// ---------------------------------------------------------------------------

func TestBuildNodeSemantics_EquationsInText(t *testing.T) {
	text := "The energy equation: $$E = mc^2$$ explains mass-energy equivalence."
	e := CanonEntry{
		Key:         "eq",
		Title:       "Equation",
		ID:          "eq-uuid-001",
		Text:        &text,
		ContentType: ContentTypeTiddlyWiki,
		Modality:    ModalityText, // mixed content, but primarily text
		Encoding:    EncodingUTF8,
	}
	sem := BuildNodeSemantics(e)

	if sem.SemanticText != text {
		t.Errorf("equation not preserved in semantic_text: got %q", sem.SemanticText)
	}
	if sem.AssetID != "" {
		t.Errorf("asset_id = %q, want empty for equation in text", sem.AssetID)
	}
}

// ---------------------------------------------------------------------------
// Case I — Binary or referential node
// S36 §18.I: semantic_text empty, raw_payload_ref present, asset_id + mime_type.
// ---------------------------------------------------------------------------

func TestBuildNodeSemantics_BinaryNode(t *testing.T) {
	text := "iVBORw0KGgoAAAANSUhEUg..."
	e := CanonEntry{
		Key:             "img",
		Title:           "Image",
		ID:              "img-uuid-001",
		Text:            &text,
		ContentType:     ContentTypePNG,
		Modality:        ModalityImage,
		Encoding:        EncodingBase64,
		IsBinary:        true,
		IsReferenceOnly: false,
	}
	sem := BuildNodeSemantics(e)

	if sem.SemanticText != "" {
		t.Errorf("semantic_text = %q, want empty for binary node", sem.SemanticText)
	}
	if sem.RawPayloadRef != "node:img-uuid-001" {
		t.Errorf("raw_payload_ref = %q, want %q", sem.RawPayloadRef, "node:img-uuid-001")
	}
	if sem.AssetID != "asset:img-uuid-001" {
		t.Errorf("asset_id = %q, want %q", sem.AssetID, "asset:img-uuid-001")
	}
	if sem.MimeType != ContentTypePNG {
		t.Errorf("mime_type = %q, want %q", sem.MimeType, ContentTypePNG)
	}
}

func TestBuildNodeSemantics_ReferenceOnlyNode(t *testing.T) {
	e := CanonEntry{
		Key:             "ref",
		Title:           "Reference",
		ID:              "ref-uuid-001",
		ContentType:     ContentTypePNG,
		Modality:        ModalityImage,
		Encoding:        EncodingBinary,
		IsBinary:        false,
		IsReferenceOnly: true,
	}
	sem := BuildNodeSemantics(e)

	if sem.SemanticText != "" {
		t.Errorf("semantic_text = %q, want empty for reference-only", sem.SemanticText)
	}
	if sem.AssetID == "" {
		t.Error("asset_id should be non-empty for reference-only node")
	}
}

// ---------------------------------------------------------------------------
// Case J — Mixed text + asset node
// S36 §18.J: text separated from payload ref; no blob duplication.
// ---------------------------------------------------------------------------

func TestBuildNodeSemantics_MixedNode(t *testing.T) {
	text := "Descriptive text with an asset reference."
	e := CanonEntry{
		Key:         "mixed",
		Title:       "Mixed",
		ID:          "mixed-uuid-001",
		Text:        &text,
		ContentType: ContentTypeTiddlyWiki,
		Modality:    ModalityText,
		Encoding:    EncodingUTF8,
		SourceTags:  []string{"asset", "nota"},
	}
	sem := BuildNodeSemantics(e)

	if sem.SemanticText != text {
		t.Errorf("semantic_text = %q, want preserved text", sem.SemanticText)
	}
	// For a textual node with asset tags but text content type,
	// the asset_id is NOT emitted (purely textual handling).
	if sem.AssetID != "" {
		t.Errorf("asset_id = %q, want empty for text/vnd.tiddlywiki textual node", sem.AssetID)
	}
	if sem.RawPayloadRef != "node:mixed-uuid-001" {
		t.Errorf("raw_payload_ref = %q, want %q", sem.RawPayloadRef, "node:mixed-uuid-001")
	}
}

// ---------------------------------------------------------------------------
// Tag merge tests — S36 §11
// ---------------------------------------------------------------------------

func TestMergeSemanticTags_BasicMerge(t *testing.T) {
	tags := MergeSemanticTags([]string{"Alpha", "Beta", "Gamma"})
	if len(tags) != 3 {
		t.Fatalf("tags = %v, want 3 elements", tags)
	}
}

func TestMergeSemanticTags_Deduplication(t *testing.T) {
	tags := MergeSemanticTags([]string{"Alpha", "alpha", "ALPHA", "Beta"})
	if len(tags) != 2 {
		t.Errorf("tags = %v, want 2 (deduplicated)", tags)
	}
	if tags[0] != "Alpha" {
		t.Errorf("first tag = %q, want %q (first occurrence preserved)", tags[0], "Alpha")
	}
}

func TestMergeSemanticTags_EmptyInput(t *testing.T) {
	tags := MergeSemanticTags(nil)
	if tags != nil {
		t.Errorf("tags = %v, want nil for empty input", tags)
	}
}

func TestMergeSemanticTags_WhitespaceOnly(t *testing.T) {
	tags := MergeSemanticTags([]string{"  ", "", "\t"})
	if tags != nil {
		t.Errorf("tags = %v, want nil for whitespace-only", tags)
	}
}

// ---------------------------------------------------------------------------
// Taxonomy path tests — S36 §12
// ---------------------------------------------------------------------------

func TestBuildTaxonomyPath_StructuralTags(t *testing.T) {
	tags := []string{"## 🧰🧱 Elementos específicos", "#### 🌀 Sesión 36"}
	path := BuildTaxonomyPath(tags)
	if len(path) == 0 {
		t.Error("taxonomy_path should not be empty for structural tags")
	}
}

func TestBuildTaxonomyPath_NoStructuralTags(t *testing.T) {
	tags := []string{"alpha", "beta", "gamma"}
	path := BuildTaxonomyPath(tags)
	if len(path) != 0 {
		t.Errorf("taxonomy_path = %v, want empty for non-structural tags", path)
	}
}

func TestBuildTaxonomyPath_EmptyInput(t *testing.T) {
	path := BuildTaxonomyPath(nil)
	if path != nil {
		t.Errorf("taxonomy_path = %v, want nil for empty input", path)
	}
}

// ---------------------------------------------------------------------------
// MIME type tests — S36 §13
// ---------------------------------------------------------------------------

func TestResolveMimeType_FromContentType(t *testing.T) {
	e := CanonEntry{ContentType: ContentTypeTiddlyWiki}
	mime, source := ResolveMimeType(e)
	if mime != ContentTypeTiddlyWiki {
		t.Errorf("mime_type = %q, want %q", mime, ContentTypeTiddlyWiki)
	}
	if source != "content_type" {
		t.Errorf("mime_source = %q, want %q", source, "content_type")
	}
}

func TestResolveMimeType_FromSourceType(t *testing.T) {
	st := "text/x-markdown"
	e := CanonEntry{ContentType: ContentTypeUnknown, SourceType: &st}
	mime, source := ResolveMimeType(e)
	if mime != "text/x-markdown" {
		t.Errorf("mime_type = %q, want %q", mime, "text/x-markdown")
	}
	if source != "metadata" {
		t.Errorf("mime_source = %q, want %q", source, "metadata")
	}
}

func TestResolveMimeType_Fallback(t *testing.T) {
	e := CanonEntry{ContentType: ContentTypeUnknown}
	_, source := ResolveMimeType(e)
	if source != "fallback" {
		t.Errorf("mime_source = %q, want %q", source, "fallback")
	}
}

// ---------------------------------------------------------------------------
// Asset ID tests — S36 §13
// ---------------------------------------------------------------------------

func TestBuildAssetID_PurelyTextual(t *testing.T) {
	e := CanonEntry{
		ID:          "test-uuid",
		ContentType: ContentTypePlain,
	}
	assetID, mode := BuildAssetID(e)
	if assetID != "" {
		t.Errorf("asset_id = %q, want empty for textual node", assetID)
	}
	if mode != "none" {
		t.Errorf("asset_mode = %q, want %q", mode, "none")
	}
}

func TestBuildAssetID_Binary(t *testing.T) {
	e := CanonEntry{
		ID:          "binary-uuid",
		ContentType: ContentTypePNG,
		IsBinary:    true,
	}
	assetID, mode := BuildAssetID(e)
	if assetID != "asset:binary-uuid" {
		t.Errorf("asset_id = %q, want %q", assetID, "asset:binary-uuid")
	}
	if mode != "derived" {
		t.Errorf("asset_mode = %q, want %q", mode, "derived")
	}
}

func TestBuildAssetID_ReferenceOnly(t *testing.T) {
	e := CanonEntry{
		ID:              "ref-uuid",
		ContentType:     ContentTypePNG,
		IsReferenceOnly: true,
	}
	assetID, mode := BuildAssetID(e)
	if assetID != "asset:ref-uuid" {
		t.Errorf("asset_id = %q, want %q", assetID, "asset:ref-uuid")
	}
	if mode != "reference_only" {
		t.Errorf("asset_mode = %q, want %q", mode, "reference_only")
	}
}

// ---------------------------------------------------------------------------
// Raw payload ref tests — S36 §13
// ---------------------------------------------------------------------------

func TestBuildRawPayloadRef_WithID(t *testing.T) {
	e := CanonEntry{ID: "test-uuid-001"}
	ref := BuildRawPayloadRef(e)
	if ref != "node:test-uuid-001" {
		t.Errorf("raw_payload_ref = %q, want %q", ref, "node:test-uuid-001")
	}
}

func TestBuildRawPayloadRef_EmptyID(t *testing.T) {
	e := CanonEntry{}
	ref := BuildRawPayloadRef(e)
	if ref != "" {
		t.Errorf("raw_payload_ref = %q, want empty for node without id", ref)
	}
}

// ---------------------------------------------------------------------------
// Structural pattern inference — S36 §9 level 4
// ---------------------------------------------------------------------------

func TestResolvePrimaryRole_StructuralJSON(t *testing.T) {
	e := CanonEntry{
		Key:         "test",
		Title:       "Test",
		ContentType: ContentTypeJSON,
	}
	got, source := ResolvePrimaryRole(e)
	if got != RoleConfig {
		t.Errorf("role_primary = %q, want %q for JSON", got, RoleConfig)
	}
	if source != "structural_rule" {
		t.Errorf("role_source = %q, want %q", source, "structural_rule")
	}
}

func TestResolvePrimaryRole_StructuralImage(t *testing.T) {
	e := CanonEntry{
		Key:         "test",
		Title:       "Test",
		ContentType: ContentTypePNG,
	}
	got, source := ResolvePrimaryRole(e)
	if got != RoleAsset {
		t.Errorf("role_primary = %q, want %q for PNG", got, RoleAsset)
	}
	if source != "structural_rule" {
		t.Errorf("role_source = %q, want %q", source, "structural_rule")
	}
}

func TestResolvePrimaryRole_Fallback(t *testing.T) {
	e := CanonEntry{
		Key:   "test",
		Title: "Test",
	}
	got, source := ResolvePrimaryRole(e)
	if got != RoleUnclassified {
		t.Errorf("role_primary = %q, want %q for fallback", got, RoleUnclassified)
	}
	if source != "fallback" {
		t.Errorf("role_source = %q, want %q", source, "fallback")
	}
}

// ---------------------------------------------------------------------------
// Domain-specific role mapping — S36 §10
// ---------------------------------------------------------------------------

func TestResolvePrimaryRole_DomainMapping_Sesion(t *testing.T) {
	role := "sesión"
	e := CanonEntry{Key: "test", Title: "Test", SourceRole: &role}
	got, _ := ResolvePrimaryRole(e)
	if got != RoleLog {
		t.Errorf("role_primary = %q, want %q for 'sesión'", got, RoleLog)
	}
}

func TestResolvePrimaryRole_DomainMapping_Hipotesis(t *testing.T) {
	role := "hipótesis"
	e := CanonEntry{Key: "test", Title: "Test", SourceRole: &role}
	got, _ := ResolvePrimaryRole(e)
	if got != RoleEvidence {
		t.Errorf("role_primary = %q, want %q for 'hipótesis'", got, RoleEvidence)
	}
}

func TestResolvePrimaryRole_DomainMapping_Documentacion(t *testing.T) {
	role := "documentación"
	e := CanonEntry{Key: "test", Title: "Test", SourceRole: &role}
	got, _ := ResolvePrimaryRole(e)
	if got != RoleNarrative {
		t.Errorf("role_primary = %q, want %q for 'documentación'", got, RoleNarrative)
	}
}

// ---------------------------------------------------------------------------
// BuildNodeSemantics integration — full pipeline
// ---------------------------------------------------------------------------

func TestBuildNodeSemantics_FullPipeline(t *testing.T) {
	text := "Full pipeline content"
	role := "policy"
	e := CanonEntry{
		Key:         "full",
		Title:       "Full Pipeline",
		ID:          "full-uuid-001",
		Text:        &text,
		ContentType: ContentTypeTiddlyWiki,
		Modality:    ModalityText,
		Encoding:    EncodingUTF8,
		SourceRole:  &role,
		SourceTags:  []string{"## 🧰🧱 Elementos específicos", "sesión"},
	}

	sem := BuildNodeSemantics(e)

	if sem.RolePrimary != RolePolicy {
		t.Errorf("role_primary = %q, want %q", sem.RolePrimary, RolePolicy)
	}
	if sem.SemanticText != text {
		t.Errorf("semantic_text = %q, want %q", sem.SemanticText, text)
	}
	if sem.MimeType != ContentTypeTiddlyWiki {
		t.Errorf("mime_type = %q, want %q", sem.MimeType, ContentTypeTiddlyWiki)
	}
	if sem.RawPayloadRef != "node:full-uuid-001" {
		t.Errorf("raw_payload_ref = %q, want %q", sem.RawPayloadRef, "node:full-uuid-001")
	}
	if sem.AssetID != "" {
		t.Errorf("asset_id = %q, want empty for textual", sem.AssetID)
	}
	if len(sem.Tags) == 0 {
		t.Error("tags should not be empty when SourceTags are present")
	}
	if sem.RoleSource != "explicit_role" {
		t.Errorf("role_source = %q, want %q", sem.RoleSource, "explicit_role")
	}
}

// ---------------------------------------------------------------------------
// Determinism — S36 §19
// ---------------------------------------------------------------------------

func TestBuildNodeSemantics_Determinism(t *testing.T) {
	text := "Determinism test"
	role := "note"
	e := CanonEntry{
		Key:         "det",
		Title:       "Det",
		ID:          "det-uuid",
		Text:        &text,
		ContentType: ContentTypePlain,
		Modality:    ModalityText,
		Encoding:    EncodingUTF8,
		SourceRole:  &role,
		SourceTags:  []string{"alpha", "beta"},
	}

	sem1 := BuildNodeSemantics(e)
	sem2 := BuildNodeSemantics(e)

	if sem1.RolePrimary != sem2.RolePrimary {
		t.Errorf("role_primary differs: %q vs %q", sem1.RolePrimary, sem2.RolePrimary)
	}
	if sem1.SemanticText != sem2.SemanticText {
		t.Errorf("semantic_text differs")
	}
	if sem1.MimeType != sem2.MimeType {
		t.Errorf("mime_type differs")
	}
	if sem1.RawPayloadRef != sem2.RawPayloadRef {
		t.Errorf("raw_payload_ref differs")
	}
	if sem1.AssetID != sem2.AssetID {
		t.Errorf("asset_id differs")
	}
}
