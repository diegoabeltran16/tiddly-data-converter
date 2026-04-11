// cmd/ingest/main.go — CLI mínima de Ingesta
//
// Uso: ingest <raw_path>
//
// Lee el artefacto raw (raw.tiddlers.json) validado por el Doctor y aplica
// la transformación semántica pre-canónica. Emite el reporte por stderr y
// escribe los tiddlers transformados como JSON en stdout.
//
// Código de salida:
//   0 — ingestión completada (ok, warning o error semántico no fatal)
//   1 — argumentos incorrectos
//   2 — error fatal de ingestión (archivo no encontrado, JSON inválido)
//   3 — error al serializar salida
//
// Ref: contratos/m01-s12-pipeline-costura.md.json

package main

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/tiddly-data-converter/ingesta"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "[ingesta] uso: ingest <raw_path>")
		os.Exit(1)
	}
	rawPath := os.Args[1]

	tiddlers, report, err := ingesta.Ingest(rawPath, ingesta.OriginHTML)
	if err != nil {
		fmt.Fprintf(os.Stderr, "[ingesta] ERROR: %v\n", err)
		os.Exit(2)
	}

	fmt.Fprintf(
		os.Stderr,
		"[ingesta] verdict=%s tiddlers=%d ingested=%d skipped=%d warnings=%d errors=%d\n",
		report.Verdict,
		report.TiddlerCount,
		report.IngestedCount,
		report.SkippedCount,
		len(report.Warnings),
		len(report.Errors),
	)
	for _, w := range report.Warnings {
		fmt.Fprintf(os.Stderr, "[ingesta] WARN: %s\n", w)
	}
	for _, e := range report.Errors {
		fmt.Fprintf(os.Stderr, "[ingesta] ERR: %s\n", e)
	}

	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(tiddlers); err != nil {
		fmt.Fprintf(os.Stderr, "[ingesta] ERROR al serializar tiddlers: %v\n", err)
		os.Exit(3)
	}
}
