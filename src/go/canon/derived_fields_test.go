package canon

import "testing"

func TestDeriveContentPlain_TextualNode(t *testing.T) {
	text := "  Hola,\r\n\nmundo\tcon   espacios.  "
	entry := CanonEntry{
		Text:        &text,
		ContentType: ContentTypeTiddlyWiki,
	}

	got := DeriveContentPlain(entry)
	if got == nil {
		t.Fatal("DeriveContentPlain returned nil for textual node")
	}
	want := "Hola, mundo con espacios."
	if *got != want {
		t.Fatalf("content.plain = %q, want %q", *got, want)
	}
}

func TestDeriveContentPlain_BinaryNode(t *testing.T) {
	text := "iVBORw0KGgoAAAANSUhEUgAA"
	entry := CanonEntry{
		Text:        &text,
		ContentType: ContentTypePNG,
		IsBinary:    true,
	}

	if got := DeriveContentPlain(entry); got != nil {
		t.Fatalf("content.plain = %q, want nil for binary node", *got)
	}
}

func TestDeriveContentProjection_AssetImage(t *testing.T) {
	text := "aGVsbG8="
	entry := CanonEntry{
		ID:            "11111111-1111-4111-8111-111111111111",
		Text:          &text,
		ContentType:   ContentTypePNG,
		Modality:      ModalityImage,
		Encoding:      EncodingBase64,
		IsBinary:      true,
		RawPayloadRef: "node:11111111-1111-4111-8111-111111111111",
		AssetID:       "asset:11111111-1111-4111-8111-111111111111",
		MimeType:      ContentTypePNG,
	}

	got := DeriveContentProjection(entry)
	if got == nil || got.Asset == nil {
		t.Fatalf("asset projection missing: %+v", got)
	}
	if got.Plain != nil {
		t.Fatalf("binary asset must not emit content.plain: %+v", got.Plain)
	}
	if got.ProjectionKind != RoleAsset {
		t.Fatalf("projection_kind = %q, want %q", got.ProjectionKind, RoleAsset)
	}
	if got.Asset.PayloadByteCount != 5 {
		t.Fatalf("payload byte count = %d, want 5", got.Asset.PayloadByteCount)
	}
	wantHash := "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
	if got.Asset.PayloadSHA256 != wantHash {
		t.Fatalf("payload hash = %q, want %q", got.Asset.PayloadSHA256, wantHash)
	}
}

func TestDeriveContentProjection_CodeEquationReferenceAndMixed(t *testing.T) {
	text := "Ver [paper](https://example.org/paper) y la ecuacion $$E=mc^2$$:\n\n```go\nfmt.Println(\"ok\")\n```"
	entry := CanonEntry{
		Text:        &text,
		ContentType: ContentTypeMarkdown,
		Modality:    ModalityMixed,
	}

	got := DeriveContentProjection(entry)
	if got == nil {
		t.Fatal("content projection is nil")
	}
	if got.ProjectionKind != ModalityMixed {
		t.Fatalf("projection_kind = %q, want %q", got.ProjectionKind, ModalityMixed)
	}
	if len(got.CodeBlocks) != 1 || got.CodeBlocks[0].Language != "go" {
		t.Fatalf("code_blocks = %+v", got.CodeBlocks)
	}
	if len(got.Equations) != 1 || got.Equations[0].Text != "E=mc^2" {
		t.Fatalf("equations = %+v", got.Equations)
	}
	if len(got.References) == 0 || got.References[0].Target != "https://example.org/paper" {
		t.Fatalf("references = %+v", got.References)
	}
	wantModalities := []string{"text", "code", "equation", "reference"}
	if !stringSliceEqual(got.Modalities, wantModalities) {
		t.Fatalf("modalities = %v, want %v", got.Modalities, wantModalities)
	}
}

func TestDeriveContentProjection_StructuredJSONPayload(t *testing.T) {
	text := `{"meta":{"memory_policy":"active"},"items":[1,2]}`
	entry := CanonEntry{
		Text:        &text,
		ContentType: ContentTypeJSON,
		Modality:    ModalityMetadata,
	}

	got := DeriveContentProjection(entry)
	if got == nil || got.StructuredPayload == nil {
		t.Fatalf("structured payload projection missing: %+v", got)
	}
	if got.ProjectionKind != "structured_payload" {
		t.Fatalf("projection_kind = %q, want structured_payload", got.ProjectionKind)
	}
	wantKeys := []string{"items", "meta"}
	if !stringSliceEqual(got.StructuredPayload.TopLevelKeys, wantKeys) {
		t.Fatalf("top_level_keys = %v, want %v", got.StructuredPayload.TopLevelKeys, wantKeys)
	}
}

func TestNormalizeTagsForComparison_CaseDiacriticsEmojiAndDuplicates(t *testing.T) {
	input := []string{
		"  ÁRBOL  ",
		"arbol",
		" Café  con   leche ",
		"cafe con leche",
		"🚀 Launch",
		"🚀  launch",
	}

	got := NormalizeTagsForComparison(input)
	want := []string{"arbol", "cafe con leche", "🚀 launch"}

	if !stringSliceEqual(got, want) {
		t.Fatalf("normalized_tags = %v, want %v", got, want)
	}
}

func TestApplyDerivedProjections_DoesNotAlterOriginalTags(t *testing.T) {
	text := "Body"
	entry := CanonEntry{
		Text:        &text,
		ContentType: ContentTypePlain,
		Tags:        []string{"Árbol", "🚀 Launch"},
	}

	original := append([]string(nil), entry.Tags...)
	ApplyDerivedProjections(&entry)

	if !stringSliceEqual(entry.Tags, original) {
		t.Fatalf("tags mutated: got %v, want %v", entry.Tags, original)
	}
	wantNormalized := []string{"arbol", "🚀 launch"}
	if !stringSliceEqual(entry.NormalizedTags, wantNormalized) {
		t.Fatalf("normalized_tags = %v, want %v", entry.NormalizedTags, wantNormalized)
	}
}
