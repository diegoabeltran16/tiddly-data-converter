# tiddly-data-converter

## Flujo operativo S44

La fuente de verdad operativa es el canon fragmentado:

- `out/tiddlers_1.jsonl`
- `out/tiddlers_2.jsonl`
- `out/tiddlers_3.jsonl`
- `out/tiddlers_4.jsonl`
- `out/tiddlers_5.jsonl`
- `out/tiddlers_6.jsonl`
- `out/tiddlers_7.jsonl`

`out/tiddlers.jsonl` ya no es el artefacto operativo principal. Si hace falta una vista monolítica para export o validación, se genera solo como artefacto temporal local.

## 1. Export temporal desde HTML

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go run ./cmd/export_tiddlers \
  --html "../../data/tiddly-data-converter (Saved).html" \
  --out "/tmp/tiddlers.export.jsonl" \
  --log "../../out/export.log" \
  --manifest "../../out/manifest.json"
```

## 2. Fragmentar el canon al layout S44

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/go-build go run ./cmd/shard_canon \
  --input "/tmp/tiddlers.export.jsonl" \
  --out-dir "../../out"
```

Política de fragmentación S44:

- `tiddlers_2.jsonl`: `#### 🌀 Sesión ...`
- `tiddlers_3.jsonl`: bloque fijo de dependencias (`#### 🌀📦 ...`) + `#### 🌀🧪 Hipótesis de sesión ...`
- `tiddlers_4.jsonl`: `#### 🌀🧾 Procedencia de sesión ...` + bloque bibliográfico (`#### 📚 Diccionario 🌀.csv`, `#### referencias especificas 🌀`, referencias numeradas `NN. ...`)
- `tiddlers_1.jsonl`, `tiddlers_5.jsonl`, `tiddlers_6.jsonl`, `tiddlers_7.jsonl`: resto del corpus en orden estable

El helper conserva las líneas del canon sin reserializarlas y falla si el corpus restante excede la capacidad actual del layout S44.

## 3. Validar el canon fragmentado

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/go-build go run ./cmd/canon_preflight \
  --mode strict \
  --input "../../out"
```

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/go-build go run ./cmd/canon_preflight \
  --mode reverse-preflight \
  --input "../../out"
```

`canon_preflight` acepta un archivo JSONL único o un directorio con shards `tiddlers_<n>.jsonl`. En modo shard valida parseo, orden estable, duplicados accidentales de shard, duplicados exactos de línea y duplicados de `title`/`key` antes de correr la validación del canon combinado.

## 4. Reverse desde shards

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go run ./cmd/reverse_tiddlers \
  --html "../../data/tiddly-data-converter (Saved).html" \
  --canon "../../out" \
  --out-html "../../out/tiddly-data-converter.derived.html" \
  --report "../../out/reverse-report.json" \
  --mode authoritative-upsert
```

`authoritative-upsert`:

- preserva el shell HTML y solo actualiza el store
- usa autoridad desde `title`, `text`, `created`, `modified`, `source_type`, `source_tags`
- usa `source_fields` solo para campos extra válidos y no derivados
- actualiza títulos existentes cuando el canon autoritativo cambió
- inserta títulos nuevos cuando no existen
- deja fuera de scope system tiddlers, binarios, nodos `reference_only` y `source_type` fuera del alcance textual/metadata actual

## 5. Verificación de round-trip local

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go run ./cmd/export_tiddlers \
  --html "../../out/tiddly-data-converter.derived.html" \
  --out "/tmp/tiddlers.roundtrip.jsonl" \
  --log "../../out/roundtrip.export.log" \
  --manifest "../../out/roundtrip.manifest.json"
```

## Artefactos esperados

- canon autoritativo: `out/tiddlers_1.jsonl` ... `out/tiddlers_7.jsonl`
- manifest del export base: `out/manifest.json`
- log del export base: `out/export.log`
- HTML derivado: `out/tiddly-data-converter.derived.html`
- reporte auditable de reverse: `out/reverse-report.json`
- manifest/log del round-trip local: `out/roundtrip.manifest.json`, `out/roundtrip.export.log`

## Notas operativas

- Los archivos en `/tmp` son temporales y prescindibles.
- `content.plain`, `normalized_tags`, `semantic_text` y demás derivados no son autoridad de reverse.
- Si un shard directory falla preflight, no se debe normalizar ni reescribir en silencio: primero hay que corregir la anomalía fuente.
