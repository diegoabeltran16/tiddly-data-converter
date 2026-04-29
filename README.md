# tiddly-data-converter

Repositorio local-first para extraer, canonizar, derivar, auditar y revertir
un corpus TiddlyWiki sin perder trazabilidad ni reversibilidad.

## 1. Preparación

Trabajar siempre desde la raíz del repositorio:

```bash
cd /repositorios/tiddly-data-converter
```

Requisitos mínimos:

- Bash
- Python 3
- Go
- Rust, solo para validar los módulos Rust

Caches locales recomendadas:

```bash
export GOCACHE=/tmp/tdc-go-build
export CARGO_TARGET_DIR=/tmp/tdc-cargo-target
mkdir -p "$GOCACHE" "$CARGO_TARGET_DIR"
```

Rutas principales:

| Ruta | Rol |
|---|---|
| `data/in/` | entradas locales, incluido el HTML vivo |
| `data/out/local/tiddlers_*.jsonl` | canon oficial local |
| `data/out/local/` | canon local, derivados, export y reverse |
| `data/sessions/` | entregables de sesiones y candidatos canónicos |
| `data/tmp/` | zona temporal de trabajo y reportes |

Reglas de autoridad:

- `data/out/local/tiddlers_*.jsonl` es la fuente de verdad local.
- `data/sessions/` es staging operativo, no canon paralelo.
- `data/tmp/` es temporal y no define autoridad canónica.
- Los derivados no son fuente de verdad.
- Reverse no redefine el canon.

HTML vivo esperado:

```text
data/in/tiddly-data-converter (Saved).html
```

## 2. Exportar del canon

Exportar del canon significa producir artefactos derivados o puntuales a partir
del canon local ya existente. No es lo mismo que construir el canon desde el
HTML vivo.

Atajo histórico para regenerar y verificar el export puntual S33:

```bash
bash shell_scripts/export_s33_regen.sh
bash shell_scripts/export_s33_verify.sh
```

Primero ejecutar `export_s33_regen.sh`; después `export_s33_verify.sh`.

Artefactos producidos en `data/out/local/export/`:

- `s33-functional-tiddlers.jsonl`
- `s33-export-log.jsonl`
- `s33-manifest.json`

Bootstrap mínimo de inspección o costura:

```bash
bash shell_scripts/run_pipeline.sh
```

Este flujo escribe en `data/out/local/pipeline/`. No reemplaza el canon local
shardizado.

## 3. Construir el canon desde HTML

Construir el canon desde HTML parte del HTML vivo y vuelve a producir el canon
local shardizado.

Flujo operativo:

```text
HTML vivo
  -> JSONL temporal
  -> shards canónicos locales
  -> validación
```

Este flujo sí puede escribir `data/out/local/tiddlers_*.jsonl` durante la
shardización. Usarlo solo cuando se quiere reconstruir el canon local desde el
HTML fuente.

## 4. Extraer desde HTML a un JSONL temporal

Este paso extrae tiddlers desde el HTML vivo hacia un JSONL temporal. El JSONL
temporal no es todavía el canon definitivo.

```bash
cd /repositorios/tiddly-data-converter/go/bridge
HTML="../../data/in/tiddly-data-converter (Saved).html"

env GOCACHE=/tmp/tdc-go-build go run ./cmd/export_tiddlers \
  --html "$HTML" \
  --out /tmp/tiddlers.export.jsonl \
  --log /tmp/tiddlers.export.log \
  --manifest /tmp/tiddlers.export.manifest.json
```

Salidas esperadas:

- `/tmp/tiddlers.export.jsonl`
- `/tmp/tiddlers.export.log`
- `/tmp/tiddlers.export.manifest.json`

## 5. Shardizar el JSONL en el canon local

Este paso convierte el JSONL temporal en shards del canon local. Escribe en
`data/out/local/`.

```bash
cd /repositorios/tiddly-data-converter/go/canon

env GOCACHE=/tmp/tdc-go-build go run ./cmd/shard_canon \
  --input /tmp/tiddlers.export.jsonl \
  --out-dir ../../data/out/local
```

Salida esperada:

```text
data/out/local/tiddlers_1.jsonl
data/out/local/tiddlers_2.jsonl
...
data/out/local/tiddlers_7.jsonl
```

## 6. Validar el canon

Validación estricta del canon:

```bash
cd /repositorios/tiddly-data-converter/go/canon

env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode strict \
  --input ../../data/out/local
```

Preflight requerido antes de reverse o admisión:

```bash
cd /repositorios/tiddly-data-converter/go/canon

env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode reverse-preflight \
  --input ../../data/out/local
```

Tests Go principales:

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go test ./... -count=1

cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/tdc-go-build go test ./... -count=1

cd /repositorios/tiddly-data-converter/go/ingesta
env GOCACHE=/tmp/tdc-go-build go test ./... -count=1
```

Tests Rust principales:

```bash
cd /repositorios/tiddly-data-converter/rust/extractor
env CARGO_TARGET_DIR=/tmp/tdc-cargo-target cargo test

