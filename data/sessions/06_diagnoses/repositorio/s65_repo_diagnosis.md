# S65 — Diagnóstico de repositorio

**Sesión:** `m03-s65-microsoft-copilot-execution-surface-and-readme-hardening-v0`  
**Fecha local:** `2026-04-23`  
**Estado verificado:** canon local en `7` shards con `702` líneas, `microsoft_copilot/` regenerado desde ese canon y reverse autoritativo en verde.

## 1. Gobernanza aplicada

| Surface | Propósito | Reglas obligatorias aplicadas en S65 | Artefactos requeridos | Impacto | Aplicación en S65 |
|---|---|---|---|---|---|
| `.github/instructions/contratos.instructions.md` | Cerrar sesiones sustantivas con contrato estructurado importable | Debe existir al menos `1` `.md.json` y quedar absorbido en canon como nodo path-like | Contrato S65 + nodo `contratos/...md.json` en canon | Canon, trazabilidad, TiddlyWiki import | Se creó [contratos/m03-s65-microsoft-copilot-execution-surface-and-readme-hardening-v0.md.json](/repositorios/tiddly-data-converter/contratos/m03-s65-microsoft-copilot-execution-surface-and-readme-hardening-v0.md.json:1) y se absorbió en `tiddlers_5.jsonl` |
| `.github/instructions/dependencia_y_superficie_externa.instructions.md` | Gobernar toolchains y superficies externas | No inventar dependencias ni superficies nuevas; distinguir superficie activa de proyecciones derivadas | Evidencia de comandos y rutas reales | Reproducibilidad y riesgo | S65 no añadió dependencias; confirmó `derive_layers.py`, `canon_preflight` y `reverse_tiddlers` como superficie activa |
| `.github/instructions/desarrollo_y_evolucion.instructions.md` | Mantener continuidad histórica | No reabrir S61-S64 sin ruptura real; dejar visible qué cambió y qué no | Diagnóstico con continuidad | Gobernanza evolutiva | S65 endurece README/canon/tests sin rediseñar `microsoft_copilot` |
| `.github/instructions/detalles_del_tema.instructions.md` | Vincular la sesión con el marco conceptual del proyecto | Conectar resultados con procedencia, hipótesis, objetivos, requisitos, DOFA, flujo, arquitectura, componentes, algoritmos e IA | `diagnose/s65_hypothesis_trace.md` | Coherencia temática | Se actualizó la trazabilidad completa con evidencia operativa real |
| `.github/instructions/elementos_especificos.istructions.md` | Preservar recursos concretos | Mantener scripts, outputs y artefactos identificables y contextualizados | Diagnóstico de superficies y derivados | Evidencia operativa | Se fijaron entrypoints, archivos generados y rutas oficiales |
| `.github/instructions/glosario_y_convenciones.instructions.md` | Estabilizar términos y rutas | No mezclar canon, derivados, reverse y legacy | README + diagnóstico consistente | Claridad semántica | S65 dejó explícito que `microsoft_copilot/` es derivado, `copilot_agent/` es sublayer y `data/out/local/copilot_agent/` es legacy no activo |
| `.github/instructions/hipotesis.instructions.md` | Separar hipótesis de hechos | No promover suposiciones a verdad sin evidencia | Mapa de hipótesis con estado | Trazabilidad epistemológica | S65 valida hipótesis de entrypoint, README y contrato faltante con ejecución real |
| `.github/instructions/politica_de_memoria_activa.instructions.md` | Recuperación situada de contexto | Leer solo contexto relevante | Diagnóstico enfocado | Control de contexto | Se limitaron lecturas a gobernanza, flujo operativo, canon, reverse, tests y sesiones S61-S64 |
| `.github/instructions/PRcommits.instructions.md` | Normar commits/PR | Solo aplica si se pide commit/PR | N/A en esta sesión | Ninguno en S65 | Leída; no aplicada porque no se pidió propuesta de commit/PR |
| `.github/instructions/principios_de_gestion.instructions.md` | Marco normativo transversal | No inventar un flujo nuevo; mantener cambio mínimo y trazable | README/tests/diagnóstico coherentes | Calidad y rigor | S65 corrigió precisión operativa sin rehacer arquitectura |
| `.github/instructions/procedencia_epistemologica.instructions.md` | Declarar el origen de decisiones y hallazgos | Explicitar qué vino del repo, del canon, de sesiones previas y de ejecución asistida | Procedencia S65 | Trazabilidad de origen | Se dejó procedencia explícita en canon y en diagnóstico |
| `.github/instructions/protocolo_de_sesion.instructions.md` | Conducir la sesión como trabajo situado | Leer, diagnosticar, ejecutar, validar y cerrar con artefactos | Diagnóstico + contrato + evidencia | Disciplina de sesión | S65 siguió lectura situada, cambios mínimos y cierre con artefactos estructurados |
| `.github/instructions/sesiones.instructions.md` | Layout operativo local-first y cierre directo | `data/out/local/tiddlers_*.jsonl` manda, `proposals.jsonl` es extraordinario, reverse es obligatorio | Absorción en canon + `strict` + `reverse-preflight` + reverse | Canon y reversibilidad | S65 cerró directo en canon y no usó `proposals.jsonl` |
| `.github/instructions/tiddlers_sesiones.instructions.md` | Cierre canónico de memoria semántica de sesión | Familia mínima `sesión + hipótesis + procedencia + contrato` absorbida directo en canon | Cuatro nodos S65 en shards activos | Canonización diaria | S65 quedó repartida en `tiddlers_2.jsonl`, `tiddlers_3.jsonl`, `tiddlers_4.jsonl` y `tiddlers_5.jsonl` |

