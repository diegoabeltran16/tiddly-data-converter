// Command accumulate implements the accumulator CLI defined in
// tools/accumulator/spec.md (S28) and promoted to production in S29.
//
// Usage:
//
//	accumulate --input <dir> --out <path> [--batch <id>] [--verify]
//	accumulate --verify --snapshot <path> --input <dir> [--batch <id>]
//	accumulate --input <dir> --out <path> --snapshot-id <id> --as-of <ts> [--export-jsonl <path>]
//
// When --snapshot is provided with --verify, the tool loads an existing
// snapshot and verifies it against a replay from the source run_reports.
// This mode performs field-by-field comparison (S31) including UUIDv5
// replay, checksum recomputation, and structured diff output.
//
// When --snapshot-id and --as-of are provided, the tool generates a
// fully deterministic snapshot suitable for baseline golden files (S32).
// Combined with --export-jsonl, it also emits the snapshot as a single
// canonical JSONL line for downstream consumption.
//
// Ref: S28 — accumulator spec.
// Ref: S29 — truth-pin implementation.
// Ref: S31 — replay verification and CI.
// Ref: S32 — baseline oracle and first JSONL.
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
	outPath := flag.String("out", "", "Output path for batch_snapshot JSON (required for generate mode)")
	verify := flag.Bool("verify", false, "Verify mode: with --snapshot verifies existing snapshot; without --snapshot replays after generation")
	snapshotPath := flag.String("snapshot", "", "Path to existing snapshot file to verify (used with --verify)")
	version := flag.Bool("version", false, "Print accumulation algorithm version")
	snapshotID := flag.String("snapshot-id", "", "Fixed snapshot_id for deterministic generation (S32)")
	asOf := flag.String("as-of", "", "Fixed as_of timestamp for deterministic generation (S32, RFC 3339)")
	exportJSONL := flag.String("export-jsonl", "", "Export snapshot as single canonical JSONL line (S32)")
	flag.Parse()

	if *version {
		fmt.Println("fold_v1 v0.1")
		os.Exit(0)
	}

	// S31: --verify --snapshot <path> --input <dir> mode.
	// Verifies an existing snapshot against a replay from source inputs.
	if *verify && *snapshotPath != "" {
		if *inputDir == "" {
			fmt.Fprintln(os.Stderr, "accumulate: --input is required with --verify --snapshot")
			flag.Usage()
			os.Exit(2)
		}

		log.Printf("accumulate: verify mode — snapshot=%q input=%q batch=%q",
			*snapshotPath, *inputDir, *batchID)

		result, err := canon.VerifySnapshot(*snapshotPath, *inputDir, *batchID)
		if err != nil {
			log.Fatalf("accumulate: verify: %v", err)
		}

		// Emit structured result as JSON.
		resultJSON, err := json.MarshalIndent(result, "", "  ")
		if err != nil {
			log.Fatalf("accumulate: marshal result: %v", err)
		}
		fmt.Println(string(resultJSON))

		if !result.OK {
			log.Printf("accumulate: %s", result.Message)
			os.Exit(1)
		}

		log.Printf("accumulate: %s", result.Message)
		os.Exit(0)
	}

	// Generate mode: --input and --out are required.
	if *inputDir == "" || *outPath == "" {
		fmt.Fprintln(os.Stderr, "accumulate: --input and --out are required")
		flag.Usage()
		os.Exit(2)
	}

	// S32: validate deterministic flags — both or neither.
	if (*snapshotID != "") != (*asOf != "") {
		fmt.Fprintln(os.Stderr, "accumulate: --snapshot-id and --as-of must be specified together")
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
	// S32: use fixed snapshot_id and as_of if provided (deterministic mode).
	// Otherwise generate from clock (legacy behavior).
	sid := *snapshotID
	aof := *asOf
	if sid == "" {
		batchSuffix := "all"
		if *batchID != "" {
			batchSuffix = *batchID
		}
		sid = fmt.Sprintf("snapshot-%s-%s", batchSuffix, time.Now().UTC().Format("20060102-150405"))
		aof = time.Now().UTC().Format(time.RFC3339)
	}
	snap := canon.FoldV1(runs, sid, aof)

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

	// S32: export snapshot as a single canonical JSONL line if requested.
	if *exportJSONL != "" {
		canonical, err := canon.CanonicalJSON(snap)
		if err != nil {
			log.Fatalf("accumulate: canonical json for export: %v", err)
		}
		canonical = append(canonical, '\n')
		if err := os.WriteFile(*exportJSONL, canonical, 0644); err != nil {
			log.Fatalf("accumulate: write jsonl %q: %v", *exportJSONL, err)
		}
		log.Printf("accumulate: wrote JSONL export to %q (%d bytes)", *exportJSONL, len(canonical))
	}

	// 5. Verify if requested (inline replay verification for generate mode)
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
		replayed := canon.FoldV1(runs2, sid, aof)
		if snap.Checksum != replayed.Checksum {
			log.Fatalf("accumulate: VERIFY FAILED — original=%s replayed=%s",
				snap.Checksum, replayed.Checksum)
		}
		log.Printf("accumulate: verify OK — checksums match: %s", snap.Checksum)
	}

	fmt.Printf("OK snapshot=%s checksum=%s runs=%d\n",
		snap.SnapshotID, snap.Checksum, len(snap.RunsIncluded))
}
