package canon

import (
	"testing"
)

// ---------------------------------------------------------------------------
// Test: DetectContentType
// ---------------------------------------------------------------------------

// Case A — Text plain simple.
func TestDetectContentType_PlainText(t *testing.T) {
	text := "Hello, world."
	st := "text/plain"
	e := CanonEntry{Key: "test", Title: "Test", Text: &text, SourceType: &st}
	got := DetectContentType(e)
	if got != ContentTypePlain {
		t.Errorf("DetectContentType = %q, want %q", got, ContentTypePlain)
	}
}

// Case B — Markdown documented.
func TestDetectContentType_Markdown(t *testing.T) {
	text := "# Heading\n\nSome **bold** text."
	st := "text/markdown"
	e := CanonEntry{Key: "md", Title: "Doc", Text: &text, SourceType: &st}
	got := DetectContentType(e)
	if got != ContentTypeMarkdown {
		t.Errorf("DetectContentType = %q, want %q", got, ContentTypeMarkdown)
	}
}

// Case C — JSON embedded.
func TestDetectContentType_JSON(t *testing.T) {
	text := `{"key": "value", "count": 42}`
	st := "application/json"
	e := CanonEntry{Key: "json", Title: "Data", Text: &text, SourceType: &st}
	got := DetectContentType(e)
	if got != ContentTypeJSON {
		t.Errorf("DetectContentType = %q, want %q", got, ContentTypeJSON)
	}
}

// Case C variant — JSON inferred from structure (no explicit type).
func TestDetectContentType_JSON_InferredFromStructure(t *testing.T) {
	text := `{"key": "value", "count": 42}`
	e := CanonEntry{Key: "json", Title: "Data", Text: &text}
	got := DetectContentType(e)
	if got != ContentTypeJSON {
		t.Errorf("DetectContentType = %q, want %q (inferred)", got, ContentTypeJSON)
	}
}

// Case D — CSV.
func TestDetectContentType_CSV(t *testing.T) {
	text := "name,age\nAlice,30\nBob,25"
	st := "text/csv"
	e := CanonEntry{Key: "csv", Title: "Table", Text: &text, SourceType: &st}
	got := DetectContentType(e)
	if got != ContentTypeCSV {
		t.Errorf("DetectContentType = %q, want %q", got, ContentTypeCSV)
	}
}

// Case E — Image PNG.
func TestDetectContentType_PNG(t *testing.T) {
	text := "iVBORw0KGgoAAAANSUhEUgAA..."
	st := "image/png"
	e := CanonEntry{Key: "img", Title: "Logo", Text: &text, SourceType: &st}
	got := DetectContentType(e)
	if got != ContentTypePNG {
		t.Errorf("DetectContentType = %q, want %q", got, ContentTypePNG)
	}
}

// Case F — TiddlyWiki native (no explicit type → default wikitext).
func TestDetectContentType_TiddlyWiki_Default(t *testing.T) {
	text := "This is some wikitext with ''bold'' and //italic//."
	e := CanonEntry{Key: "tw", Title: "Tiddler", Text: &text}
	got := DetectContentType(e)
	if got != ContentTypeTiddlyWiki {
		t.Errorf("DetectContentType = %q, want %q", got, ContentTypeTiddlyWiki)
	}
}

// Case F variant — Explicit text/vnd.tiddlywiki.
func TestDetectContentType_TiddlyWiki_Explicit(t *testing.T) {
	text := "Some ''wikitext'' content"
	st := "text/vnd.tiddlywiki"
	e := CanonEntry{Key: "tw", Title: "TW Node", Text: &text, SourceType: &st}
	got := DetectContentType(e)
	if got != ContentTypeTiddlyWiki {
		t.Errorf("DetectContentType = %q, want %q", got, ContentTypeTiddlyWiki)
	}
}

