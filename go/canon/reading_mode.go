// Package canon — reading_mode.go
//
// S35 — canon-node-reading-mode-and-typing-v0
//
// Defines the reading mode and minimal typing layer for each node in the
// canonical JSONL export. Every exported line must expose five reading mode
// fields:
//
//   content_type      — what type of content the node carries
//   modality          — how the node should be read (primary channel)
//   encoding          — how the payload is represented
//   is_binary         — whether the content requires binary treatment
//   is_reference_only — whether the node is a reference/pointer, not content
//
// These five fields are complementary, not redundant.
//
// Dependencies on prior sessions (not reopened here):
//   S33 — JSONL functional export (1 tiddler = 1 line)
//   S34 — structural identity (id, key, title, canonical_slug, version_id)
//   S30 — UUIDv5 and canonical JSON
//
// Design principles:
//   - Prefer fidelity over sophistication
//   - Prefer conservative classification over aggressive inference
//   - Prefer documented "unknown" over false precision
//   - Do not transform or rewrite payloads to classify them
//
// Ref: S35 — canon-node-reading-mode-and-typing-v0.
package canon

import (
	"encoding/json"
	"strings"
)

// ---------------------------------------------------------------------------
// Constants — allowed catalogues
// ---------------------------------------------------------------------------

// Content type catalogue (S35 §16.1).
const (
	ContentTypePlain         = "text/plain"
	ContentTypeMarkdown      = "text/markdown"
	ContentTypeHTML          = "text/html"
	ContentTypeTiddlyWiki    = "text/vnd.tiddlywiki"
	ContentTypeJSON          = "application/json"
	ContentTypeCSV           = "text/csv"
	ContentTypePNG           = "image/png"
	ContentTypeJPEG          = "image/jpeg"
	ContentTypeSVG           = "image/svg+xml"
	ContentTypeOctetStream   = "application/octet-stream"
	ContentTypeTiddler       = "application/x-tiddler"
	ContentTypeUnknown       = "unknown"
)

// Modality catalogue (S35 §16.2).
const (
	ModalityText     = "text"
	ModalityCode     = "code"
	ModalityTable    = "table"
	ModalityImage    = "image"
	ModalityMetadata = "metadata"
	ModalityBinary   = "binary"
	ModalityEquation = "equation"
	ModalityMixed    = "mixed"
	ModalityUnknown  = "unknown"
)

// Encoding catalogue (S35 §16.3).
const (
	EncodingUTF8    = "utf-8"
	EncodingBase64  = "base64"
	EncodingBinary  = "binary"
	EncodingUnknown = "unknown"
)

// ---------------------------------------------------------------------------
// ReadingMode — the five-field typing output
// ---------------------------------------------------------------------------

// ReadingMode holds the five reading mode fields for a canonical node.
//
// Ref: S35 §11 — conceptual rule: each node must answer these five questions.
type ReadingMode struct {
	ContentType     string `json:"content_type"`
	Modality        string `json:"modality"`
	Encoding        string `json:"encoding"`
	IsBinary        bool   `json:"is_binary"`
	IsReferenceOnly bool   `json:"is_reference_only"`
}

// ---------------------------------------------------------------------------
// Detection helpers
// ---------------------------------------------------------------------------

// DetectContentType determines the content type for a canon entry.
//
// Inference order (S35 §17.1):
//  1. Explicit source signal: if CanonEntry carries a SourceType from the
//     raw tiddler "type" field, use that if it maps to a known content_type.
//  2. Structural analysis of the payload.
//  3. Conservative fallback: "unknown".
//
// Ref: S35 §17.2 — content_type rules.
func DetectContentType(e CanonEntry) string {
	// Step 1: check explicit source type from the tiddler.
	if e.SourceType != nil && *e.SourceType != "" {
		ct := normalizeSourceType(*e.SourceType)
		if ct != "" {
			return ct
		}
	}

	// Step 2: structural analysis of the text payload.
	if e.Text == nil {
		return ContentTypeUnknown
	}
	text := *e.Text
	if text == "" {
		return ContentTypeUnknown
	}

	// Check if it looks like JSON (conservative: must parse).
	if looksLikeJSON(text) {
		return ContentTypeJSON
	}

	// Default for textual content without explicit type:
	// TiddlyWiki tiddlers without an explicit type are wikitext.
	return ContentTypeTiddlyWiki
}

