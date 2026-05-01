package canon

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"
)

// ContentProjection carries auxiliary non-authoritative content views.
type ContentProjection struct {
	ProjectionKind    string                       `json:"projection_kind,omitempty"`
	Modalities        []string                     `json:"modalities,omitempty"`
	Plain             *string                      `json:"plain,omitempty"`
	Asset             *AssetContentProjection      `json:"asset,omitempty"`
	CodeBlocks        []CodeBlockProjection        `json:"code_blocks,omitempty"`
	Equations         []EquationProjection         `json:"equations,omitempty"`
	References        []ReferenceProjection        `json:"references,omitempty"`
	StructuredPayload *StructuredPayloadProjection `json:"structured_payload,omitempty"`
}

// AssetContentProjection describes a binary/reference payload without
// duplicating the authoritative payload stored in Text.
type AssetContentProjection struct {
	AssetID             string `json:"asset_id,omitempty"`
	MimeType            string `json:"mime_type,omitempty"`
	Encoding            string `json:"encoding,omitempty"`
	PayloadRef          string `json:"payload_ref,omitempty"`
	PayloadPresent      bool   `json:"payload_present"`
	PayloadByteCount    int    `json:"payload_byte_count,omitempty"`
	PayloadSHA256       string `json:"payload_sha256,omitempty"`
	SourceTextByteCount int    `json:"source_text_byte_count,omitempty"`
}

// CodeBlockProjection describes fenced code detected in textual content.
type CodeBlockProjection struct {
	Language  string `json:"language,omitempty"`
	Text      string `json:"text"`
	LineCount int    `json:"line_count"`
	ByteCount int    `json:"byte_count"`
	Source    string `json:"source"`
}

// EquationProjection describes explicit LaTeX/TiddlyWiki equation spans.
type EquationProjection struct {
	Notation string `json:"notation"`
	Text     string `json:"text"`
	Source   string `json:"source"`
}

// ReferenceProjection preserves reference targets discovered in text.
type ReferenceProjection struct {
	Kind   string `json:"kind"`
	Target string `json:"target"`
	Label  string `json:"label,omitempty"`
	Source string `json:"source"`
}

// StructuredPayloadProjection summarizes a valid structured payload without
// treating the summary as authoritative content.
type StructuredPayloadProjection struct {
	Format       string   `json:"format"`
	Source       string   `json:"source"`
	TopLevelType string   `json:"top_level_type"`
	TopLevelKeys []string `json:"top_level_keys,omitempty"`
	ArrayLength  *int     `json:"array_length,omitempty"`
}

// ApplyDerivedProjections computes S41 derived helper fields.
func ApplyDerivedProjections(e *CanonEntry) {
	if e == nil {
		return
	}

	e.Content = DeriveContentProjection(*e)
	e.NormalizedTags = DeriveNormalizedTags(*e)
}

// DeriveContentProjection builds a conservative, non-authoritative content
// projection for the material already preserved in the canonical node.
func DeriveContentProjection(e CanonEntry) *ContentProjection {
	projection := &ContentProjection{}
	modalities := make(map[string]bool)

	if plain := DeriveContentPlain(e); plain != nil {
		projection.Plain = plain
		if e.ContentType != ContentTypeJSON && e.Modality != ModalityMetadata {
			modalities[ModalityText] = true
		}
	}

	if asset := DeriveAssetProjection(e); asset != nil {
		projection.Asset = asset
		modalities[RoleAsset] = true
	}

	if e.Text != nil && !e.IsBinary {
		if blocks := ExtractCodeBlocks(*e.Text); len(blocks) > 0 {
			projection.CodeBlocks = blocks
			modalities[ModalityCode] = true
		}
		if equations := ExtractEquations(*e.Text); len(equations) > 0 {
			projection.Equations = equations
			modalities[ModalityEquation] = true
		}
		if references := ExtractReferences(*e.Text); len(references) > 0 {
			projection.References = references
			modalities["reference"] = true
		}
		if structured := DeriveStructuredPayload(e); structured != nil {
			projection.StructuredPayload = structured
			modalities["structured_payload"] = true
		}
	}

	projection.Modalities = orderedModalities(modalities)
	if len(projection.Modalities) == 0 {
		return nil
	}
	if len(projection.Modalities) == 1 {
		projection.ProjectionKind = projection.Modalities[0]
	} else {
		projection.ProjectionKind = ModalityMixed
	}
	return projection
}