// Case I — Ambiguous / unknown (nil text, no source type).
func TestDetectContentType_Unknown_NilText(t *testing.T) {
	e := CanonEntry{Key: "empty", Title: "Empty"}
	got := DetectContentType(e)
	if got != ContentTypeUnknown {
		t.Errorf("DetectContentType = %q, want %q", got, ContentTypeUnknown)
	}
}

// Case I variant — Empty text, no source type.
func TestDetectContentType_Unknown_EmptyText(t *testing.T) {
	text := ""
	e := CanonEntry{Key: "empty", Title: "Empty", Text: &text}
	got := DetectContentType(e)
	if got != ContentTypeUnknown {
		t.Errorf("DetectContentType = %q, want %q", got, ContentTypeUnknown)
	}
}

// Unrecognized source type falls through to structure analysis.
func TestDetectContentType_UnrecognizedSourceType(t *testing.T) {
	text := "Some content"
	st := "application/x-custom"
	e := CanonEntry{Key: "custom", Title: "Custom", Text: &text, SourceType: &st}
	got := DetectContentType(e)
	// Unrecognized source type → structure analysis → not JSON → default TiddlyWiki
	if got != ContentTypeTiddlyWiki {
		t.Errorf("DetectContentType = %q, want %q", got, ContentTypeTiddlyWiki)
	}
}

// ---------------------------------------------------------------------------
// Test: DetectModality
// ---------------------------------------------------------------------------

// Case A — Text plain → modality text.
func TestDetectModality_Text(t *testing.T) {
	text := "Simple text"
	e := CanonEntry{Key: "t", Title: "T", Text: &text}
	got := DetectModality(ContentTypePlain, e)
	if got != ModalityText {
		t.Errorf("DetectModality = %q, want %q", got, ModalityText)
	}
}

// Case C — JSON → modality metadata.
func TestDetectModality_Metadata(t *testing.T) {
	text := `{"a":1}`
	e := CanonEntry{Key: "j", Title: "J", Text: &text}
	got := DetectModality(ContentTypeJSON, e)
	if got != ModalityMetadata {
		t.Errorf("DetectModality = %q, want %q", got, ModalityMetadata)
	}
}

// Case D — CSV → modality table.
func TestDetectModality_Table(t *testing.T) {
	text := "a,b\n1,2"
	e := CanonEntry{Key: "c", Title: "C", Text: &text}
	got := DetectModality(ContentTypeCSV, e)
	if got != ModalityTable {
		t.Errorf("DetectModality = %q, want %q", got, ModalityTable)
	}
}

// Case E — Image PNG → modality image.
func TestDetectModality_Image(t *testing.T) {
	text := "base64data..."
	e := CanonEntry{Key: "img", Title: "Img", Text: &text}
	got := DetectModality(ContentTypePNG, e)
	if got != ModalityImage {
		t.Errorf("DetectModality = %q, want %q", got, ModalityImage)
	}
}

// Case G — Equation in TiddlyWiki (latex widget).
func TestDetectModality_Equation_LatexWidget(t *testing.T) {
	text := "<$latex>E = mc^2</$latex>"
	e := CanonEntry{Key: "eq", Title: "Equation", Text: &text}
	got := DetectModality(ContentTypeTiddlyWiki, e)
	if got != ModalityEquation {
		t.Errorf("DetectModality = %q, want %q", got, ModalityEquation)
	}
}

// Case G — Equation with $$ delimiters.
func TestDetectModality_Equation_DoubleDollar(t *testing.T) {
	text := "$$\\int_0^1 x^2 dx$$"
	e := CanonEntry{Key: "eq2", Title: "Integral", Text: &text}
	got := DetectModality(ContentTypeTiddlyWiki, e)
	if got != ModalityEquation {
		t.Errorf("DetectModality = %q, want %q", got, ModalityEquation)
	}
}

