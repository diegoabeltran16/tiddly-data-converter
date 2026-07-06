# src

Esta carpeta contiene la superficie ejecutable poliglota de TDC.

TDC conserva en la raíz del repositorio los dominios de infraestructura
como `data/`, `docs/`, `tests/`, `ux/`, `runtime/` y `packaging/`.
La carpeta `src/` agrupa únicamente código fuente y scripts de ejecución.

## Subcarpetas

- `go/`: módulos Go para canon, bridge e ingesta.
- `python_scripts/`: scripts de pipeline, auditoría, derivación y gobierno.
- `rust/`: componentes Rust para extracción, diagnóstico y calidad.
- `shell_scripts/`: orquestación local del pipeline y comandos operativos.

## Regla de workspace Go

`go.work` y `go.work.sum` permanecen en la raíz del repositorio porque
coordinan el workspace Go global de TDC.
