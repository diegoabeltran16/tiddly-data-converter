<div align="center">

![License](https://img.shields.io/github/license/diegoabeltran16/tiddly-data-converter.svg)
![CI](https://github.com/diegoabeltran16/tiddly-data-converter/actions/workflows/ci.yml/badge.svg)
![Last Commit](https://img.shields.io/github/last-commit/diegoabeltran16/tiddly-data-converter)

<p>
  <img src="./ux/assets/Open%20eyes.PNG" alt="Tiddly Data Converter icon" width="130">
</p>

# tiddly-data-converter (TDC)

</div>

TDC es una infraestructura local-first de ingeniería del conocimiento, agnóstica respecto al dominio, diseñada para transformar información fragmentada en una memoria semántica canónica, organizada, auditable y consultable.
Puede utilizarse para estudiar, desarrollar y estructurar cualquier área del saber mediante enfoques metodológicos cuantitativos, cualitativos o mixtos. El sistema preserva no solo el contenido, sino también sus relaciones, procedencia, estados epistemológicos, decisiones, cambios y contexto de producción.

La superficie de trabajo es [TiddlyWiki](https://github.com/TiddlyWiki), mientras que el convertidor formaliza ese conocimiento para su uso en sistemas RAG, inteligencia artificial, análisis de datos, grafos de conocimiento y otros consumidores computacionales.
Este proceso se articula mediante un pipeline de extracción, canonización, derivación y auditoría, diseñado para garantizar la trazabilidad del linaje de los datos, la reversibilidad de sus estados y la autoridad explícita de cada artefacto.

El canon de TDC es evolutivo por diseño. A medida que el conocimiento sobre un tema se amplía, se corrige, se relaciona o se formaliza mediante nuevas fuentes, conceptos, hipótesis, evidencias, procedimientos, documentos o sesiones de trabajo, el canon debe crecer o actualizarse con él.
Su estabilidad no consiste en permanecer inmutable, sino en evolucionar mediante mecanismos gobernados, trazables, validables y reversibles. Cuando el canon cambia, sus derivados y demás superficies dependientes deben reconciliarse, revalidarse o regenerarse contra el estado canónico vigente antes de continuar con operaciones de escritura, admisión o promoción.

## Ejecución

Desde la raíz del repositorio, usar ejecutable:

```bash
src/shell_scripts/tdc.sh
```

Este comando invoca de forma guiada al orquestador de admisión, al canonizador, al reverse y los scripts existentes; muestra métricas y exige confirmaciones robustas antes de cualquier acción que pueda escribirse en el canon local.

## Licencia
El software first-party de TDC se distribuye bajo `AGPL-3.0-or-later`. Consulte [LICENSE](LICENSE) y [LICENSE_SCOPE.md](docs/LICENSE_SCOPE.md) para el alcance, incluidos los límites entre software, datos y materiales de terceros.
