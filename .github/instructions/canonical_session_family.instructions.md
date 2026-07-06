---
description: >
  Dueño normativo de la familia canónica de sesión, rutas oficiales,
  títulos, líneas candidatas y compuertas de admisión local para
  tiddly-data-converter.
---

# Familia Canónica de Sesión

## Modelo de conjuntos

Universo:

```text
I = conjunto total de archivos de instrucciones
R = conjunto total de reglas, obligaciones, prohibiciones y criterios de salida
```

Regla de propiedad:

```text
owner(r) = archivo o conjunto normativo responsable de definir r
uses(f, r) != owns(f, r)
forall r in R, existe exactamente un owner(r)
```

Principio rector:

```text
One source of truth + repeated short enforcement references.
```

Una regla vive completa en un solo lugar. Los demás archivos solo la invocan
cuando necesitan hacerla cumplir. Una regla crítica puede repetirse como señal
corta de cumplimiento, pero no como definición completa divergente.

## Conjuntos normativos

| Conjunto | Dueño | Responsabilidad |
|---|---|---|
| `G` | gobernanza global del sistema | Reglas globales y autoridad general |
| `S` | `protocolo_de_sesion.instructions.md` | Apertura, conducción y cierre conceptual |
| `F` | `canonical_session_family.instructions.md` | Familia mínima, rutas, títulos, candidatos y admisión |
| `A` | `canonical_session_family.instructions.md` | Admisión canónica y líneas candidatas de sesión |
| `T` | `tiddlers_sesiones.instructions.md` | Schema y validación de artefactos `.md.json`; diagnósticos no sesionales |
| `P` | `procedencia_epistemologica.instructions.md` | Origen, actor, método, fuente e inferencia |
| `H` | `hipotesis.instructions.md` | Formulación tentativa, estatuto y validación |
| `M` | `politica_de_memoria_activa.instructions.md` | Memoria, TTL, relevancia, recencia y recuperabilidad |
| `E` | `elementos_especificos.instructions.md` | Recursos, referencias y materiales concretos |
| `L` | `glosario_y_convenciones.instructions.md` | Vocabulario, alias y convenciones semánticas |
| `N` | `principios_de_gestion.instructions.md` | Principios transversales y conflictos normativos |
| `X` | `dependencia_y_superficie_externa.instructions.md` | Dependencias, CI/CD, supply chain y toolchains |
| `K` | `contratos.instructions.md` | Contratos de sesión y familias contractuales |
| `RPR` | `PRcommits.instructions.md` | Commits, PRs y contrato JSON de PR |
| `D` | `detalles_del_tema.instructions.md` | Detalles del tema y despliegue temático |

## Regla transversal S66

S66 es la regla de cierre gobernado de sesión:

- `data/out/local/sessions/` registra memoria operativa, evidencia de cierre,
  trazabilidad y staging.
- `data/out/local/tiddlers_*.jsonl` conserva la autoridad de canon local cuando
  existe en la máquina.
- El agente no escribe directamente al canon por defecto.
- Las salidas que deban poder entrar al canon comienzan como líneas candidatas
  bajo `data/out/local/sessions/`.
- La admisión al canon es un proceso local posterior y autorizado, no un efecto
  de conversación, Git, commit, PR o generación de archivos.

## Familia mínima obligatoria

Toda sesión ordinaria debe cerrar con un archivo propio por sesión y por familia
de artefacto:

```text
{contrato, procedencia, detalles, hipótesis, balance, propuesta, diagnóstico}
```

Rutas oficiales:

```text
data/out/local/sessions/00_contratos/<session>.md.json
data/out/local/sessions/01_procedencia/<session>.md.json
data/out/local/sessions/02_detalles_de_sesion/<session>.md.json
data/out/local/sessions/03_hipotesis/<session>.md.json
data/out/local/sessions/04_balance_de_sesion/<session>.md.json
data/out/local/sessions/05_propuesta_de_sesion/<session>.md.json
data/out/local/sessions/06_diagnoses/sesion/<session>.md.json
```

