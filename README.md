# tiddly-data-converter

Repositorio local-first para extraer, canonizar, derivar, auditar y revertir
un corpus TiddlyWiki sin perder trazabilidad ni reversibilidad.

---

## Layout de datos

`data/` usa solo dos raíces activas:

| Ruta | Rol |
|---|---|
| `data/in/` | entradas locales, incluido el HTML vivo |
| `data/out/local/` | zona de salida gobernada: canon, derivados, reverse y export |

Dentro de `data/out/local/`:

| Subcarpeta | Rol |
|---|---|
| `tiddlers_*.jsonl` | canon local — fuente de verdad única |
| `enriched/` | capa derivada A: enriquecimiento estructural |
| `ai/` | capa derivada B: preparación para RAG y chunking |
| `audit/` | capa de auditoría normativa |
| `export/` | artefactos de exportación puntual |
| `reverse_html/` | HTML reconstruido desde el canon — no es fuente de verdad |
| `proposals.jsonl` | buffer legado y extraordinario — no es ruta diaria de cierre |

`data/out/remote/` queda reservado para proyección o intercambio remoto.

---

## Preparación

Los comandos de Go y Rust requieren cache local escribible:

```bash
export GOCACHE=/tmp/tdc-go-build
export CARGO_TARGET_DIR=/tmp/tdc-cargo-target
mkdir -p "$GOCACHE" "$CARGO_TARGET_DIR"
```

El HTML vivo esperado por defecto:

```
data/in/tiddly-data-converter (Saved).html
```

---

## I. Exportar del canon

El canon local es el conjunto shardeado `data/out/local/tiddlers_*.jsonl`.
Todo el trabajo del repositorio parte de este canon o termina en él.

Esta sección explica cómo se construye el canon desde el HTML vivo,
cómo se valida, y qué artefactos de exportación se pueden producir a partir de él.

### I.1 Construir el canon desde HTML

El flujo convierte el HTML vivo en shards canónicos locales.

**Paso 1. Extraer desde HTML a un JSONL temporal**

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/tdc-go-build go run ./cmd/export_tiddlers \
  --html ../../data/in/'tiddly-data-converter (Saved).html' \
  --out /tmp/tiddlers.export.jsonl \
  --log /tmp/tiddlers.export.log \
  --manifest /tmp/tiddlers.export.manifest.json
```

Produce: un JSONL temporal en `/tmp/`, una línea por tiddler.

**Paso 2. Shardizar el JSONL en el canon local**

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/shard_canon \
  --input /tmp/tiddlers.export.jsonl \
  --out-dir ../../data/out/local
```

Produce: `data/out/local/tiddlers_1.jsonl` … `tiddlers_7.jsonl`.

**Paso 3. Validar el canon**

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode strict \
  --input ../../data/out/local
```

Si `data/out/local/` no contiene los siete shards, `canon_preflight` falla con `missing-shards`.

### I.2 Export S33

Atajo para regenerar y verificar el export puntual S33:

```bash
bash shell_scripts/export_s33_regen.sh
bash shell_scripts/export_s33_verify.sh
```

Primero `export_s33_regen.sh`, después `export_s33_verify.sh`.

Artefactos producidos en `data/out/local/export/`:

- `s33-functional-tiddlers.jsonl`
- `s33-export-log.jsonl`
- `s33-manifest.json`

### I.3 Bootstrap mínimo de pipeline

Para un flujo de inspección o costura mínima (Extractor → Doctor → Ingesta → Canon JSONL):

```bash
bash shell_scripts/run_pipeline.sh
```

Escribe en `data/out/local/pipeline/`. No reemplaza la shardización del canon local.
Si se pasa `--audit` o `--audit-apply`, el auditor normativo opera sobre `data/out/local`.

---

## II. Derivados del canon

Los derivados son capas producidas a partir del canon establecido.
Nunca son fuente de verdad: son subordinados al canon.

El entrypoint principal es `python_scripts/derive_layers.py`:

```bash
python3 python_scripts/derive_layers.py \
  --input-dir data/out/local \
  --enriched-dir data/out/local/enriched \
  --ai-dir data/out/local/ai \
  --reports-dir data/out/local/ai/reports \
  --chunk-target-tokens 1800 \
  --chunk-max-tokens 4000