cd /repositorios/tiddly-data-converter/rust/doctor
env CARGO_TARGET_DIR=/tmp/tdc-cargo-target cargo test
```

Checks Python y shell útiles:

```bash
cd /repositorios/tiddly-data-converter

python3 python_scripts/validate_corpus_governance.py \
  --canon-dir data/out/local \
  --ai-dir data/out/local/ai

bash tests/fixtures/s49/run_canon_proposal_test.sh
bash tests/fixtures/s47/run_audit_test.sh
env GOCACHE=/tmp/tdc-go-build-smoke CARGO_TARGET_DIR=/tmp/tdc-cargo-target-smoke bash tests/smoke/test_pipeline_smoke.sh
```

Condición crítica para reverse y admisión canónica: `Rejected: 0`.

## 7. Pasar los entregables de sesiones al canon

`data/sessions/` contiene entregables de sesión. Cada entregable que deba poder
entrar al canon debe tener una línea equivalente dentro del archivo
`*.canon-candidates.jsonl` de su sesión.

Los archivos `.md.json` son artefactos de sesión importables o auditables, pero
no se pasan uno por uno a `admit_session_candidates.py`. La unidad operativa
simple es la sesión completa.

El script de admisión no reemplaza al canonizador. Orquesta una admisión manual,
validada y reversible:

```text
validate -> dry-run -> revisión humana -> apply --confirm-apply
```

Listar sesiones con candidatos:

```bash
cd /repositorios/tiddly-data-converter

find data/sessions -type f -name "*.canon-candidates.jsonl" | sort
```

Construir la lista de sesiones desde los candidatos existentes. El valor usado
por `--session-id` es el nombre del archivo sin `.canon-candidates.jsonl`:

```bash
mapfile -t SESSION_IDS < <(
  find data/sessions -type f -name "*.canon-candidates.jsonl" \
    -printf "%f\n" \
    | sed 's/\.canon-candidates\.jsonl$//' \
    | sort
)

printf '%s\n' "${SESSION_IDS[@]}"
```

Validar las sesiones sin tocar el canon:

```bash
for SESSION_ID in "${SESSION_IDS[@]}"; do
  python3 python_scripts/admit_session_candidates.py validate \
    --session-id "$SESSION_ID" \
    --sessions-dir data/sessions \
    --canon-dir data/out/local \
    --allow-replacements \
    --report-dir data/tmp/admissions
done
```

Ejecutar dry-run sobre copia temporal del canon:

```bash
for SESSION_ID in "${SESSION_IDS[@]}"; do
  python3 python_scripts/admit_session_candidates.py dry-run \
    --session-id "$SESSION_ID" \
    --sessions-dir data/sessions \
    --canon-dir data/out/local \
    --tmp-dir data/tmp/session_admission \
    --report-dir data/tmp/admissions \
    --allow-replacements
done
```

Revisar los reportes generados:

```bash
test -n "$(ls data/tmp/admissions/admit-*.json 2>/dev/null)" || {
  echo "No hay reportes admit-*.json en data/tmp/admissions" >&2
  exit 1
}

ls -t data/tmp/admissions/admit-*.json | head
```

Abrir cada reporte que se quiera revisar:

```bash
ADMISSION_REPORT="$(ls -t data/tmp/admissions/admit-*.json | head -1)"
python3 -m json.tool "$ADMISSION_REPORT" | less
```

Comprobar en cada reporte de `dry-run`:

- `status` debe ser `ok`.
- `rejected_candidates` debe estar vacío.
- `reverse_result.rejected` debe ser `0`.
- `canon_modified` debe ser `false` en `dry-run`.
- Las pruebas relacionadas deben estar en `passed` o justificadamente en `skipped`.

Aplicar al canon local solo como acción deliberada:

```bash
for SESSION_ID in "${SESSION_IDS[@]}"; do
  python3 python_scripts/admit_session_candidates.py apply \
    --session-id "$SESSION_ID" \
    --sessions-dir data/sessions \
    --canon-dir data/out/local \
    --tmp-dir data/tmp/session_admission \
    --report-dir data/tmp/admissions \
    --allow-replacements \
    --confirm-apply
done
```

Para admitir o reparar todos los contratos históricos bajo
`data/sessions/00_contratos/`, usar el lote automático de contratos. Este modo
genera candidatos temporales, verifica qué contratos faltan o requieren
reemplazo por `source_path`, y evita append ciego:

```bash
python3 python_scripts/admit_session_candidates.py dry-run \
  --all-contracts \
  --sessions-dir data/sessions \
  --canon-dir data/out/local \
  --tmp-dir data/tmp/session_admission \
  --report-dir data/tmp/admissions
```

Si el reporte queda en `status: ok`, `rejected_count: 0` y
`reverse_rejected: 0`, aplicar deliberadamente:

```bash
python3 python_scripts/admit_session_candidates.py apply \
  --all-contracts \
  --sessions-dir data/sessions \
  --canon-dir data/out/local \
  --tmp-dir data/tmp/session_admission \
  --report-dir data/tmp/admissions \
  --confirm-apply
