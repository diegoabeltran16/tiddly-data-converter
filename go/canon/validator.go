// Package canon — validator.go
//
// # S39 — canon-executable-policy-and-reverse-readiness-v0
//
// Validates a candidate canonical JSONL file or individual canon lines
// against the executable policy. Supports strict mode (reject on any
// inconsistency) and reports detailed diagnostics.
//
// The validator does NOT modify the input. For correction, use the
// normalizer (normalizer.go).
//
// Ref: S39 §10.2 — validator.
// Ref: S39 §13 — invariants.
package canon

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"reflect"
	"strings"
)

// ValidationIssue describes a single problem found during validation.
type ValidationIssue struct {
	Line     int    `json:"line"`
	Field    string `json:"field,omitempty"`
	RuleID   string `json:"rule_id"`
	Message  string `json:"message"`
	Severity string `json:"severity"` // "error" or "warning"
}

// ValidationReport holds the result of validating a canon JSONL file.
type ValidationReport struct {
	LinesRead  int               `json:"lines_read"`
	LinesValid int               `json:"lines_valid"`
	Issues     []ValidationIssue `json:"issues,omitempty"`
}

// OK returns true if there are no error-level issues.
func (r ValidationReport) OK() bool {
	for _, issue := range r.Issues {
		if issue.Severity == "error" {
			return false
		}
	}
	return true
}

// ErrorCount returns the number of error-level issues.
func (r ValidationReport) ErrorCount() int {
	count := 0
	for _, issue := range r.Issues {
		if issue.Severity == "error" {
			count++
		}
	}
	return count
}

// ValidateCanonJSONL reads a JSONL stream and validates each line in strict mode.
//
// Strict mode:
//   - Validates required fields are present and non-empty.
//   - Rejects unknown top-level fields.
//   - Checks that derived fields (id, canonical_slug, version_id) match recomputation.
//   - Checks semantic_text redundancy per S38 policy.
//   - Does NOT correct anything.
//
// Ref: S39 §12.3 — strict mode behavior.
func ValidateCanonJSONL(r io.Reader, policy CanonPolicy) ValidationReport {
	report := ValidationReport{}
	scanner := bufio.NewScanner(r)

	// Increase buffer for large lines.
	buf := make([]byte, 0, 1024*1024)
	scanner.Buffer(buf, 64*1024*1024)

	lineNum := 0
	for scanner.Scan() {
		lineNum++
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		report.LinesRead++

		issues := validateLine(lineNum, []byte(line), policy)
		if len(issues) == 0 {
			report.LinesValid++
		}
		report.Issues = append(report.Issues, issues...)
	}
	if err := scanner.Err(); err != nil {
		report.Issues = append(report.Issues, ValidationIssue{
			Line:     lineNum + 1,
			RuleID:   "read-error",
			Message:  fmt.Sprintf("cannot continue scanning canon JSONL: %v", err),
			Severity: "error",
		})
	}
	return report
}