## 2. Entrypoint real y helpers efectivos

### Entrypoint oficial

`python_scripts/derive_layers.py` es el entrypoint real que hoy produce los derivados de `microsoft_copilot` y del sublayer `copilot_agent`.

Comando validado:

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

### Helpers que sí participan

| Surface | Función actual | ¿Participa en el flujo oficial? | Inputs / Outputs | Gap detectado | Cambio mínimo aplicado | Validación |
|---|---|---|---|---|---|---|
| [python_scripts/derive_layers.py](/repositorios/tiddly-data-converter/python_scripts/derive_layers.py:1) | Deriva `enriched/`, `ai/`, reportes y `microsoft_copilot/` | Sí, entrypoint oficial | Consume `data/out/local/tiddlers_*.jsonl`; produce `enriched/`, `ai/`, `microsoft_copilot/` y `copilot_agent/` | README omitía `--audit-dir` y `--export-dir` | README endurecido | Ejecución real sobre `702` registros |
| [python_scripts/path_governance.py](/repositorios/tiddly-data-converter/python_scripts/path_governance.py:17) | Declara rutas gobernadas | Sí, como soporte | Define `DEFAULT_MICROSOFT_COPILOT_DIR` y `DEFAULT_COPILOT_AGENT_DIR` | Sin gap operativo nuevo | Ninguno | Cubierto por derive + tests S65 |
| [python_scripts/corpus_governance.py](/repositorios/tiddly-data-converter/python_scripts/corpus_governance.py:285) | Valida layout, capas y alineación AI/canon | Sí, como validación | Consume canon + AI; reporta `status` | Ningún gap funcional; sí advertencias opcionales | Ninguno | `status: ok`, `0` errores |
| [python_scripts/audit_normative_projection.py](/repositorios/tiddly-data-converter/python_scripts/audit_normative_projection.py:1) | Audita proyección normativa | Sí, como validación complementaria | Consume canon + derivados; escribe `audit/` | Debía rerun tras cerrar canon S65 | Ejecutado | `global_compliance=pass` |
| [shell_scripts/run_pipeline.sh](/repositorios/tiddly-data-converter/shell_scripts/run_pipeline.sh:1) | Bootstrap Extractor → Doctor → Ingesta → Canon mínimo | No para `microsoft_copilot` | Consume HTML; escribe `data/out/local/pipeline/` | Podía confundirse con entrypoint de Copilot | Documentado como bootstrap mínimo, no como generador de `microsoft_copilot` | Lectura situada + contraste con README |
| [go/canon/cmd/canon_preflight/main.go](/repositorios/tiddly-data-converter/go/canon/cmd/canon_preflight/main.go:35) | `strict`, `normalize`, `reverse-preflight` | Sí | Valida canon local | Ninguno | Usado como compuerta real | `STRICT PASSED`, `REVERSE-PREFLIGHT PASSED` |
| [go/bridge/cmd/reverse_tiddlers/main.go](/repositorios/tiddly-data-converter/go/bridge/cmd/reverse_tiddlers/main.go:12) | Reverse autoritativo o insert-only | Sí | Consume HTML base + canon; escribe `reverse_html/` | Ninguno | Usado como compuerta real | `Rejected: 0`, `Inserted: 4` |

## 3. Referencias legacy detectadas

| Legacy / desalineación | Dónde aparecía | Estado real | Resolución S65 |
|---|---|---|---|
| `data/out/local/copilot_agent/` como ruta activa | Hipótesis/documentación previa, no en superficie vigente | No existe | Se confirmó su ausencia y se fijó con tests |
| Omitir `--audit-dir` y `--export-dir` en el comando documentado | [README.md](/repositorios/tiddly-data-converter/README.md:137) pre-S65 | El binario acepta ambas rutas y el README estaba incompleto | README actualizado |
| Omitir `spec/**` y `copilot_agent/*` de la lista de artefactos | [README.md](/repositorios/tiddly-data-converter/README.md:166) pre-S65 | Los artefactos existen en disco | README actualizado |
| Omitir `copilot_agent/` en [data/README.md](/repositorios/tiddly-data-converter/data/README.md:11) | `data/README.md` pre-S65 | El sublayer existe y es oficial | `data/README.md` actualizado |
| Familia S65 incompleta | Canon y `contratos/` | Existían sesión/hipótesis/procedencia pero faltaba el contrato físico y su nodo path-like | Contrato creado y absorbido |
| Conteos mezclados `698/701/702` | `diagnose/s65_*` | El estado final real es `702` | Diagnóstico reescrito |

