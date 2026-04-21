# tiddly-data-converter

Repositorio local-first para extraer, canonizar, derivar, auditar y revertir
un corpus TiddlyWiki sin perder trazabilidad ni reversibilidad.

## Layout operativo

`data/` usa solo tres raíces:

| Ruta | Rol |
|---|---|
| `data/in/` | entradas locales, incluido el HTML vivo |
| `data/out/` | zona de salida gobernada, dividida en `local/` y `remote/` |
| `data/reverse_html/` | HTML derivado por reverse y su reporte |

Regla central:

- `data/out/local/tiddlers_*.jsonl` es la fuente de verdad.
- `data/out/local/enriched/`, `data/out/local/ai/` y `data/out/local/audit/` son derivados locales.
- `data/out/local/proposals.jsonl` acumula las líneas de propuestas canonizadas, incluidas líneas de sesión y de dependencias.
- `data/out/remote/` queda reservado para proyección o intercambio remoto.
- `data/reverse_html/` no es canon; es salida de reverse

## Qué hace hoy

- extrae tiddlers desde HTML local
- ejecuta doctor e ingesta
- admite entradas a canon y emite JSONL
- valida el canon shardeado
- genera capas `enriched`, `ai`, `chunks` y reportes de auditoría
- ejecuta reverse desde canon hacia HTML
- permite emitir líneas JSONL de sesión ya canonizadas y compatibles con canon

## Preparación rápida

Los comandos de Go y Rust funcionan mejor si fijan cache local escribible:

```bash
export GOCACHE=/tmp/tdc-go-build
export CARGO_TARGET_DIR=/tmp/tdc-cargo-target
mkdir -p "$GOCACHE" "$CARGO_TARGET_DIR"
```

El HTML vivo esperado por defecto es:

- `data/in/tiddly-data-converter (Saved).html`

## Flujo recomendado

Flujo operativo normal:

1. Exportar desde `data/in/` a un JSONL temporal.
2. Shardizar ese JSONL hacia `data/out/local/tiddlers_*.jsonl`.
3. Validar el canon local con `canon_preflight --mode strict`.
4. Generar derivados locales si hacen falta (`enriched`, `ai`, `chunks`, `audit`).
5. Validar `reverse-preflight` y ejecutar reverse hacia `data/reverse_html/`.

La diferencia importante es esta:

- `export_tiddlers` produce un JSONL temporal o de export.
- `shard_canon` convierte ese export en el canon operativo local.
- `reverse_tiddlers` nunca escribe canon; solo proyecta HTML derivado.

## Canon local

La fuente de verdad local es el conjunto shardeado:

- `data/out/local/tiddlers_1.jsonl`
- `data/out/local/tiddlers_2.jsonl`
- `data/out/local/tiddlers_3.jsonl`
- `data/out/local/tiddlers_4.jsonl`
- `data/out/local/tiddlers_5.jsonl`
- `data/out/local/tiddlers_6.jsonl`
- `data/out/local/tiddlers_7.jsonl`

Si `data/out/local/` no contiene esos shards, `canon_preflight` va a fallar
correctamente con `missing-shards`.

Validación estricta del canon:

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode strict \
  --input ../../data/out/local
```

Chequeo previo para reverse:

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode reverse-preflight \
  --input ../../data/out/local
```

## Flujo de exportación

Este flujo es el correcto cuando se quiere reconstruir o regenerar el canon
local desde el HTML vivo.

Paso 1. Exportar desde HTML a un JSONL temporal.
Qué hace:

- extrae el store del HTML
- filtra tiddlers funcionales
- ejecuta ingesta y bridge
- emite un JSONL plano con una línea por tiddler

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/tdc-go-build go run ./cmd/export_tiddlers \
  --html ../../data/in/'tiddly-data-converter (Saved).html' \
  --out /tmp/tiddlers.export.jsonl \
  --log /tmp/tiddlers.export.log \
  --manifest /tmp/tiddlers.export.manifest.json
