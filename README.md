![License](https://img.shields.io/github/license/diegoabeltran16/tiddly-data-converter.svg)
![CI](https://github.com/diegoabeltran16/tiddly-data-converter/actions/workflows/ci.yml/badge.svg)

<p>
  <img src="./ux/assets/Open%20eyes.PNG" alt="Tiddly Data Converter icon" width="130">
</p>

# tiddly-data-converter

Aplicación de escritorio local‑first para convertir un corpus TiddlyWiki básico en un canon gestionado, mediante procesos de extracción, canonización, derivación, auditoría y reversión, preservando trazabilidad y reversibilidad.

## Ejecución

Desde la raíz del repositorio, usar ejecutable:

```bash
shell_scripts/tdc.sh
```

Este comando invoca de forma guiada al orquestador de admisión, al canonizador, al reverse y los scripts existentes; muestra métricas y exige confirmaciones robustas antes de cualquier acción que pueda escribirse en el canon local.
