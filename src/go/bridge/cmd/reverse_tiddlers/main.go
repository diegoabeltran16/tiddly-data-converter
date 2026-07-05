package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"github.com/tiddly-data-converter/bridge"
)

func main() {
	htmlPath := flag.String("html", "", "Path to the base TiddlyWiki HTML file (required)")
	canonPath := flag.String("canon", "", "Path to the canonical JSONL file or shard directory (required)")
	outHTMLPath := flag.String("out-html", "", "Path for the reversed HTML output (required)")
	reportPath := flag.String("report", "", "Path for the reverse report JSON (optional; defaults to <out-html dir>/reverse-report.json)")
	mode := flag.String("mode", bridge.ReverseModeAuthoritativeUpsert, "Reverse mode: authoritative-upsert or insert-only")
	storePolicy := flag.String("store-policy", bridge.ReverseStorePolicyPreserve, "Store policy: preserve or replace")
	flag.Parse()

	if *htmlPath == "" || *canonPath == "" || *outHTMLPath == "" {
		fmt.Fprintln(os.Stderr, "[reverse_tiddlers] usage: reverse_tiddlers --html <path> --canon <path> --out-html <path> [--report <path>] [--mode <mode>] [--store-policy <policy>]")
		flag.PrintDefaults()
		os.Exit(1)
	}
	if *mode != bridge.ReverseModeInsertOnly && *mode != bridge.ReverseModeAuthoritativeUpsert {
		fmt.Fprintf(os.Stderr, "[reverse_tiddlers] ERROR: unsupported mode %q; expected %q or %q\n", *mode, bridge.ReverseModeAuthoritativeUpsert, bridge.ReverseModeInsertOnly)
		os.Exit(1)
	}
	if *storePolicy != bridge.ReverseStorePolicyPreserve && *storePolicy != bridge.ReverseStorePolicyReplace {
		fmt.Fprintf(os.Stderr, "[reverse_tiddlers] ERROR: unsupported store policy %q; expected %q or %q\n", *storePolicy, bridge.ReverseStorePolicyPreserve, bridge.ReverseStorePolicyReplace)
		os.Exit(1)
	}
	effectiveReportPath := *reportPath
	if effectiveReportPath == "" {
		effectiveReportPath = filepath.Join(filepath.Dir(*outHTMLPath), "reverse-report.json")
	}

	result, err := bridge.ReverseFiles(*htmlPath, *canonPath, *outHTMLPath, *mode, *storePolicy)
	if result != nil {
		if writeErr := bridge.WriteReverseReport(effectiveReportPath, result.Report); writeErr != nil {
			fmt.Fprintf(os.Stderr, "[reverse_tiddlers] WARNING: cannot write report: %v\n", writeErr)
		} else {
			fmt.Fprintf(os.Stderr, "[reverse_tiddlers] Report: %s\n", effectiveReportPath)
		}
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "[reverse_tiddlers] ERROR: %v\n", err)
		if result != nil {
			fmt.Fprintf(os.Stderr, "[reverse_tiddlers] Summary: eligible=%d skipped=%d inserted=%d updated=%d already_present=%d rejected=%d\n",
				result.Report.EligibleEntriesEvaluated, result.Report.OutOfScopeSkipped, result.Report.InsertedCount, result.Report.UpdatedCount, result.Report.AlreadyPresentCount, result.Report.RejectedCount)
		}
		os.Exit(3)
	}

	fmt.Fprintf(os.Stderr, "[reverse_tiddlers] Reverse complete ✓\n")
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Mode:            %s\n", result.Report.Mode)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Store policy:    %s\n", result.Report.StorePolicy)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Store blocks:    %d\n", result.Report.StoreBlocksFound)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Existing store:   %d\n", result.Report.ExistingTiddlers)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Output store:     %d\n", result.Report.OutputTiddlers)
	if result.Report.StructuralTiddlersKept > 0 {
		fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Structural kept: %d\n", result.Report.StructuralTiddlersKept)
	}
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Canon lines:     %d\n", result.Report.CanonLinesRead)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Eligible:        %d\n", result.Report.EligibleEntriesEvaluated)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Out-of-scope:    %d\n", result.Report.OutOfScopeSkipped)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Already present: %d\n", result.Report.AlreadyPresentCount)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Inserted:        %d\n", result.Report.InsertedCount)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Updated:         %d\n", result.Report.UpdatedCount)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Rejected:        %d\n", result.Report.RejectedCount)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Source fields:   %t (%d candidates)\n",
		result.Report.SourceFieldsUsed, result.Report.SourceFieldsUsedCount)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Output HTML:     %s\n", *outHTMLPath)
}
