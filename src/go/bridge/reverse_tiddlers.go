package bridge

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"github.com/tiddly-data-converter/canon"
	"github.com/tiddly-data-converter/ingesta"
)

const (
	ReverseModeInsertOnly          = "insert-only"
	ReverseModeAuthoritativeUpsert = "authoritative-upsert"
	ReverseStorePolicyPreserve     = "preserve"
	ReverseStorePolicyReplace      = "replace"

	ReverseDecisionInserted       = "inserted"
	ReverseDecisionAlreadyPresent = "already_present"
	ReverseDecisionUpdated        = "updated"
	ReverseDecisionSkipped        = "skipped"
	ReverseDecisionRejected       = "rejected"
)

var allowedRawReverseTopLevelFields = map[string]struct{}{
	"schema_version": {},
	"key":            {},
	"title":          {},
	"text":           {},
	"created":        {},
	"modified":       {},
	"source_type":    {},
	"source_tags":    {},
	"source_fields":  {},
	"source_role":    {},
}

var reservedReverseSourceFields = map[string]struct{}{
	"schema_version":  {},
	"key":             {},
	"title":           {},
	"text":            {},
	"type":            {},
	"tags":            {},
	"created":         {},
	"modified":        {},
	"source_type":     {},
	"source_tags":     {},
	"source_fields":   {},
	"source_position": {},
	"source_role":     {},
}

var derivedReverseSourceFields = map[string]struct{}{
	"id":                {},
	"canonical_slug":    {},
	"version_id":        {},
	"content":           {},
	"content.plain":     {},
	"content_type":      {},
	"modality":          {},
	"encoding":          {},
	"is_binary":         {},
	"is_reference_only": {},
	"role_primary":      {},
	"roles_secondary":   {},
	"taxonomy_path":     {},
	"semantic_text":     {},
	"normalized_tags":   {},
	"raw_payload_ref":   {},
	"asset_id":          {},
	"mime_type":         {},
	"document_id":       {},
	"section_path":      {},
	"order_in_document": {},
	"relations":         {},
}

var supportedReverseSourceTypes = map[string]struct{}{
	"text/vnd.tiddlywiki": {},
	"text/markdown":       {},
	"text/plain":          {},
	"text/csv":            {},
	"application/json":    {},
}

// ReverseDecision records the disposition taken for a raw reverse candidate.
type ReverseDecision struct {
	Line     int    `json:"line"`
	Title    string `json:"title,omitempty"`
	Decision string `json:"decision"`
	RuleID   string `json:"rule_id,omitempty"`
	Message  string `json:"message,omitempty"`
}

// ReverseReport exposes deterministic evidence for one reverse run.
type ReverseReport struct {
	Mode                     string                       `json:"mode"`
	StorePolicy              string                       `json:"store_policy"`
	StoreBlocksFound         int                          `json:"store_blocks_found"`
	ExistingTiddlers         int                          `json:"existing_tiddlers"`
	OutputTiddlers           int                          `json:"output_tiddlers"`
	BaseTiddlersDropped      int                          `json:"base_tiddlers_dropped,omitempty"`
	StructuralTiddlersKept   int                          `json:"structural_tiddlers_kept,omitempty"`
	CanonLinesRead           int                          `json:"canon_lines_read"`
	EligibleEntriesEvaluated int                          `json:"eligible_entries_evaluated"`
	OutOfScopeSkipped        int                          `json:"out_of_scope_skipped"`
	InsertedCount            int                          `json:"inserted_count"`
	UpdatedCount             int                          `json:"updated_count"`
	AlreadyPresentCount      int                          `json:"already_present_count"`
	RejectedCount            int                          `json:"rejected_count"`
	RejectedByRule           map[string]int               `json:"rejected_by_rule,omitempty"`
	SkippedByRule            map[string]int               `json:"skipped_by_rule,omitempty"`
	ProcessedSourceTypes     map[string]int               `json:"processed_source_types,omitempty"`
	SourceFieldsUsed         bool                         `json:"source_fields_used"`
	SourceFieldsUsedCount    int                          `json:"source_fields_used_count"`
	HTMLInputPath            string                       `json:"html_input_path,omitempty"`
	CanonInputPath           string                       `json:"canon_input_path,omitempty"`
	OutputHTMLPath           string                       `json:"output_html_path,omitempty"`
	Decisions                []ReverseDecision            `json:"decisions,omitempty"`
	ValidationReport         canon.ValidationReport       `json:"validation_report"`
	ReversePreflight         canon.ReversePreflightReport `json:"reverse_preflight"`
	CanonSource              canon.CanonSourceReport      `json:"canon_source"`
}

// OK reports whether the reverse run completed without raw-candidate
// rejections and with both canon prechecks satisfied.
func (r ReverseReport) OK() bool {
	return r.RejectedCount == 0 &&
		r.CanonSource.OK() &&
		r.ValidationReport.OK() &&
		r.ReversePreflight.OK()
}

// ReverseResult contains the generated HTML plus its report.
type ReverseResult struct {
	HTML   []byte        `json:"-"`
	Report ReverseReport `json:"report"`
}

type reverseCanonLine struct {
	Line   int
	Entry  canon.CanonEntry
	Fields map[string]json.RawMessage
}

type reverseStoreBlock struct {
	ArrayStart  int
	ArrayEnd    int
	ArrayRaw    string
	BlocksFound int
}

