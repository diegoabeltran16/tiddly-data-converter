![License](https://img.shields.io/github/license/diegoabeltran16/tiddly-data-converter.svg)
![Last Commit](https://img.shields.io/github/last-commit/diegoabeltran16/tiddly-data-converter.svg)
![CI](https://github.com/diegoabeltran16/tiddly-data-converter/actions/workflows/ci.yml/badge.svg)


# tiddly-data-converter

Repositorio local-first para extraer, canonizar, derivar, auditar y revertir un corpus TiddlyWiki sin perder trazabilidad ni reversibilidad.

## Operación

Desde la raíz del repositorio, usar un solo ejecutable:

```bash
shell_scripts/tdc.sh
```

Ese comando abre el menú operador local. El menú no reemplaza al orquestador de admisión, al canonizador, al reverse ni a los scripts existentes: los invoca de forma guiada, muestra métricas y exige confirmaciones fuertes antes de cualquier acción que pueda escribir en el canon local.