// DetectModality determines the primary reading modality of the node.
//
// Ref: S35 §17.6 — modality derivation from content_type.
func DetectModality(contentType string, e CanonEntry) string {
	// Special case: equation detection for TiddlyWiki content (S35 §17.4).
	if contentType == ContentTypeTiddlyWiki && isExplicitEquation(e) {
		return ModalityEquation
	}

	switch contentType {
	case ContentTypePlain, ContentTypeMarkdown, ContentTypeHTML, ContentTypeTiddlyWiki:
		return ModalityText
	case ContentTypeJSON:
		return ModalityMetadata
	case ContentTypeCSV:
		return ModalityTable
	case ContentTypePNG, ContentTypeJPEG, ContentTypeSVG:
		return ModalityImage
	case ContentTypeOctetStream:
		return ModalityBinary
	case ContentTypeTiddler:
		return ModalityMetadata
	default:
		return ModalityUnknown
	}
}

// DetectEncoding determines how the payload is encoded.
//
// Ref: S35 §17.7 — encoding rules.
func DetectEncoding(contentType string, e CanonEntry) string {
	switch contentType {
	case ContentTypePlain, ContentTypeMarkdown, ContentTypeHTML,
		ContentTypeTiddlyWiki, ContentTypeJSON, ContentTypeCSV,
		ContentTypeSVG, ContentTypeTiddler:
		return EncodingUTF8
	case ContentTypePNG, ContentTypeJPEG:
		// In TiddlyWiki exports, images are embedded as base64.
		if e.Text != nil && looksLikeBase64(*e.Text) {
			return EncodingBase64
		}
		return EncodingBinary
	case ContentTypeOctetStream:
		if e.Text != nil && looksLikeBase64(*e.Text) {
			return EncodingBase64
		}
		return EncodingBinary
	default:
		return EncodingUnknown
	}
}

// DetectBinaryFlag determines whether the content requires binary treatment.
//
// Ref: S35 §17.8 — is_binary rules.
func DetectBinaryFlag(contentType string, encoding string) bool {
	switch contentType {
	case ContentTypePNG, ContentTypeJPEG, ContentTypeOctetStream:
		return true
	}
	if encoding == EncodingBinary {
		return true
	}
	return false
}

// DetectReferenceOnlyFlag determines whether the node is a reference/pointer
// without carrying the actual primary content.
//
// A node is reference-only when:
//   - It has a SourceType indicating a reference (e.g., application/x-tiddler)
//     AND has no text content.
//   - It is an image type but carries no embedded content (external reference).
//
// Ref: S35 §17.9 — is_reference_only rules.
func DetectReferenceOnlyFlag(contentType string, e CanonEntry) bool {
	hasText := e.Text != nil && *e.Text != ""

	switch contentType {
	case ContentTypePNG, ContentTypeJPEG, ContentTypeSVG:
		// Image nodes without embedded content are references.
		if !hasText {
			return true
		}
	case ContentTypeTiddler:
		// application/x-tiddler without content is a structural reference.
		if !hasText {
			return true
		}
	}

	// A node with explicit source type but completely empty content
	// and the type suggests it should have content is reference-only.
	// But we must not infer reference-only merely from empty text (S35 §13).
	return false
}

// ---------------------------------------------------------------------------
// BuildNodeReadingMode — single entry point
// ---------------------------------------------------------------------------

