package canon

import "strings"

// ContentProjection carries auxiliary non-authoritative content views.
type ContentProjection struct {
	Plain *string `json:"plain,omitempty"`
}

// ApplyDerivedProjections computes S41 derived helper fields.
func ApplyDerivedProjections(e *CanonEntry) {
	if e == nil {
		return
	}

	if plain := DeriveContentPlain(*e); plain != nil {
		e.Content = &ContentProjection{Plain: plain}
	} else {
		e.Content = nil
	}

	e.NormalizedTags = DeriveNormalizedTags(*e)
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