```

Rollback desde un reporte de `apply`. Se revierte una sesión por reporte. Por
defecto se revisa el reporte de admisión más reciente:

```bash
APPLY_REPORT="$(ls -t data/tmp/admissions/admit-*.json 2>/dev/null | head -1)"

test -f "$APPLY_REPORT" || {
  echo "No hay reportes admit-*.json en data/tmp/admissions" >&2
  exit 1
}

python3 -m json.tool "$APPLY_REPORT" | less
```

Antes de continuar, confirmar en ese reporte:

- `mode` debe ser `apply`;
- `rollback_ready` debe ser `true`;
- `admitted_ids` debe contener los ids admitidos por esa corrida.

Ejecutar rollback solo después de esa revisión:

```bash
python3 python_scripts/admit_session_candidates.py rollback \
  --admission-report "$APPLY_REPORT" \
  --canon-dir data/out/local \
  --tmp-dir data/tmp/session_admission_rollback \
  --report-dir data/tmp/admissions
```

Advertencias:

- `--session-id` admite el paquete de candidatos de la sesión completa.
- `--all-contracts` procesa los contratos existentes en `data/sessions/00_contratos/`.
- `--allow-replacements` permite reemplazar una línea ya admitida solo cuando el `source_path` coincide; se usa para reparar nomenclatura sin duplicar.
- `--candidate-file` queda como opción avanzada cuando se necesita apuntar a un JSONL concreto.
- No usar `--candidate-file data/sessions`.
- `--candidate-file` debe apuntar a un archivo `.canon-candidates.jsonl`, no a una carpeta.
- No copiar placeholders con signos de menor/mayor en Bash: Bash los interpreta como redirección.
- No ejecutar comandos con `SESSION_IDS`, `SESSION_ID` o `APPLY_REPORT` vacíos.
- No ejecutar rollback si no hubo un `apply` real previo.
- Para la primera operación real, revisar los reportes de `dry-run` antes de lanzar el loop de `apply`.
- No ejecutar `apply --confirm-apply` sin revisar antes el reporte de `dry-run`.

## 8. Derivados

Los derivados se generan desde el canon local. No son fuente de verdad y no hacen
writeback al canon.

Entry point principal:

```bash
cd /repositorios/tiddly-data-converter

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

Capas actuales:

| Capa | Ubicación | Rol |
|---|---|---|
| `enriched` | `data/out/local/enriched/` | enriquecimiento estructural |
| `ai` | `data/out/local/ai/` | preparación RAG y chunking |
| `microsoft_copilot` | `data/out/local/microsoft_copilot/` | proyección JSON/CSV/TXT para lectura por agentes |
| `chunks` | `data/out/local/ai/chunks_ai_*.jsonl` | fragmentos trazables al nodo fuente |
| `audit` | `data/out/local/audit/` | reportes de auditoría normativa |
| `export` | `data/out/local/export/` | exportaciones puntuales |

Gobernanza de derivados:

```bash
python3 python_scripts/validate_corpus_governance.py \
  --canon-dir data/out/local \
  --ai-dir data/out/local/ai
```

Auditoría normativa:

```bash
python3 python_scripts/audit_normative_projection.py \
  --mode audit \
  --input-root data/out/local \
  --docs-root docs
```

Auditoría con safe fixes y regeneración:

```bash
python3 python_scripts/audit_normative_projection.py \
  --mode apply \
  --input-root data/out/local \
  --docs-root docs
```

Salidas de auditoría en `data/out/local/audit/`:

- `manifest.json`
- `compliance_report.json`
- `compliance_summary.md`
- `proposed_fixes.json`
- `applied_safe_fixes.json`
- `pre_post_diff.json`

## 9. Reverse

Reverse reconstruye una salida HTML interpretable desde el canon local. El HTML
resultante es derivado: no cambia la autoridad del canon y no debe usarse para
corregir el canon manualmente.

Preflight antes de reverse:

```bash
cd /repositorios/tiddly-data-converter/go/canon

env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode reverse-preflight \
  --input ../../data/out/local
```

Reverse autoritativo recomendado:

```bash
cd /repositorios/tiddly-data-converter/go/bridge
HTML="../../data/in/tiddly-data-converter (Saved).html"

env GOCACHE=/tmp/tdc-go-build go run ./cmd/reverse_tiddlers \
  --html "$HTML" \
  --canon ../../data/out/local \
  --out-html ../../data/out/local/reverse_html/tiddly-data-converter.derived.html \
  --report ../../data/out/local/reverse_html/reverse-report.json \
  --mode authoritative-upsert
```

Salidas:

- `data/out/local/reverse_html/tiddly-data-converter.derived.html`
- `data/out/local/reverse_html/reverse-report.json`

Condición crítica:

```text
Rejected: 0
```

Si reverse rechaza líneas, corregir antes el canon o los candidatos. No corregir
a mano el HTML resultante como sustituto de una reparación canónica.
