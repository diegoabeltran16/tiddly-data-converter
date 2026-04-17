package bridge

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"slices"
	"strings"

	"github.com/tiddly-data-converter/canon"
	"github.com/tiddly-data-converter/ingesta"
)

const (
	ReverseModeInsertOnly = "insert-only"

	ReverseDecisionInserted       = "inserted"
	ReverseDecisionAlreadyPresent = "already_present"
	ReverseDecisionExcluded       = "excluded"
	ReverseDecisionRejected       = "rejected"
)

// ReverseDecision records the disposition taken for a canon line during S42
// reverse insert-only processing.
type ReverseDecision struct {
	Line     int    `json:"line"`
	Title    string `json:"title,omitempty"`
	Decision string `json:"decision"`
	RuleID   string `json:"rule_id,omitempty"`
	Message  string `json:"message,omitempty"`
}

// ReverseReport exposes deterministic evidence for one reverse run.
type ReverseReport struct {
	Mode                string                       `json:"mode"`
	StoreBlocksFound    int                          `json:"store_blocks_found"`
	ExistingTiddlers    int                          `json:"existing_tiddlers"`
	CanonLinesRead      int                          `json:"canon_lines_read"`
	InsertedCount       int                          `json:"inserted_count"`
	AlreadyPresentCount int                          `json:"already_present_count"`
	ExcludedCount       int                          `json:"excluded_count"`
	RejectedCount       int                          `json:"rejected_count"`
	Decisions           []ReverseDecision            `json:"decisions,omitempty"`
	ValidationReport    canon.ValidationReport       `json:"validation_report"`
	ReversePreflight    canon.ReversePreflightReport `json:"reverse_preflight"`
}

// OK reports whether the reverse run completed without entry-level rejections
// and with both canon prechecks satisfied.
func (r ReverseReport) OK() bool {
	return r.RejectedCount == 0 &&
		r.ValidationReport.OK() &&
		r.ReversePreflight.OK()
}

// ReverseResult contains the generated HTML plus its report.
type ReverseResult struct {
	HTML   []byte        `json:"-"`
	Report ReverseReport `json:"report"`
}

type reverseCanonLine struct {
	Line  int
	Entry canon.CanonEntry
}

type reverseStoreBlock struct {
	ArrayStart  int
	ArrayEnd    int
	ArrayRaw    string
	BlocksFound int
}

type reverseShape struct {
	Title      string
	Text       *string
	Created    *string
	Modified   *string
	SourceType *string
	SourceTags []string
}

type storedTiddler struct {
	Shape reverseShape
}

type reverseIssue struct {
	RuleID  string
	Message string
	Fatal   bool
}