// Case G — Equation with \[ \] delimiters.
func TestDetectModality_Equation_DisplayMath(t *testing.T) {
	text := "\\[x^2 + y^2 = r^2\\]"
	e := CanonEntry{Key: "eq3", Title: "Circle", Text: &text}
	got := DetectModality(ContentTypeTiddlyWiki, e)
	if got != ModalityEquation {
		t.Errorf("DetectModality = %q, want %q", got, ModalityEquation)
	}
}

// Case G — Equation with \( \) delimiters.
func TestDetectModality_Equation_InlineMath(t *testing.T) {
	text := "\\(a^2 + b^2 = c^2\\)"
	e := CanonEntry{Key: "eq4", Title: "Pythagoras", Text: &text}
	got := DetectModality(ContentTypeTiddlyWiki, e)
	if got != ModalityEquation {
		t.Errorf("DetectModality = %q, want %q", got, ModalityEquation)
	}
}

// Non-equation TiddlyWiki content should NOT be classified as equation.
func TestDetectModality_TiddlyWiki_NotEquation(t *testing.T) {
	text := "This has some ''bold'' and a {{transclusion}} and `code` but no math."
	e := CanonEntry{Key: "tw", Title: "Normal", Text: &text}
	got := DetectModality(ContentTypeTiddlyWiki, e)
	if got != ModalityText {
		t.Errorf("DetectModality = %q, want %q (should NOT be equation)", got, ModalityText)
	}
}

// Binary → modality binary.
func TestDetectModality_Binary(t *testing.T) {
	text := "raw bytes"
	e := CanonEntry{Key: "bin", Title: "Bin", Text: &text}
	got := DetectModality(ContentTypeOctetStream, e)
	if got != ModalityBinary {
		t.Errorf("DetectModality = %q, want %q", got, ModalityBinary)
	}
}

// Unknown → modality unknown.
func TestDetectModality_Unknown(t *testing.T) {
	e := CanonEntry{Key: "u", Title: "U"}
	got := DetectModality(ContentTypeUnknown, e)
	if got != ModalityUnknown {
		t.Errorf("DetectModality = %q, want %q", got, ModalityUnknown)
	}
}

// ---------------------------------------------------------------------------
// Test: DetectEncoding
// ---------------------------------------------------------------------------

// Text content → utf-8.
func TestDetectEncoding_UTF8(t *testing.T) {
	text := "Hello"
	e := CanonEntry{Key: "t", Title: "T", Text: &text}
	got := DetectEncoding(ContentTypePlain, e)
	if got != EncodingUTF8 {
		t.Errorf("DetectEncoding = %q, want %q", got, EncodingUTF8)
	}
}

// Case E — Image PNG with base64 content.
func TestDetectEncoding_Base64_PNG(t *testing.T) {
	text := "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
	e := CanonEntry{Key: "img", Title: "Img", Text: &text}
	got := DetectEncoding(ContentTypePNG, e)
	if got != EncodingBase64 {
		t.Errorf("DetectEncoding = %q, want %q", got, EncodingBase64)
	}
}

// Case E — Image PNG without text content → binary encoding.
func TestDetectEncoding_Binary_PNG(t *testing.T) {
	e := CanonEntry{Key: "img", Title: "Img"}
	got := DetectEncoding(ContentTypePNG, e)
	if got != EncodingBinary {
		t.Errorf("DetectEncoding = %q, want %q", got, EncodingBinary)
	}
}

// Unknown content type → unknown encoding.
func TestDetectEncoding_Unknown(t *testing.T) {
	e := CanonEntry{Key: "u", Title: "U"}
	got := DetectEncoding(ContentTypeUnknown, e)
	if got != EncodingUnknown {
		t.Errorf("DetectEncoding = %q, want %q", got, EncodingUnknown)
	}
}

// Case J — Emojis and special chars don't break utf-8 detection.
func TestDetectEncoding_UTF8_WithEmojis(t *testing.T) {
	text := "🌀 Sesión con émojis y diacríticos: ñ, ü, ß"
	e := CanonEntry{Key: "emoji", Title: "Emoji", Text: &text}
	got := DetectEncoding(ContentTypeTiddlyWiki, e)
	if got != EncodingUTF8 {
		t.Errorf("DetectEncoding = %q, want %q", got, EncodingUTF8)
	}
}