El diagnóstico de sesión de familia `sesion` es obligatorio. Diagnósticos
especializados (`tema`, `canon`, `derivados`, `reverse`, `proyecto`, `modulo`,
`micro_ciclo`, `meso_ciclo`) solo se producen si el operador lo pide o si una
sesión diagnóstica lo declara como objetivo explícito.

No crear archivos acumulativos globales de sesión. No inventar familias, rutas,
numeración ni formatos alternos.

## Convención de títulos

Todo tiddler producido como resultado de una sesión debe tener un `title` que
empiece por `#### 🌀`.

La numeración universal de sesión usa exactamente 4 dígitos con ceros a la
izquierda y sin prefijo `S` en el campo `title`:

```text
n -> f'{int(n):04d}'
```

El prefijo `S` puede usarse en campos técnicos como `"session": "S0163"` o en
rutas de archivo, pero no dentro del título canónico.

Títulos por familia:

```text
#### 🌀 Contrato de sesión <NNNN> = <slug>
#### 🌀🧾 Procedencia de sesión <NNNN> = <slug>
#### 🌀 Sesión <NNNN> = <slug>
#### 🌀🧪 Hipótesis de sesión <NNNN> = <slug>
#### 🌀 Balance de sesión <NNNN> = <slug>
#### 🌀 Propuesta de sesión <NNNN> = <slug>
#### 🌀 Diagnóstico de sesión <NNNN> = <slug>
```

`<NNNN>` se extrae de `mXX-sNNNN-...`. `<slug>` es el resto del identificador
sin el prefijo `mXX-sNNNN-` y sin `session-` cuando aparezca como prefijo
operativo inmediato.

## Sesión, candidato, canon local y derivado

- `sesión`: familia de artefactos `.md.json` bajo `data/out/local/sessions/`
  que documenta trabajo situado y evidencia.
- `línea candidata`: JSONL en formato canon producido durante una sesión y
  todavía no admitido.
- `canon local`: `data/out/local/tiddlers_*.jsonl`, fuente de verdad local
  validada cuando existe.
- `derivado`: capa computada a partir del canon, como `enriched/`, `ai/`,
  `audit/`, `export/` o `reverse_html/`; no es autoridad canónica por sí misma.

`data/out/local/sessions/` no es canon paralelo.

## Líneas candidatas

Cuando una sesión produzca memoria que deba poder entrar al canon, debe dejar
líneas candidatas en formato canon bajo `data/out/local/sessions/`.

Toda línea candidata debe:

- ser JSONL válido;
- respetar la estructura canónica vigente;
- declarar sesión de origen;
- declarar familia de artefacto;
- declarar procedencia suficiente;
- apuntar al archivo fuente bajo `data/out/local/sessions/`;
- conservar estado de candidata no admitida;
- evitar campos reservados por reverse dentro de `source_fields`;
- no reclamar autoridad final antes de admisión.

Campos de trazabilidad recomendados en `source_fields`: `session_origin`,
`artifact_family`, `source_path`, `provenance_ref`, `canonical_status` y claves
específicas con prefijo `x_`.

## Compuertas de admisión

Ninguna línea candidata debe considerarse admitida al canon hasta pasar, como
mínimo:

1. validación local de JSON/JSONL;
2. validación de estructura canónica;
3. validación de campos obligatorios;
4. validación de identificadores;
5. validación de procedencia;
6. validación de relaciones, si aplica;
7. `strict`;
8. `reverse-preflight`;
9. reverse autoritativo con `Rejected: 0`;
10. tests pertinentes para canon, reverse, derivados o el frente afectado.

La admisión se ejecuta sobre una copia temporal o mediante proceso local
autorizado. Si cualquier compuerta falla, no se modifica
`data/out/local/tiddlers_*.jsonl`.

`git add`, `git commit`, `git push`, PRs y conversación no son mecanismos de
admisión canónica.

## Señal corta permitida para archivos dependientes

Los archivos que usan esta regla pueden conservar una señal de cumplimiento como:

```md
Nota de cumplimiento S66:
para cierre de sesión, títulos canónicos, líneas candidatas y admisión local,
seguir `.github/instructions/canonical_session_family.instructions.md`.
No inventar familias, rutas, numeración ni formatos alternos.
```

No deben copiar nuevamente la definición completa de familia mínima, rutas,
títulos, candidatos y compuertas.
