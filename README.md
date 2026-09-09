<div align="center">

![License](https://img.shields.io/github/license/diegoabeltran16/tiddly-data-converter.svg)
![CI](https://github.com/diegoabeltran16/tiddly-data-converter/actions/workflows/ci.yml/badge.svg)
![Last Commit](https://img.shields.io/github/last-commit/diegoabeltran16/tiddly-data-converter)

<p>
  <img src="./ux/assets/Open%20eyes.PNG" alt="Tiddly Data Converter icon" width="130">
</p>

# tiddly-data-converter (TDC)

</div>

TDC es una infraestructura local-first de ingeniería del conocimiento, agnóstica respecto al dominio, diseñada para transformar información fragmentada en una memoria semántica gobernada, organizada, auditable y consultable. Su Canon representa el conocimiento admitido con autoridad dentro del sistema, sin confundirse con la totalidad del registro histórico, evidenciario u operacional que puede acompañarlo.

Puede utilizarse para estudiar, desarrollar y estructurar cualquier área del saber, y para soportar enfoques metodológicos cuantitativos, cualitativos o mixtos. TDC preserva no solo contenido, sino también relaciones, procedencia, estados epistemológicos, decisiones, cambios y contexto de producción, de forma que afirmaciones, evidencias, hipótesis, inferencias y conclusiones puedan mantenerse diferenciadas y trazables. Hacer conocimiento computable no significa reducir todas sus formas a una única representación, sino hacer explícitas las relaciones, transformaciones, fuentes, límites y condiciones necesarias para que representaciones heterogéneas puedan utilizarse sin perder su significado ni su estatuto epistemológico.

La superficie de trabajo es [TiddlyWiki](https://github.com/TiddlyWiki), mientras que TDC formaliza ese conocimiento en representaciones computables para su uso por sistemas RAG, inteligencia artificial, análisis de datos, grafos de conocimiento y otros consumidores. Este proceso articula extracción, formalización, validación y admisión, derivación y auditoría, manteniendo explícitos el linaje de los artefactos, su estatuto de autoridad y las condiciones necesarias para reconstruir o revertir transformaciones cuando corresponda.

El Canon de TDC es evolutivo por diseño. A medida que el conocimiento se amplía, corrige, relaciona o formaliza mediante nuevas fuentes, conceptos, hipótesis, evidencias, procedimientos, documentos o sesiones de trabajo, su estado canónico puede evolucionar mediante mecanismos gobernados, trazables y validables. Su estabilidad no consiste en permanecer inmutable, sino en cambiar sin perder identidad, procedencia, autoridad ni continuidad histórica.

Cuando el Canon cambia, las representaciones y superficies que dependan de ese estado deben reconciliarse, revalidarse o regenerarse contra el estado canónico vigente antes de utilizarse nuevamente como base para operaciones que requieran currentness.

El Canon es independiente del modelo de IA, runtime agentic, sistema de recuperación o proveedor utilizado. TDC gobierna identidad, procedencia, autoridad, ciclo de vida, relaciones, candidatas, admisión y derivación; los sistemas externos consumen contexto y producen resultados, evidencia o candidatas sometidas a esa gobernanza. La persistencia en una memoria agentic, un índice, un grafo, un sistema RAG o cualquier otro servicio externo no confiere por sí misma autoridad canónica.

## Ejecución

Desde la raíz del repositorio, usar ejecutable:

```bash
src/shell_scripts/tdc.sh
```

Este comando invoca de forma guiada al orquestador de admisión, al canonizador, al reverse y los scripts existentes; muestra métricas y exige confirmaciones robustas antes de cualquier acción que pueda escribirse en el canon local.

## Licencia
El software first-party de TDC se distribuye bajo `AGPL-3.0-or-later`. Consulte [LICENSE](LICENSE) y [LICENSE_SCOPE.md](docs/LICENSE_SCOPE.md) para el alcance, incluidos los límites entre software, datos y materiales de terceros.