// ReverseInsertOnlyHTML executes the S42 reverse path:
// canon JSONL -> controlled insert-only merge -> re-openable TiddlyWiki HTML.
//
// The function never mutates the input HTML. It returns an HTML byte slice for
// the caller to persist explicitly to a separate file.
func ReverseInsertOnlyHTML(baseHTML, canonJSONL []byte) (*ReverseResult, error) {
	report := ReverseReport{Mode: ReverseModeInsertOnly}

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

	existingByTitle, existingCount, err := parseStoredTiddlers(store.ArrayRaw)
	report.ExistingTiddlers = existingCount
	if err != nil {
		return &ReverseResult{Report: report}, fmt.Errorf("reverse_tiddlers: parse base HTML store: %w", err)
	}

	seenCanonTitles := make(map[string]int, len(lines))
	newItems := make([]string, 0, len(lines))

	for _, line := range lines {
		entry := line.Entry
		title := entry.Title

		if prevLine, duplicated := seenCanonTitles[title]; duplicated {
			report.RejectedCount++
			report.Decisions = append(report.Decisions, ReverseDecision{
				Line:     line.Line,
				Title:    title,
				Decision: ReverseDecisionRejected,
				RuleID:   "batch-duplicate-title",
				Message:  fmt.Sprintf("canon title duplicates line %d; insert-only reverse requires unique titles", prevLine),
			})
			continue
		}
		seenCanonTitles[title] = line.Line

		issues := validateReverseInsertable(entry)
		if len(issues) > 0 {
			if reverseIssuesContainFatal(issues) {
				report.RejectedCount++
				report.Decisions = append(report.Decisions, buildRejectedReverseDecision(line.Line, title, issues))
			} else {
				report.ExcludedCount++
				report.Decisions = append(report.Decisions, buildExcludedReverseDecision(line.Line, title, issues))
			}
			continue
		}

		projected := reverseShapeFromCanonEntry(entry)
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

	if report.RejectedCount > 0 {
		return &ReverseResult{Report: report}, fmt.Errorf(
			"reverse_tiddlers: rejected %d canon line(s); no HTML written",
			report.RejectedCount,
		)
	}

	if len(newItems) == 0 {
		return &ReverseResult{
			HTML:   append([]byte(nil), baseHTML...),
			Report: report,
		}, nil
	}

	updatedArray, err := appendToJSONArrayPreserveOriginal(store.ArrayRaw, newItems, existingCount)
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
// It reads the inputs, runs S42 reverse, and writes the output HTML to a new
// path without modifying the source HTML in place.
func ReverseInsertOnlyFiles(htmlPath, canonPath, outHTMLPath string) (*ReverseResult, error) {
	baseHTML, err := os.ReadFile(htmlPath)
	if err != nil {
		return nil, fmt.Errorf("reverse_tiddlers: read html %s: %w", htmlPath, err)
	}

	canonJSONL, err := os.ReadFile(canonPath)
	if err != nil {
		return nil, fmt.Errorf("reverse_tiddlers: read canon %s: %w", canonPath, err)
	}

	result, err := ReverseInsertOnlyHTML(baseHTML, canonJSONL)
	if err != nil {
		return result, err
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
	if err := os.WriteFile(path, data, 0o644); err != nil {
		return fmt.Errorf("reverse_tiddlers: write report %s: %w", path, err)
	}
	return nil
}

func parseReverseCanonLines(data []byte) ([]reverseCanonLine, error) {
	scanner := bufio.NewScanner(bytes.NewReader(data))
	buf := make([]byte, 0, 1024*1024)
	scanner.Buffer(buf, 10*1024*1024)

	var lines []reverseCanonLine
	lineNum := 0
	for scanner.Scan() {
		lineNum++
		raw := strings.TrimSpace(scanner.Text())
		if raw == "" {
			continue
		}

		var entry canon.CanonEntry
		if err := json.Unmarshal([]byte(raw), &entry); err != nil {
			return nil, fmt.Errorf("line %d: %w", lineNum, err)
		}
		lines = append(lines, reverseCanonLine{
			Line:  lineNum,
			Entry: entry,
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
			"reverse_tiddlers: found %d tiddler-store blocks; S42 insert-only reverse requires exactly 1",
			len(matches),
		)
	}
}

func parseStoredTiddlers(arrayRaw string) (map[string]storedTiddler, int, error) {
	var rawItems []map[string]interface{}
	if err := json.Unmarshal([]byte(arrayRaw), &rawItems); err != nil {
		return nil, 0, err
	}

	byTitle := make(map[string]storedTiddler, len(rawItems))
	for idx, raw := range rawItems {
		shape, err := reverseShapeFromStoredMap(raw)
		if err != nil {
			return nil, 0, fmt.Errorf("tiddler[%d]: %w", idx, err)
		}
		if _, duplicated := byTitle[shape.Title]; duplicated {
			return nil, 0, fmt.Errorf("title %q appears more than once in the base HTML store", shape.Title)
		}
		byTitle[shape.Title] = storedTiddler{Shape: shape}
	}

	return byTitle, len(rawItems), nil
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

	return shape, nil
}

func validateReverseInsertable(entry canon.CanonEntry) []reverseIssue {
	var issues []reverseIssue

	addIssue := func(ruleID, message string) {
		issues = append(issues, reverseIssue{
			RuleID:  ruleID,
			Message: message,
			Fatal:   true,
		})
	}
	addExclusion := func(ruleID, message string) {
		issues = append(issues, reverseIssue{
			RuleID:  ruleID,
			Message: message,
			Fatal:   false,
		})
	}

	if entry.Title != "" && strings.HasPrefix(entry.Title, "$:/") {
		addExclusion("unsupported-system-title", "system tiddlers are outside the S42 insert-only reverse scope")
	}
	if entry.Key != "" && entry.Title != "" && string(entry.Key) != entry.Title {
		addIssue("key-title-mismatch", "key must be identical to title under the canonical identity rule")
	}
	if entry.IsBinary {
		addExclusion("unsupported-binary-node", "binary nodes are outside the S42 minimal reverse scope")
	}
	if entry.IsReferenceOnly {
		addExclusion("unsupported-reference-node", "reference-only nodes are outside the S42 minimal reverse scope")
	}
	if entry.SourceType != nil && !isSupportedReverseSourceType(*entry.SourceType) {
		addExclusion(
			"unsupported-source-type",
			fmt.Sprintf("source_type %q is outside the S42 minimal textual reverse scope", *entry.SourceType),
		)
	}
	for i, tag := range entry.SourceTags {
		if strings.TrimSpace(tag) == "" {
			addIssue("invalid-source-tags", fmt.Sprintf("source_tags[%d] is empty after trimming", i))
		}
	}

	return issues
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

func buildExcludedReverseDecision(line int, title string, issues []reverseIssue) ReverseDecision {
	if len(issues) == 1 {
		return ReverseDecision{
			Line:     line,
			Title:    title,
			Decision: ReverseDecisionExcluded,
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
		Decision: ReverseDecisionExcluded,
		RuleID:   "multiple-reverse-exclusions",
		Message:  fmt.Sprintf("%s (%s)", strings.Join(messages, "; "), strings.Join(ruleIDs, ",")),
	}
}

func reverseIssuesContainFatal(issues []reverseIssue) bool {
	for _, issue := range issues {
		if issue.Fatal {
			return true
		}
	}
	return false
}

func isSupportedReverseSourceType(sourceType string) bool {
	st := strings.TrimSpace(strings.ToLower(sourceType))
	if st == "" {
		return true
	}
	if strings.HasPrefix(st, "text/") {
		return true
	}

	switch st {
	case "application/json",
		"application/javascript",
		"application/x-tiddler-dictionary",
		"application/xml":
		return true
	default:
		return false
	}
}

func reverseShapeFromCanonEntry(entry canon.CanonEntry) reverseShape {
	return reverseShape{
		Title:      entry.Title,
		Text:       cloneNonNilString(entry.Text),
		Created:    normalizeOptionalField(entry.Created),
		Modified:   normalizeOptionalField(entry.Modified),
		SourceType: normalizeOptionalField(entry.SourceType),
		SourceTags: cloneStringSlice(entry.SourceTags),
	}
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
	return slices.Equal(existing.SourceTags, projected.SourceTags)
}

func marshalReverseStoreTiddler(shape reverseShape) (string, error) {
	item := make(map[string]string, 6)
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

	data, err := json.Marshal(item)
	if err != nil {
		return "", err
	}
	return string(data), nil
}

func formatTW5Tags(tags []string) (string, error) {
	if len(tags) == 0 {
		return "", nil
	}

	formatted := make([]string, 0, len(tags))
	for i, tag := range tags {
		value := strings.TrimSpace(tag)
		if value == "" {
			return "", fmt.Errorf("tag[%d] is empty after trimming", i)
		}

		if strings.ContainsAny(value, " []") {
			formatted = append(formatted, "[["+value+"]]")
			continue
		}
		formatted = append(formatted, value)
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
