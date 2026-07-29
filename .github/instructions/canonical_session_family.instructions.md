---
description: >
  Dueño normativo de la familia canónica de sesión, sus rutas, títulos,
  identidad documental, líneas candidatas y admisión local gobernada.
---

# Familia canónica de sesión

## Alcance

Este archivo gobierna:

- la familia obligatoria de siete entregables;
- sus nombres, rutas y títulos exactos;
- su identidad documental;
- su maduración y cierre;
- su capacidad de producir líneas candidatas;
- la admisión local gobernada por S66.

No gobierna:

- la metodología de sesión;
- la selección de la instrucción ejecutable;
- el contenido epistemológico de cada entregable;
- el schema interno de los archivos `.md.json`;
- la ejecución de commits o pull requests.

Estas responsabilidades pertenecen a sus instrucciones especializadas.

## Principio rector

Una sesión ordinaria conserva:

```text
una sesión
→ una identidad
→ una familia
→ siete entregables
````

Cada regla tiene un único dueño.

Los archivos dependientes pueden invocar esta instrucción, pero no deben copiar
ni redefinir la familia, los títulos, las rutas o las compuertas de admisión.

## Familia obligatoria

Toda sesión ordinaria debe producir exactamente estos siete entregables:

| Orden | Entregable canónico     | Ruta oficial                                                       |
| ----: | ----------------------- | ------------------------------------------------------------------ |
|     1 | `Contrato de sesión`    | `data/out/local/sessions/00_contratos/<session>.md.json`           |
|     2 | `Procedencia de sesión` | `data/out/local/sessions/01_procedencia/<session>.md.json`         |
|     3 | `Sesión`                | `data/out/local/sessions/02_detalles_de_sesion/<session>.md.json`  |
|     4 | `Hipótesis de sesión`   | `data/out/local/sessions/03_hipotesis/<session>.md.json`           |
|     5 | `Balance de sesión`     | `data/out/local/sessions/04_balance_de_sesion/<session>.md.json`   |
|     6 | `Propuesta de sesión`   | `data/out/local/sessions/05_propuesta_de_sesion/<session>.md.json` |
|     7 | `Diagnóstico de sesión` | `data/out/local/sessions/06_diagnoses/sesion/<session>.md.json`    |

`<session>` usa el patrón:

```text
mXX-sNNNN-<slug>
```

Ejemplo:

```text
m04-s0183-admision-relacional-canonica-gobernada.md.json
```

El mismo nombre base debe usarse en las siete rutas.

No inventes:

* familias adicionales;
* carpetas alternativas;
* nombres abreviados;
* archivos acumulativos globales;
* extensiones distintas de `.md.json`.

El `Diagnóstico de sesión` es obligatorio.

Los diagnósticos especializados no sustituyen este entregable y se gobiernan
en `tiddlers_sesiones.instructions.md`.

## Títulos canónicos

Todo entregable debe usar exactamente el título correspondiente:

```text
#### 🌀 Contrato de sesión <NNNN> = <slug>
#### 🌀🧾 Procedencia de sesión <NNNN> = <slug>
#### 🌀 Sesión <NNNN> = <slug>
#### 🌀🧪 Hipótesis de sesión <NNNN> = <slug>
#### 🌀 Balance de sesión <NNNN> = <slug>
#### 🌀 Propuesta de sesión <NNNN> = <slug>
#### 🌀 Diagnóstico de sesión <NNNN> = <slug>
```

Reglas:

* `<NNNN>` usa exactamente cuatro dígitos.
* El número se obtiene de `mXX-sNNNN`.
* El título no incluye el prefijo `S`.
* `<slug>` corresponde al tema estable de la sesión.
* No agregues anotaciones entre `<NNNN>` y `=`.
* No sustituyas los nombres canónicos por sinónimos.

El nombre operativo `detalles de sesión` corresponde al entregable cuyo título
canónico es `Sesión`.

## Identidad documental

Los siete entregables comparten:

* `session_id`;
* módulo;
* número de sesión;
* slug temático base.

Cada entregable conserva:

* su ruta;
* su título;
* su `canonical_slug` propio;
* su fecha `created`;
* su identidad documental.

Durante la sesión:

* actualiza el mismo archivo;
* preserva `created`;
* actualiza `modified`;
* reconcilia el contenido existente;
* evita reemplazos destructivos.

No crees variantes como:

```text
-inicial
-final
-v2
-revisado
-corregido
-nuevo
```

Una modificación no crea una nueva identidad.

Un cambio de identidad requiere una nueva sesión o una decisión explícita de
migración.

## Maduración de la familia

La familia madura progresivamente durante:

```text
preimpacto
→ impacto
→ postimpacto
```

La macrofase no cambia la identidad del artefacto.

Distribución principal:

| Instrucción    | Entregables principales                          |
| -------------- | ------------------------------------------------ |
| Reconocimiento | `Procedencia de sesión`, `Diagnóstico de sesión` |
| Formulación    | `Hipótesis de sesión`, `Contrato de sesión`      |
| Implementación | `Sesión`                                         |
| Cierre         | `Balance de sesión`, `Propuesta de sesión`       |

Cualquier entregable puede actualizarse después cuando aparezca evidencia
relevante.

La existencia física de un archivo no significa que esté completo o cerrado.

## Cierre de la familia

La familia solo se considera cerrada después del postimpacto.

Para cerrar deben cumplirse todas estas condiciones:

* existen los siete entregables;
* pertenecen a la misma sesión;
* usan los nombres y rutas oficiales;
* usan títulos canónicos;
* conservan identidad coherente;
* no existen variantes paralelas;
* el schema de los siete archivos es válido;
* el diagnóstico refleja el estado final;
* las hipótesis tienen estado explícito;
* el contrato fue contrastado;
* los detalles contienen evidencia operativa;
* el balance evalúa el resultado;
* la propuesta deriva de la evidencia real.

Una implementación terminada no cierra por sí sola la familia.

Un commit, push o pull request tampoco la cierra.

## Canonizabilidad

Todos los entregables deben ser canonizables.

Un entregable es canonizable cuando:

* es un objeto `.md.json` válido;
* usa el título canónico;
* conserva una identidad estable;
* contiene texto estructurado suficiente;
* declara sesión y procedencia verificables;
* puede transformarse mediante el productor autoritativo;
* puede producir una línea candidata compatible con el canon vigente.

Canonizable no significa admitido.

La ausencia de una candidata no invalida automáticamente el entregable, pero
la sesión debe declarar si:

* no era necesaria;
* quedó pendiente;
* fue producida;
* fue validada;
* fue admitida.

## Superficies de autoridad

```text
data/out/local/sessions/
```

Es:

* memoria operativa;
* superficie de entrega;
* evidencia de sesión;
* staging de candidatas.

No es canon paralelo.

```text
data/out/local/tiddlers_*.jsonl
```

Es el canon local autoritativo cuando existe en la máquina.

Son derivados no autoritativos por sí mismos:

* `enriched/`;
* `ai/`;
* `audit/`;
* `export/`;
* `reverse_html/`;
* `data/out/remote/`.

Una superficie derivada puede aportar evidencia, pero no reemplaza al canon.

## Líneas candidatas

Cuando un entregable deba poder ingresar al canon, genera una línea candidata
bajo la superficie de sesión gobernada.

Toda candidata debe:

* ser JSONL válido;
* respetar la estructura canónica vigente;
* declarar la sesión de origen;
* declarar la familia del artefacto;
* apuntar al archivo fuente;
* declarar procedencia verificable;
* conservar estado no admitido;
* evitar campos reservados por reverse;
* no reclamar autoridad final.

Trazabilidad mínima:

* `session_origin`;
* `artifact_family`;
* `source_path`;
* `provenance_ref`;
* `canonical_status`.

Los campos auxiliares específicos deben usar el prefijo `x_` cuando
corresponda.

Si cambia el artefacto fuente, la candidata relacionada debe regenerarse o
revalidarse.

Una candidata no debe asumirse vigente solo porque ya existe.

## Regla S66

S66 gobierna el cierre documental y la admisión local:

```text
sesión
→ entregable canonizable
→ línea candidata
→ validación
→ autorización
→ admisión local
→ reverse verificable
```

La admisión es posterior, local, explícita y reversible.

No ocurre como consecuencia automática de:

* conversación;
* generación de archivos;
* validación de schema;
* commit;
* push;
* pull request;
* sincronización remota.

## Compuertas de admisión

Una candidata solo puede admitirse después de superar, cuando correspondan:

1. validación JSON y JSONL;
2. validación de schema canónico;
3. validación de campos obligatorios;
4. validación de identificadores;
5. validación de procedencia;
6. validación de relaciones;
7. preflight `strict`;
8. `reverse-preflight`;
9. reverse autoritativo con `Rejected: 0`;
10. tests del canon, reverse, derivados o frente afectado.

La operación debe:

* usar una copia temporal o proceso local gobernado;
* registrar el lote exacto;
* reconciliar conteos;
* conservar respaldo;
* disponer de rollback cuando aplique;
* producir evidencia o receipt;
* contar con autorización humana explícita.

Si una compuerta falla, no modifiques:

```text
data/out/local/tiddlers_*.jsonl
```

## Vigencia de la autorización

Toda autorización queda vinculada al estado exacto validado.

Debe renovarse si cambia alguno de estos elementos:

* canon;
* hash;
* lote;
* manifest;
* candidatas;
* decisiones humanas;
* conteos esperados;
* archivos de destino;
* operación;
* snapshot;
* rollback;
* gate report.

No reutilices una autorización vinculada a un estado anterior.

## Evolución canónica

El canon puede cambiar legítimamente en:

* contenido;
* estructura;
* procedencia;
* relaciones;
* conteo;
* hash.

Un cambio de conteo o hash no constituye por sí mismo deriva.

Es gobernado cuando:

* existe un productor autorizado;
* la procedencia es suficiente;
* las compuertas aprueban;
* los consumidores vinculados fueron reconciliados;
* el cambio es reversible y verificable.

Es deriva no explicada cuando falta mecanismo, evidencia o coherencia con el
flujo autorizado.

## Prohibiciones

* No omitas uno de los siete entregables.
* No cambies sus nombres canónicos.
* No cambies las rutas oficiales.
* No crees archivos paralelos para una misma identidad.
* No trates `sessions/` como canon.
* No escribas directamente en el canon por defecto.
* No declares una candidata como admitida por existir.
* No promociones derivados como fuente de verdad.
* No uses Git como mecanismo de admisión.
* No absorbas una candidata después de una compuerta fallida.
* No copies esta definición completa en otras instrucciones.

## Referencia corta permitida

Los archivos dependientes pueden usar:

```text
Para familia, títulos, identidad, canonizabilidad, candidatas y admisión local,
aplica canonical_session_family.instructions.md.
```

No deben redefinir estas reglas.

## Criterio de cumplimiento

Esta instrucción se cumple cuando:

* existe exactamente una familia de siete entregables;
* sus nombres, rutas y títulos son canónicos;
* cada artefacto conserva una identidad estable;
* los siete archivos son `.md.json` válidos y canonizables;
* no existen variantes paralelas;
* la familia solo se cierra después del postimpacto;
* toda candidata conserva estado no admitido hasta superar S66;
* toda admisión es local, autorizada, verificable y reversible.

