# S37 Local Checks

- Fecha: 2026-04-15
- Sesión: `m02-s37-canon-document-context-and-relations-v0`
- Estado: completado en entorno local

## Archivos tocados (resumen)
- `go/canon/context_relations.go`
- `go/canon/exporter_tiddler.go`
- `go/canon/identity.go`
- `go/canon/schema.go`
- `go/bridge/bridge.go`
- `go/canon/context_relations_test.go`
- `go/canon/export_context_relations_integration_test.go`
- `tests/fixtures/s37/context_relations_fixture.json`
- `docs/context_relations/context_relations_rules.md`
- `export/s37-functional-tiddlers.jsonl`
- `export/s37-export-log.jsonl`
- `export/s37-manifest.json`

## Comandos ejecutados y resultado

1. Formato Go
```bash
gofmt -w go/canon/context_relations.go go/canon/context_relations_test.go go/canon/export_context_relations_integration_test.go go/canon/exporter_tiddler.go go/canon/identity.go go/canon/schema.go go/canon/schema_test.go go/canon/gate_acceptance_test.go go/bridge/bridge.go
```
Resultado: OK.

2. Suite canon
```bash
cd go/canon
go test ./... -count=1 -v
```
Resultado: OK (toda la suite pasa, incluidos tests nuevos S37).

3. Suite bridge
```bash
cd go/bridge
go test ./... -count=1
```
Resultado: OK.

4. Smoke pipeline E2E
```bash
cd /repositorios/tiddly-data-converter
./tests/smoke/test_pipeline_smoke.sh
```
Resultado: OK (19 checks pasados, 0 fallidos).

5. Export real S37 (evidencia de observabilidad)
```bash
cd go/bridge
go run ./cmd/export_tiddlers \
  --html "../../data/tiddly-data-converter (Saved).html" \
  --out "../../export/s37-functional-tiddlers.jsonl" \
  --log "../../export/s37-export-log.jsonl" \
  --manifest "../../export/s37-manifest.json" \
  --run-id "s37-local-run"
```
Resultado: OK (`exported_count=538`, `skipped_by_gate=0`).

6. Validación estructural de artefactos de sesión (wrapper + `text` interno JSON)
```bash
python3 - <<'PY'
import json
for p in [
  'docs/tiddlers_de_sesiones/#### 🌀🧾 Procedencia de sesión 37.json',
  'docs/tiddlers_de_sesiones/#### 🌀🧪 Hipótesis de sesión 37 = canon-document-context-and-relations-v0.json',
  'docs/tiddlers_de_sesiones/#### 🌀 Sesión 37 = canon-document-context-and-relations-v0.json',
  'contratos/m02-s37-canon-document-context-and-relations-v0.md.json',
]:
    obj = json.load(open(p, 'r', encoding='utf-8'))
    if p.startswith('docs/tiddlers_de_sesiones/'):
        json.loads(obj[0]['text'])
print('OK')
PY
```
Resultado: OK.

## Verificación S37 observable
- `export/s37-manifest.json` incluye:
  - `document_count`
  - `nodes_with_section_path_count`
  - `nodes_with_relations_count`
  - `relation_counts.child_of`
  - `relation_counts.references`
- `export/s37-export-log.jsonl` incluye `context_info` por nodo exportado:
  - `document_id`
  - `order_in_document`
  - `section_path_length`
  - `relation_count`
  - `relation_resolution_status`
- `export/s37-functional-tiddlers.jsonl` incluye por línea:
  - `document_id`
  - `section_path`
  - `order_in_document`
  - `relations`

## Compatibilidad / límites
- No se detectó regresión en pruebas S34–S36.
- No existe un test automatizado específico de reverse en el repositorio; se validó no degradación por compilación y smoke E2E del pipeline vigente.