// BuildNodeReadingMode computes all five reading mode fields for a CanonEntry.
//
// The function follows the inference order defined in S35 §17.1:
//  1. Explicit source signals
//  2. Structural analysis
//  3. Conservative fallback
//  4. "unknown" when certainty is insufficient
//
// It does NOT modify the CanonEntry; it returns a ReadingMode struct.
// The caller is responsible for applying the reading mode to the entry.
//
// Ref: S35 §17 — detection rules.
// Ref: S35 §11 — centralisation requirement.
func BuildNodeReadingMode(e CanonEntry) ReadingMode {
	ct := DetectContentType(e)
	mod := DetectModality(ct, e)
	enc := DetectEncoding(ct, e)
	isBin := DetectBinaryFlag(ct, enc)
	isRef := DetectReferenceOnlyFlag(ct, e)

	return ReadingMode{
		ContentType:     ct,
		Modality:        mod,
		Encoding:        enc,
		IsBinary:        isBin,
		IsReferenceOnly: isRef,
	}
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

// normalizeSourceType maps a raw tiddler "type" field to our content_type
// catalogue. Returns empty string if the type is not recognized.
func normalizeSourceType(rawType string) string {
	t := strings.TrimSpace(strings.ToLower(rawType))

	// Direct MIME type matches.
	knownTypes := map[string]string{
		"text/plain":               ContentTypePlain,
		"text/markdown":            ContentTypeMarkdown,
		"text/x-markdown":          ContentTypeMarkdown,
		"text/html":                ContentTypeHTML,
		"text/vnd.tiddlywiki":      ContentTypeTiddlyWiki,
		"application/json":         ContentTypeJSON,
		"text/csv":                 ContentTypeCSV,
		"image/png":                ContentTypePNG,
		"image/jpeg":               ContentTypeJPEG,
		"image/jpg":                ContentTypeJPEG,
		"image/svg+xml":            ContentTypeSVG,
		"application/octet-stream": ContentTypeOctetStream,
		"application/x-tiddler":    ContentTypeTiddler,
	}

	if ct, ok := knownTypes[t]; ok {
		return ct
	}

	// Broad prefix matches for image types.
	if strings.HasPrefix(t, "image/png") {
		return ContentTypePNG
	}
	if strings.HasPrefix(t, "image/jpeg") || strings.HasPrefix(t, "image/jpg") {
		return ContentTypeJPEG
	}
	if strings.HasPrefix(t, "image/svg") {
		return ContentTypeSVG
	}

	return ""
}

// looksLikeJSON performs a conservative check: the text must parse as valid JSON.
// Does NOT attempt partial parsing or structural guessing.
//
// Ref: S35 §13 — do not assume JSON just because it "looks like" JSON.
func looksLikeJSON(text string) bool {
	trimmed := strings.TrimSpace(text)
	if len(trimmed) < 2 {
		return false
	}
	// Must start with { or [.
	first := trimmed[0]
	if first != '{' && first != '[' {
		return false
	}
	// Must parse as valid JSON.
	return json.Valid([]byte(trimmed))
}

// isExplicitEquation checks whether a TiddlyWiki node is explicitly
// mathematical, based on structural signals (not mere presence of symbols).
//
// S35 §17.4 — equation modality requires explicit evidence:
//   - <$latex> widget
//   - $$ delimiters
//   - \( ... \) or \[ ... \] LaTeX delimiters
//
// The check is conservative: the pattern must dominate the content,
// not just appear incidentally.
func isExplicitEquation(e CanonEntry) bool {
	if e.Text == nil {
		return false
	}
	text := *e.Text
	if text == "" {
		return false
	}

	trimmed := strings.TrimSpace(text)

	// Check for TiddlyWiki LaTeX widget.
	if strings.Contains(trimmed, "<$latex") {
		return true
	}

	// Check for display math delimiters: $$ ... $$
	if strings.HasPrefix(trimmed, "$$") && strings.HasSuffix(trimmed, "$$") {
		return true
	}

	// Check for LaTeX inline/display delimiters as primary content.
	if strings.HasPrefix(trimmed, "\\(") && strings.HasSuffix(trimmed, "\\)") {
		return true
	}
	if strings.HasPrefix(trimmed, "\\[") && strings.HasSuffix(trimmed, "\\]") {
		return true
	}

	return false
}

// looksLikeBase64 checks if text content appears to be base64-encoded.
// Conservative: long string of base64 characters with no whitespace
// or structured text markers.
func looksLikeBase64(text string) bool {
	trimmed := strings.TrimSpace(text)
	if len(trimmed) < 16 {
		return false
	}
	// Base64 should be mostly alphanumeric + /+=.
	// If it contains newlines or spaces (non-base64 chars), it's likely text.
	for _, r := range trimmed {
		if (r >= 'A' && r <= 'Z') || (r >= 'a' && r <= 'z') ||
			(r >= '0' && r <= '9') || r == '+' || r == '/' || r == '=' {
			continue
		}
		// Allow line breaks in base64 (some encoders wrap lines).
		if r == '\n' || r == '\r' {
			continue
		}
		return false
	}
	return true
}