```

Paso 2. Convertir ese export temporal en shards canónicos.
Qué hace:

- lee el JSONL exportado
- distribuye por el layout canónico vigente
- escribe `tiddlers_*.jsonl` en `data/out/local/`

Importante:

- este paso se ejecuta desde `go/canon`, no desde `go/bridge`

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/shard_canon \
  --input /tmp/tiddlers.export.jsonl \
  --out-dir ../../data/out/local
```

Paso 3. Validar el resultado antes de seguir:

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode strict \
  --input ../../data/out/local
```

Atajo soportado para la exportación S33:

```bash
bash scripts/export_s33_regen.sh
bash scripts/export_s33_verify.sh
```

Orden correcto:

- primero `export_s33_regen.sh`
- después `export_s33_verify.sh`

Artefactos:

- `data/out/local/export/s33-functional-tiddlers.jsonl`
- `data/out/local/export/s33-export-log.jsonl`
- `data/out/local/export/s33-manifest.json`

## Flujo de reverse

El reverse siempre parte del canon local validado y nunca reescribe
`data/out/local/tiddlers_*.jsonl`.

Paso 1. Certificar que el canon es reverse-ready:

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode reverse-preflight \
  --input ../../data/out/local
```

Paso 2. Ejecutar reverse hacia `data/reverse_html/`.
Qué hace:

- lee el HTML base en `data/in/`
- compara contra el canon en `data/out/local/`
- inserta o actualiza solo lo autorizado por el contrato de reverse
- escribe un HTML derivado y un reporte auditable

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/tdc-go-build go run ./cmd/reverse_tiddlers \
  --html ../../data/in/'tiddly-data-converter (Saved).html' \
  --canon ../../data/out/local \
  --out-html ../../data/reverse_html/tiddly-data-converter.derived.html \
  --report ../../data/reverse_html/reverse-report.json \
  --mode authoritative-upsert
```

Salidas:

- `data/reverse_html/tiddly-data-converter.derived.html`
- `data/reverse_html/reverse-report.json`

Modo recomendado: `authoritative-upsert`

Usar `insert-only` solo cuando se quiera impedir actualización de títulos ya
presentes en el HTML base.

## Derivados locales

El entrypoint estable es `scripts/derive_layers.py`.

```bash
python3 scripts/derive_layers.py
```

Ejecución explícita:

```bash
python3 scripts/derive_layers.py \
  --input-dir data/out/local \
  --enriched-dir data/out/local/enriched \
  --ai-dir data/out/local/ai \
  --reports-dir data/out/local/ai/reports \
  --chunk-target-tokens 1800 \
  --chunk-max-tokens 4000