// ---------------------------------------------------------------------------
// Test: DetectBinaryFlag
// ---------------------------------------------------------------------------

// Case E — Image PNG → is_binary = true.
func TestDetectBinaryFlag_PNG(t *testing.T) {
	got := DetectBinaryFlag(ContentTypePNG, EncodingBase64)
	if !got {
		t.Error("DetectBinaryFlag = false, want true for PNG")
	}
}

// Case A — Text plain → is_binary = false.
func TestDetectBinaryFlag_TextPlain(t *testing.T) {
	got := DetectBinaryFlag(ContentTypePlain, EncodingUTF8)
	if got {
		t.Error("DetectBinaryFlag = true, want false for text/plain")
	}
}

// OctetStream → is_binary = true.
func TestDetectBinaryFlag_OctetStream(t *testing.T) {
	got := DetectBinaryFlag(ContentTypeOctetStream, EncodingBinary)
	if !got {
		t.Error("DetectBinaryFlag = false, want true for octet-stream")
	}
}

// Unknown → is_binary = false (conservative).
func TestDetectBinaryFlag_Unknown(t *testing.T) {
	got := DetectBinaryFlag(ContentTypeUnknown, EncodingUnknown)
	if got {
		t.Error("DetectBinaryFlag = true, want false for unknown")
	}
}

// ---------------------------------------------------------------------------
// Test: DetectReferenceOnlyFlag
// ---------------------------------------------------------------------------

// Case H — Image without content → is_reference_only = true.
func TestDetectReferenceOnlyFlag_ImageNoContent(t *testing.T) {
	e := CanonEntry{Key: "img", Title: "External Image"}
	got := DetectReferenceOnlyFlag(ContentTypePNG, e)
	if !got {
		t.Error("DetectReferenceOnlyFlag = false, want true for image without content")
	}
}

// Case H — Image with content → is_reference_only = false.
func TestDetectReferenceOnlyFlag_ImageWithContent(t *testing.T) {
	text := "base64imagedata"
	e := CanonEntry{Key: "img", Title: "Embedded Image", Text: &text}
	got := DetectReferenceOnlyFlag(ContentTypePNG, e)
	if got {
		t.Error("DetectReferenceOnlyFlag = true, want false for image with content")
	}
}

// Normal text content → is_reference_only = false.
func TestDetectReferenceOnlyFlag_TextContent(t *testing.T) {
	text := "Hello"
	e := CanonEntry{Key: "t", Title: "T", Text: &text}
	got := DetectReferenceOnlyFlag(ContentTypePlain, e)
	if got {
		t.Error("DetectReferenceOnlyFlag = true, want false for text content")
	}
}

// Case H — application/x-tiddler without content → reference-only.
func TestDetectReferenceOnlyFlag_TiddlerReference(t *testing.T) {
	e := CanonEntry{Key: "ref", Title: "Reference Tiddler"}
	got := DetectReferenceOnlyFlag(ContentTypeTiddler, e)
	if !got {
		t.Error("DetectReferenceOnlyFlag = false, want true for x-tiddler without content")
	}
}

// ---------------------------------------------------------------------------
// Test: BuildNodeReadingMode — integration
// ---------------------------------------------------------------------------

// Case A — Text plain simple.
func TestBuildNodeReadingMode_CaseA_TextPlain(t *testing.T) {
	text := "Hello, world."
	st := "text/plain"
	e := CanonEntry{Key: "test", Title: "Test", Text: &text, SourceType: &st}
	rm := BuildNodeReadingMode(e)

	assertEqual(t, "content_type", rm.ContentType, ContentTypePlain)
	assertEqual(t, "modality", rm.Modality, ModalityText)
	assertEqual(t, "encoding", rm.Encoding, EncodingUTF8)
	assertFalse(t, "is_binary", rm.IsBinary)
	assertFalse(t, "is_reference_only", rm.IsReferenceOnly)
}

