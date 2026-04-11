// Package bridge implements the minimal conversion layer between the
// pre-canonical output of Ingesta and the canonical entry shape required
// by Canon.
//
// This package is the S14 integration point. It does NOT redefine Canon
// internals (identity, collision, or policy). It simply converts shapes
// and invokes the existing Canon bootstrap logic for admission.
//
// Contract reference: contratos/m01-s14-bridge-ingesta-canon.md.json
// Ref: S13 §6 — conversion of ingesta.Tiddler to CanonEntry is the
// responsibility of the Bridge or the integration layer.
package bridge

import (
	"github.com/tiddly-data-converter/canon"
	"github.com/tiddly-data-converter/ingesta"
)

// ToCanonEntry converts a single pre-canonical ingesta.Tiddler into
// the canon.CanonEntry shape expected by the Canon bootstrap.
//
// The mapping is minimal and faithful:
//   - Key is derived via canon.KeyOf(title) — no custom normalization.
//   - Title, Text, SourcePosition are carried over directly.
//   - Fields, Tags, timestamps, Type, OriginFormat are NOT carried into
//     CanonEntry because the S13 canonical shape does not include them yet.
//     They are not lost — they remain in the Ingesta artifact.
//
// Ref: S13 §B — CanonEntry shape.
// Ref: S05 §5 — Tiddler shape.
func ToCanonEntry(t ingesta.Tiddler) canon.CanonEntry {
	return canon.CanonEntry{
		Key:            canon.KeyOf(t.Title),
		Title:          t.Title,
		Text:           t.Text,
		SourcePosition: t.SourcePosition,
	}
}

// ToCanonEntries converts a batch of pre-canonical ingesta.Tiddler values
// into their corresponding canon.CanonEntry values.
//
// Order is preserved: output[i] corresponds to input[i].
func ToCanonEntries(tiddlers []ingesta.Tiddler) []canon.CanonEntry {
	entries := make([]canon.CanonEntry, len(tiddlers))
	for i, t := range tiddlers {
		entries[i] = ToCanonEntry(t)
	}
	return entries
}
