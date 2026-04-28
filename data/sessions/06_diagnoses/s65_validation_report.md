# S65 — Reporte de validación

**Sesión:** `m03-s65-microsoft-copilot-execution-surface-and-readme-hardening-v0`  
**Fecha local:** `2026-04-23`

## 1. Comandos ejecutados

| Comando | Resultado |
|---|---|
| `env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight --mode strict --input ../../data/out/local` | `STRICT PASSED — 702 line(s) valid` |
| `env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight --mode reverse-preflight --input ../../data/out/local` | `REVERSE-PREFLIGHT PASSED — 702 line(s) ready` |
| `python3 python_scripts/derive_layers.py --input-dir data/out/local --enriched-dir data/out/local/enriched --ai-dir data/out/local/ai --microsoft-copilot-dir data/out/local/microsoft_copilot --reports-dir data/out/local/ai/reports --audit-dir data/out/local/audit --export-dir data/out/local/export --chunk-target-tokens 1800 --chunk-max-tokens 4000` | `702` enriched, `702` AI, `1187` chunks, `51` artefactos Copilot |
| `python3 python_scripts/audit_normative_projection.py --mode audit --input-root data/out/local --docs-root docs` | `global_compliance=pass`, `702` nodos auditados, `manual_review_debt=427` |
| `python3 python_scripts/validate_corpus_governance.py --canon-dir data/out/local --ai-dir data/out/local/ai` | `status: ok`, `0` errores, `0` mismatches AI |
| `python3 -m unittest tests.fixtures.s52.test_chunking_structure tests.fixtures.s54.test_semantic_microchunk tests.fixtures.s55.test_corpus_governance tests.fixtures.s64.test_copilot_agent_projection tests.fixtures.s65.test_s65_microsoft_copilot_flow` | `Ran 49 tests ... OK` |
| `env GOCACHE=/tmp/tdc-go-build go test ./... -count=1` en `go/canon` | `ok github.com/tiddly-data-converter/canon` |
| `env GOCACHE=/tmp/tdc-go-build go test ./... -count=1` en `go/bridge` | `ok github.com/tiddly-data-converter/bridge` |
| `env GOCACHE=/tmp/tdc-go-build go run ./cmd/reverse_tiddlers --html ../../data/in/'tiddly-data-converter (Saved).html' --canon ../../data/out/local --out-html ../../data/out/local/reverse_html/tiddly-data-converter.derived.html --report ../../data/out/local/reverse_html/reverse-report.json --mode authoritative-upsert` | `Inserted: 4`, `Rejected: 0`, `Already present: 655` |

## 2. Tests corridos

| Suite | Casos | Estado |
|---|---|---|
| `tests.fixtures.s52.test_chunking_structure` | `5` | ✅ OK |
| `tests.fixtures.s54.test_semantic_microchunk` | `4` | ✅ OK |
| `tests.fixtures.s55.test_corpus_governance` | `5` | ✅ OK |
| `tests.fixtures.s64.test_copilot_agent_projection` | `4` | ✅ OK |
| `tests.fixtures.s65.test_s65_microsoft_copilot_flow` | `31` | ✅ OK |
| `go/canon` | paquete | ✅ OK |
| `go/bridge` | paquete | ✅ OK |
| **Total Python** | **49** | ✅ **OK** |

## 3. Outputs generados y verificados

| Output | Ruta | Métrica verificada |
|---|---|---|
| Manifest Copilot | `data/out/local/microsoft_copilot/manifest.json` | `23123` bytes, `generated_at = 2026-04-24T01:20:34Z`, `total_records = 702` |
| Índice Copilot | `data/out/local/microsoft_copilot/entities.json` | `1893388` bytes |
| Corpus `copilot_agent` | `data/out/local/microsoft_copilot/copilot_agent/corpus.txt` | `27163` bytes |
| Entidades `copilot_agent` | `data/out/local/microsoft_copilot/copilot_agent/entities.json` | `55021` bytes, `50` entidades, `updated_at = 2026-04-24T01:20:34Z` |
| Relaciones `copilot_agent` | `data/out/local/microsoft_copilot/copilot_agent/relations.csv` | `15684` bytes |
| Reporte de auditoría | `data/out/local/audit/compliance_report.json` | `global_compliance = pass`, `manual_review_debt = 427`, `safe_fixes_applied = 0` |
| Reverse report | `data/out/local/reverse_html/reverse-report.json` | `201717` bytes |
| Reverse HTML | `data/out/local/reverse_html/tiddly-data-converter.derived.html` | `37015654` bytes |

