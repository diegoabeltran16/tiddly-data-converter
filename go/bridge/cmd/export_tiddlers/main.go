// cmd/export_tiddlers/main.go — S33 CLI: export functional tiddlers from real HTML
//
// Usage:
//
//	export_tiddlers --html <path> --out <jsonl_path> [--log <log_path>] [--manifest <manifest_path>] [--run-id <id>]
//
// This CLI implements the S33 Bridge→Canon costura:
//  1. Extract raw tiddlers from TiddlyWiki HTML (Go adapter)
//  2. Apply filtering rules (exclude system tiddlers)
//  3. Ingest raw tiddlers to pre-canonical shape
//  4. Convert via Bridge to CanonEntry
//  5. Export as JSONL (1 tiddler = 1 line) with S19 gate
//  6. Write export log and manifest
//
// Exit codes:
//
//	0 — export completed successfully
//	1 — usage error
//	2 — extraction error (HTML parse failure)
//	4 — export error
//
// Contract reference: contratos/m01-s33-single-jsonl-functional-tiddlers-from-real-html-v0.md.json
// Ref: S14 — bridge is the integration layer
// Ref: S33 — functional tiddler export from real HTML
package main

import (
	"crypto/sha256"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"github.com/tiddly-data-converter/bridge"
	"github.com/tiddly-data-converter/canon"
	"github.com/tiddly-data-converter/ingesta"
)

