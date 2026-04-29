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

- preparación del entorno;
- revisión del estado del canon;
- construcción del canon desde HTML;
- extracción HTML a JSONL temporal;
- shardización hacia el canon local;
- validación strict y reverse-preflight;
- sincronización de entregables de sesiones por ID;
- generación de derivados;
- reverse hacia HTML derivado;
- revisión de reportes y métricas;
- rollback de admisiones cuando aplique.

## Rutas De Autoridad

| Ruta | Rol |
|---|---|
| `data/in/` | entradas locales, incluido el HTML vivo |
| `data/out/local/tiddlers_*.jsonl` | canon oficial local |
| `data/sessions/` | staging operativo de entregables de sesión |
| `data/tmp/` | temporales, reportes e inventarios |
| `data/out/local/reverse_html/` | HTML derivado y reportes de reverse |

## Reglas

- `data/out/local/tiddlers_*.jsonl` es la fuente de verdad local.
- `data/sessions/` no es canon paralelo.
- Los derivados no son fuente de verdad.
- Reverse no corrige ni redefine el canon.
- La admisión de sesiones es manual, validada y reversible.
- La condición crítica para admisión y reverse es `Rejected: 0`.
