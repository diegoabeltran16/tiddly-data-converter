// cmd/emit/main.go — CLI mínima de emisión canon.jsonl
//
// Uso: emit <canon_entries_json> [<output_jsonl>]
//
// Lee el artefacto canon.entries.json (JSON array de CanonEntry) producido
// por el bridge y emite cada entrada como una línea JSONL independiente.
//
// Si output_jsonl se omite, escribe a stdout.
//
// Código de salida:
//   0 — emisión completada
//   1 — argumentos incorrectos
//   2 — error fatal al leer o parsear el archivo
//   3 — error al escribir la salida
//
// Schema v0 shape per JSONL line (S18):
//   {"schema_version":"v0","key":"…","title":"…","text":"…","source_position":"…","created":"…","modified":"…"}
//
// schema_version is stamped by the writer on every emitted line.
// created and modified are present only when available from Ingesta (omitempty).
//
// Campos deliberadamente ausentes:
//   - UUID v5 estable (deferred)
//   - primary_role, relations, provenance, meta blocks (deferred)
//
// Ref: contratos/m01-s16-canon-jsonl-writer.md.json
// Ref: contratos/m01-s18-canon-schema-v0.md.json
// Ref: S13 §B — CanonEntry shape.
// Ref: S17 — shape enriched with created/modified.
// Ref: S18 — schema v0 explícito.
package main

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/tiddly-data-converter/canon"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "[emit] uso: emit <canon_entries_json> [<output_jsonl>]")
		os.Exit(1)
	}

	inputPath := os.Args[1]

	// Read the canon entries artifact.
	data, err := os.ReadFile(inputPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "[emit] ERROR: cannot read %s: %v\n", inputPath, err)
		os.Exit(2)
	}

	var entries []canon.CanonEntry
	if err := json.Unmarshal(data, &entries); err != nil {
		fmt.Fprintf(os.Stderr, "[emit] ERROR: invalid JSON in %s: %v\n", inputPath, err)
		os.Exit(2)
	}

	// Determine output writer.
	var out *os.File
	if len(os.Args) >= 3 {
		outputPath := os.Args[2]
		out, err = os.Create(outputPath)
		if err != nil {
			fmt.Fprintf(os.Stderr, "[emit] ERROR: cannot create %s: %v\n", outputPath, err)
			os.Exit(3)
		}
		defer out.Close()
	} else {
		out = os.Stdout
	}

	// Emit JSONL.
	result, err := canon.WriteJSONL(out, entries)
	if err != nil {
		fmt.Fprintf(os.Stderr, "[emit] ERROR: %v\n", err)
		os.Exit(3)
	}

	// Report on stderr.
	fmt.Fprintf(os.Stderr, "[emit] %s\n", result.Summary())

	// S19: log validation errors for observability.
	for _, ve := range result.ValidationErrors {
		fmt.Fprintf(os.Stderr, "[emit] REJECTED: %s\n", ve)
	}
}
