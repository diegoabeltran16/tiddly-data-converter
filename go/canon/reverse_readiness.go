// Package canon — reverse_readiness.go
//
// # S39 — canon-executable-policy-and-reverse-readiness-v0
//
// Checks whether a canonical JSONL file is ready for reverse
// (reconstruction to TiddlyWiki tiddlers). This is a preflight check
// that certifies the dataset without writing any HTML.
//
// Reverse readiness depends only on the canon, not on derived layers.
//
// Ref: S39 §10.3 — reverse readiness.
// Ref: contratos/reverse/reverse_contract_rules.md — formal contract.
package canon

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"strings"
)

// ReverseIssue describes a single problem found during reverse-preflight.
type ReverseIssue struct {
	Line    int    `json:"line"`
	Title   string `json:"title,omitempty"`
	Field   string `json:"field,omitempty"`
	RuleID  string `json:"rule_id"`
	Message string `json:"message"`
}

// ReversePreflightReport holds the result of a reverse-preflight check.
type ReversePreflightReport struct {
	LinesRead    int            `json:"lines_read"`
	ReverseReady int            `json:"reverse_ready"`
	NotReady     int            `json:"not_ready"`
	Issues       []ReverseIssue `json:"issues,omitempty"`
}

// OK returns true when all lines are reverse-ready.
func (r ReversePreflightReport) OK() bool {
	return r.NotReady == 0
}

// ReversePreflightCanonJSONL reads a JSONL stream and checks each node
// for reverse readiness according to the reverse contract.
//
// A node is reverse-ready when:
//   - title is non-empty
//   - schema_version is "v0"
//   - key is non-empty
//
// text may be null (reconstructed as empty body), but title must exist.
//
// Ref: S39 §12.3 — reverse-preflight mode.
// Ref: contratos/reverse/reverse_contract_rules.md §5.
func ReversePreflightCanonJSONL(r io.Reader) ReversePreflightReport {
	report := ReversePreflightReport{}
	scanner := bufio.NewScanner(r)

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

		issues := reversePreflightLine(lineNum, []byte(line))
		if len(issues) == 0 {
			report.ReverseReady++
		} else {
			report.NotReady++
			report.Issues = append(report.Issues, issues...)
		}
	}
	if err := scanner.Err(); err != nil {
		report.NotReady++
		report.Issues = append(report.Issues, ReverseIssue{
			Line:    lineNum + 1,
			RuleID:  "read-error",
			Message: fmt.Sprintf("cannot continue scanning canon JSONL: %v", err),
		})
	}
	return report
}

// reversePreflightLine checks one JSONL line for reverse readiness.
func reversePreflightLine(lineNum int, data []byte) []ReverseIssue {
	var issues []ReverseIssue

	var entry CanonEntry
	if err := json.Unmarshal(data, &entry); err != nil {
		issues = append(issues, ReverseIssue{
			Line:    lineNum,
			RuleID:  "invalid-json",
			Message: fmt.Sprintf("cannot parse: %v", err),
		})
		return issues
	}

	if entry.Title == "" {
		issues = append(issues, ReverseIssue{
			Line:    lineNum,
			Field:   "title",
			RuleID:  "missing-title",
			Message: "title is empty; node is not reversible",
		})
	}

	if entry.SchemaVersion != SchemaV0 {
		issues = append(issues, ReverseIssue{
			Line:    lineNum,
			Title:   entry.Title,
			Field:   "schema_version",
			RuleID:  "wrong-schema-version",
			Message: fmt.Sprintf("schema_version is %q, expected %q", entry.SchemaVersion, SchemaV0),
		})
	}

	if entry.Key == "" {
		issues = append(issues, ReverseIssue{
			Line:    lineNum,
			Title:   entry.Title,
			Field:   "key",
			RuleID:  "missing-key",
			Message: "key is empty; node is not reversible",
		})
	}

	return issues
}
