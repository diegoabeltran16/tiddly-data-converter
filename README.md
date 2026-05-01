![License](https://img.shields.io/github/license/diegoabeltran16/tiddly-data-converter.svg)
![Last Commit](https://img.shields.io/github/last-commit/diegoabeltran16/tiddly-data-converter.svg)
![CI](https://github.com/diegoabeltran16/tiddly-data-converter/actions/workflows/ci.yml/badge.svg)


# tiddly-data-converter

Repositorio local-first para extraer, canonizar, derivar, auditar y revertir
un corpus TiddlyWiki sin perder trazabilidad ni reversibilidad.

## Operación

Desde la raíz del repositorio, usar un solo ejecutable:

```bash
shell_scripts/tdc.sh
```

Ese comando abre el menú operador local. El menú no reemplaza al orquestador de
admisión, al canonizador, al reverse ni a los scripts existentes: los invoca de
forma guiada, muestra métricas y exige confirmaciones fuertes antes de cualquier
acción que pueda escribir en el canon local.

## Qué Permite Hacer

El menú centraliza el flujo operativo actual:

- Preparación del entorno
- Chequeo del perímetro Rust de entradas, canon, reverse y capas no autoritativas
- Compuerta Rust del plan de reconstrucción antes de tocar canon o reverse
- Compuerta Rust de coherencia HTML → JSONL temporal antes de shardizar
- Compuerta Rust de calidad de línea canónica y deriva de plantillas
- Perfiles Rust de hardening focal por familia e incompletas priorizadas
- Inspector Rust de estructura interna de nodos
- Auditoría Rust de proyección modal canónica para assets, código, ecuaciones, referencias y payloads estructurados
- Proyección modal integrada en la exportación canónica para assets, código, ecuaciones, referencias y payloads estructurados
- Revisión del estado del canon
- Construcción del canon desde HTML
- Extracción HTML a JSONL temporal
- Shardización secuencial hacia el canon local con máximo 100 líneas por archivo y evidencia `canon_before` / `canon_after`
- Validación strict y reverse-preflight
- Sincronización de entregables de sesiones por ID
- Generación de derivados
- Reverse hacia HTML derivado
- Revisión de reportes y métricas
- Rollback de admisiones cuando aplique
- Rollback guiado de reconstrucciones cuando existe backup verificable

## Rutas De Autoridad

| Ruta | Rol |
|---|---|
| `data/in/` | entradas locales, incluido el HTML vivo |
| `data/out/local/tiddlers_*.jsonl` | canon oficial local |
| `data/sessions/` | staging operativo de entregables de sesión |
| `data/tmp/` | temporales, reportes e inventarios |
| `data/tmp/reconstruction/` | evidencia de reconstrucción: gates, backups, before/after y rollback |
| `data/tmp/canonical_quality/` | reportes no destructivos de calidad de líneas y estructura interna |
| `data/out/local/reverse_html/` | HTML derivado y reportes de reverse |

## Reglas

- `data/out/local/tiddlers_*.jsonl` es la fuente de verdad local.
- `data/in/objeto_de_estudio_trazabilidad_y_desarrollo.html` es la semilla reusable principal; `empty-store.html` es auxiliar.
- `data/sessions/` no es canon paralelo.
- Los derivados no son fuente de verdad.
- Reverse no corrige ni redefine el canon.
- La reconstrucción desde HTML exige fuente explícita, destino explícito, backup y reporte de hash cuando puede escribir `data/out/local`.
- El JSONL temporal que se shardiza debe corresponder al HTML declarado mediante manifiesto de export con `source_html_path`, `source_html_sha256`, `output_path` y hash real.
- Toda shardización autorizada usa partición secuencial `tiddlers_<n>.jsonl` con máximo 100 líneas por shard y deja `canon_before/`, `canon_after/` y `reconstruction-report.json` bajo `data/tmp/reconstruction/<run_id>/`.
- Si el canon local fue reiniciado y no hay shards previos, la reconstrucción puede continuar con evidencia before/after, pero `rollback_ready` queda falso porque no existe canon previo real que restaurar.
- Después de shardizar, el menú ejecuta `canon_preflight --mode strict` y `canon_preflight --mode reverse-preflight`; si fallan, bloquea continuidad operativa.
- Los derivados solo se generan como continuidad operativa cuando existe reverse ejecutado con `Rejected: 0`.
- El rollback de reconstrucción restaura únicamente desde `canon_before/` asociado a un reporte `rollback_ready`, y valida strict + reverse-preflight tras restaurar.
- El canonical-line gate y el deep-node inspector de Rust clasifican calidad, riqueza interna, perfiles por familia, triage de incompletas y deriva de plantillas; no admiten líneas ni reescriben nodos.
- La separación entre JSON estructural, fragmentos recuperables y JSON pedagógico es evidencia no destructiva; no promueve payloads ni corrige canon por sí sola.
- `content` es una proyección derivada no autoritativa: puede describir `plain`, `asset`, `code_blocks`, `equations`, `references` y `structured_payload`, pero reverse sigue leyendo `text`, `source_tags` y `source_fields`.
- La deuda modal de assets S76/S77 queda absorbida por regeneración canónica completa cuando el canon se exporta de nuevo desde HTML y se valida con compuertas duras.
- La admisión de sesiones es manual, validada y reversible.
- La condición crítica para admisión y reverse es `Rejected: 0`.
