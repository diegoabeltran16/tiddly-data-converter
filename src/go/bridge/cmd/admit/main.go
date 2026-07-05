// cmd/admit/main.go — CLI mínima del bridge Ingesta → Canon
//
// Uso: admit <ingesta_json>
//
// Lee el artefacto pre-canónico (ingesta.tiddlers.json) producido por la
// Ingesta, convierte cada tiddler a CanonEntry vía el bridge, ejecuta la
// admisión con clasificación de colisiones, y emite el reporte por stderr.
// Escribe las CanonEntries como JSON en stdout.
//
// Código de salida:
//   0 — admisión completada
//   1 — argumentos incorrectos
//   2 — error fatal al leer o parsear el archivo
//   3 — error al serializar salida
//
// Ref: contratos/m01-s14-bridge-ingesta-canon.md.json
package main

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/tiddly-data-converter/bridge"
	"github.com/tiddly-data-converter/ingesta"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "[bridge] uso: admit <ingesta_json>")
		os.Exit(1)
	}
	ingestaPath := os.Args[1]

	// Read the ingesta artifact.
	data, err := os.ReadFile(ingestaPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "[bridge] ERROR: cannot read %s: %v\n", ingestaPath, err)
		os.Exit(2)
	}

	var tiddlers []ingesta.Tiddler
	if err := json.Unmarshal(data, &tiddlers); err != nil {
		fmt.Fprintf(os.Stderr, "[bridge] ERROR: invalid JSON in %s: %v\n", ingestaPath, err)
		os.Exit(2)
	}

	// Step 1: convert Ingesta → Canon.
	entries := bridge.ToCanonEntries(tiddlers)

	// Step 2: run admission (collision classification).
	report := bridge.Admit(entries)

	// Emit report on stderr.
	fmt.Fprintf(os.Stderr, "[bridge] %s\n", report.Summary())
	for _, c := range report.Collisions {
		fmt.Fprintf(os.Stderr, "[bridge] collision: %s (%q vs %q) disposition=%s note=%q\n",
			c.Result.Class, c.TitleA, c.TitleB, c.Result.Disposition, c.Result.Note)
	}

	// Write entries to stdout.
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(entries); err != nil {
		fmt.Fprintf(os.Stderr, "[bridge] ERROR: cannot serialize output: %v\n", err)
		os.Exit(3)
	}
}