// DeriveContentPlain builds a deterministic plain-text projection from the
// authoritative textual content only. Binary and reference-only nodes do not
// emit content.plain.
func DeriveContentPlain(e CanonEntry) *string {
	if e.IsBinary || e.IsReferenceOnly || e.Text == nil {
		return nil
	}

	switch e.ContentType {
	case "", ContentTypeUnknown, ContentTypePlain, ContentTypeMarkdown,
		ContentTypeTiddlyWiki, ContentTypeHTML, ContentTypeCSV, ContentTypeJSON,
		ContentTypeTiddler:
	default:
		return nil
	}

	normalized := strings.ReplaceAll(*e.Text, "\r\n", "\n")
	normalized = strings.ReplaceAll(normalized, "\r", "\n")
	normalized = strings.Join(strings.Fields(normalized), " ")
	if normalized == "" {
		return nil
	}
	return &normalized
}

// DeriveAssetProjection builds a payload index for asset-like nodes. It never
// duplicates the payload; Text remains the reversible source.
func DeriveAssetProjection(e CanonEntry) *AssetContentProjection {
	isAssetLike := e.IsBinary || e.IsReferenceOnly || e.AssetID != "" ||
		e.Modality == ModalityImage || e.Modality == ModalityBinary ||
		e.ContentType == ContentTypePNG || e.ContentType == ContentTypeJPEG ||
		e.ContentType == ContentTypeSVG || e.ContentType == ContentTypeOctetStream
	if !isAssetLike {
		return nil
	}

	projection := &AssetContentProjection{
		AssetID:    e.AssetID,
		MimeType:   firstNonEmpty(e.MimeType, e.ContentType),
		Encoding:   e.Encoding,
		PayloadRef: e.RawPayloadRef,
	}
	if e.Text == nil || strings.TrimSpace(*e.Text) == "" {
		return projection
	}

	payload := strings.TrimSpace(*e.Text)
	projection.PayloadPresent = true
	projection.SourceTextByteCount = len([]byte(payload))

	if e.Encoding == EncodingBase64 {
		if decoded, ok := decodeBase64Payload(payload); ok {
			projection.PayloadByteCount = len(decoded)
			sum := sha256.Sum256(decoded)
			projection.PayloadSHA256 = fmt.Sprintf("sha256:%x", sum[:])
			return projection
		}
	}

	sum := sha256.Sum256([]byte(payload))
	projection.PayloadByteCount = len([]byte(payload))
	projection.PayloadSHA256 = fmt.Sprintf("sha256:%x", sum[:])
	return projection
}

// ExtractCodeBlocks detects fenced code blocks without interpreting the code.
func ExtractCodeBlocks(text string) []CodeBlockProjection {
	lines := strings.Split(strings.ReplaceAll(text, "\r\n", "\n"), "\n")
	var blocks []CodeBlockProjection
	inFence := false
	language := ""
	startLine := 0
	var body []string

	for i, line := range lines {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "```") {
			if !inFence {
				inFence = true
				language = strings.TrimSpace(strings.TrimPrefix(trimmed, "```"))
				startLine = i + 1
				body = nil
				continue
			}

			blockText := strings.TrimRight(strings.Join(body, "\n"), "\n")
			if strings.TrimSpace(blockText) != "" {
				blocks = append(blocks, CodeBlockProjection{
					Language:  language,
					Text:      blockText,
					LineCount: len(strings.Split(blockText, "\n")),
					ByteCount: len([]byte(blockText)),
					Source:    fmt.Sprintf("fenced_code_block:%d", startLine),
				})
				if len(blocks) >= 20 {
					return blocks
				}
			}
			inFence = false
			language = ""
			body = nil
			continue
		}
		if inFence {
			body = append(body, line)
		}
	}
	return blocks
}

