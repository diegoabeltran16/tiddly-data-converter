![License](https://img.shields.io/github/license/diegoabeltran16/tiddly-data-converter.svg)
![CI](https://github.com/diegoabeltran16/tiddly-data-converter/actions/workflows/ci.yml/badge.svg)

<p>
  <img src="./ux/assets/Open%20eyes.PNG" alt="Tiddly Data Converter icon" width="130">
</p>

# tiddly-data-converter

Repositorio local-first para extraer, canonizar, derivar, auditar y revertir un corpus TiddlyWiki sin perder trazabilidad ni reversibilidad.

## Operación

Desde la raíz del repositorio, usar ejecutable:

```bash
shell_scripts/tdc.sh
```

Este comando invoca de forma guiada al orquestador de admisión, al canonizador, al reverse y los scripts existentes; muestra métricas y exige confirmaciones robustas antes de cualquier acción que pueda escribirse en el canon local.

El menú incluye la opción `Generación de derivados`, que regenera las capas locales desde `data/out/local/tiddlers_*.jsonl` hacia `enriched/`, `ai/`, `audit/`, `export/` y `microsoft_copilot/` según corresponda. Los derivados no son fuente de verdad: pueden borrarse y regenerarse desde el canon local y sus artefactos gobernados.
