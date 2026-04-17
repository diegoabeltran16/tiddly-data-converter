package canon

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
)

const (
	CanonSourceModeSingleFile = "single-file"
	CanonSourceModeSharded    = "sharded"
)

type CanonSourceIssue struct {
	Path     string `json:"path,omitempty"`
	Line     int    `json:"line,omitempty"`
	RuleID   string `json:"rule_id"`
	Message  string `json:"message"`
	Severity string `json:"severity"`
}

type CanonSourceShard struct {
	Path      string `json:"path"`
	Order     int    `json:"order"`
	LinesRead int    `json:"lines_read"`
	SHA256    string `json:"sha256"`
}

type CanonSourceReport struct {
	Mode       string             `json:"mode"`
	RootPath   string             `json:"root_path,omitempty"`
	InputPath  string             `json:"input_path,omitempty"`
	InputPaths []string           `json:"input_paths,omitempty"`
	LinesRead  int                `json:"lines_read"`
	Shards     []CanonSourceShard `json:"shards,omitempty"`
	Issues     []CanonSourceIssue `json:"issues,omitempty"`
}

func (r CanonSourceReport) OK() bool {
	for _, issue := range r.Issues {
		if issue.Severity == "error" {
			return false
		}
	}
	return true
}

type canonSourceSeenLine struct {
	Path string
	Line int
}

type canonSourceSeenValue struct {
	Path string
	Line int
}

func LoadCanonSource(path string) ([]byte, CanonSourceReport, error) {
	info, err := os.Stat(path)
	if err != nil {
		return nil, CanonSourceReport{}, err
	}

	if info.IsDir() {
		return loadCanonSourceDir(path)
	}
	return loadCanonSourceFile(path)
}

func loadCanonSourceFile(path string) ([]byte, CanonSourceReport, error) {
	report := CanonSourceReport{
		Mode:       CanonSourceModeSingleFile,
		InputPath:  path,
		InputPaths: []string{path},
	}

	data, err := os.ReadFile(path)
	if err != nil {
		return nil, report, err
	}

	report.LinesRead, report.Issues = scanCanonSourceData(path, data)
	if !report.OK() {
		return data, report, fmt.Errorf("canon_source: strict preflight failed for %s", path)
	}

	return data, report, nil
}

func loadCanonSourceDir(root string) ([]byte, CanonSourceReport, error) {
	report := CanonSourceReport{
		Mode:     CanonSourceModeSharded,
		RootPath: root,
	}

	entries, err := os.ReadDir(root)
	if err != nil {
		return nil, report, err
	}

	type shardPath struct {
		order int
		path  string
	}

	shardPaths := make([]shardPath, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		order, ok := parseCanonShardFilename(entry.Name())
		if !ok {
			continue
		}
		shardPaths = append(shardPaths, shardPath{
			order: order,
			path:  filepath.Join(root, entry.Name()),
		})
	}

	slices.SortFunc(shardPaths, func(a, b shardPath) int {
		if a.order != b.order {
			return a.order - b.order
		}
		return strings.Compare(a.path, b.path)
	})

	if len(shardPaths) == 0 {
		report.Issues = append(report.Issues, CanonSourceIssue{
			Path:     root,
			RuleID:   "missing-shards",
			Message:  "no files matching tiddlers_<n>.jsonl were found",
			Severity: "error",
		})
		return nil, report, fmt.Errorf("canon_source: no shards found in %s", root)
	}

	report.InputPaths = make([]string, 0, len(shardPaths))
	var out bytes.Buffer
	issues := make([]CanonSourceIssue, 0)
	seenShardSHA := make(map[string]string)
	seenLineHashes := make(map[[32]byte]canonSourceSeenLine)
	seenTitles := make(map[string]canonSourceSeenValue)
	seenKeys := make(map[string]canonSourceSeenValue)

	for _, shard := range shardPaths {
		data, readErr := os.ReadFile(shard.path)
		if readErr != nil {
			return nil, report, readErr
		}

		sum := sha256.Sum256(data)
		sumLabel := fmt.Sprintf("sha256:%x", sum[:])
		if firstPath, duplicated := seenShardSHA[sumLabel]; duplicated {
			issues = append(issues, CanonSourceIssue{
				Path:     shard.path,
				RuleID:   "duplicate-shard-content",
				Message:  fmt.Sprintf("shard content matches %s exactly; refusing ambiguous shard set", firstPath),
				Severity: "error",
			})
		} else {
			seenShardSHA[sumLabel] = shard.path
		}

		linesRead, lineIssues := scanCanonSourceDataWithState(
			shard.path,
			data,
			seenLineHashes,
			seenTitles,
			seenKeys,
		)
		issues = append(issues, lineIssues...)
		report.LinesRead += linesRead
		report.InputPaths = append(report.InputPaths, shard.path)
		report.Shards = append(report.Shards, CanonSourceShard{
			Path:      shard.path,
			Order:     shard.order,
			LinesRead: linesRead,
			SHA256:    sumLabel,
		})
		out.Write(data)
		if len(data) > 0 && data[len(data)-1] != '\n' {
			out.WriteByte('\n')
		}
	}

	report.Issues = issues
	if !report.OK() {
		return out.Bytes(), report, fmt.Errorf("canon_source: shard preflight failed for %s", root)
	}

	return out.Bytes(), report, nil
}