var (
	displayEquationRe = regexp.MustCompile(`(?s)\$\$(.+?)\$\$`)
	parenEquationRe   = regexp.MustCompile(`(?s)\\\((.+?)\\\)|\\\[(.+?)\\\]`)
	latexWidgetRe     = regexp.MustCompile(`(?s)<\$latex\b([^>]*)>(.*?)</\$latex>|<\$latex\b([^>]*)/>`)
	markdownLinkRe    = regexp.MustCompile(`\[[^\]\n]+\]\(([^)\s]+)\)`)
	tiddlyLinkRe      = regexp.MustCompile(`\[\[([^\]\n]+)\]\]`)
	bareURLRe         = regexp.MustCompile(`https?://[^\s<>)"\]]+`)
	doiRe             = regexp.MustCompile(`(?i)\b10\.\d{4,9}/[-._;()/:A-Z0-9]+`)
)

// ExtractEquations detects explicit equation spans. It is conservative and
// only recognizes standard LaTeX delimiters or the TiddlyWiki latex widget.
func ExtractEquations(text string) []EquationProjection {
	var equations []EquationProjection
	seen := make(map[string]bool)
	add := func(notation, body, source string) {
		body = strings.TrimSpace(body)
		if body == "" {
			return
		}
		key := notation + "\x00" + body
		if seen[key] {
			return
		}
		seen[key] = true
		equations = append(equations, EquationProjection{
			Notation: notation,
			Text:     body,
			Source:   source,
		})
	}

	for _, match := range displayEquationRe.FindAllStringSubmatch(text, -1) {
		add("latex_display", match[1], "delimiter:$$")
		if len(equations) >= 20 {
			return equations
		}
	}
	for _, match := range parenEquationRe.FindAllStringSubmatch(text, -1) {
		body := match[1]
		notation := "latex_inline"
		source := "delimiter:\\(\\)"
		if body == "" {
			body = match[2]
			notation = "latex_display"
			source = "delimiter:\\[\\]"
		}
		add(notation, body, source)
		if len(equations) >= 20 {
			return equations
		}
	}
	for _, match := range latexWidgetRe.FindAllStringSubmatch(text, -1) {
		body := latexWidgetText(match)
		add("tiddlywiki_latex_widget", body, "widget:<$latex>")
		if len(equations) >= 20 {
			return equations
		}
	}
	return equations
}

// ExtractReferences detects links and reference identifiers while preserving
// labels when the source syntax exposes them.
func ExtractReferences(text string) []ReferenceProjection {
	var refs []ReferenceProjection
	seen := make(map[string]bool)
	add := func(kind, target, label, source string) {
		target = strings.TrimSpace(target)
		label = strings.TrimSpace(label)
		if target == "" {
			return
		}
		key := kind + "\x00" + target + "\x00" + label
		if seen[key] {
			return
		}
		seen[key] = true
		refs = append(refs, ReferenceProjection{
			Kind:   kind,
			Target: target,
			Label:  label,
			Source: source,
		})
	}

	for _, match := range markdownLinkRe.FindAllStringSubmatchIndex(text, -1) {
		label := text[match[0]+1 : match[2]-2]
		target := text[match[2]:match[3]]
		add(referenceKindForTarget(target), target, label, "markdown_link")
		if len(refs) >= 50 {
			return refs
		}
	}
	for _, match := range tiddlyLinkRe.FindAllStringSubmatch(text, -1) {
		label, target := splitTiddlyWikiLink(match[1])
		add("tiddlywiki_link", target, label, "tw_link")
		if len(refs) >= 50 {
			return refs
		}
	}
	for _, target := range bareURLRe.FindAllString(text, -1) {
		add("url", strings.TrimRight(target, ".,;:"), "", "bare_url")
		if len(refs) >= 50 {
			return refs
		}
	}
	for _, target := range doiRe.FindAllString(text, -1) {
		add("doi", strings.TrimRight(target, ".,;:"), "", "doi")
		if len(refs) >= 50 {
			return refs
		}
	}
	return refs
}