// Case B — Markdown documented.
func TestBuildNodeReadingMode_CaseB_Markdown(t *testing.T) {
	text := "# Title\n\nParagraph with **bold**."
	st := "text/markdown"
	e := CanonEntry{Key: "md", Title: "Doc", Text: &text, SourceType: &st}
	rm := BuildNodeReadingMode(e)

	assertEqual(t, "content_type", rm.ContentType, ContentTypeMarkdown)
	assertEqual(t, "modality", rm.Modality, ModalityText)
	assertEqual(t, "encoding", rm.Encoding, EncodingUTF8)
	assertFalse(t, "is_binary", rm.IsBinary)
	assertFalse(t, "is_reference_only", rm.IsReferenceOnly)
}

// Case C — JSON embedded.
func TestBuildNodeReadingMode_CaseC_JSON(t *testing.T) {
	text := `{"name": "test", "value": 42}`
	st := "application/json"
	e := CanonEntry{Key: "json", Title: "Data", Text: &text, SourceType: &st}
	rm := BuildNodeReadingMode(e)

	assertEqual(t, "content_type", rm.ContentType, ContentTypeJSON)
	assertEqual(t, "modality", rm.Modality, ModalityMetadata)
	assertEqual(t, "encoding", rm.Encoding, EncodingUTF8)
	assertFalse(t, "is_binary", rm.IsBinary)
	assertFalse(t, "is_reference_only", rm.IsReferenceOnly)
}

// Case D — CSV.
func TestBuildNodeReadingMode_CaseD_CSV(t *testing.T) {
	text := "col1,col2\nval1,val2"
	st := "text/csv"
	e := CanonEntry{Key: "csv", Title: "Table", Text: &text, SourceType: &st}
	rm := BuildNodeReadingMode(e)

	assertEqual(t, "content_type", rm.ContentType, ContentTypeCSV)
	assertEqual(t, "modality", rm.Modality, ModalityTable)
	assertEqual(t, "encoding", rm.Encoding, EncodingUTF8)
	assertFalse(t, "is_binary", rm.IsBinary)
	assertFalse(t, "is_reference_only", rm.IsReferenceOnly)
}

// Case E — Image PNG with base64.
func TestBuildNodeReadingMode_CaseE_PNG(t *testing.T) {
	text := "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
	st := "image/png"
	e := CanonEntry{Key: "img", Title: "Logo", Text: &text, SourceType: &st}
	rm := BuildNodeReadingMode(e)

	assertEqual(t, "content_type", rm.ContentType, ContentTypePNG)
	assertEqual(t, "modality", rm.Modality, ModalityImage)
	assertEqual(t, "encoding", rm.Encoding, EncodingBase64)
	assertTrue(t, "is_binary", rm.IsBinary)
	assertFalse(t, "is_reference_only", rm.IsReferenceOnly)
}

// Case F — Tiddler nativo TiddlyWiki.
func TestBuildNodeReadingMode_CaseF_TiddlyWiki(t *testing.T) {
	text := "This is ''wikitext'' with //emphasis// and @@highlight@@."
	st := "text/vnd.tiddlywiki"
	e := CanonEntry{Key: "tw", Title: "Wiki Node", Text: &text, SourceType: &st}
	rm := BuildNodeReadingMode(e)

	assertEqual(t, "content_type", rm.ContentType, ContentTypeTiddlyWiki)
	assertEqual(t, "modality", rm.Modality, ModalityText)
	assertEqual(t, "encoding", rm.Encoding, EncodingUTF8)
	assertFalse(t, "is_binary", rm.IsBinary)
	assertFalse(t, "is_reference_only", rm.IsReferenceOnly)
}

