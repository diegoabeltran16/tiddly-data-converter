# S65 — Diagnóstico de derivados

**Sesión:** `m03-s65-microsoft-copilot-execution-surface-and-readme-hardening-v0`  
**Fecha local:** `2026-04-23`  
**Generación verificada:** `2026-04-24T01:20:34Z` UTC desde canon de `702` líneas.

## 1. Qué produce hoy `microsoft_copilot`

El entrypoint real [python_scripts/derive_layers.py](/repositorios/tiddly-data-converter/python_scripts/derive_layers.py:4240) generó `data/out/local/microsoft_copilot/` con `51` artefactos y `0` salidas `.jsonl`.

| Grupo de salida | Rutas verificadas | Estado real |
|---|---|---|
| Manifest y navegación | `manifest.json`, `navigation_index.json`, `source_arbitration_report.json` | Presentes; `manifest.json` reporta `702` records |
| Índices estructurados | `entities.json`, `topics.json` | Presentes |
| Tablas CSV | `nodes.csv`, `edges.csv`, `artifacts.csv`, `coverage.csv` | Presentes |
| Textos de orientación | `overview.txt`, `reading_guide.txt` | Presentes |
| Bundles | `bundles/governance_core.txt`, `bundles/pipeline_and_layers.txt`, `bundles/recent_sessions.txt` | Presentes |
| Especificación auxiliar | `spec/**/*.md`, `spec/**/*.json` | Presentes |
| Sublayer `copilot_agent/` | `corpus.txt`, `entities.json`, `relations.csv` | Presente y exacto |

Métricas verificadas:

- `manifest.json`: `23123` bytes, `generated_at = 2026-04-24T01:20:34Z`
- `entities.json`: `1893388` bytes
- `copilot_agent/corpus.txt`: `27163` bytes
- `copilot_agent/entities.json`: `55021` bytes, `50` entidades
- `copilot_agent/relations.csv`: `15684` bytes

## 2. Qué produce hoy `copilot_agent`

El sublayer `copilot_agent/` es generado internamente por `write_copilot_agent_artifacts()` en la fase `5` de `derive_layers.py`.

| Restricción / propiedad | Estado verificado |
|---|---|
| Número exacto de archivos | `3` (`corpus.txt`, `entities.json`, `relations.csv`) |
| Límite de entidades | `50` |
| Linaje de sesiones | `integration_baseline = m03-s63`, `generated_from_session = m03-s64`, `parent_layer_session = m03-s61` |
| Formato de salida | `TXT + JSON + CSV`, sin `.jsonl` |
| Densidad relacional | `relations.csv` presente y no vacío |

## 3. Coincidencia entre repo, README y derivados

| Dimensión | README / código previo | Estado final real | Resultado S65 |
|---|---|---|---|
| Entrypoint documentado | README incompleto | `derive_layers.py` con flags verificadas | Alineado |
| Sublayer `copilot_agent/` en README | Ausente | Existe y es oficial | Alineado |
| `spec/**` en README | Ausente | Existe | Alineado |
| `data/README.md` | No mencionaba `copilot_agent/` | Ya lo declara | Alineado |
| `.jsonl` dentro de `microsoft_copilot/` | Riesgo de legado conceptual | `0` archivos `.jsonl` | Alineado |
| `data/out/local/copilot_agent/` | Ruta legacy histórica | No existe | Alineado |

## 4. Inconsistencias detectadas y resueltas

1. El canon final ya tenía `701` líneas antes del contrato S65, pero los derivados seguían generados desde un canon anterior de `698`.
   Acción: se absorbió el contrato path-like S65, el canon pasó a `702` y se regeneró toda la capa derivada.
2. El README exponía un comando válido pero incompleto.
   Acción: se añadieron `--audit-dir` y `--export-dir`.
3. La documentación no fijaba el sublayer `copilot_agent/` ni su artefacto `spec/**`.
   Acción: se alinearon README, `data/README.md` y tests S65.

## 5. Conclusión

El flujo real de `microsoft_copilot` quedó visible, ejecutable y verificable sin reactivar superficie legacy. El estado final del repo, del canon y de los derivados coincide: canon `702`, derivados `702`, `51` artefactos Copilot y paquete `copilot_agent/` exacto de `3` archivos.
