package main

import (
	"flag"
	"fmt"
	"os"

	"github.com/tiddly-data-converter/bridge"
)

func main() {
	htmlPath := flag.String("html", "", "Path to the base TiddlyWiki HTML file (required)")
	canonPath := flag.String("canon", "", "Path to the canonical JSONL file (required)")
	outHTMLPath := flag.String("out-html", "", "Path for the reversed HTML output (required)")
	reportPath := flag.String("report", "", "Path for the reverse report JSON (optional)")
	mode := flag.String("mode", bridge.ReverseModeInsertOnly, "Reverse mode (only insert-only is supported in S43)")
	flag.Parse()

	if *htmlPath == "" || *canonPath == "" || *outHTMLPath == "" {
		fmt.Fprintln(os.Stderr, "[reverse_tiddlers] usage: reverse_tiddlers --html <path> --canon <path> --out-html <path>")
		flag.PrintDefaults()
		os.Exit(1)
	}
	if *mode != bridge.ReverseModeInsertOnly {
		fmt.Fprintf(os.Stderr, "[reverse_tiddlers] ERROR: unsupported mode %q; expected %q\n", *mode, bridge.ReverseModeInsertOnly)
		os.Exit(1)
	}

	result, err := bridge.ReverseInsertOnlyFiles(*htmlPath, *canonPath, *outHTMLPath)
	if *reportPath != "" && result != nil {
		if writeErr := bridge.WriteReverseReport(*reportPath, result.Report); writeErr != nil {
			fmt.Fprintf(os.Stderr, "[reverse_tiddlers] WARNING: cannot write report: %v\n", writeErr)
		} else {
			fmt.Fprintf(os.Stderr, "[reverse_tiddlers] Report: %s\n", *reportPath)
		}
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "[reverse_tiddlers] ERROR: %v\n", err)
		if result != nil {
			fmt.Fprintf(os.Stderr, "[reverse_tiddlers] Summary: raw_evaluated=%d inserted=%d already_present=%d rejected=%d\n",
				result.Report.RawTiddlersEvaluated, result.Report.InsertedCount, result.Report.AlreadyPresentCount, result.Report.RejectedCount)
		}
		os.Exit(3)
	}

	fmt.Fprintf(os.Stderr, "[reverse_tiddlers] Reverse complete ✓\n")
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Mode:            %s\n", result.Report.Mode)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Store blocks:    %d\n", result.Report.StoreBlocksFound)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Canon lines:     %d\n", result.Report.CanonLinesRead)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Raw evaluated:   %d\n", result.Report.RawTiddlersEvaluated)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Non-raw skipped: %d\n", result.Report.NonRawRecordsSkipped)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Already present: %d\n", result.Report.AlreadyPresentCount)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Inserted:        %d\n", result.Report.InsertedCount)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Rejected:        %d\n", result.Report.RejectedCount)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Source fields:   %t (%d candidates)\n",
		result.Report.SourceFieldsUsed, result.Report.SourceFieldsUsedCount)
	fmt.Fprintf(os.Stderr, "[reverse_tiddlers]   Output HTML:     %s\n", *outHTMLPath)
}