// Case G — Ecuación explícita en TiddlyWiki.
func TestBuildNodeReadingMode_CaseG_Equation(t *testing.T) {
	text := "<$latex>E = mc^2</$latex>"
	st := "text/vnd.tiddlywiki"
	e := CanonEntry{Key: "eq", Title: "Energy", Text: &text, SourceType: &st}
	rm := BuildNodeReadingMode(e)

	assertEqual(t, "content_type", rm.ContentType, ContentTypeTiddlyWiki)
	assertEqual(t, "modality", rm.Modality, ModalityEquation)
	assertEqual(t, "encoding", rm.Encoding, EncodingUTF8)
	assertFalse(t, "is_binary", rm.IsBinary)
	assertFalse(t, "is_reference_only", rm.IsReferenceOnly)
}

// Case H — Nodo referencia (image without content).
func TestBuildNodeReadingMode_CaseH_Reference(t *testing.T) {
	st := "image/png"
	e := CanonEntry{Key: "ref", Title: "External Image", SourceType: &st}
	rm := BuildNodeReadingMode(e)

	assertEqual(t, "content_type", rm.ContentType, ContentTypePNG)
	assertEqual(t, "modality", rm.Modality, ModalityImage)
	assertTrue(t, "is_binary", rm.IsBinary)
	assertTrue(t, "is_reference_only", rm.IsReferenceOnly)
}

// Case I — Caso ambiguo (fallback conservador).
func TestBuildNodeReadingMode_CaseI_Ambiguous(t *testing.T) {
	e := CanonEntry{Key: "amb", Title: "Ambiguous"}
	rm := BuildNodeReadingMode(e)

	assertEqual(t, "content_type", rm.ContentType, ContentTypeUnknown)
	assertEqual(t, "modality", rm.Modality, ModalityUnknown)
	assertEqual(t, "encoding", rm.Encoding, EncodingUnknown)
	assertFalse(t, "is_binary", rm.IsBinary)
	assertFalse(t, "is_reference_only", rm.IsReferenceOnly)
}

// Case J — Caracteres especiales / emojis.
func TestBuildNodeReadingMode_CaseJ_SpecialChars(t *testing.T) {
	text := "🌀 Sesión con diacríticos: ñ, ü, ß, 中文, العربية"
	e := CanonEntry{Key: "special", Title: "Special", Text: &text}
	rm := BuildNodeReadingMode(e)

	// Content without explicit type and not JSON → default TiddlyWiki.
	assertEqual(t, "content_type", rm.ContentType, ContentTypeTiddlyWiki)
	assertEqual(t, "modality", rm.Modality, ModalityText)
	assertEqual(t, "encoding", rm.Encoding, EncodingUTF8)
	assertFalse(t, "is_binary", rm.IsBinary)
	assertFalse(t, "is_reference_only", rm.IsReferenceOnly)
}

// ---------------------------------------------------------------------------
// Test: Determinism
// ---------------------------------------------------------------------------

// Same inputs → same reading mode (S35 §21.B).
func TestBuildNodeReadingMode_Deterministic(t *testing.T) {
	text := "Determinism test content"
	st := "text/markdown"
	e := CanonEntry{Key: "det", Title: "Det", Text: &text, SourceType: &st}
	rm1 := BuildNodeReadingMode(e)
	rm2 := BuildNodeReadingMode(e)

	if rm1 != rm2 {
		t.Errorf("non-deterministic: %+v != %+v", rm1, rm2)
	}
}

// ---------------------------------------------------------------------------
// Test: normalizeSourceType
// ---------------------------------------------------------------------------

