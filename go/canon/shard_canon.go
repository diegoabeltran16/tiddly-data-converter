package canon

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

const (
	SessionTitlePrefix    = "#### 🌀 Sesión "
	HypothesisTitlePrefix = "#### 🌀🧪 Hipótesis de sesión "
	ProvenanceTitlePrefix = "#### 🌀🧾 Procedencia de sesión "

	auxShardMaxLines = 144
)

var auxShardOrder = []int{1, 5, 6, 7}

var shard3PinnedTitles = map[string]struct{}{
	"#### 🌀📦 Hipótesis de dependencias = m01":   {},
	"#### 🌀📦 Política de dependencias":          {},
	"#### 🌀📦 Procedencia de dependencias = m01": {},
	"#### 🌀📦 Registro de dependencias críticas": {},
}

var shard4PinnedTitles = map[string]struct{}{
	"#### 📚 Diccionario 🌀.csv":       {},
	"#### referencias especificas 🌀": {},
}

var shard4ReferenceTitlePattern = regexp.MustCompile(`^\d{2}\. `)

// ShardCanonReport captures the deterministic shard layout inferred from the
// authoritative S44 corpus.
type ShardCanonReport struct {
	LinesRead        int            `json:"lines_read"`
	SessionCount     int            `json:"session_count"`
	HypothesisCount  int            `json:"hypothesis_count"`
	ProvenanceCount  int            `json:"provenance_count"`
	RemainingCount   int            `json:"remaining_count"`
	ShardLineCounts  map[string]int `json:"shard_line_counts"`
	AuxShardMaxLines int            `json:"aux_shard_max_lines"`
	ShardOrder       []string       `json:"shard_order"`
}

type shardCanonLine struct {
	Title string `json:"title"`
}

// ShardCanonJSONL splits a canonical JSONL stream into the S44 shard layout:
// session records in shard 2, hypotheses in 3, provenance in 4, and the
// remaining corpus in order across shards 1, 5, 6 and 7.
func ShardCanonJSONL(r io.Reader) (map[string][]string, ShardCanonReport, error) {
	report := ShardCanonReport{
		ShardLineCounts:  make(map[string]int, 7),
		AuxShardMaxLines: auxShardMaxLines,
		ShardOrder: []string{
			"tiddlers_1.jsonl",
			"tiddlers_2.jsonl",
			"tiddlers_3.jsonl",
			"tiddlers_4.jsonl",
			"tiddlers_5.jsonl",
			"tiddlers_6.jsonl",
			"tiddlers_7.jsonl",
		},
	}
	shards := map[string][]string{
		"tiddlers_1.jsonl": {},
		"tiddlers_2.jsonl": {},
		"tiddlers_3.jsonl": {},
		"tiddlers_4.jsonl": {},
		"tiddlers_5.jsonl": {},
		"tiddlers_6.jsonl": {},
		"tiddlers_7.jsonl": {},
	}

	var shard3Pinned []string
	var shard3Hypotheses []string
	var shard4Provenance []string
	var shard4Pinned []string
	var remaining []string
	scanner := bufio.NewScanner(r)
	buf := make([]byte, 0, 1024*1024)
	scanner.Buffer(buf, 64*1024*1024)

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		report.LinesRead++

		var parsed shardCanonLine
		if err := json.Unmarshal([]byte(line), &parsed); err != nil {
			return nil, report, fmt.Errorf("line %d: parse title: %w", report.LinesRead, err)
		}
		if strings.TrimSpace(parsed.Title) == "" {
			return nil, report, fmt.Errorf("line %d: title is empty", report.LinesRead)
		}

		switch {
		case strings.HasPrefix(parsed.Title, SessionTitlePrefix):
			shards["tiddlers_2.jsonl"] = append(shards["tiddlers_2.jsonl"], line)
			report.SessionCount++
		case belongsInShard3(parsed.Title):
			shard3Pinned = append(shard3Pinned, line)
			report.HypothesisCount++
		case strings.HasPrefix(parsed.Title, HypothesisTitlePrefix):
			shard3Hypotheses = append(shard3Hypotheses, line)
			report.HypothesisCount++
		case belongsInShard4(parsed.Title):
			shard4Pinned = append(shard4Pinned, line)
			report.ProvenanceCount++
		case strings.HasPrefix(parsed.Title, ProvenanceTitlePrefix):
			shard4Provenance = append(shard4Provenance, line)
			report.ProvenanceCount++
		default:
			remaining = append(remaining, line)
			report.RemainingCount++
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, report, fmt.Errorf("scan canon jsonl: %w", err)
	}

	maxRemaining := auxShardMaxLines * len(auxShardOrder)
	if len(remaining) > maxRemaining {
		return nil, report, fmt.Errorf(
			"remaining corpus has %d lines, exceeds S44 auxiliary shard capacity of %d",
			len(remaining),
			maxRemaining,
		)
	}

	shards["tiddlers_3.jsonl"] = append(shards["tiddlers_3.jsonl"], shard3Pinned...)
	shards["tiddlers_3.jsonl"] = append(shards["tiddlers_3.jsonl"], shard3Hypotheses...)
	shards["tiddlers_4.jsonl"] = append(shards["tiddlers_4.jsonl"], shard4Provenance...)
	shards["tiddlers_4.jsonl"] = append(shards["tiddlers_4.jsonl"], shard4Pinned...)

	cursor := 0
	for idx, shardNumber := range auxShardOrder {
		filename := fmt.Sprintf("tiddlers_%d.jsonl", shardNumber)
		count := auxShardMaxLines
		if idx == 0 && len(remaining)%auxShardMaxLines != 0 {
			count = len(remaining) % auxShardMaxLines
		}
		if len(remaining) == 0 {
			count = 0
		}
		if idx > 0 && cursor >= len(remaining) {
			count = 0
		}
		if count > len(remaining)-cursor {
			count = len(remaining) - cursor
		}
		if count < 0 {
			count = 0
		}
		if count > 0 {
			shards[filename] = append(shards[filename], remaining[cursor:cursor+count]...)
			cursor += count
		}
	}

	for shardName, lines := range shards {
		report.ShardLineCounts[shardName] = len(lines)
	}
	return shards, report, nil
}

func belongsInShard3(title string) bool {
	_, ok := shard3PinnedTitles[title]
	return ok
}

func belongsInShard4(title string) bool {
	if _, ok := shard4PinnedTitles[title]; ok {
		return true
	}
	return shard4ReferenceTitlePattern.MatchString(title)
}

// WriteShardSet writes the seven S44 canon shard files to outDir.
func WriteShardSet(inputPath, outDir string) (ShardCanonReport, error) {
	report := ShardCanonReport{}

	inFile, err := os.Open(inputPath)
	if err != nil {
		return report, fmt.Errorf("open input %s: %w", inputPath, err)
	}
	defer inFile.Close()

	shards, shardReport, err := ShardCanonJSONL(inFile)
	if err != nil {
		return report, err
	}
	report = shardReport

	if err := os.MkdirAll(outDir, 0o755); err != nil {
		return report, fmt.Errorf("create output dir %s: %w", outDir, err)
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