type reverseShape struct {
	Title       string
	Text        *string
	Created     *string
	Modified    *string
	SourceType  *string
	SourceTags  []string
	ExtraFields map[string]string
}

type storedTiddler struct {
	Index int
	Raw   map[string]interface{}
	Shape reverseShape
}

type reverseIssue struct {
	RuleID  string
	Message string
}

// ReverseInsertOnlyHTML executes the S43 reverse path:
// mixed canon JSONL -> raw-tiddler selection -> controlled insert-only merge.
//
// The function never mutates the input HTML. It returns an HTML byte slice for
// the caller to persist explicitly to a separate file.
func ReverseInsertOnlyHTML(baseHTML, canonJSONL []byte) (*ReverseResult, error) {
	return reverseHTMLWithMode(baseHTML, canonJSONL, canon.CanonSourceReport{}, ReverseModeInsertOnly, ReverseStorePolicyPreserve)
}

// ReverseAuthoritativeHTML executes the S44 reverse path:
// canonical source of truth -> authoritative upsert into the existing store.
func ReverseAuthoritativeHTML(baseHTML, canonJSONL []byte) (*ReverseResult, error) {
	return reverseHTMLWithMode(baseHTML, canonJSONL, canon.CanonSourceReport{}, ReverseModeAuthoritativeUpsert, ReverseStorePolicyPreserve)
}

// ReverseFiles executes reverse with explicit mode and store policy.
func ReverseFiles(htmlPath, canonPath, outHTMLPath, mode, storePolicy string) (*ReverseResult, error) {
	return reverseFilesWithMode(htmlPath, canonPath, outHTMLPath, mode, storePolicy)
}

