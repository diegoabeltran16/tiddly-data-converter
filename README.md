# tiddly-data-converter

Repositorio local-first para extraer, canonizar, derivar, auditar y revertir
un corpus TiddlyWiki sin perder trazabilidad ni reversibilidad.

---

## Layout de datos

`data/` usa solo dos raíces activas:

| Ruta | Rol |
|---|---|
| `data/sessions/` | artefactos de sesión, staging operativo y líneas candidatas |
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
| `microsoft_copilot/` | proyección legible para Microsoft Copilot y otros agentes remotos; derivada y no autoritativa |
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
  --microsoft-copilot-dir data/out/local/microsoft_copilot \
  --reports-dir data/out/local/ai/reports \
  --audit-dir data/out/local/audit \
  --export-dir data/out/local/export \
  --chunk-target-tokens 1800 \
  --chunk-max-tokens 4000
```

### II.1 Capas derivadas

| Capa | Ubicación | Rol |
|---|---|---|
| `enriched` | `data/out/local/enriched/` | Enriquecimiento estructural: metadatos, roles, estados |
| `ai` | `data/out/local/ai/` | Preparación RAG: registros listos para embeddings |
| `microsoft_copilot` | `data/out/local/microsoft_copilot/` | Proyección gobernada y legible para Microsoft Copilot y agentes remotos; emite JSON/CSV/TXT y puede arbitrar canon, enriched, ai, audit y export sin ganar autoridad; incluye sublayer `copilot_agent/` con paquete semántico reversible |
| `chunks` | `data/out/local/ai/chunks_ai_*.jsonl` | Fragmentos trazables al nodo fuente |

Artefactos producidos:

- `data/out/local/enriched/tiddlers_enriched_*.jsonl`
- `data/out/local/enriched/manifest.json`
- `data/out/local/ai/tiddlers_ai_*.jsonl`
- `data/out/local/ai/chunks_ai_*.jsonl`
- `data/out/local/ai/manifest.json`
- `data/out/local/ai/reports/*.json`
- `data/out/local/microsoft_copilot/manifest.json`
- `data/out/local/microsoft_copilot/navigation_index.json`
- `data/out/local/microsoft_copilot/entities.json`
- `data/out/local/microsoft_copilot/topics.json`
- `data/out/local/microsoft_copilot/source_arbitration_report.json`
- `data/out/local/microsoft_copilot/nodes.csv`
- `data/out/local/microsoft_copilot/edges.csv`
- `data/out/local/microsoft_copilot/artifacts.csv`
- `data/out/local/microsoft_copilot/coverage.csv`
- `data/out/local/microsoft_copilot/overview.txt`
- `data/out/local/microsoft_copilot/reading_guide.txt`
- `data/out/local/microsoft_copilot/bundles/*.txt`
- `data/out/local/microsoft_copilot/spec/**/*.md`
- `data/out/local/microsoft_copilot/spec/**/*.json`
- `data/out/local/microsoft_copilot/copilot_agent/corpus.txt`
- `data/out/local/microsoft_copilot/copilot_agent/entities.json`
- `data/out/local/microsoft_copilot/copilot_agent/relations.csv`

`data/out/local/microsoft_copilot/` forma parte del flujo de derivación local.
Sigue siendo una proyección derivada y no autoritativa: no reemplaza al canon,
no reemplaza a `enriched/` ni a `ai/`, y no hace writeback al canon. En S61
la salida final de lectura de esta capa deja de ser JSONL: JSON expone
estructura, CSV expone relaciones/tablas y TXT preserva contexto narrativo
seleccionado con punteros explícitos a la fuente canónica.

### II.2 Política de chunking

- El chunking parte del canon local, no de `enriched/` ni de `ai/`.
- El estimador de tokens es local y proxy-aware; no depende de tokenizadores remotos.
- El chunker refina por fronteras útiles: secciones, párrafos, oraciones y, en código, bloques estructurales.
- Cada chunk queda trazable al nodo fuente mediante `source_id`, `tiddler_id`, `source_anchor`, `section_path` y `taxonomy_path`.
- Nodos `status:archival-only` y artefactos históricos `out/*.json` / `out/*.html` quedan fuera del chunking para no distorsionar RAG.

### II.3 Gobernanza de derivados

La gramática estructural activa del corpus vive en:

- `data/sessions/00_contratos/policy/canon_policy_bundle.json`: define `corpus_state`, reglas de resolución y compuertas de promoción.
- `data/sessions/00_contratos/projections/derived_layers_registry.json`: declara autoridad y linaje entre capas.

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
```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ../bridge/cmd/reverse_tiddlers \
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

La ruta diaria de cierre es `data/sessions/`, no escritura directa en el canon final.

Cada sesión debe producir su familia mínima:

- `data/sessions/00_contratos/<session>.md.json`
- `data/sessions/01_procedencia/<session>.md.json`
- `data/sessions/02_detalles_de_sesion/<session>.md.json`
- `data/sessions/03_hipotesis/<session>.md.json`
- `data/sessions/04_balance_de_sesion/<session>.md.json`
- `data/sessions/05_propuesta_de_sesion/<session>.md.json`
- `data/sessions/06_diagnoses/sesion/<session>.md.json`

Los títulos de los tiddlers de cierre deben iniciar con `#### 🌀`. Para
procedencia, sesión e hipótesis se usan respectivamente:
`#### 🌀🧾 Procedencia de sesión ## = <session>`,
`#### 🌀 Sesión ## = <session>` y
`#### 🌀🧪 Hipótesis de sesión ## = <session>`.

Si la sesión deja memoria que debe poder entrar al canon, debe producir líneas
candidatas en formato canon bajo `data/sessions/`. La admisión real se prueba sobre
una copia temporal del canon y solo después puede aplicarse localmente.

**Validación de copia temporal o JSONL candidato:**

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

**Reverse autoritativo sobre copia temporal:**

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/tdc-go-build go run ./cmd/reverse_tiddlers \
  --html ../../data/in/'tiddly-data-converter (Saved).html' \
  --canon /tmp/<canon-temporal> \
  --out-html /tmp/<session>.reverse.html \
  --report /tmp/<session>.reverse-report.json \
  --mode authoritative-upsert
```

Para admitir líneas, el reverse debe terminar con `Rejected: 0`.

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
- `data/sessions/00_contratos/policy/canon_policy_bundle.json`
- `data/sessions/00_contratos/projections/derived_layers_registry.json`
- `python_scripts/validate_corpus_governance.py`
- `python_scripts/path_governance.py`