```

Artefactos derivados esperados:

- `data/out/local/enriched/tiddlers_enriched_*.jsonl`
- `data/out/local/enriched/manifest.json`
- `data/out/local/ai/tiddlers_ai_*.jsonl`
- `data/out/local/ai/chunks_ai_*.jsonl`
- `data/out/local/ai/manifest.json`
- `data/out/local/ai/reports/*.json`

Política vigente de chunking:

- el chunking parte del canon local y no de atajos desde `enriched/` o `ai/`
- el estimador es local y token-aware por proxy; no usa un tokenizador remoto
- el chunker refina por fronteras útiles: secciones, párrafos, oraciones y, en código, bloques estructurales
- cada chunk queda trazable al nodo fuente mediante `source_id`, `tiddler_id`, `source_anchor`, `section_path` y `taxonomy_path`
- nodos marcados `status:archival-only` y artefactos históricos `out/*.json` o `out/*.html` quedan fuera del chunking general para no distorsionar RAG
- que un nodo quede fuera del chunking no significa que deje de existir en canon; solo cambia su elegibilidad dentro de la capa `ai/chunks`

## Auditoría normativa

Solo auditoría:

```bash
python3 scripts/audit_normative_projection.py \
  --mode audit \
  --input-root data/out/local \
  --docs-root docs
```

Auditoría con safe fixes y regeneración:

```bash
python3 scripts/audit_normative_projection.py \
  --mode apply \
  --input-root data/out/local \
  --docs-root docs
```

Salidas:

- `data/out/local/audit/manifest.json`
- `data/out/local/audit/compliance_report.json`
- `data/out/local/audit/compliance_summary.md`
- `data/out/local/audit/proposed_fixes.json`
- `data/out/local/audit/applied_safe_fixes.json`
- `data/out/local/audit/pre_post_diff.json`

## Propuestas de sesión

Las propuestas ya no usan un sobre JSON separado ni un archivo por sesión.
Se acumulan como líneas JSONL ya canonizadas, con la forma completa del canon,
en `data/out/local/proposals.jsonl`.

Agregar propuestas canonizadas:

```bash
python3 scripts/canon_proposal.py create \
  --session m03-s49-mcp-onedrive-canon-proposals-v0 \
  --payload-file tests/fixtures/s49/candidate_line.json \
  --canon-dir data/out/local
```

Eso agrega líneas por defecto a:

- `data/out/local/proposals.jsonl`

Validar el archivo consolidado de propuestas:

```bash
python3 scripts/canon_proposal.py validate \
  --proposal-file data/out/local/proposals.jsonl \
  --canon-dir data/out/local
```

Si una propuesta reutiliza una línea ya existente del canon, usar
`--allow-existing`.

La validación ahora exige que el archivo ya esté canonizado: si el normalizador
del canon todavía corregiría `id`, `canonical_slug`, `version_id`,
`normalized_tags` o `content.plain`, el archivo se rechaza.

Lo que no debe hacerse por defecto:

- escribir directo en `data/out/local/tiddlers_*.jsonl`
- tratar `data/reverse_html/` como fuente de verdad
- usar `data/out/remote/` como fuente de verdad local

## Pipeline bootstrap

`scripts/run_pipeline.sh` sigue existiendo para el flujo mínimo
Extractor -> Doctor -> Ingesta -> Canon JSONL bootstrap.

Por defecto:

```bash
bash scripts/run_pipeline.sh
```

Notas:

- toma por defecto `data/in/tiddly-data-converter (Saved).html`
- escribe por defecto en `data/out/local/pipeline/`
- si se usa `--audit` o `--audit-apply`, el auditor opera sobre `data/out/local`
- no reemplaza la shardización del canon local; deja un bootstrap monolítico para inspección o costura mínima

## Export S33

Regeneración:

```bash
bash scripts/export_s33_regen.sh
```

Verificación:

```bash
bash scripts/export_s33_verify.sh
```

Los artefactos quedan en `data/out/local/export/`.

## Validación local

Checks útiles ya verificados:

```bash
bash tests/fixtures/s49/run_canon_proposal_test.sh
bash tests/fixtures/s47/run_audit_test.sh
env GOCACHE=/tmp/tdc-go-build-smoke CARGO_TARGET_DIR=/tmp/tdc-cargo-target-smoke bash tests/smoke/test_pipeline_smoke.sh
```

Entry points operativos:

```bash
bash scripts/run_pipeline.sh
python3 scripts/derive_layers.py
python3 scripts/audit_normative_projection.py --mode audit --input-root data/out/local --docs-root docs
python3 scripts/canon_proposal.py validate --proposal-file data/out/local/proposals.jsonl --canon-dir data/out/local
```

Suites principales:

```bash
cd go/canon && env GOCACHE=/tmp/tdc-go-build go test ./... -count=1
cd /repositorios/tiddly-data-converter/go/bridge && env GOCACHE=/tmp/tdc-go-build go test ./... -count=1
cd /repositorios/tiddly-data-converter/go/ingesta && env GOCACHE=/tmp/tdc-go-build go test ./... -count=1
cd /repositorios/tiddly-data-converter/rust/extractor && env CARGO_TARGET_DIR=/tmp/tdc-cargo-target cargo test
cd /repositorios/tiddly-data-converter/rust/doctor && env CARGO_TARGET_DIR=/tmp/tdc-cargo-target cargo test
```

## Referencias activas

- `.github/instructions/tiddlers_sesiones.instructions.md`
- `esquemas/canon/canon_guarded_session_rules.md`
- `contratos/policy/canon_policy_bundle.json`
- `scripts/path_governance.py`
