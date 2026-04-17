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
