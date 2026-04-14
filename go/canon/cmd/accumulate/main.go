// Command accumulate implements the accumulator CLI defined in
// tools/accumulator/spec.md (S28) and promoted to production in S29.
//
// Usage:
//
//	accumulate --input <dir> --out <path> [--batch <id>] [--verify]
//
// Ref: S28 — accumulator spec.
// Ref: S29 — truth-pin implementation.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"time"

	canon "github.com/tiddly-data-converter/canon"
)

func main() {
	inputDir := flag.String("input", "", "Directory containing run_report JSON files (required)")
	batchID := flag.String("batch", "", "Filter runs by batch_id (optional)")
	outPath := flag.String("out", "", "Output path for batch_snapshot JSON (required)")
	verify := flag.Bool("verify", false, "After generating, replay from runs and verify checksum")
	version := flag.Bool("version", false, "Print accumulation algorithm version")
	flag.Parse()

	if *version {
		fmt.Println("fold_v1 v0.1")
		os.Exit(0)
	}

	if *inputDir == "" || *outPath == "" {
		fmt.Fprintln(os.Stderr, "accumulate: --input and --out are required")
		flag.Usage()
		os.Exit(2)
	}

	// 1. Load run reports
	log.Printf("accumulate: reading run_reports from %q", *inputDir)
	runs, err := canon.LoadRunReports(*inputDir)
	if err != nil {
		log.Fatalf("accumulate: load: %v", err)
	}
	log.Printf("accumulate: loaded %d run_reports", len(runs))

	// 2. Filter by batch_id if specified
	if *batchID != "" {
		var filtered []canon.RunReport
		for _, r := range runs {
			if r.BatchID == *batchID {
				filtered = append(filtered, r)
			}
		}
		log.Printf("accumulate: filtered to %d runs for batch %q", len(filtered), *batchID)
		runs = filtered
	}

	if len(runs) == 0 {
		log.Fatal("accumulate: no run_reports found after filtering")
	}

	// 3. Fold
	snapshotID := fmt.Sprintf("snapshot-%s", time.Now().UTC().Format("20060102-150405"))
	asOf := time.Now().UTC().Format(time.RFC3339)
	snap := canon.FoldV1(runs, snapshotID, asOf)

	log.Printf("accumulate: fold complete — %d runs, checksum=%s", len(snap.RunsIncluded), snap.Checksum)

	// 4. Write output
	data, err := json.MarshalIndent(snap, "", "  ")
	if err != nil {
		log.Fatalf("accumulate: marshal: %v", err)
	}
	data = append(data, '\n')
	if err := os.WriteFile(*outPath, data, 0644); err != nil {
		log.Fatalf("accumulate: write %q: %v", *outPath, err)
	}
	log.Printf("accumulate: wrote snapshot to %q (%d bytes)", *outPath, len(data))

	// 5. Verify if requested
	if *verify {
		log.Printf("accumulate: verifying by replay...")
		runs2, err := canon.LoadRunReports(*inputDir)
		if err != nil {
			log.Fatalf("accumulate: verify load: %v", err)
		}
		if *batchID != "" {
			var filtered []canon.RunReport
			for _, r := range runs2 {
				if r.BatchID == *batchID {
					filtered = append(filtered, r)
				}
			}
			runs2 = filtered
		}
		replayed := canon.FoldV1(runs2, snapshotID, asOf)
		if snap.Checksum != replayed.Checksum {
			log.Fatalf("accumulate: VERIFY FAILED — original=%s replayed=%s",
				snap.Checksum, replayed.Checksum)
		}
		log.Printf("accumulate: verify OK — checksums match: %s", snap.Checksum)
	}

	fmt.Printf("OK snapshot=%s checksum=%s runs=%d\n",
		snap.SnapshotID, snap.Checksum, len(snap.RunsIncluded))
}