func main() {
	htmlPath := flag.String("html", "", "Path to TiddlyWiki HTML file (required)")
	outPath := flag.String("out", "", "Path for output JSONL file (required)")
	logPath := flag.String("log", "", "Path for export log JSONL (optional)")
	manifestPath := flag.String("manifest", "", "Path for export manifest JSON (optional)")
	runID := flag.String("run-id", "", "Unique run identifier (default: auto-generated)")
	flag.Parse()

	if *htmlPath == "" || *outPath == "" {
		fmt.Fprintln(os.Stderr, "[export_tiddlers] usage: export_tiddlers --html <path> --out <jsonl_path>")
		flag.PrintDefaults()
		os.Exit(1)
	}

	if *runID == "" {
		*runID = fmt.Sprintf("s33-run-%s", time.Now().UTC().Format("20060102T150405Z"))
	}
	sourceHTMLPath, err := filepath.Abs(*htmlPath)
	if err != nil {
		sourceHTMLPath = *htmlPath
	}
	sourceHTMLSHA256, err := fileSHA256Label(*htmlPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "[export_tiddlers] ERROR: cannot hash %s: %v\n", *htmlPath, err)
		os.Exit(2)
	}

	// ─── Step 1: Extract from HTML ─────────────────────────────────────────
	fmt.Fprintf(os.Stderr, "[export_tiddlers] === Step 1: Extract from HTML ===\n")
	htmlFile, err := os.Open(*htmlPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "[export_tiddlers] ERROR: cannot open %s: %v\n", *htmlPath, err)
		os.Exit(2)
	}
	defer htmlFile.Close()

	raws, extractResult, err := bridge.ExtractRawTiddlersFromHTML(htmlFile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "[export_tiddlers] ERROR: extraction failed: %v\n", err)
		os.Exit(2)
	}
	fmt.Fprintf(os.Stderr, "[export_tiddlers] Extracted: blocks=%d tiddlers=%d\n",
		extractResult.BlocksFound, extractResult.TotalExtracted)

	// ─── Step 2: Filter ────────────────────────────────────────────────────
	fmt.Fprintf(os.Stderr, "[export_tiddlers] === Step 2: Filter (functional tiddlers) ===\n")
	rules := bridge.DefaultFunctionalTiddlerRules()
	filtered, filterLog := bridge.ApplyFilterRules(raws, rules, *runID)
	excludedCount := len(raws) - len(filtered)
	fmt.Fprintf(os.Stderr, "[export_tiddlers] Filtered: total=%d included=%d excluded=%d\n",
		len(raws), len(filtered), excludedCount)

	// ─── Step 3: Ingest ────────────────────────────────────────────────────
	fmt.Fprintf(os.Stderr, "[export_tiddlers] === Step 3: Ingest (pre-canonical) ===\n")
	tiddlers, ingestReport := ingestFromRaws(filtered)
	fmt.Fprintf(os.Stderr, "[export_tiddlers] Ingested: total=%d ingested=%d skipped=%d verdict=%s\n",
		ingestReport.TiddlerCount, ingestReport.IngestedCount,
		ingestReport.SkippedCount, ingestReport.Verdict)

	// ─── Step 4: Bridge to CanonEntry ──────────────────────────────────────
	fmt.Fprintf(os.Stderr, "[export_tiddlers] === Step 4: Bridge → Canon ===\n")
	entries := bridge.ToCanonEntries(tiddlers)
	fmt.Fprintf(os.Stderr, "[export_tiddlers] Canon entries: %d\n", len(entries))

	// ─── Step 5: Export JSONL ──────────────────────────────────────────────
	fmt.Fprintf(os.Stderr, "[export_tiddlers] === Step 5: Export JSONL ===\n")
	outFile, err := os.Create(*outPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "[export_tiddlers] ERROR: cannot create %s: %v\n", *outPath, err)
		os.Exit(4)
	}
	defer outFile.Close()

	exportResult, err := canon.ExportTiddlersJSONL(outFile, entries, *runID)
	if err != nil {
		fmt.Fprintf(os.Stderr, "[export_tiddlers] ERROR: export failed: %v\n", err)
		os.Exit(4)
	}

	exportResult.Manifest.OutputPath = *outPath
	exportResult.Manifest.SourceHTMLPath = sourceHTMLPath
	exportResult.Manifest.SourceHTMLSHA256 = sourceHTMLSHA256

	fmt.Fprintf(os.Stderr, "[export_tiddlers] Exported: %d lines, excluded: %d\n",
		exportResult.Manifest.ExportedCount, exportResult.Manifest.ExcludedCount)
	fmt.Fprintf(os.Stderr, "[export_tiddlers] SHA-256: %s\n", exportResult.Manifest.SHA256)

	// ─── Step 6: Write log and manifest ────────────────────────────────────
	// Merge filter log entries with export log entries
	allLogEntries := make([]canon.ExportLogEntry, 0, len(filterLog)+len(exportResult.LogEntries))
	for _, fl := range filterLog {
		allLogEntries = append(allLogEntries, canon.ExportLogEntry{
			RunID:     fl.RunID,
			SourceRef: fl.TiddlerTitle,
			Decision:  fl.Action,
			RuleID:    fl.RuleID,
			Reason:    fl.Reason,
		})
	}
	allLogEntries = append(allLogEntries, exportResult.LogEntries...)

	if *logPath != "" {
		if err := canon.WriteExportLog(*logPath, allLogEntries); err != nil {
			fmt.Fprintf(os.Stderr, "[export_tiddlers] WARNING: cannot write log: %v\n", err)
		} else {
			fmt.Fprintf(os.Stderr, "[export_tiddlers] Export log: %s (%d entries)\n", *logPath, len(allLogEntries))
		}
	}

	if *manifestPath != "" {
		if err := canon.WriteExportManifest(*manifestPath, exportResult.Manifest); err != nil {
			fmt.Fprintf(os.Stderr, "[export_tiddlers] WARNING: cannot write manifest: %v\n", err)
		} else {
			fmt.Fprintf(os.Stderr, "[export_tiddlers] Manifest: %s\n", *manifestPath)
		}
	}

	// ─── Summary ───────────────────────────────────────────────────────────
	fmt.Fprintf(os.Stderr, "[export_tiddlers] ============================================\n")
	fmt.Fprintf(os.Stderr, "[export_tiddlers] S33 export complete ✓\n")
	fmt.Fprintf(os.Stderr, "[export_tiddlers]   Extracted:  %d\n", extractResult.TotalExtracted)
	fmt.Fprintf(os.Stderr, "[export_tiddlers]   Filtered:   %d excluded\n", excludedCount)
	fmt.Fprintf(os.Stderr, "[export_tiddlers]   Ingested:   %d\n", ingestReport.IngestedCount)
	fmt.Fprintf(os.Stderr, "[export_tiddlers]   Exported:   %d\n", exportResult.Manifest.ExportedCount)
	fmt.Fprintf(os.Stderr, "[export_tiddlers]   SHA-256:    %s\n", exportResult.Manifest.SHA256)
	fmt.Fprintf(os.Stderr, "[export_tiddlers] ============================================\n")
}

// ingestFromRaws performs in-memory ingestion of RawTiddler values,
// reusing the Ingesta transformation logic without writing to disk.
func ingestFromRaws(raws []ingesta.RawTiddler) ([]ingesta.Tiddler, *ingesta.IngestReport) {
	report := &ingesta.IngestReport{
		TiddlerCount: len(raws),
		Warnings:     []string{},
		Errors:       []string{},
	}

	tiddlers := make([]ingesta.Tiddler, 0, len(raws))

	for _, raw := range raws {
		t, warns, errs := ingesta.TransformOne(raw, ingesta.OriginHTML)

		report.Warnings = append(report.Warnings, warns...)
		report.Errors = append(report.Errors, errs...)

		if len(errs) > 0 {
			report.SkippedCount++
			continue
		}

		tiddlers = append(tiddlers, t)
		report.IngestedCount++
	}

	switch {
	case len(report.Errors) > 0:
		report.Verdict = ingesta.VerdictError
	case len(report.Warnings) > 0:
		report.Verdict = ingesta.VerdictWarning
	default:
		report.Verdict = ingesta.VerdictOk
	}

	return tiddlers, report
}

func fileSHA256Label(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()

	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return "", err
	}
	return fmt.Sprintf("sha256:%x", hash.Sum(nil)), nil
}
