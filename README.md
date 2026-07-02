![License](https://img.shields.io/github/license/diegoabeltran16/tiddly-data-converter.svg)
![CI](https://github.com/diegoabeltran16/tiddly-data-converter/actions/workflows/ci.yml/badge.svg)

<p>
  <img src="./ux/assets/Open%20eyes.PNG" alt="Tiddly Data Converter icon" width="130">
</p>

# tiddly-data-converter (TDC)

TDC es una infraestructura de ingeniería del conocimiento, de escritorio local-first, que prepara una memoria semántica para sistemas RAG. Lo logra mediante la transformación y conversión de información fragmentada (TiddlyWiki) en un corpus canónico, organizado y consultable. Este proceso se basa en un pipeline de extracción, canonización, derivación y auditoría, diseñado para garantizar la máxima trazabilidad del linaje de los datos y la reversibilidad de sus estados.

## Ejecución

Desde la raíz del repositorio, usar ejecutable:

```bash
shell_scripts/tdc.sh
```

Este comando invoca de forma guiada al orquestador de admisión, al canonizador, al reverse y los scripts existentes; muestra métricas y exige confirmaciones robustas antes de cualquier acción que pueda escribirse en el canon local.