## 4. Mapa de superficies

| Surface | Current source of truth | Entrypoint | Legacy refs | Verified command | Expected outputs | Actual outputs | Tests | Canon status | Reverse status | Action required | Priority |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `python_scripts/derive_layers.py` | Código del repo | Sí | Ninguna | `python3 python_scripts/derive_layers.py ...` | `enriched/`, `ai/`, `microsoft_copilot/`, `copilot_agent/` | `702` enriched, `702` AI, `1187` chunks, `51` artefactos Copilot | `s52`, `s54`, `s55`, `s64`, `s65` | Consume canon final `702` | No altera canon; reverse sigue verde | Ninguna | P0 |
| `README.md` | README validado en ejecución | No | Omitía flags y artefactos | Lectura + ejecución del comando documentado | Comando y outputs reales visibles | Flags y artefactos alineados | `s65` | N/A | N/A | Ninguna | P0 |
| `data/README.md` | README de layout | No | Omitía `copilot_agent/` | Lectura + contraste con outputs | Layout local coherente | Sublayer declarado | `s65` | N/A | N/A | Ninguna | P1 |
| `data/out/local/microsoft_copilot/` | Derivados regenerados | Derivado por `derive_layers.py` | `.jsonl` legacy no activo | Derive command anterior | `manifest.json`, JSON/CSV/TXT, `spec/**`, `copilot_agent/` | `51` archivos, `0` `.jsonl` | `s64`, `s65` | Deriva de canon `702` | Compatible; reverse usa canon, no esta capa | Ninguna | P0 |
| `data/out/local/microsoft_copilot/copilot_agent/` | Sublayer derivada | `write_copilot_agent_artifacts()` | Root legacy ausente | Derive command anterior | `corpus.txt`, `entities.json`, `relations.csv` | Exactamente esos `3` archivos, `50` entidades | `s64`, `s65` | Deriva de canon `702` | Compatible; no rompe reverse | Ninguna | P0 |
| `go/canon/cmd/canon_preflight` | Código Go | Sí | Ninguna | `go run ./cmd/canon_preflight --mode strict|reverse-preflight` | Validación del canon | `702` líneas válidas y listas | `go/canon` | `PASSED` | `PASSED` | Ninguna | P0 |
| `go/bridge/cmd/reverse_tiddlers` | Código Go | Sí | Ninguna | `go run ./cmd/reverse_tiddlers --mode authoritative-upsert ...` | HTML derivado + report | `4` insertados, `0` rechazados | `go/bridge` | Canon consumido: `702` | `PASSED` | Ninguna | P0 |
| `shell_scripts/run_pipeline.sh` | Script bootstrap | No para Copilot | Podía interpretarse como entrypoint Copilot | Lectura situada | `pipeline/` mínimo | No usado para generar Copilot | N/A | No aplica | No aplica | Mantenerlo documentado como bootstrap, no como surface Copilot | P2 |

## 5. Superficie oficialmente soportada al cierre

- `python_scripts/derive_layers.py` es la superficie oficial para `microsoft_copilot`.
- `data/out/local/microsoft_copilot/` y `data/out/local/microsoft_copilot/copilot_agent/` son las rutas oficiales de salida.
- `go/canon/cmd/canon_preflight` es la compuerta obligatoria antes del cierre.
- `go/bridge/cmd/reverse_tiddlers` es la verificación autoritativa de reversibilidad.
- `shell_scripts/run_pipeline.sh` sigue siendo bootstrap mínimo del pipeline, no generador oficial de `microsoft_copilot`.

## 6. Gaps priorizados

| Gap | Gravedad | Capa afectada | Evidencia | Acción inmediata | ¿Bloquea cierre S65? |
|---|---|---|---|---|---|
| Diagnóstico S65 con conteos inconsistentes | Alta | Diagnóstico / gobernanza | Archivos S65 mezclaban `698`, `701` y `702` | Reescribir `diagnose/s65_*` con el estado final ejecutado | Sí |
| Contrato S65 ausente en `contratos/` y en canon como path-like node | Alta | Contrato / canon | Canon referenciaba `contratos/...` pero el archivo faltaba | Crear contrato y absorberlo | Sí |
| README y `data/README` podían volver a desalinearse | Media | Documentación | No había tests que fijaran flags, artefactos y familia mínima | Añadir compuertas S65 en tests | Sí |
| `data/out/local/export/` no existe hoy | Baja | Layout opcional | Gobernanza lo reporta como opcional ausente | Dejar como deuda explícita para S66 | No |
| El canon sigue dependiendo de heurística para `corpus_state` por falta de `state:*` explícitos | Baja | Canon / gobernanza | `validate_corpus_governance` lo reporta como warning histórico | Tratar en sesión posterior, no en S65 | No |
