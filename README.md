# tiddly-data-converter

## Export local del canon

Genera el canon base desde el HTML real sin tocar la red:

```bash
cd /repositorios/tiddly-data-converter/go/bridge
mkdir -p ../../out
env GOCACHE=/tmp/go-build go run ./cmd/export_tiddlers \
  --html "../../data/tiddly-data-converter (Saved).html" \
  --out "../../out/tiddlers.jsonl" \
  --log "../../out/export.log" \
  --manifest "../../out/manifest.json"
```

## Reverse textual robusto

Hace esto:

- usa `data/tiddly-data-converter (Saved).html` como HTML base real
- lee `out/tiddlers.jsonl` como canon mixto
- detecta solo raw-tiddlers agregados al canon
- inserta tiddlers textuales nuevos en modo `insert-only`
- preserva el HTML base fuera del store
- admite `source_fields` solo como autoridad opcional y controlada

No hace esto:

- no reconstruye el HTML completo desde cero
- no sobrescribe títulos ya existentes
- no materializa binarios ni system tiddlers `$:/...`
- no usa `content.plain`, `normalized_tags`, `semantic_text` ni otros derivados como autoridad

HTML base actual:

- `data/tiddly-data-converter (Saved).html`

Canon de entrada:

- `out/tiddlers.jsonl`
- debe ser un canon mixto ya aumentado con raw-tiddlers válidos; S43 deja un ejemplo local en `out/s43-raw-tiddlers.jsonl`

Generar el HTML derivado:

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go run ./cmd/reverse_tiddlers \
  --html "../../data/tiddly-data-converter (Saved).html" \
  --canon "../../out/tiddlers.jsonl" \
  --out-html "../../out/tiddly-data-converter.derived.html" \
  --report "../../out/reverse-report.json" \
  --mode insert-only
```

Validar round-trip local:

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go run ./cmd/export_tiddlers \
  --html "../../out/tiddly-data-converter.derived.html" \
  --out "../../out/roundtrip.tiddlers.jsonl" \
  --log "../../out/roundtrip.export.log" \
  --manifest "../../out/roundtrip.manifest.json"
```

Revisar evidencia rápida del round-trip:

```bash
cd /repositorios/tiddly-data-converter
rg -n 'Sesión 43|Hipótesis de sesión 43|Procedencia de sesión 43|m03-s43-canon-robust-textual-reverse-v0' out/roundtrip.tiddlers.jsonl
```