## 4. Rutas verificadas

- ✅ `data/out/local/tiddlers_*.jsonl` sigue siendo la única fuente de verdad local.
- ✅ `data/out/local/microsoft_copilot/` es la ruta oficial y activa de salida Copilot.
- ✅ `data/out/local/microsoft_copilot/copilot_agent/` es la ruta oficial y activa del sublayer.
- ✅ `data/out/local/reverse_html/` contiene el reverse autoritativo.
- ✅ `data/out/local/copilot_agent/` no existe.
- ✅ `data/out/local/microsoft_copilot/` contiene `0` archivos `.jsonl`.

## 5. Cambios aplicados

| Cambio | Surface | Tipo |
|---|---|---|
| Añadir `--audit-dir` y `--export-dir` al comando documentado de `derive_layers.py` | [README.md](/repositorios/tiddly-data-converter/README.md:137) | Documentación |
| Añadir `spec/**` y `copilot_agent/*` a la lista de artefactos Copilot | [README.md](/repositorios/tiddly-data-converter/README.md:166) | Documentación |
| Declarar el sublayer `copilot_agent/` en el layout de datos | [data/README.md](/repositorios/tiddly-data-converter/data/README.md:11) | Documentación |
| Crear contrato importable S65 | [contratos/m03-s65-microsoft-copilot-execution-surface-and-readme-hardening-v0.md.json](/repositorios/tiddly-data-converter/contratos/m03-s65-microsoft-copilot-execution-surface-and-readme-hardening-v0.md.json:1) | Contrato |
| Completar familia mínima S65 en canon | `tiddlers_2/3/4/5.jsonl` | Canon |
| Endurecer compuertas S65 | [tests/fixtures/s65/test_s65_microsoft_copilot_flow.py](/repositorios/tiddly-data-converter/tests/fixtures/s65/test_s65_microsoft_copilot_flow.py:39) | Tests |
| Reescribir evidencia diagnóstica con conteos finales consistentes | `diagnose/s65_*` | Diagnóstico |

## 6. Resultado de `reverse-preflight`

```text
[canon_preflight] Canon source: ../../data/out/local (7 shard(s), 702 line(s))
{
  "lines_read": 702,
  "reverse_ready": 702,
  "not_ready": 0
}
[canon_preflight] REVERSE-PREFLIGHT PASSED — 702 line(s) ready
```

## 7. Resultado del reverse autoritativo

```text
[reverse_tiddlers] Reverse complete ✓
[reverse_tiddlers]   Mode:            authoritative-upsert
[reverse_tiddlers]   Canon lines:     702
[reverse_tiddlers]   Eligible:        659
[reverse_tiddlers]   Out-of-scope:    43
[reverse_tiddlers]   Already present: 655
[reverse_tiddlers]   Inserted:        4
[reverse_tiddlers]   Updated:         0
[reverse_tiddlers]   Rejected:        0
```

## 8. Conclusión final de la sesión

S65 queda cerrada con evidencia operativa real:

1. Se identificó y ejecutó el entrypoint real: `python_scripts/derive_layers.py`.
2. El flujo vigente se validó sin superficie legacy.
3. Se confirmó exactamente qué genera `microsoft_copilot` y dónde lo genera.
4. README y `data/README.md` quedaron alineados con comandos y rutas ejecutados.
5. La familia mínima S65 llegó completa al canon.
6. `strict`, `reverse-preflight`, pruebas Python, pruebas Go y reverse autoritativo pasaron.
7. El estado final es consistente entre repo, canon, derivados y diagnóstico: `702` líneas de canon, `702` registros derivados y `0` rechazos en reverse.

**Próximo paso recomendado:** dedicar S66 a dos deudas no bloqueantes: materializar `data/out/local/export/` si se vuelve operativa y empezar a promover tags `state:*` / `status:*` explícitos en nodos de alta prioridad para reducir la dependencia de heurística en `corpus_state`.