func reverseHTMLWithMode(baseHTML, canonJSONL []byte, sourceReport canon.CanonSourceReport, mode, storePolicy string) (*ReverseResult, error) {
	if mode != ReverseModeInsertOnly && mode != ReverseModeAuthoritativeUpsert {
		return nil, fmt.Errorf("reverse_tiddlers: unsupported reverse mode %q", mode)
	}
	if storePolicy != ReverseStorePolicyPreserve && storePolicy != ReverseStorePolicyReplace {
		return nil, fmt.Errorf("reverse_tiddlers: unsupported store policy %q", storePolicy)
	}

	report := ReverseReport{
		Mode:                 mode,
		StorePolicy:          storePolicy,
		RejectedByRule:       make(map[string]int),
		SkippedByRule:        make(map[string]int),
		ProcessedSourceTypes: make(map[string]int),
		CanonSource:          sourceReport,
	}

	policy := canon.DefaultCanonPolicy()
	report.ValidationReport = canon.ValidateCanonJSONL(bytes.NewReader(canonJSONL), policy)
	report.ReversePreflight = canon.ReversePreflightCanonJSONL(bytes.NewReader(canonJSONL))

	if !report.ValidationReport.OK() {
		return &ReverseResult{Report: report}, fmt.Errorf(
			"reverse_tiddlers: canon strict validation failed with %d error(s)",
			report.ValidationReport.ErrorCount(),
		)
	}
	if !report.ReversePreflight.OK() {
		return &ReverseResult{Report: report}, fmt.Errorf(
			"reverse_tiddlers: canon reverse-preflight failed with %d non-ready line(s)",
			report.ReversePreflight.NotReady,
		)
	}

	lines, err := parseReverseCanonLines(canonJSONL)
	if err != nil {
		return &ReverseResult{Report: report}, fmt.Errorf("reverse_tiddlers: parse canon lines: %w", err)
	}
	report.CanonLinesRead = len(lines)

	store, err := locateSingleTiddlerStore(string(baseHTML))
	report.StoreBlocksFound = store.BlocksFound
	if err != nil {
		return &ReverseResult{Report: report}, err
	}

	storedItems, existingByTitle, existingCount, err := parseStoredTiddlers(store.ArrayRaw)
	report.ExistingTiddlers = existingCount
	if err != nil {
		return &ReverseResult{Report: report}, fmt.Errorf("reverse_tiddlers: parse base HTML store: %w", err)
	}

	seenTitles := make(map[string]int, len(lines))
	newItems := make([]string, 0, len(lines))
	replacedItems := make([]map[string]interface{}, 0, len(lines))
	replacedTitles := make(map[string]struct{}, len(lines))
	updatedStore := false

	if storePolicy == ReverseStorePolicyReplace {
		replacedItems, replacedTitles = seedStructuralStoreForReplace(storedItems)
		report.StructuralTiddlersKept = len(replacedItems)
	}

	for _, line := range lines {
		entry := line.Entry
		title := entry.Title

		if !isReverseEligibleLine(line.Fields) {
			report.OutOfScopeSkipped++
			reportSkipRule(&report, "non-authoritative-mixed-line")
			report.Decisions = append(report.Decisions, ReverseDecision{
				Line:     line.Line,
				Title:    title,
				Decision: ReverseDecisionSkipped,
				RuleID:   "non-authoritative-mixed-line",
				Message:  "line is neither a legacy raw reverse addition nor a full canonical record",
			})
			continue
		}

		if skipRule, skipMessage, skip := classifyReverseScopeSkip(entry); skip {
			report.OutOfScopeSkipped++
			reportSkipRule(&report, skipRule)
			report.Decisions = append(report.Decisions, ReverseDecision{
				Line:     line.Line,
				Title:    title,
				Decision: ReverseDecisionSkipped,
				RuleID:   skipRule,
				Message:  skipMessage,
			})
			continue
		}

		report.EligibleEntriesEvaluated++
		report.ProcessedSourceTypes[normalizedReverseSourceTypeLabel(line.Entry.SourceType)]++
		if len(line.Entry.SourceFields) > 0 {
			report.SourceFieldsUsed = true
			report.SourceFieldsUsedCount++
		}

		if prevLine, duplicated := seenTitles[title]; duplicated {
			reportRuleRejection(&report, "batch-duplicate-title")
			report.RejectedCount++
			report.Decisions = append(report.Decisions, ReverseDecision{
				Line:     line.Line,
				Title:    title,
				Decision: ReverseDecisionRejected,
				RuleID:   "batch-duplicate-title",
				Message:  fmt.Sprintf("reverse candidate duplicates line %d; reverse requires unique titles", prevLine),
			})
			continue
		}
		seenTitles[title] = line.Line

		projected, issues := projectReverseShape(entry)
		if len(issues) > 0 {
			report.RejectedCount++
			for _, issue := range issues {
				reportRuleRejection(&report, issue.RuleID)
			}
			report.Decisions = append(report.Decisions, buildRejectedReverseDecision(line.Line, title, issues))
			continue
		}

		if storePolicy == ReverseStorePolicyReplace {
			replacedItem, err := marshalReverseStoreTiddlerMap(projected)
			if err != nil {
				reportRuleRejection(&report, "reverse-projection-failed")
				report.RejectedCount++
				report.Decisions = append(report.Decisions, ReverseDecision{
					Line:     line.Line,
					Title:    title,
					Decision: ReverseDecisionRejected,
					RuleID:   "reverse-projection-failed",
					Message:  err.Error(),
				})
				continue
			}

			replacedItems = append(replacedItems, replacedItem)
			replacedTitles[projected.Title] = struct{}{}

			if existing, found := existingByTitle[projected.Title]; found {
				if reverseShapesEquivalent(existing.Shape, projected) {
					report.AlreadyPresentCount++
					report.Decisions = append(report.Decisions, ReverseDecision{
						Line:     line.Line,
						Title:    title,
						Decision: ReverseDecisionAlreadyPresent,
						RuleID:   "existing-title-match",
						Message:  "base HTML already contains an equivalent authoritative tiddler; replace policy rewrites the store with canon-projected entries only",
					})
					continue
				}

				report.UpdatedCount++
				report.Decisions = append(report.Decisions, ReverseDecision{
					Line:     line.Line,
					Title:    title,
					Decision: ReverseDecisionUpdated,
					RuleID:   "updated-authoritative-title",
					Message:  "base HTML contained this title with stale authoritative fields; replace policy emitted the canon projection only",
				})
				continue
			}

			report.InsertedCount++
			report.Decisions = append(report.Decisions, ReverseDecision{
				Line:     line.Line,
				Title:    title,
				Decision: ReverseDecisionInserted,
				RuleID:   "inserted-new-title",
				Message:  "projected into the replacement TiddlyWiki store",
			})
			continue
		}

		if existing, found := existingByTitle[projected.Title]; found {
			if reverseShapesEquivalent(existing.Shape, projected) {
				report.AlreadyPresentCount++
				report.Decisions = append(report.Decisions, ReverseDecision{
					Line:     line.Line,
					Title:    title,
					Decision: ReverseDecisionAlreadyPresent,
					RuleID:   "existing-title-match",
					Message:  "base HTML already contains an equivalent authoritative tiddler; left untouched",
				})
				continue
			}

			if report.Mode == ReverseModeAuthoritativeUpsert {
				mergedRaw, mergeErr := mergeStoredTiddler(existing.Raw, projected)
				if mergeErr != nil {
					reportRuleRejection(&report, "reverse-projection-failed")
					report.RejectedCount++
					report.Decisions = append(report.Decisions, ReverseDecision{
						Line:     line.Line,
						Title:    title,
						Decision: ReverseDecisionRejected,
						RuleID:   "reverse-projection-failed",
						Message:  mergeErr.Error(),
					})
					continue
				}
				storedItems[existing.Index] = mergedRaw
				existingByTitle[projected.Title] = storedTiddler{
					Index: existing.Index,
					Raw:   mergedRaw,
					Shape: projected,
				}
				updatedStore = true
				report.UpdatedCount++
				report.Decisions = append(report.Decisions, ReverseDecision{
					Line:     line.Line,
					Title:    title,
					Decision: ReverseDecisionUpdated,
					RuleID:   "updated-authoritative-title",
					Message:  "base HTML contained this title with stale authoritative fields and was updated from canon",
				})
				continue
			}

			reportRuleRejection(&report, "existing-title-conflict")
			report.RejectedCount++
			report.Decisions = append(report.Decisions, ReverseDecision{
				Line:     line.Line,
				Title:    title,
				Decision: ReverseDecisionRejected,
				RuleID:   "existing-title-conflict",
				Message:  "base HTML already contains this title with different authoritative reverse fields",
			})
			continue
		}

		itemJSON, err := marshalReverseStoreTiddler(projected)
		if err != nil {
			reportRuleRejection(&report, "reverse-projection-failed")
			report.RejectedCount++
			report.Decisions = append(report.Decisions, ReverseDecision{
				Line:     line.Line,
				Title:    title,
				Decision: ReverseDecisionRejected,
				RuleID:   "reverse-projection-failed",
				Message:  err.Error(),
			})
			continue
		}

		newItems = append(newItems, itemJSON)
		report.InsertedCount++
		report.Decisions = append(report.Decisions, ReverseDecision{
			Line:     line.Line,
			Title:    title,
			Decision: ReverseDecisionInserted,
			RuleID:   "inserted-new-title",
			Message:  "projected and appended to the TiddlyWiki store",
		})
	}

	if len(report.RejectedByRule) == 0 {
		report.RejectedByRule = nil
	}
	if len(report.SkippedByRule) == 0 {
		report.SkippedByRule = nil
	}
	if len(report.ProcessedSourceTypes) == 0 {
		report.ProcessedSourceTypes = nil
	}

	if report.RejectedCount > 0 {
		return &ReverseResult{Report: report}, fmt.Errorf(
			"reverse_tiddlers: rejected %d reverse candidate(s); no HTML written",
			report.RejectedCount,
		)
	}

	if storePolicy == ReverseStorePolicyReplace {
		for title := range existingByTitle {
			if _, kept := replacedTitles[title]; !kept {
				report.BaseTiddlersDropped++
			}
		}

		updatedArray, err := marshalStoredArray(replacedItems)
		if err != nil {
			return &ReverseResult{Report: report}, fmt.Errorf("reverse_tiddlers: marshal replacement store: %w", err)
		}
		report.OutputTiddlers = len(replacedItems)

		baseHTMLString := string(baseHTML)
		outHTML := baseHTMLString[:store.ArrayStart] + updatedArray + baseHTMLString[store.ArrayEnd:]
		return &ReverseResult{
			HTML:   []byte(outHTML),
			Report: report,
		}, nil
	}

	if len(newItems) == 0 {
		if updatedStore {
			updatedArray, err := marshalStoredArray(storedItems)
			if err != nil {
				return &ReverseResult{Report: report}, fmt.Errorf("reverse_tiddlers: marshal updated store: %w", err)
			}
			report.OutputTiddlers = len(storedItems)

			baseHTMLString := string(baseHTML)
			outHTML := baseHTMLString[:store.ArrayStart] + updatedArray + baseHTMLString[store.ArrayEnd:]
			return &ReverseResult{
				HTML:   []byte(outHTML),
				Report: report,
			}, nil
		}
		report.OutputTiddlers = existingCount
		return &ReverseResult{
			HTML:   append([]byte(nil), baseHTML...),
			Report: report,
		}, nil
	}

	var updatedArray string
	if updatedStore {
		appendedItems, err := marshalStoreItems(newItems)
		if err != nil {
			return &ReverseResult{Report: report}, fmt.Errorf("reverse_tiddlers: decode inserted items: %w", err)
		}
		storedItems = append(storedItems, appendedItems...)
		updatedArray, err = marshalStoredArray(storedItems)
		if err != nil {
			return &ReverseResult{Report: report}, fmt.Errorf("reverse_tiddlers: marshal updated store: %w", err)
		}
		report.OutputTiddlers = len(storedItems)
	} else {
		updatedArray, err = appendToJSONArrayPreserveOriginal(store.ArrayRaw, newItems, existingCount)
		report.OutputTiddlers = existingCount + len(newItems)
	}
	if err != nil {
		return &ReverseResult{Report: report}, fmt.Errorf("reverse_tiddlers: append JSON items: %w", err)
	}

	baseHTMLString := string(baseHTML)
	outHTML := baseHTMLString[:store.ArrayStart] + updatedArray + baseHTMLString[store.ArrayEnd:]

	return &ReverseResult{
		HTML:   []byte(outHTML),
		Report: report,
	}, nil
}

