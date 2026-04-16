// cmd/canon_preflight/main.go — S39 CLI: canon validation and preflight
//
// Usage:
//   canon_preflight --mode <strict|normalize|reverse-preflight> --input <jsonl_path> [--output <jsonl_path>]
//
// Modes:
//   strict             — validates shape and invariants; fails on any inconsistency
//   normalize          — recalculates derived fields, emits normalized JSONL
//   reverse-preflight  — certifies whether the canon is ready for reverse
//
// Exit codes:
//   0 — passed / all checks OK
//   1 — usage error
//   2 — validation or preflight failure (issues found)
//   3 — I/O error
//
// Contract reference: contratos/m02-s39-canon-executable-policy-and-reverse-readiness-v0.md.json
// Ref: S39 — canon executable policy and reverse readiness.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"github.com/tiddly-data-converter/canon"
)

func main() {
	mode := flag.String("mode", "", "Validation mode: strict, normalize, reverse-preflight (required)")
	input := flag.String("input", "", "Path to input JSONL file (required)")
	output := flag.String("output", "", "Path for normalized output JSONL (normalize mode only)")
	flag.Parse()

	if *mode == "" || *input == "" {
		fmt.Fprintln(os.Stderr, "[canon_preflight] usage: canon_preflight --mode <strict|normalize|reverse-preflight> --input <jsonl_path>")
		flag.PrintDefaults()
		os.Exit(1)
	}

	inFile, err := os.Open(*input)
	if err != nil {
		fmt.Fprintf(os.Stderr, "[canon_preflight] ERROR: cannot open %s: %v\n", *input, err)
		os.Exit(3)
	}
	defer inFile.Close()

	switch *mode {
	case "strict":
		runStrict(inFile)
	case "normalize":
		runNormalize(inFile, *output)
	case "reverse-preflight":
		runReversePreflight(inFile)
	default:
		fmt.Fprintf(os.Stderr, "[canon_preflight] ERROR: unknown mode %q\n", *mode)
		os.Exit(1)
	}
}

func runStrict(f *os.File) {
	policy := canon.DefaultCanonPolicy()
	report := canon.ValidateCanonJSONL(f, policy)

	reportJSON, _ := json.MarshalIndent(report, "", "  ")
	fmt.Println(string(reportJSON))

	if !report.OK() {
		fmt.Fprintf(os.Stderr, "[canon_preflight] STRICT FAILED — %d error(s) in %d line(s)\n",
			report.ErrorCount(), report.LinesRead)
		os.Exit(2)
	}
	fmt.Fprintf(os.Stderr, "[canon_preflight] STRICT PASSED — %d line(s) valid\n", report.LinesValid)
}

func runNormalize(f *os.File, outputPath string) {
	var outW *os.File
	var err error
	if outputPath == "" {
		outW = os.Stdout
	} else {
		outW, err = os.Create(outputPath)
		if err != nil {
			fmt.Fprintf(os.Stderr, "[canon_preflight] ERROR: cannot create %s: %v\n", outputPath, err)
			os.Exit(3)
		}
		defer outW.Close()
	}

	report := canon.NormalizeCanonJSONL(f, outW)

	reportJSON, _ := json.MarshalIndent(report, "", "  ")
	fmt.Fprintln(os.Stderr, string(reportJSON))

	if !report.OK() {
		fmt.Fprintf(os.Stderr, "[canon_preflight] NORMALIZE — %d rejected out of %d\n",
			report.LinesRejected, report.LinesRead)
		os.Exit(2)
	}
	fmt.Fprintf(os.Stderr, "[canon_preflight] NORMALIZE OK — %d line(s) normalized\n", report.LinesNormalized)
}

func runReversePreflight(f *os.File) {
	report := canon.ReversePreflightCanonJSONL(f)

	reportJSON, _ := json.MarshalIndent(report, "", "  ")
	fmt.Println(string(reportJSON))

	if !report.OK() {
		fmt.Fprintf(os.Stderr, "[canon_preflight] REVERSE-PREFLIGHT FAILED — %d not ready out of %d\n",
			report.NotReady, report.LinesRead)
		os.Exit(2)
	}
	fmt.Fprintf(os.Stderr, "[canon_preflight] REVERSE-PREFLIGHT PASSED — %d line(s) ready\n", report.ReverseReady)
}