```

### II.1 Capas derivadas

| Capa | Ubicación | Rol |
|---|---|---|
| `enriched` | `data/out/local/enriched/` | Enriquecimiento estructural: metadatos, roles, estados |
| `ai` | `data/out/local/ai/` | Preparación RAG: registros listos para embeddings |
| `chunks` | `data/out/local/ai/chunks_ai_*.jsonl` | Fragmentos trazables al nodo fuente |

Artefactos producidos:

- `data/out/local/enriched/tiddlers_enriched_*.jsonl`
- `data/out/local/enriched/manifest.json`
- `data/out/local/ai/tiddlers_ai_*.jsonl`
- `data/out/local/ai/chunks_ai_*.jsonl`
- `data/out/local/ai/manifest.json`
- `data/out/local/ai/reports/*.json`

### II.2 Política de chunking

- El chunking parte del canon local, no de `enriched/` ni de `ai/`.
- El estimador de tokens es local y proxy-aware; no depende de tokenizadores remotos.
- El chunker refina por fronteras útiles: secciones, párrafos, oraciones y, en código, bloques estructurales.
- Cada chunk queda trazable al nodo fuente mediante `source_id`, `tiddler_id`, `source_anchor`, `section_path` y `taxonomy_path`.
- Nodos `status:archival-only` y artefactos históricos `out/*.json` / `out/*.html` quedan fuera del chunking para no distorsionar RAG.

### II.3 Gobernanza de derivados

La gramática estructural activa del corpus vive en:

- `contratos/policy/canon_policy_bundle.json`: define `corpus_state`, reglas de resolución y compuertas de promoción.
- `contratos/projections/derived_layers_registry.json`: declara autoridad y linaje entre capas.

Estados gobernados:

| Estado | Descripción |
|---|---|
| `general` | Fallback para nodos sin evidencia estructural fuerte |
| `repo_path` | Nodo path-like sin tag explícito de vigencia |
| `live_path` | Nodo marcado vivo con `state:live-path` |
| `historical_snapshot` | Snapshot histórico o supersedido |
| `historical_artifact` | Artefacto legacy `out/*.json` o `out/*.html` |
| `archival_only` | Preservado en canon pero fuera de derivados generales |

Validación de gobernanza:

```bash
python3 python_scripts/validate_corpus_governance.py \
  --canon-dir data/out/local \
  --ai-dir data/out/local/ai
```

### II.4 Auditoría normativa

La auditoría verifica coherencia entre el canon y sus capas derivadas.

Solo inspección:

```bash
python3 python_scripts/audit_normative_projection.py \
  --mode audit \
  --input-root data/out/local \
  --docs-root docs
```

Inspección + safe fixes + regeneración:

```bash
python3 python_scripts/audit_normative_projection.py \
  --mode apply \
  --input-root data/out/local \
  --docs-root docs
```

Salidas en `data/out/local/audit/`:

- `manifest.json`, `compliance_report.json`, `compliance_summary.md`
- `proposed_fixes.json`, `applied_safe_fixes.json`, `pre_post_diff.json`

---

## III. Reverse y tipos de reverse

Reverse es el proceso inverso: reconstruye un HTML funcional a partir del canon local.
El HTML resultante es una proyección reversible, no una fuente autoritativa.
`reverse_tiddlers` nunca escribe ni modifica `data/out/local/tiddlers_*.jsonl`.

### III.1 Preflight antes de reverse

El reverse exige que el canon pase una validación específica antes de ejecutarse:

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode reverse-preflight \
  --input ../../data/out/local
```

Si `canon_preflight --mode reverse-preflight` reporta `duplicate-title`, `duplicate-key`
o líneas mal formadas, el reverse aborta sin escribir HTML.

### III.2 Ejecutar reverse

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/tdc-go-build go run ./cmd/reverse_tiddlers \
  --html ../../data/in/'tiddly-data-converter (Saved).html' \
  --canon ../../data/out/local \
  --out-html ../../data/out/local/reverse_html/tiddly-data-converter.derived.html \
  --report ../../data/out/local/reverse_html/reverse-report.json \
  --mode authoritative-upsert
```

Salidas en `data/out/local/reverse_html/`:

- `tiddly-data-converter.derived.html`
- `reverse-report.json`

### III.3 Tipos de reverse

| Modo | Comportamiento |
|---|---|
| `authoritative-upsert` | Inserta tiddlers nuevos y actualiza los ya presentes en el HTML base. Modo recomendado. |
| `insert-only` | Solo inserta títulos nuevos. Nunca actualiza los ya presentes en el HTML base. |

Usar `insert-only` únicamente cuando se quiera impedir la actualización de títulos que ya existen en el HTML base.

---

## Cierre semántico de sesión

La ruta diaria de cierre es directamente en canon, no en `proposals.jsonl`.

**Ruta diaria:** escribir en `data/out/local/tiddlers_*.jsonl` y validar:

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode strict \
  --input ../../data/out/local
```

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode reverse-preflight \
  --input ../../data/out/local
```

**Ruta extraordinaria:** `data/out/local/proposals.jsonl` solo para recuperación manual
o lotes excepcionales que no deban absorberse aún al canon base.

Uso extraordinario de propuestas:

```bash
python3 python_scripts/canon_proposal.py create \
  --session m03-s49-mcp-onedrive-canon-proposals-v0 \
  --payload-file tests/fixtures/s49/candidate_line.json \
  --canon-dir data/out/local \
  --output /tmp/manual-recovery.proposals.jsonl

python3 python_scripts/canon_proposal.py validate \
  --proposal-file /tmp/manual-recovery.proposals.jsonl \
  --canon-dir data/out/local
```

---

## Validación local

Suites principales:

```bash
cd go/canon && env GOCACHE=/tmp/tdc-go-build go test ./... -count=1
cd /repositorios/tiddly-data-converter/go/bridge && env GOCACHE=/tmp/tdc-go-build go test ./... -count=1
cd /repositorios/tiddly-data-converter/go/ingesta && env GOCACHE=/tmp/tdc-go-build go test ./... -count=1
cd /repositorios/tiddly-data-converter/rust/extractor && env CARGO_TARGET_DIR=/tmp/tdc-cargo-target cargo test
cd /repositorios/tiddly-data-converter/rust/doctor && env CARGO_TARGET_DIR=/tmp/tdc-cargo-target cargo test
```

Checks útiles:

```bash
bash tests/fixtures/s49/run_canon_proposal_test.sh
bash tests/fixtures/s47/run_audit_test.sh
env GOCACHE=/tmp/tdc-go-build-smoke CARGO_TARGET_DIR=/tmp/tdc-cargo-target-smoke bash tests/smoke/test_pipeline_smoke.sh
```

Entry points operativos:

```bash
bash shell_scripts/run_pipeline.sh
python3 python_scripts/derive_layers.py
python3 python_scripts/validate_corpus_governance.py --canon-dir data/out/local --ai-dir data/out/local/ai
python3 python_scripts/audit_normative_projection.py --mode audit --input-root data/out/local --docs-root docs
python3 python_scripts/canon_proposal.py validate --proposal-file /tmp/manual-recovery.proposals.jsonl --canon-dir data/out/local
```

---

## Referencias activas

- `.github/instructions/tiddlers_sesiones.instructions.md`
- `esquemas/canon/canon_guarded_session_rules.md`
- `contratos/policy/canon_policy_bundle.json`
- `contratos/projections/derived_layers_registry.json`
- `python_scripts/validate_corpus_governance.py`
- `python_scripts/path_governance.py`