// DeriveStructuredPayload summarizes fully valid JSON payloads. Partial or
// pedagogical JSON stays under Rust deep-node inspection rather than being
// promoted here.
func DeriveStructuredPayload(e CanonEntry) *StructuredPayloadProjection {
	if e.Text == nil {
		return nil
	}
	trimmed := strings.TrimSpace(*e.Text)
	if trimmed == "" {
		return nil
	}
	if e.ContentType != ContentTypeJSON && !looksLikeJSON(trimmed) {
		return nil
	}

	var value interface{}
	if err := json.Unmarshal([]byte(trimmed), &value); err != nil {
		return nil
	}
	projection := &StructuredPayloadProjection{
		Format: "json",
		Source: "text",
	}
	switch typed := value.(type) {
	case map[string]interface{}:
		projection.TopLevelType = "object"
		for key := range typed {
			projection.TopLevelKeys = append(projection.TopLevelKeys, key)
		}
		sort.Strings(projection.TopLevelKeys)
		if len(projection.TopLevelKeys) > 20 {
			projection.TopLevelKeys = projection.TopLevelKeys[:20]
		}
	case []interface{}:
		projection.TopLevelType = "array"
		n := len(typed)
		projection.ArrayLength = &n
	case string:
		projection.TopLevelType = "string"
	case float64:
		projection.TopLevelType = "number"
	case bool:
		projection.TopLevelType = "bool"
	case nil:
		projection.TopLevelType = "null"
	default:
		projection.TopLevelType = "unknown"
	}
	return projection
}

// DeriveNormalizedTags builds a deterministic normalized tag projection for
// comparison and filtering. Order is preserved by first surviving occurrence
// after normalization; equivalent normalized values are collapsed.
func DeriveNormalizedTags(e CanonEntry) []string {
	source := e.Tags
	if len(source) == 0 {
		source = e.SourceTags
	}
	return NormalizeTagsForComparison(source)
}

// NormalizeTagsForComparison applies conservative normalization:
// - trim outer whitespace
// - collapse internal whitespace
// - lowercase
// - strip diacritics
// - preserve emoji and other non-diacritic symbols
// - collapse duplicates after normalization
func NormalizeTagsForComparison(tags []string) []string {
	if len(tags) == 0 {
		return nil
	}

	seen := make(map[string]bool)
	var normalized []string
	for _, tag := range tags {
		value := strings.TrimSpace(tag)
		if value == "" {
			continue
		}
		value = strings.Join(strings.Fields(value), " ")
		value = strings.ToLower(value)
		value = stripDiacritics(value)
		if value == "" || seen[value] {
			continue
		}
		seen[value] = true
		normalized = append(normalized, value)
	}

	if len(normalized) == 0 {
		return nil
	}
	return normalized
}

func orderedModalities(values map[string]bool) []string {
	order := []string{
		ModalityText,
		RoleAsset,
		ModalityCode,
		ModalityEquation,
		"reference",
		"structured_payload",
	}
	var modalities []string
	for _, item := range order {
		if values[item] {
			modalities = append(modalities, item)
			delete(values, item)
		}
	}
	var extra []string
	for item := range values {
		extra = append(extra, item)
	}
	sort.Strings(extra)
	return append(modalities, extra...)
}

func decodeBase64Payload(payload string) ([]byte, bool) {
	cleaned := strings.Map(func(r rune) rune {
		switch r {
		case '\n', '\r', '\t', ' ':
			return -1
		default:
			return r
		}
	}, payload)
	decoded, err := base64.StdEncoding.DecodeString(cleaned)
	if err != nil {
		return nil, false
	}
	return decoded, true
}

func latexWidgetText(match []string) string {
	for _, rawAttrs := range []string{match[1], match[3]} {
		if rawAttrs == "" {
			continue
		}
		if value := attrValue(rawAttrs, "text"); value != "" {
			return value
		}
	}
	return match[2]
}

func attrValue(attrs, name string) string {
	needle := name + "=\""
	start := strings.Index(attrs, needle)
	if start < 0 {
		return ""
	}
	start += len(needle)
	end := strings.Index(attrs[start:], "\"")
	if end < 0 {
		return ""
	}
	return attrs[start : start+end]
}

func splitTiddlyWikiLink(raw string) (label string, target string) {
	parts := strings.SplitN(raw, "|", 2)
	if len(parts) == 2 {
		return strings.TrimSpace(parts[0]), strings.TrimSpace(parts[1])
	}
	return "", strings.TrimSpace(raw)
}

func referenceKindForTarget(target string) string {
	lower := strings.ToLower(strings.TrimSpace(target))
	if strings.HasPrefix(lower, "http://") || strings.HasPrefix(lower, "https://") {
		return "url"
	}
	if strings.HasPrefix(lower, "doi:") || doiRe.MatchString(lower) {
		return "doi"
	}
	return "reference"
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}
