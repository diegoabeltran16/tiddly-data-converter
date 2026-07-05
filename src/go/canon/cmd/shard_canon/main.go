package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"github.com/tiddly-data-converter/canon"
)

func main() {
	input := flag.String("input", "", "Path to a temporary monolithic canonical JSONL file (required)")
	outDir := flag.String("out-dir", "", "Directory where tiddlers_<n>.jsonl shards will be written (required)")
	maxLines := flag.Int("max-lines", canon.DefaultCanonShardMaxLines, "Maximum non-empty JSONL lines per shard")
	flag.Parse()

	if *input == "" || *outDir == "" {
		fmt.Fprintln(os.Stderr, "[shard_canon] usage: shard_canon --input <jsonl_path> --out-dir <dir>")
		flag.PrintDefaults()
		os.Exit(1)
	}

	report, err := canon.WriteShardSetWithMaxLines(*input, *outDir, *maxLines)
	if err != nil {
		fmt.Fprintf(os.Stderr, "[shard_canon] ERROR: %v\n", err)
		os.Exit(2)
	}

	reportJSON, _ := json.MarshalIndent(report, "", "  ")
	fmt.Println(string(reportJSON))
	fmt.Fprintf(os.Stderr, "[shard_canon] Wrote shard set to %s\n", *outDir)
}
