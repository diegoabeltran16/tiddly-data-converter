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

## 6. Derivación local (capas enriquecida y AI-friendly)

El entrypoint estable para derivación local es `scripts/derive_layers.py` (S46+).

### ¿Qué genera cada capa?

| Capa | Descripción | Directorio |
|------|-------------|------------|
| **Canon** | Fuente de verdad autoritativa fragmentada. No tocar directamente. | `out/tiddlers_*.jsonl` |
| **Enriched** | Capa A: copia enriquecida del canon con campos derivados deterministas (`preview_text`, `semantic_text`, `secondary_roles`, `quality_flags`, `taxonomy_path` mejorado). | `out/enriched/` |
| **AI-friendly** | Capa B: proyección compacta orientada a ingesta por IA. Incluye `ai_summary`, `retrieval_terms`, `retrieval_aliases`, relaciones validadas y señales de clasificación semántica. | `out/ai/` |
| **Chunks** | Fragmentación jerárquica del contenido textual largo. Hard max: 4000 tokens. | `out/ai/chunks_ai_*.jsonl` |
| **QC Reports** | Reportes de calidad auditables: clasificación, chunking, retrieval, relaciones. | `out/ai/reports/` |

### Archivos de salida

```
out/enriched/
  tiddlers_enriched_1.jsonl  ...  tiddlers_enriched_N.jsonl
  manifest.json

out/ai/
  tiddlers_ai_1.jsonl  ...  tiddlers_ai_N.jsonl
  chunks_ai_1.jsonl    ...  chunks_ai_M.jsonl
  manifest.json
  reports/
    classification_report.json
    chunk_qc_report.json
    retrieval_qc_report.json
    relations_qc_report.json
    derivation_report.json
```

### Ejecución de la derivación local

```bash
python3 scripts/derive_layers.py \
  --input-dir out \
  --enriched-dir out/enriched \
  --ai-dir out/ai
```

Con parámetros explícitos:

```bash
python3 scripts/derive_layers.py \
  --input-dir out \
  --enriched-dir out/enriched \
  --ai-dir out/ai \
  --reports-dir out/ai/reports \
  --chunk-target-tokens 1800 \
  --chunk-max-tokens 4000 \
  --tiddler-shard-size 100 \
  --chunk-shard-size 200
```

Con guardrail estricto (falla si algún chunk supera el hard max):

```bash
python3 scripts/derive_layers.py \
  --input-dir out \
  --enriched-dir out/enriched \
  --ai-dir out/ai \
  --fail-on-chunk-violation
```

### Si ya existen artefactos

El script siempre sobreescribe los artefactos existentes en `out/enriched/` y `out/ai/`. No es necesario borrarlos antes. Para hacer explícita la sobreescritura voluntaria, se puede usar `--overwrite`.

### Qué revisar después de ejecutar

1. **Manifests**: `out/enriched/manifest.json` y `out/ai/manifest.json` — confirmar `total_records` y `shard_count`.
2. **`classification_report.json`** — revisar `role_primary_distribution`, `unclassified_count`, cobertura de `taxonomy_path` y `section_path`.
3. **`chunk_qc_report.json`** — confirmar `chunks_above_hard_max: 0` (hard max jamás debe violarse).
4. **`retrieval_qc_report.json`** — revisar `avg_hints_per_node` y `nodes_with_empty_hints`.
5. **`relations_qc_report.json`** — revisar `total_invalid_relations_discarded`.

### Compatibilidad con S45

`scripts/s45_derive_layers.py` es ahora un wrapper de compatibilidad que redirige a `derive_layers.py`. No usarlo directamente para trabajo nuevo.

---

## Notas operativas

- Los archivos en `/tmp` son temporales y prescindibles.
- `content.plain`, `normalized_tags`, `semantic_text` y demás derivados no son autoridad de reverse.
- Si un shard directory falla preflight, no se debe normalizar ni reescribir en silencio: primero hay que corregir la anomalía fuente.
- La derivación local (capas enriched y AI) no modifica el canon. Siempre puede regenerarse desde `out/tiddlers_*.jsonl`.