func scanCanonSourceData(path string, data []byte) (int, []CanonSourceIssue) {
	return scanCanonSourceDataWithState(
		path,
		data,
		make(map[[32]byte]canonSourceSeenLine),
		make(map[string]canonSourceSeenValue),
		make(map[string]canonSourceSeenValue),
	)
}

func scanCanonSourceDataWithState(
	path string,
	data []byte,
	seenLineHashes map[[32]byte]canonSourceSeenLine,
	seenTitles map[string]canonSourceSeenValue,
	seenKeys map[string]canonSourceSeenValue,
) (int, []CanonSourceIssue) {
	scanner := bufio.NewScanner(bytes.NewReader(data))
	buf := make([]byte, 0, 1024*1024)
	scanner.Buffer(buf, 64*1024*1024)

	linesRead := 0
	var issues []CanonSourceIssue
	lineNum := 0
	for scanner.Scan() {
		lineNum++
		raw := strings.TrimSpace(scanner.Text())
		if raw == "" {
			continue
		}
		linesRead++

		lineHash := sha256.Sum256([]byte(raw))
		if first, duplicated := seenLineHashes[lineHash]; duplicated {
			issues = append(issues, CanonSourceIssue{
				Path:     path,
				Line:     lineNum,
				RuleID:   "duplicate-line-content",
				Message:  fmt.Sprintf("line content duplicates %s:%d exactly", first.Path, first.Line),
				Severity: "error",
			})
		} else {
			seenLineHashes[lineHash] = canonSourceSeenLine{Path: path, Line: lineNum}
		}

		var entry CanonEntry
		if err := json.Unmarshal([]byte(raw), &entry); err != nil {
			issues = append(issues, CanonSourceIssue{
				Path:     path,
				Line:     lineNum,
				RuleID:   "invalid-json",
				Message:  fmt.Sprintf("cannot parse canon line: %v", err),
				Severity: "error",
			})
			continue
		}

		if entry.Title != "" {
			if first, duplicated := seenTitles[entry.Title]; duplicated {
				issues = append(issues, CanonSourceIssue{
					Path:     path,
					Line:     lineNum,
					RuleID:   "duplicate-title",
					Message:  fmt.Sprintf("title %q duplicates %s:%d", entry.Title, first.Path, first.Line),
					Severity: "error",
				})
			} else {
				seenTitles[entry.Title] = canonSourceSeenValue{Path: path, Line: lineNum}
			}
		}

		if entry.Key != "" {
			key := string(entry.Key)
			if first, duplicated := seenKeys[key]; duplicated {
				issues = append(issues, CanonSourceIssue{
					Path:     path,
					Line:     lineNum,
					RuleID:   "duplicate-key",
					Message:  fmt.Sprintf("key %q duplicates %s:%d", key, first.Path, first.Line),
					Severity: "error",
				})
			} else {
				seenKeys[key] = canonSourceSeenValue{Path: path, Line: lineNum}
			}
		}
	}

	if err := scanner.Err(); err != nil {
		issues = append(issues, CanonSourceIssue{
			Path:     path,
			Line:     lineNum + 1,
			RuleID:   "read-error",
			Message:  fmt.Sprintf("cannot continue scanning canon source: %v", err),
			Severity: "error",
		})
	}

	return linesRead, issues
}

func parseCanonShardFilename(name string) (int, bool) {
	if !strings.HasPrefix(name, "tiddlers_") || !strings.HasSuffix(name, ".jsonl") {
		return 0, false
	}
	number := strings.TrimSuffix(strings.TrimPrefix(name, "tiddlers_"), ".jsonl")
	if number == "" {
		return 0, false
	}
	value, err := strconv.Atoi(number)
	if err != nil || value <= 0 {
		return 0, false
	}
	return value, true
}