// ReverseInsertOnlyFiles is a filesystem helper used by the CLI and tests.
// It reads the inputs, runs S43 reverse, and writes the output HTML to a new
// path without modifying the source HTML in place.
func ReverseInsertOnlyFiles(htmlPath, canonPath, outHTMLPath string) (*ReverseResult, error) {
	return reverseFilesWithMode(htmlPath, canonPath, outHTMLPath, ReverseModeInsertOnly, ReverseStorePolicyPreserve)
}

// ReverseAuthoritativeFiles runs the S44 authoritative-upsert reverse path.
func ReverseAuthoritativeFiles(htmlPath, canonPath, outHTMLPath string) (*ReverseResult, error) {
	return reverseFilesWithMode(htmlPath, canonPath, outHTMLPath, ReverseModeAuthoritativeUpsert, ReverseStorePolicyPreserve)
}

func reverseFilesWithMode(htmlPath, canonPath, outHTMLPath, mode, storePolicy string) (*ReverseResult, error) {
	baseHTML, err := os.ReadFile(htmlPath)
	if err != nil {
		return nil, fmt.Errorf("reverse_tiddlers: read html %s: %w", htmlPath, err)
	}

	canonJSONL, sourceReport, err := canon.LoadCanonSource(canonPath)
	if err != nil {
		result := &ReverseResult{
			Report: ReverseReport{
				Mode:           mode,
				StorePolicy:    storePolicy,
				HTMLInputPath:  htmlPath,
				CanonInputPath: canonPath,
				OutputHTMLPath: outHTMLPath,
				CanonSource:    sourceReport,
			},
		}
		return result, fmt.Errorf("reverse_tiddlers: load canon %s: %w", canonPath, err)
	}

	result, err := reverseHTMLWithMode(baseHTML, canonJSONL, sourceReport, mode, storePolicy)
	if result != nil {
		result.Report.HTMLInputPath = htmlPath
		result.Report.CanonInputPath = canonPath
		result.Report.OutputHTMLPath = outHTMLPath
	}
	if err != nil {
		return result, err
	}

	if err := ensureParentDir(outHTMLPath); err != nil {
		return result, fmt.Errorf("reverse_tiddlers: prepare output html %s: %w", outHTMLPath, err)
	}
	if err := os.WriteFile(outHTMLPath, result.HTML, 0o644); err != nil {
		return result, fmt.Errorf("reverse_tiddlers: write output html %s: %w", outHTMLPath, err)
	}

	return result, nil
}

