// Package bridge — adapter_real_html.go
//
// S33 adapter: extracts tiddlers directly from a TiddlyWiki HTML file
// by parsing <script class="tiddlywiki-tiddler-store" type="application/json">
// blocks and converting the JSON objects into ingesta.RawTiddler shapes.
//
// This adapter is a non-invasive extension that does NOT modify Ingesta,
// Canon, or existing Bridge logic. It provides a Go-native HTML→RawTiddler
// path that bypasses the Rust Extractor when processing the real HTML corpus.
//
// Contract reference: contratos/m01-s33-single-jsonl-functional-tiddlers-from-real-html-v0.md.json
// Ref: S05 §4 — RawTiddler shape expected by Ingesta.
// Ref: S14 — Bridge is the integration layer.
package bridge

import (
	"encoding/json"
	"fmt"
	"io"
	"regexp"
	"strings"

	"github.com/tiddly-data-converter/ingesta"
)

// tiddlerStoreRe matches TiddlyWiki tiddler store script blocks.
// The content between tags is a JSON array of tiddler objects.
var tiddlerStoreRe = regexp.MustCompile(
	`(?s)<script\s+class="tiddlywiki-tiddler-store"\s+type="application/json"\s*>\s*(\[.*?\])\s*</script>`)

// ExtractResult holds observable counters from HTML extraction.
type ExtractResult struct {
	// BlocksFound is the number of tiddler-store script blocks found.
	BlocksFound int `json:"blocks_found"`
	// TotalExtracted is the total number of raw tiddlers extracted.
	TotalExtracted int `json:"total_extracted"`
}

// ExtractRawTiddlersFromHTML parses a TiddlyWiki HTML file and extracts
// all tiddler objects from <script class="tiddlywiki-tiddler-store"> blocks.
//
// Each tiddler object is converted into an ingesta.RawTiddler with:
//   - Title from the "title" field
//   - RawText from the "text" field (nil if absent)
//   - RawFields containing all other fields as strings
//   - SourcePosition indicating the block and index within the HTML
//
// This function uses stdlib only (no external HTML parser dependency).
// The regex approach is safe because TiddlyWiki always emits tiddler stores
// as well-formed <script> blocks with known class/type attributes.
//
// Returns the extracted tiddlers and an ExtractResult for observability.
func ExtractRawTiddlersFromHTML(r io.Reader) ([]ingesta.RawTiddler, *ExtractResult, error) {
	htmlBytes, err := io.ReadAll(r)
	if err != nil {
		return nil, nil, fmt.Errorf("adapter_real_html: read HTML: %w", err)
	}
	html := string(htmlBytes)

	matches := tiddlerStoreRe.FindAllStringSubmatch(html, -1)
	result := &ExtractResult{
		BlocksFound: len(matches),
	}

	if len(matches) == 0 {
		return nil, result, fmt.Errorf("adapter_real_html: no tiddlywiki-tiddler-store blocks found")
	}

	var allRaw []ingesta.RawTiddler

	for blockIdx, match := range matches {
		jsonContent := match[1]

		var tiddlerMaps []map[string]interface{}
		if err := json.Unmarshal([]byte(jsonContent), &tiddlerMaps); err != nil {
			return nil, result, fmt.Errorf("adapter_real_html: parse block %d: %w", blockIdx, err)
		}

		for tidIdx, tmap := range tiddlerMaps {
			raw := mapToRawTiddler(tmap, blockIdx, tidIdx)
			allRaw = append(allRaw, raw)
		}
	}

	result.TotalExtracted = len(allRaw)
	return allRaw, result, nil
}