func TestNormalizeSourceType(t *testing.T) {
	tests := []struct {
		name string
		raw  string
		want string
	}{
		{"plain", "text/plain", ContentTypePlain},
		{"markdown", "text/markdown", ContentTypeMarkdown},
		{"x-markdown", "text/x-markdown", ContentTypeMarkdown},
		{"html", "text/html", ContentTypeHTML},
		{"tiddlywiki", "text/vnd.tiddlywiki", ContentTypeTiddlyWiki},
		{"json", "application/json", ContentTypeJSON},
		{"csv", "text/csv", ContentTypeCSV},
		{"png", "image/png", ContentTypePNG},
		{"jpeg", "image/jpeg", ContentTypeJPEG},
		{"jpg", "image/jpg", ContentTypeJPEG},
		{"svg", "image/svg+xml", ContentTypeSVG},
		{"octet", "application/octet-stream", ContentTypeOctetStream},
		{"x-tiddler", "application/x-tiddler", ContentTypeTiddler},
		{"unknown", "application/x-custom", ""},
		{"uppercase", "TEXT/PLAIN", ContentTypePlain},
		{"whitespace", "  text/plain  ", ContentTypePlain},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := normalizeSourceType(tt.raw)
			if got != tt.want {
				t.Errorf("normalizeSourceType(%q) = %q, want %q", tt.raw, got, tt.want)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// Test: looksLikeJSON
// ---------------------------------------------------------------------------

func TestLooksLikeJSON(t *testing.T) {
	tests := []struct {
		name string
		text string
		want bool
	}{
		{"valid object", `{"key":"value"}`, true},
		{"valid array", `[1,2,3]`, true},
		{"invalid json", `{invalid}`, false},
		{"empty string", ``, false},
		{"plain text", `hello world`, false},
		{"starts with brace but invalid", `{not json at all}`, false},
		{"nested valid", `{"a":{"b":[1,2]}}`, true},
		// Must not confuse markdown with JSON
		{"markdown heading", `# Title`, false},
		{"wikitext", `''bold'' text`, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := looksLikeJSON(tt.text)
			if got != tt.want {
				t.Errorf("looksLikeJSON(%q) = %v, want %v", tt.text, got, tt.want)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// Test: isExplicitEquation
// ---------------------------------------------------------------------------

func TestIsExplicitEquation(t *testing.T) {
	tests := []struct {
		name string
		text string
		want bool
	}{
		{"latex widget", "<$latex>E=mc^2</$latex>", true},
		{"double dollar", "$$x^2 + y^2$$", true},
		{"display math", "\\[\\sum_{i=0}^n x_i\\]", true},
		{"inline math", "\\(a+b=c\\)", true},
		{"normal text", "This is normal text with $ signs", false},
		{"code block", "```\nif x > 0 { return x }\n```", false},
		{"empty", "", false},
		{"braces only", "{}", false},
		{"partial dollar", "$x=1$", false}, // Single dollar not supported
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			text := tt.text
			e := CanonEntry{Key: "eq", Title: "Eq", Text: &text}
			got := isExplicitEquation(e)
			if got != tt.want {
				t.Errorf("isExplicitEquation(%q) = %v, want %v", tt.text, got, tt.want)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// Test: looksLikeBase64
// ---------------------------------------------------------------------------

func TestLooksLikeBase64(t *testing.T) {
	tests := []struct {
		name string
		text string
		want bool
	}{
		{"valid base64", "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ", true},
		{"too short", "abc", false},
		{"contains spaces", "not base64 at all", false},
		{"contains braces", "{\"key\":\"value\"}", false},
		{"long alphanumeric", "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop", true},
		{"base64 with padding", "SGVsbG8gV29ybGQ=", true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := looksLikeBase64(tt.text)
			if got != tt.want {
				t.Errorf("looksLikeBase64(%q) = %v, want %v", tt.text, got, tt.want)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func assertEqual(t *testing.T, field, got, want string) {
	t.Helper()
	if got != want {
		t.Errorf("%s = %q, want %q", field, got, want)
	}
}

func assertTrue(t *testing.T, field string, got bool) {
	t.Helper()
	if !got {
		t.Errorf("%s = false, want true", field)
	}
}

func assertFalse(t *testing.T, field string, got bool) {
	t.Helper()
	if got {
		t.Errorf("%s = true, want false", field)
	}
}