// WriteReverseReport persists the reverse report as indented JSON.
func WriteReverseReport(path string, report ReverseReport) error {
	data, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		return fmt.Errorf("reverse_tiddlers: marshal report: %w", err)
	}
	data = append(data, '\n')
	if err := ensureParentDir(path); err != nil {
		return err
	}
	if err := os.WriteFile(path, data, 0o644); err != nil {
		return fmt.Errorf("reverse_tiddlers: write report %s: %w", path, err)
	}
	return nil
}

func parseReverseCanonLines(data []byte) ([]reverseCanonLine, error) {
	scanner := bufio.NewScanner(bytes.NewReader(data))
	buf := make([]byte, 0, 1024*1024)
	scanner.Buffer(buf, 64*1024*1024)

	var lines []reverseCanonLine
	lineNum := 0
	for scanner.Scan() {
		lineNum++
		raw := strings.TrimSpace(scanner.Text())
		if raw == "" {
			continue
		}

		var fields map[string]json.RawMessage
		if err := json.Unmarshal([]byte(raw), &fields); err != nil {
			return nil, fmt.Errorf("line %d: %w", lineNum, err)
		}

		var entry canon.CanonEntry
		if err := json.Unmarshal([]byte(raw), &entry); err != nil {
			return nil, fmt.Errorf("line %d: %w", lineNum, err)
		}

		lines = append(lines, reverseCanonLine{
			Line:   lineNum,
			Entry:  entry,
			Fields: fields,
		})
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	return lines, nil
}

func locateSingleTiddlerStore(html string) (reverseStoreBlock, error) {
	matches := tiddlerStoreRe.FindAllStringSubmatchIndex(html, -1)
	store := reverseStoreBlock{BlocksFound: len(matches)}

	switch len(matches) {
	case 0:
		return store, fmt.Errorf("reverse_tiddlers: no tiddlywiki-tiddler-store block found")
	case 1:
		match := matches[0]
		store.ArrayStart = match[2]
		store.ArrayEnd = match[3]
		store.ArrayRaw = html[store.ArrayStart:store.ArrayEnd]
		return store, nil
	default:
		return store, fmt.Errorf(
			"reverse_tiddlers: found %d tiddler-store blocks; S43 insert-only reverse requires exactly 1",
			len(matches),
		)
	}
}

func parseStoredTiddlers(arrayRaw string) ([]map[string]interface{}, map[string]storedTiddler, int, error) {
	var rawItems []map[string]interface{}
	if err := json.Unmarshal([]byte(arrayRaw), &rawItems); err != nil {
		return nil, nil, 0, err
	}

	byTitle := make(map[string]storedTiddler, len(rawItems))
	for idx, raw := range rawItems {
		shape, err := reverseShapeFromStoredMap(raw)
		if err != nil {
			return nil, nil, 0, fmt.Errorf("tiddler[%d]: %w", idx, err)
		}
		if _, duplicated := byTitle[shape.Title]; duplicated {
			return nil, nil, 0, fmt.Errorf("title %q appears more than once in the base HTML store", shape.Title)
		}
		byTitle[shape.Title] = storedTiddler{
			Index: idx,
			Raw:   raw,
			Shape: shape,
		}
	}

	return rawItems, byTitle, len(rawItems), nil
}

func seedStructuralStoreForReplace(items []map[string]interface{}) ([]map[string]interface{}, map[string]struct{}) {
	seeded := make([]map[string]interface{}, 0, len(items))
	titles := make(map[string]struct{}, len(items))

	for _, item := range items {
		title, ok := item["title"].(string)
		if !ok || !strings.HasPrefix(title, "$:/") {
			continue
		}
		seeded = append(seeded, cloneStoredItem(item))
		titles[title] = struct{}{}
	}

	return seeded, titles
}

func cloneStoredItem(source map[string]interface{}) map[string]interface{} {
	cloned := make(map[string]interface{}, len(source))
	for key, value := range source {
		cloned[key] = value
	}
	return cloned
}

func reverseShapeFromStoredMap(raw map[string]interface{}) (reverseShape, error) {
	title, ok := optionalStoredString(raw, "title")
	if !ok || title == nil || *title == "" {
		return reverseShape{}, fmt.Errorf("missing non-empty title in stored tiddler")
	}

	shape := reverseShape{Title: *title}
	if text, ok := optionalStoredString(raw, "text"); ok {
		shape.Text = cloneNonNilString(text)
	}
	if created, ok := optionalStoredString(raw, "created"); ok {
		shape.Created = normalizeOptionalField(created)
	}
	if modified, ok := optionalStoredString(raw, "modified"); ok {
		shape.Modified = normalizeOptionalField(modified)
	}
	if sourceType, ok := optionalStoredString(raw, "type"); ok {
		shape.SourceType = normalizeOptionalField(sourceType)
	}
	if tags, ok := optionalStoredString(raw, "tags"); ok && tags != nil && strings.TrimSpace(*tags) != "" {
		parsed, err := ingesta.ParseTW5Tags(*tags)
		if err != nil {
			return reverseShape{}, fmt.Errorf("stored tiddler %q has malformed tags: %w", shape.Title, err)
		}
		shape.SourceTags = append(shape.SourceTags, parsed...)
	}

	for field := range raw {
		switch field {
		case "title", "text", "created", "modified", "type", "tags":
			continue
		}

		value, ok := optionalStoredString(raw, field)
		if !ok {
			continue
		}
		if shape.ExtraFields == nil {
			shape.ExtraFields = make(map[string]string)
		}
		if value == nil {
			shape.ExtraFields[field] = ""
			continue
		}
		shape.ExtraFields[field] = *value
	}

	return shape, nil
}

func isReverseEligibleLine(fields map[string]json.RawMessage) bool {
	if len(fields) == 0 {
		return false
	}
	if isLegacyRawReverseCandidate(fields) {
		return true
	}
	return isFullCanonicalReverseRecord(fields)
}

func isLegacyRawReverseCandidate(fields map[string]json.RawMessage) bool {
	for field := range fields {
		if _, ok := allowedRawReverseTopLevelFields[field]; !ok {
			return false
		}
	}
	return true
}

func isFullCanonicalReverseRecord(fields map[string]json.RawMessage) bool {
	for field := range fields {
		switch field {
		case "id",
			"canonical_slug",
			"version_id",
			"content_type",
			"modality",
			"encoding",
			"is_binary",
			"is_reference_only",
			"role_primary",
			"roles_secondary",
			"tags",
			"taxonomy_path",
			"semantic_text",
			"content",
			"normalized_tags",
			"raw_payload_ref",
			"asset_id",
			"mime_type",
			"document_id",
			"section_path",
			"order_in_document",
			"relations":
			return true
		}
	}
	return false
}

func projectReverseShape(entry canon.CanonEntry) (reverseShape, []reverseIssue) {
	extraFields, issues := validateReverseInsertable(entry)
	if len(issues) > 0 {
		return reverseShape{}, issues
	}

	return reverseShape{
		Title:       entry.Title,
		Text:        cloneNonNilString(entry.Text),
		Created:     normalizeOptionalField(entry.Created),
		Modified:    normalizeOptionalField(entry.Modified),
		SourceType:  normalizeTrimmedOptionalField(entry.SourceType),
		SourceTags:  cloneStringSlice(entry.SourceTags),
		ExtraFields: extraFields,
	}, nil
}

func validateReverseInsertable(entry canon.CanonEntry) (map[string]string, []reverseIssue) {
	var issues []reverseIssue

	addIssue := func(ruleID, message string) {
		issues = append(issues, reverseIssue{
			RuleID:  ruleID,
			Message: message,
		})
	}

	if entry.Key != "" && entry.Title != "" && string(entry.Key) != entry.Title {
		addIssue("key-title-mismatch", "key must be identical to title under the canonical identity rule")
	}
	for i, tag := range entry.SourceTags {
		if tag == "" || strings.TrimSpace(tag) == "" || strings.TrimSpace(tag) != tag {
			addIssue("invalid-source-tags", fmt.Sprintf("source_tags[%d] must be a non-empty trimmed string", i))
		}
	}

	extraFields, fieldIssues := validateReverseSourceFields(entry)
	issues = append(issues, fieldIssues...)
	return extraFields, issues
}

func validateReverseSourceFields(entry canon.CanonEntry) (map[string]string, []reverseIssue) {
	if len(entry.SourceFields) == 0 {
		return nil, nil
	}

	extraFields := make(map[string]string, len(entry.SourceFields))
	var issues []reverseIssue

	for key, value := range entry.SourceFields {
		trimmedKey := strings.TrimSpace(key)
		switch {
		case trimmedKey == "":
			issues = append(issues, reverseIssue{
				RuleID:  "invalid-source-fields-key",
				Message: "source_fields contains an empty field name",
			})
			continue
		case trimmedKey != key:
			issues = append(issues, reverseIssue{
				RuleID:  "invalid-source-fields-key",
				Message: fmt.Sprintf("source_fields field %q must not carry leading or trailing whitespace", key),
			})
			continue
		}

		if _, reserved := reservedReverseSourceFields[trimmedKey]; reserved {
			if reservedValueConflicts(entry, trimmedKey, value) {
				issues = append(issues, reverseIssue{
					RuleID:  "source-fields-reserved-conflict",
					Message: fmt.Sprintf("source_fields reserved field %q conflicts with authoritative reverse fields", trimmedKey),
				})
			}
			continue
		}
		if _, derived := derivedReverseSourceFields[trimmedKey]; derived {
			issues = append(issues, reverseIssue{
				RuleID:  "source-fields-derived-key",
				Message: fmt.Sprintf("source_fields must not project derived field %q as authoritative tiddler data", trimmedKey),
			})
			continue
		}

		extraFields[trimmedKey] = value
	}

	if len(extraFields) == 0 {
		return nil, issues
	}
	return extraFields, issues
}

func classifyReverseScopeSkip(entry canon.CanonEntry) (string, string, bool) {
	switch {
	case entry.Title != "" && strings.HasPrefix(entry.Title, "$:/"):
		return "out-of-scope-system-title", "system tiddlers stay preserved from the base HTML and are not re-materialized from canon", true
	case entry.IsBinary:
		return "out-of-scope-binary-node", "binary nodes remain outside the S44 textual/metadata reverse scope", true
	case entry.IsReferenceOnly:
		return "out-of-scope-reference-node", "reference-only nodes remain outside the S44 textual/metadata reverse scope", true
	case entry.SourceType != nil && !isSupportedReverseSourceType(*entry.SourceType):
		return "out-of-scope-source-type", fmt.Sprintf("source_type %q is outside the S44 textual/metadata reverse scope", strings.TrimSpace(*entry.SourceType)), true
	default:
		return "", "", false
	}
}

func buildRejectedReverseDecision(line int, title string, issues []reverseIssue) ReverseDecision {
	if len(issues) == 1 {
		return ReverseDecision{
			Line:     line,
			Title:    title,
			Decision: ReverseDecisionRejected,
			RuleID:   issues[0].RuleID,
			Message:  issues[0].Message,
		}
	}

	ruleIDs := make([]string, 0, len(issues))
	messages := make([]string, 0, len(issues))
	for _, issue := range issues {
		ruleIDs = append(ruleIDs, issue.RuleID)
		messages = append(messages, issue.Message)
	}

	return ReverseDecision{
		Line:     line,
		Title:    title,
		Decision: ReverseDecisionRejected,
		RuleID:   "multiple-reverse-issues",
		Message:  fmt.Sprintf("%s (%s)", strings.Join(messages, "; "), strings.Join(ruleIDs, ",")),
	}
}

func reportRuleRejection(report *ReverseReport, ruleID string) {
	if report.RejectedByRule == nil {
		report.RejectedByRule = make(map[string]int)
	}
	report.RejectedByRule[ruleID]++
}

func reportSkipRule(report *ReverseReport, ruleID string) {
	if report.SkippedByRule == nil {
		report.SkippedByRule = make(map[string]int)
	}
	report.SkippedByRule[ruleID]++
}

func isSupportedReverseSourceType(sourceType string) bool {
	label := strings.ToLower(strings.TrimSpace(sourceType))
	if label == "" {
		return true
	}
	_, ok := supportedReverseSourceTypes[label]
	return ok
}

func normalizedReverseSourceTypeLabel(sourceType *string) string {
	if sourceType == nil {
		return "unspecified"
	}
	trimmed := strings.TrimSpace(*sourceType)
	if trimmed == "" {
		return "unspecified"
	}
	return strings.ToLower(trimmed)
}

func reverseShapesEquivalent(existing, projected reverseShape) bool {
	if existing.Title != projected.Title {
		return false
	}
	if normalizedBody(existing.Text) != normalizedBody(projected.Text) {
		return false
	}
	if normalizedOptionalValue(existing.Created) != normalizedOptionalValue(projected.Created) {
		return false
	}
	if normalizedOptionalValue(existing.Modified) != normalizedOptionalValue(projected.Modified) {
		return false
	}
	if normalizedOptionalValue(existing.SourceType) != normalizedOptionalValue(projected.SourceType) {
		return false
	}
	if !slices.Equal(existing.SourceTags, projected.SourceTags) {
		return false
	}

	for key, projectedValue := range projected.ExtraFields {
		existingValue, ok := existing.ExtraFields[key]
		if !ok || existingValue != projectedValue {
			return false
		}
	}

	return true
}

func marshalReverseStoreTiddler(shape reverseShape) (string, error) {
	item := make(map[string]string, 6+len(shape.ExtraFields))
	item["title"] = shape.Title

	if shape.Text != nil {
		item["text"] = *shape.Text
	}
	if shape.Created != nil {
		item["created"] = *shape.Created
	}
	if shape.Modified != nil {
		item["modified"] = *shape.Modified
	}
	if shape.SourceType != nil {
		item["type"] = *shape.SourceType
	}
	if len(shape.SourceTags) > 0 {
		tags, err := formatTW5Tags(shape.SourceTags)
		if err != nil {
			return "", fmt.Errorf("format tags for %q: %w", shape.Title, err)
		}
		if tags != "" {
			item["tags"] = tags
		}
	}
	for key, value := range shape.ExtraFields {
		item[key] = value
	}

	data, err := json.Marshal(item)
	if err != nil {
		return "", err
	}
	return string(data), nil
}

func marshalReverseStoreTiddlerMap(shape reverseShape) (map[string]interface{}, error) {
	itemJSON, err := marshalReverseStoreTiddler(shape)
	if err != nil {
		return nil, err
	}

	var raw map[string]interface{}
	if err := json.Unmarshal([]byte(itemJSON), &raw); err != nil {
		return nil, err
	}
	return raw, nil
}

func marshalStoreItems(items []string) ([]map[string]interface{}, error) {
	decoded := make([]map[string]interface{}, 0, len(items))
	for _, item := range items {
		var raw map[string]interface{}
		if err := json.Unmarshal([]byte(item), &raw); err != nil {
			return nil, err
		}
		decoded = append(decoded, raw)
	}
	return decoded, nil
}

func marshalStoredArray(items []map[string]interface{}) (string, error) {
	data, err := json.Marshal(items)
	if err != nil {
		return "", err
	}
	return string(data), nil
}

func mergeStoredTiddler(existing map[string]interface{}, projected reverseShape) (map[string]interface{}, error) {
	merged := make(map[string]interface{}, len(existing)+len(projected.ExtraFields)+6)
	for key, value := range existing {
		merged[key] = value
	}

	merged["title"] = projected.Title
	applyProjectedStoredField(merged, "text", projected.Text)
	applyProjectedStoredField(merged, "created", projected.Created)
	applyProjectedStoredField(merged, "modified", projected.Modified)
	applyProjectedStoredField(merged, "type", projected.SourceType)

	if len(projected.SourceTags) > 0 {
		tags, err := formatTW5Tags(projected.SourceTags)
		if err != nil {
			return nil, fmt.Errorf("format tags for %q: %w", projected.Title, err)
		}
		merged["tags"] = tags
	} else {
		delete(merged, "tags")
	}

	for key, value := range projected.ExtraFields {
		merged[key] = value
	}

	return merged, nil
}

func ensureParentDir(path string) error {
	dir := filepath.Dir(path)
	if dir == "." || dir == "" {
		return nil
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("reverse_tiddlers: create parent dir %s: %w", dir, err)
	}
	return nil
}

func formatTW5Tags(tags []string) (string, error) {
	if len(tags) == 0 {
		return "", nil
	}

	formatted := make([]string, 0, len(tags))
	for i, tag := range tags {
		if tag == "" || strings.TrimSpace(tag) == "" || strings.TrimSpace(tag) != tag {
			return "", fmt.Errorf("tag[%d] must be a non-empty trimmed string", i)
		}

		if strings.ContainsAny(tag, " []") {
			formatted = append(formatted, "[["+tag+"]]")
			continue
		}
		formatted = append(formatted, tag)
	}

	return strings.Join(formatted, " "), nil
}

func appendToJSONArrayPreserveOriginal(original string, newItems []string, existingCount int) (string, error) {
	if len(newItems) == 0 {
		return original, nil
	}
	if existingCount == 0 {
		if strings.Contains(original, "\n") {
			return "[\n" + strings.Join(newItems, ",\n") + "\n]", nil
		}
		return "[" + strings.Join(newItems, ",") + "]", nil
	}

	end := strings.LastIndex(original, "]")
	if end == -1 {
		return "", fmt.Errorf("array terminator not found")
	}

	beforeBracket := original[:end]
	afterBracket := original[end:]
	trimmedBefore := strings.TrimRight(beforeBracket, " \t\r\n")
	trailingWhitespace := beforeBracket[len(trimmedBefore):]

	return trimmedBefore + ",\n" + strings.Join(newItems, ",\n") + trailingWhitespace + afterBracket, nil
}

func optionalStoredString(raw map[string]interface{}, field string) (*string, bool) {
	value, ok := raw[field]
	if !ok {
		return nil, false
	}
	if value == nil {
		return nil, true
	}
	switch typed := value.(type) {
	case string:
		return &typed, true
	default:
		s := fmt.Sprintf("%v", typed)
		return &s, true
	}
}

func applyProjectedStoredField(raw map[string]interface{}, field string, value *string) {
	if value == nil {
		delete(raw, field)
		return
	}
	raw[field] = *value
}

func cloneNonNilString(value *string) *string {
	if value == nil {
		return nil
	}
	cloned := *value
	return &cloned
}

func normalizeOptionalField(value *string) *string {
	if value == nil {
		return nil
	}
	if *value == "" {
		return nil
	}
	cloned := *value
	return &cloned
}

func normalizeTrimmedOptionalField(value *string) *string {
	if value == nil {
		return nil
	}
	trimmed := strings.TrimSpace(*value)
	if trimmed == "" {
		return nil
	}
	return &trimmed
}

func normalizedOptionalValue(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}

func normalizedBody(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}

func cloneStringSlice(values []string) []string {
	if len(values) == 0 {
		return nil
	}
	cloned := make([]string, len(values))
	copy(cloned, values)
	return cloned
}

func reservedValueConflicts(entry canon.CanonEntry, key, value string) bool {
	switch key {
	case "schema_version":
		return value != canon.SchemaV0
	case "key":
		return value != string(entry.Key)
	case "title":
		return value != entry.Title
	case "text":
		return value != normalizedBody(entry.Text)
	case "type", "source_type":
		return value != normalizedOptionalValue(normalizeTrimmedOptionalField(entry.SourceType))
	case "created":
		return value != normalizedOptionalValue(entry.Created)
	case "modified":
		return value != normalizedOptionalValue(entry.Modified)
	case "tags":
		formatted, err := formatTW5Tags(entry.SourceTags)
		if err != nil {
			return true
		}
		return value != formatted
	case "source_fields", "source_tags", "source_position", "source_role":
		return value != ""
	default:
		return value != ""
	}
}