// validateLine validates a single JSONL line against the policy.
func validateLine(lineNum int, data []byte, policy CanonPolicy) []ValidationIssue {
	var issues []ValidationIssue

	// Parse as generic map to check field names.
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		issues = append(issues, ValidationIssue{
			Line:     lineNum,
			RuleID:   "invalid-json",
			Message:  fmt.Sprintf("invalid JSON: %v", err),
			Severity: "error",
		})
		return issues
	}

	// Check unknown top-level fields.
	for field := range raw {
		if !policy.IsAllowedField(field) {
			issues = append(issues, ValidationIssue{
				Line:     lineNum,
				Field:    field,
				RuleID:   "unknown-top-level-field",
				Message:  fmt.Sprintf("field %q is not in the allowed top-level fields", field),
				Severity: "error",
			})
		}
	}

	// Parse as CanonEntry for structured validation.
	var entry CanonEntry
	if err := json.Unmarshal(data, &entry); err != nil {
		issues = append(issues, ValidationIssue{
			Line:     lineNum,
			RuleID:   "parse-error",
			Message:  fmt.Sprintf("cannot parse as CanonEntry: %v", err),
			Severity: "error",
		})
		return issues
	}

	// Check required fields.
	if entry.SchemaVersion == "" {
		issues = append(issues, ValidationIssue{
			Line:     lineNum,
			Field:    "schema_version",
			RuleID:   "missing-required-field",
			Message:  "schema_version is empty",
			Severity: "error",
		})
	} else if entry.SchemaVersion != SchemaV0 {
		issues = append(issues, ValidationIssue{
			Line:     lineNum,
			Field:    "schema_version",
			RuleID:   "wrong-schema-version",
			Message:  fmt.Sprintf("schema_version is %q, expected %q", entry.SchemaVersion, SchemaV0),
			Severity: "error",
		})
	}
	if entry.Key == "" {
		issues = append(issues, ValidationIssue{
			Line:     lineNum,
			Field:    "key",
			RuleID:   "missing-required-field",
			Message:  "key is empty",
			Severity: "error",
		})
	}
	if entry.Title == "" {
		issues = append(issues, ValidationIssue{
			Line:     lineNum,
			Field:    "title",
			RuleID:   "missing-required-field",
			Message:  "title is empty",
			Severity: "error",
		})
	}

	// Check derived field consistency (only if present and title/key available).
	if entry.Title != "" && entry.Key != "" {
		// Check id consistency.
		if entry.ID != "" {
			expectedID, err := ComputeNodeUUID(string(entry.Key))
			if err == nil && entry.ID != expectedID {
				issues = append(issues, ValidationIssue{
					Line:     lineNum,
					Field:    "id",
					RuleID:   "inconsistent-derived-id",
					Message:  fmt.Sprintf("id %q does not match recomputed %q", entry.ID, expectedID),
					Severity: "error",
				})
			}
		}

		// Check canonical_slug consistency.
		if entry.CanonicalSlug != "" {
			expectedSlug := CanonicalSlugOf(entry.Title)
			if entry.CanonicalSlug != expectedSlug {
				issues = append(issues, ValidationIssue{
					Line:     lineNum,
					Field:    "canonical_slug",
					RuleID:   "inconsistent-derived-slug",
					Message:  fmt.Sprintf("canonical_slug %q does not match recomputed %q", entry.CanonicalSlug, expectedSlug),
					Severity: "error",
				})
			}
		}

		// Check version_id consistency.
		if entry.VersionID != "" {
			expectedVID, err := ComputeVersionID(entry)
			if err == nil && entry.VersionID != expectedVID {
				issues = append(issues, ValidationIssue{
					Line:     lineNum,
					Field:    "version_id",
					RuleID:   "inconsistent-derived-version-id",
					Message:  fmt.Sprintf("version_id %q does not match recomputed %q", entry.VersionID, expectedVID),
					Severity: "error",
				})
			}
		}
	}

	// Check semantic_text redundancy per S38.
	if entry.SemanticText != nil && entry.Text != nil && *entry.SemanticText == *entry.Text {
		issues = append(issues, ValidationIssue{
			Line:     lineNum,
			Field:    "semantic_text",
			RuleID:   "semantic-text-redundant",
			Message:  "semantic_text equals text; should be null per S38 policy",
			Severity: "warning",
		})
	}

	expectedPlain := DeriveContentPlain(entry)
	actualPlain := ""
	hasActualPlain := entry.Content != nil && entry.Content.Plain != nil
	if hasActualPlain {
		actualPlain = *entry.Content.Plain
	}
	expectedPlainValue := ""
	hasExpectedPlain := expectedPlain != nil
	if hasExpectedPlain {
		expectedPlainValue = *expectedPlain
	}
	if hasActualPlain && (!hasExpectedPlain || actualPlain != expectedPlainValue) {
		issues = append(issues, ValidationIssue{
			Line:     lineNum,
			Field:    "content",
			RuleID:   "inconsistent-derived-content-plain",
			Message:  fmt.Sprintf("content.plain does not match deterministic recomputation (got %q, expected %q)", actualPlain, expectedPlainValue),
			Severity: "error",
		})
	}

	expectedNormalizedTags := DeriveNormalizedTags(entry)
	if len(entry.NormalizedTags) > 0 && !reflect.DeepEqual(entry.NormalizedTags, expectedNormalizedTags) {
		issues = append(issues, ValidationIssue{
			Line:     lineNum,
			Field:    "normalized_tags",
			RuleID:   "inconsistent-derived-normalized-tags",
			Message:  fmt.Sprintf("normalized_tags do not match deterministic recomputation (got %v, expected %v)", entry.NormalizedTags, expectedNormalizedTags),
			Severity: "error",
		})
	}

	return issues
}