// mapToRawTiddler converts a generic map from the JSON tiddler store
// into the ingesta.RawTiddler shape.
//
// The mapping follows the same convention as the Rust Extractor:
//   - "title" → Title
//   - "text" → RawText (pointer, nil if absent)
//   - all other fields → RawFields as string values
//   - SourcePosition set to "html:block{N}:tiddler{M}"
func mapToRawTiddler(m map[string]interface{}, blockIdx, tidIdx int) ingesta.RawTiddler {
	raw := ingesta.RawTiddler{
		RawFields: make(map[string]string),
	}

	// Extract title.
	if title, ok := m["title"]; ok {
		raw.Title = fmt.Sprintf("%v", title)
	}

	// Extract text (nullable).
	if text, ok := m["text"]; ok {
		s := fmt.Sprintf("%v", text)
		raw.RawText = &s
	}

	// Extract all other fields into RawFields.
	for k, v := range m {
		if k == "title" || k == "text" {
			continue
		}
		raw.RawFields[k] = fmt.Sprintf("%v", v)
	}

	// SourcePosition for audit trail.
	sp := fmt.Sprintf("html:block%d:tiddler%d", blockIdx, tidIdx)
	raw.SourcePosition = &sp

	return raw
}

// FilterRule defines an inclusion/exclusion criterion for tiddlers.
type FilterRule struct {
	// ID is a unique identifier for this rule (for audit trail).
	ID string `json:"id"`
	// Description is a human-readable explanation of the rule.
	Description string `json:"description"`
	// Match returns true if the tiddler matches this rule.
	Match func(title string, fields map[string]string) bool `json:"-"`
	// Action is "exclude" or "include".
	Action string `json:"action"`
}

// FilterLogEntry records the filtering decision for a single tiddler.
type FilterLogEntry struct {
	TiddlerTitle string `json:"tiddler_title"`
	Action       string `json:"action"` // "included" or "excluded"
	RuleID       string `json:"rule_id"`
	Reason       string `json:"reason"`
	RunID        string `json:"run_id"`
}

// DefaultFunctionalTiddlerRules returns the S33 minimal, auditable
// filtering rules for functional tiddlers.
//
// Rule R1: Exclude system tiddlers (title starts with "$:/")
//
//	These are TiddlyWiki internal configuration/plugin tiddlers.
//
// Rule R2: Include all remaining tiddlers as functional project tiddlers.
//
// This rule set is reversible: changing from exclude to include is a
// single-line change, and the export log records every decision.
func DefaultFunctionalTiddlerRules() []FilterRule {
	return []FilterRule{
		{
			ID:          "R1-exclude-system",
			Description: "Exclude system tiddlers whose title starts with $:/",
			Action:      "exclude",
			Match: func(title string, _ map[string]string) bool {
				return strings.HasPrefix(title, "$:/")
			},
		},
	}
}

// ApplyFilterRules applies the filter rules to a list of RawTiddlers,
// returning included tiddlers and a log of all filtering decisions.
//
// Rules are evaluated in order; the first matching rule determines the
// action. If no rule matches, the tiddler is included by default.
func ApplyFilterRules(
	raws []ingesta.RawTiddler,
	rules []FilterRule,
	runID string,
) (included []ingesta.RawTiddler, logEntries []FilterLogEntry) {
	for _, raw := range raws {
		matched := false
		for _, rule := range rules {
			if rule.Match(raw.Title, raw.RawFields) {
				entry := FilterLogEntry{
					TiddlerTitle: raw.Title,
					Action:       rule.Action + "d", // "excluded" or "included"
					RuleID:       rule.ID,
					Reason:       rule.Description,
					RunID:        runID,
				}
				logEntries = append(logEntries, entry)
				if rule.Action == "include" {
					included = append(included, raw)
				}
				matched = true
				break
			}
		}
		if !matched {
			// Default: include
			entry := FilterLogEntry{
				TiddlerTitle: raw.Title,
				Action:       "included",
				RuleID:       "default-include",
				Reason:       "No exclusion rule matched; included by default",
				RunID:        runID,
			}
			logEntries = append(logEntries, entry)
			included = append(included, raw)
		}
	}
	return included, logEntries
}
