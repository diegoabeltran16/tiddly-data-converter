package canon

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

const (
	// DefaultCanonShardMaxLines is the local canon shard policy for S78+.
	// Shards are sequential tiddlers_<n>.jsonl files and each contains at most
	// this many non-empty JSONL lines.
	DefaultCanonShardMaxLines = 100
)

// ShardCanonReport captures the deterministic shard layout produced from a
// monolithic canonical JSONL stream.
type ShardCanonReport struct {
	LinesRead       int            `json:"lines_read"`
	ShardLineCounts map[string]int `json:"shard_line_counts"`
	ShardMaxLines   int            `json:"shard_max_lines"`
	ShardOrder      []string       `json:"shard_order"`
	PolicyID        string         `json:"policy_id"`
}

type shardCanonLine struct {
	Title string `json:"title"`
}

// ShardCanonJSONL splits a canonical JSONL stream into sequential shards using
// the default S78+ policy of DefaultCanonShardMaxLines lines per file.
func ShardCanonJSONL(r io.Reader) (map[string][]string, ShardCanonReport, error) {
	return ShardCanonJSONLWithMaxLines(r, DefaultCanonShardMaxLines)
}

// ShardCanonJSONLWithMaxLines splits a canonical JSONL stream into sequential
// tiddlers_<n>.jsonl shards with at most maxLines non-empty lines per shard.
func ShardCanonJSONLWithMaxLines(r io.Reader, maxLines int) (map[string][]string, ShardCanonReport, error) {
	report := ShardCanonReport{
		ShardLineCounts: make(map[string]int),
		ShardMaxLines:   maxLines,
		PolicyID:        "sequential-max-lines-v0",
	}
	shards := make(map[string][]string)
	if maxLines <= 0 {
		return nil, report, fmt.Errorf("shard max lines must be positive, got %d", maxLines)
	}

	var currentShard string
	scanner := bufio.NewScanner(r)
	buf := make([]byte, 0, 1024*1024)
	scanner.Buffer(buf, 64*1024*1024)

	for scanner.Scan() {
		rawLine := scanner.Text()
		if strings.TrimSpace(rawLine) == "" {
			continue
		}
		report.LinesRead++

		var parsed shardCanonLine
		if err := json.Unmarshal([]byte(rawLine), &parsed); err != nil {
			return nil, report, fmt.Errorf("line %d: parse title: %w", report.LinesRead, err)
		}
		if strings.TrimSpace(parsed.Title) == "" {
			return nil, report, fmt.Errorf("line %d: title is empty", report.LinesRead)
		}

		shardIndex := ((report.LinesRead - 1) / maxLines) + 1
		shardName := fmt.Sprintf("tiddlers_%d.jsonl", shardIndex)
		if shardName != currentShard {
			currentShard = shardName
			report.ShardOrder = append(report.ShardOrder, shardName)
		}
		shards[shardName] = append(shards[shardName], rawLine)
	}
	if err := scanner.Err(); err != nil {
		return nil, report, fmt.Errorf("scan canon jsonl: %w", err)
	}

	for shardName, lines := range shards {
		report.ShardLineCounts[shardName] = len(lines)
	}
	return shards, report, nil
}

// WriteShardSet writes the S78+ sequential canon shard set to outDir.
func WriteShardSet(inputPath, outDir string) (ShardCanonReport, error) {
	return WriteShardSetWithMaxLines(inputPath, outDir, DefaultCanonShardMaxLines)
}

// WriteShardSetWithMaxLines writes the sequential canon shard set to outDir.
func WriteShardSetWithMaxLines(inputPath, outDir string, maxLines int) (ShardCanonReport, error) {
	report := ShardCanonReport{}

	inFile, err := os.Open(inputPath)
	if err != nil {
		return report, fmt.Errorf("open input %s: %w", inputPath, err)
	}
	defer inFile.Close()

	shards, shardReport, err := ShardCanonJSONLWithMaxLines(inFile, maxLines)
	if err != nil {
		return report, err
	}
	report = shardReport

	if err := os.MkdirAll(outDir, 0o755); err != nil {
		return report, fmt.Errorf("create output dir %s: %w", outDir, err)
	}
	if err := removeExistingCanonShards(outDir); err != nil {
		return report, err
	}

	for _, shardName := range report.ShardOrder {
		lines := shards[shardName]
		payload := ""
		if len(lines) > 0 {
			payload = strings.Join(lines, "\n") + "\n"
		}
		target := filepath.Join(outDir, shardName)
		if err := os.WriteFile(target, []byte(payload), 0o644); err != nil {
			return report, fmt.Errorf("write %s: %w", target, err)
		}
	}

	return report, nil
}

func removeExistingCanonShards(outDir string) error {
	entries, err := os.ReadDir(outDir)
	if err != nil {
		return fmt.Errorf("read output dir %s: %w", outDir, err)
	}
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		if _, ok := parseCanonShardFilename(entry.Name()); !ok {
			continue
		}
		target := filepath.Join(outDir, entry.Name())
		if err := os.Remove(target); err != nil {
			return fmt.Errorf("remove stale shard %s: %w", target, err)
		}
	}
	return nil
}
