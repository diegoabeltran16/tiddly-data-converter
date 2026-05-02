## Instrucción de commits y pull requests

Para tareas de commits y pull requests en el repositorio `tiddly-data-converter`, usa como contrato activo, fuente de verdad y regla obligatoria de salida el archivo:

`data/sessions/00_contratos/policy/estructura_de_commits_tiddly-data-converter.JSON`

Además, debes respetar la instrucción contractual definida en:

`.github/instructions/contratos.instructions.md`

Debes leer ambos marcos antes de construir cualquier propuesta de commit o pull request.

Actúa como asistente operativo de commits y pull requests del repositorio. Cada vez que el usuario describa un cambio, una sesión, una propuesta de integración, una corrección, un ajuste documental o una modificación de ejecución real, debes documentar esa propuesta siguiendo estrictamente la estructura de commits y pull requests definida en el contrato JSON del repositorio.

Esto no aplica solo a una respuesta aislada. Aplica a toda propuesta que el agente genere en materia de commits y pull requests. Toda propuesta debe quedar estructurada conforme al contrato del repositorio, sin inventar formatos alternativos, sin simplificar la salida y sin sustituir la taxonomía definida en el JSON.

---

## Principio rector

**El JSON gobierna; el Markdown operacionaliza.**

`estructura_de_commits_tiddly-data-converter.JSON` es la fuente de verdad contractual.

`PRcommits.instructions.md` es la proyección operativa legible de esa fuente de verdad. Su función es impedir que el agente reduzca la entrega a un resumen informal, omita tablas, omita secciones, use categorías inventadas o entregue un PR incompleto.

Si existe divergencia entre este archivo y el contrato JSON activo, el JSON prevalece. Sin embargo, la divergencia debe considerarse deuda documental y debe corregirse en el mismo PR o declararse explícitamente en `Notas para el revisor`.

---

## Instrucción crítica

Debes:

- leer `data/sessions/00_contratos/estructura_de_commits_tiddly-data-converter.JSON` antes de responder;
- leer `.github/instructions/contratos.instructions.md` antes de responder;
- obedecer las reglas duras del contrato JSON;
- usar sus clasificaciones;
- aplicar sus templates;
- respetar sus enums;
- inferir campos faltantes según su política conservadora;
- usar sus fallbacks cuando falte información suficiente;
- mantener consistencia semántica con el repositorio;
- no reemplazar el contrato por convenciones genéricas de Git, GitHub o Conventional Commits.

---

## Objetivo obligatorio

Cuando el usuario describa lo realizado en una sesión o un cambio técnico concreto, debes analizar ese cambio y devolver siempre exactamente estos 3 artefactos, en este orden:

1. `commitName`
2. `prTitle`
3. `prDescriptionMarkdown`

No debes devolver solo uno o dos artefactos.

No debes devolver solo YAML, solo metadatos, solo un resumen, solo observaciones o solo recomendaciones.

---

## Regla de documentación obligatoria

Cada propuesta generada por el agente debe quedar documentada en la descripción del pull request siguiendo la estructura del contrato definido en:

`data/sessions/00_contratos/estructura_de_commits_tiddly-data-converter.JSON`

No debes producir descripciones libres, resúmenes informales ni formatos improvisados. La descripción del pull request debe responder a la estructura oficial del repositorio.

El campo `prDescriptionMarkdown` no es una explicación narrativa del cambio.

El campo `prDescriptionMarkdown` es la descripción completa del pull request, en Markdown, lista para copiar y pegar en GitHub.

---

## Estructura obligatoria del `prDescriptionMarkdown`

La salida debe conservar la anatomía completa del template oficial. Como mínimo, el PR debe incluir las siguientes secciones, en este orden:

1. Título del PR.
2. Bloque inicial en `text` con:
   - `Commit`
   - `Meta`
   - `Arch`
3. Separador `---`.
4. Tabla de `Metadatos`.
5. Separador `---`.
6. Tabla de `Tablero y Arquitectura`.
7. Separador `---`.
8. `Objetivo`.
9. Separador `---`.
10. `Resultado integrado`.
11. Separador `---`.
12. `Acciones realizadas`.
13. Separador `---`.
14. `Archivos modificados / añadidos`.
15. Separador `---`.
16. `Comprobaciones sugeridas`.
17. Separador `---`.
18. `Notas para el revisor`.

No está permitido sustituir esta estructura por:

- una explicación narrativa;
- una lista corta;
- un resumen ejecutivo;
- una descripción informal;
- una tabla parcial;
- un bloque YAML;
- un bloque `Meta` sin cuerpo de PR;
- una respuesta que diga que el contrato debe leerse sin entregar el PR completo.

---

## Template operativo obligatorio

El agente debe producir el `prDescriptionMarkdown` con esta forma base:

````markdown
# PR: {prTitle}

```text
Commit: {commitName}
Meta: Es:{Estado}|V:{Vuelta}|R:{Radio}|Md:{Madurez}|B:{Bloque}|Ctx:{ContextoCambio}|Pr:{Priority}|Sz:{Size}|Est:{Estimate}|Dr:{Delta-r}|Dc:{Delta-c}
Arch: Sb:{StatusTablero}|Ea:{EstadoArquitectonico}|Cx:{CajaArquitectonica}|Lg:{Lenguajes}|Mdls:{Modulos}
```

---

## Metadatos

| Campo | Valor |
|-------|-------|
| Estado | {Estado} |
| Vuelta | {Vuelta} |
| Radio | {Radio} |
| Madurez | {Madurez} |
| Bloque | {Bloque} |
| ContextoCambio | {ContextoCambio} |
| Priority | {Priority} |
| Size | {Size} |
| Estimate | {Estimate} |
| Delta-r | {Delta-r} |
| Delta-c | {Delta-c} |

---

## Tablero y Arquitectura

| Campo | Valor |
|-------|-------|
| StatusTablero | {StatusTablero} |
| EstadoArquitectonico | {EstadoArquitectonico} |
| Caja | {CajaArquitectonica} |
| Lenguajes | {Lenguajes} |
| Modulos | {Modulos} |

---

## Objetivo

{Objetivo}

---

## Resultado integrado

{ResultadoIntegrado}

---

## Acciones realizadas

{AccionesRealizadas}

---

## Archivos modificados / añadidos

{ArchivosModificados}

---

## Comprobaciones sugeridas

{ComprobacionesSugeridas}

---

## Notas para el revisor

{NotasRevisor}
````

El template anterior debe respetarse incluso cuando el cambio sea pequeño, documental o aparentemente simple.

---

## Regla sobre `commitName`

`commitName` debe seguir el template contractual:

```text
{tipoCommit}({alcance}): {operacionNormalizada} {complementoEspecifico}
```

El commit debe ser concreto, verificable y coherente con el alcance real del cambio.

No usar:

- `update`
- `changes`
- `misc`
- `varios`
- `cambios varios`
- `ajustes varios`
- fórmulas ambiguas que no permitan entender qué se integró.

Ejemplo aceptable para un cambio documental de contrato:

```text
docs(contract): formaliza entrega completa de PRs contractuales
```

---

## Regla sobre `prTitle`

`prTitle` debe seguir el template contractual:

```text
{bloquePR}({alcance}): {sintesisIntegradora} {resultadoPrincipal}
```

El título del PR debe expresar la integración realizada, no solo la actividad ejecutada.

No debe limitarse a decir:

- `Actualización de documentación`
- `Cambios en instrucciones`
- `Mejoras`
- `PR de sesión`
- `Ajustes varios`

Ejemplo aceptable:

```text
docs(contract): aclara estructura obligatoria de PRs con tablas y trazabilidad
```

---

## Regla sobre las líneas `Meta` y `Arch`

El bloque inicial del PR debe incluir siempre las líneas `Meta` y `Arch`.

Estas líneas no sustituyen las tablas posteriores. Funcionan como encabezado compacto para lectura rápida, automatización futura y revisión operativa.

La línea `Meta` debe contener:

```text
Meta: Es:{Estado}|V:{Vuelta}|R:{Radio}|Md:{Madurez}|B:{Bloque}|Ctx:{ContextoCambio}|Pr:{Priority}|Sz:{Size}|Est:{Estimate}|Dr:{Delta-r}|Dc:{Delta-c}
```

La línea `Arch` debe contener:

```text
Arch: Sb:{StatusTablero}|Ea:{EstadoArquitectonico}|Cx:{CajaArquitectonica}|Lg:{Lenguajes}|Mdls:{Modulos}
```

No separar estos campos en otro formato si el contrato activo no lo permite.

---

## Regla sobre tablas obligatorias

Las tablas de `Metadatos` y `Tablero y Arquitectura` son obligatorias.

No son decoración. Cumplen una función de:

- revisión rápida;
- trazabilidad;
- comparación entre PRs;
- detección de contradicciones;
- lectura de impacto;
- auditoría documental;
- futura automatización del tablero.

El agente no debe omitirlas aunque:

- el cambio sea pequeño;
- el cambio sea solo documental;
- el usuario pida algo breve;
- el PR parezca evidente;
- ya existan las líneas `Meta` y `Arch`.

Si las tablas faltan, el `prDescriptionMarkdown` está incompleto.

---

## Regla sobre `Objetivo`

La sección `Objetivo` debe explicar qué busca integrar el PR.

Debe responder:

- qué problema o vacío corrige;
- qué decisión estabiliza;
- qué comportamiento futuro busca asegurar.

No debe limitarse a repetir el nombre del commit.

Ejemplo aceptable:

```markdown
Formalizar la instrucción operativa de commits y pull requests para que los agentes entreguen siempre un PR completo, con tablas de metadatos, clasificación arquitectónica, acciones verificables, archivos afectados y comprobaciones sugeridas.
```

---

## Regla sobre `Resultado integrado`

La sección `Resultado integrado` debe explicar el estado final que deja el PR después de aplicarse.

Debe responder:

- qué queda más claro;
- qué queda gobernado;
- qué ambigüedad se elimina;
- qué parte del flujo queda protegida.

Ejemplo aceptable:

```markdown
El repositorio queda con una instrucción operativa más explícita para construir `commitName`, `prTitle` y `prDescriptionMarkdown`, evitando que los PRs contractuales se entreguen como resúmenes informales o sin las tablas obligatorias definidas por el contrato JSON.
```

---

## Regla sobre `Acciones realizadas`

La sección `Acciones realizadas` debe describir los cambios de forma verificable.

No usar frases vagas como:

- `se hicieron ajustes`;
- `se actualizó documentación`;
- `se mejoraron instrucciones`;
- `cambios varios`;
- `se refinó el contrato`;
- `se agregó claridad`.

Cada acción debe indicar qué se modificó y con qué propósito.

Ejemplo aceptable:

```markdown
- Se añadió una regla explícita que define el `prDescriptionMarkdown` como una descripción completa de Pull Request, no como resumen libre.
- Se incorporó el template operativo completo con bloque `Commit`, línea `Meta`, línea `Arch`, tablas obligatorias y secciones de revisión.
- Se aclaró que las tablas de `Metadatos` y `Tablero y Arquitectura` no son opcionales.
- Se formalizó la regla especial para PRs normativos que modifican la estructura de commits y pull requests.
- Se reforzó la relación entre el JSON como fuente de verdad y este Markdown como proyección operativa legible.
```

---

## Regla sobre `Archivos modificados / añadidos`

La sección `Archivos modificados / añadidos` debe listar los archivos concretos tocados por el cambio.

Cada archivo debe incluir una breve explicación de su función dentro del PR.

No basta con mencionar una carpeta o decir `documentación`.

Ejemplo aceptable:

```markdown
- `.github/instructions/PRcommits.instructions.md`
  - Formaliza la entrega obligatoria de PRs completos.
  - Replica la anatomía crítica del `prDescriptionMarkdown` para evitar salidas incompletas.
  - Aclara cómo manejar PRs normativos sobre estructura de commits y pull requests.

- `data/sessions/00_contratos/estructura_de_commits_tiddly-data-converter.JSON`
  - No modificado en este PR.
  - Se mantiene como fuente de verdad contractual.
```

Si un archivo no fue modificado pero es relevante para entender el cambio, puede mencionarse como `No modificado`, siempre que quede claro por qué se referencia.

---

## Regla sobre `Comprobaciones sugeridas`

La sección `Comprobaciones sugeridas` debe permitir que el revisor valide el PR sin reconstruir mentalmente la intención del cambio.

Debe indicar, según aplique:

- si el cambio es solo documental;
- si modifica o no el contrato JSON;
- si requiere o no migración;
- si afecta o no CI, scripts, validadores o runtime;
- si requiere o no contrato de sesión `.md.json`;
- si existen pruebas, validaciones o revisión manual esperada;
- si las tablas obligatorias aparecen completas;
- si los enums usados pertenecen al contrato activo.

Ejemplo aceptable:

```markdown
- Verificar que el PR conserva los 3 artefactos obligatorios: `commitName`, `prTitle` y `prDescriptionMarkdown`.
- Verificar que el `prDescriptionMarkdown` incluye las tablas de `Metadatos` y `Tablero y Arquitectura`.
- Verificar que no se introducen categorías fuera de los enums definidos en el contrato JSON.
- Verificar que el cambio es documental y no altera comportamiento runtime.
- Verificar si corresponde acompañar este PR con contrato de sesión `.md.json`.
```

---

## Regla sobre `Notas para el revisor`

La sección `Notas para el revisor` debe explicar cualquier decisión que pueda generar duda.

En PRs normativos, debe aclarar especialmente:

- si el cambio altera reglas futuras;
- si afecta PRs históricos;
- si el JSON fue modificado o solo referenciado;
- si este `.md` funciona como espejo operativo del JSON o como nueva fuente normativa;
- si existe deuda de sincronización entre JSON y Markdown;
- si hay alguna decisión que no debe interpretarse como cambio runtime.

Ejemplo aceptable:

```markdown
Este PR no cambia la fuente de verdad contractual. El JSON sigue gobernando la estructura oficial de commits y pull requests.

El cambio refuerza `PRcommits.instructions.md` como instrucción operativa legible para que los agentes no reduzcan el PR a un resumen informal ni omitan las tablas obligatorias.
```

---

## Regla especial: PR normativo sobre estructura de commits y pull requests

Cuando el pull request tenga como objetivo crear, corregir, endurecer, aclarar o dictaminar la estructura de commits y pull requests del repositorio, debe tratarse como un **PR normativo de gobernanza documental/contractual**.

Este tipo de PR no se entrega como explicación libre, resumen informal ni propuesta conceptual. Debe entregarse usando los mismos 3 artefactos obligatorios definidos por el contrato:

1. `commitName`
2. `prTitle`
3. `prDescriptionMarkdown`

La diferencia es que el `prDescriptionMarkdown` debe dejar explícito, dentro de las secciones oficiales del template, que el cambio afecta las reglas futuras de generación, revisión o interpretación de commits y pull requests.

### Clasificación por defecto para PR normativo

Para un PR normativo sobre estructura de commits y pull requests, usar por defecto:

- `tipoCommit`: `docs`
- `alcance`: `contract`
- `bloquePR`: `docs` o `contract`, según el énfasis del cambio;
- `ContextoCambio`: `documental`
- `StatusTablero`: `Documentación`
- `EstadoArquitectonico`: `Documentación`
- `CajaArquitectonica`: `no aplica`
- `Lenguajes`: `no aplica`
- `Modulos`: los artefactos documentales o contractuales afectados.

Solo usar `ContextoCambio = transversal` si el cambio modifica también validadores, automatizaciones, CI, tooling, scripts o consumidores runtime que dependan de la estructura de commits/PRs.

### Archivos esperados para PR normativo

Un PR normativo sobre estructura de commits puede modificar uno o varios de estos artefactos:

- `.github/instructions/PRcommits.instructions.md`
- `data/sessions/00_contratos/estructura_de_commits_tiddly-data-converter.JSON`
- `data/sessions/00_contratos/<sesion>.md.json`

Si el cambio solo aclara cómo debe comportarse el agente al entregar commits y PRs, basta con modificar `PRcommits.instructions.md`.

Si el cambio altera enums, templates, campos, fallbacks, reglas de inferencia o el formato obligatorio de salida, entonces también debe modificarse el contrato JSON correspondiente.

Si el cambio es sustantivo, debe existir además un contrato de sesión `.md.json` que preserve la trazabilidad de la decisión.

### Contenido obligatorio en PR normativo

El `prDescriptionMarkdown` de un PR normativo debe explicar claramente:

- qué regla se está creando, aclarando o endureciendo;
- por qué la regla anterior era ambigua o insuficiente;
- qué comportamiento deben seguir los agentes a partir de este cambio;
- si el cambio afecta o no PRs históricos;
- si el cambio requiere o no migración del contrato JSON;
- si el cambio requiere o no ajustes en scripts, validadores, CI o documentación relacionada;
- si el JSON sigue siendo la fuente de verdad o si fue actualizado por el PR.

### Regla de compatibilidad para PR normativo

Un PR que modifica la estructura de commits y pull requests debe construirse usando la versión vigente del contrato al momento de redactarlo.

El PR no puede inventar una nueva forma de entregarse para justificarse a sí mismo.

La nueva regla solo gobierna los PRs futuros una vez el cambio sea aceptado e integrado.

### Regla de no mezcla para PR normativo

Un PR normativo sobre estructura de commits no debe mezclarse con cambios runtime, refactors de código, admisión canónica, reverse, tests funcionales o modificaciones no relacionadas.

Si además se requiere cambiar tooling o validadores, esos cambios deben declararse explícitamente como impacto transversal o separarse en otro PR.

---

## Acople obligatorio con contratos de sesión

Si la propuesta de pull request describe un cambio sustantivo, estructural, operativo, semántico o documental relevante, no basta con generar:

1. `commitName`
2. `prTitle`
3. `prDescriptionMarkdown`

También debe existir al menos **1 contrato de sesión serializado como archivo `.md.json`** bajo `data/sessions/00_contratos/`, compatible con la lógica de importación a TiddlyWiki usada por el repositorio.

Ese contrato no reemplaza el PR y el PR no reemplaza el contrato.

La descripción del pull request resume e integra el cambio.

El contrato de sesión conserva la trazabilidad técnica estructurada.

Si falta ese artefacto `.md.json` cuando la sesión respalda cambios sustantivos, la propuesta debe considerarse documentalmente incompleta.

Git no decide la admisión canónica. Antes de recomendar commit o push de una sesión que afecte canon o produzca líneas candidatas, debe existir evidencia de:

- familia mínima producida bajo `data/sessions/`;
- diagnóstico de sesión obligatorio;
- líneas candidatas en formato canon, si existen;
- validación local pasada o documentada como pendiente;
- reverse autoritativo con `Rejected: 0` si se ejecutó admisión temporal o canónica;
- tests requeridos pasados o documentados como no ejecutados.

---

## Reglas de ejecución

- No devuelvas solo YAML.
- No devuelvas solo meta.
- No devuelvas un resumen corto.
- No expliques el contrato cuando el usuario pidió los artefactos.
- No reformules el pedido como teoría.
- Entrega directamente los 3 artefactos completos.
- El markdown del pull request debe venir listo para copiar y pegar en GitHub.
- Si el cambio es documental, usa la clasificación documental definida en el JSON.
- Si el cambio afecta ejecución real, usa la clasificación runtime definida en el JSON.
- Si el cambio afecta varias zonas compartidas, usa la clasificación transversal.
- Si falta información, inferir de forma conservadora y coherente usando los fallbacks del JSON.
- No inventes categorías, campos, nombres, scopes o estructuras por fuera del contrato.
- No reemplaces el contrato por convenciones genéricas si el JSON ya define una forma oficial.
- No consideres completo un PR sustantivo si no está acompañado por su contrato de sesión `.md.json`.
- No omitas las tablas de `Metadatos` y `Tablero y Arquitectura`.
- No reemplaces `Acciones realizadas` por frases genéricas.
- No dejes `Archivos modificados / añadidos` sin rutas concretas.
- No dejes `Comprobaciones sugeridas` sin criterios revisables.

---

## Proceso obligatorio

1. Leer `data/sessions/00_contratos/estructura_de_commits_tiddly-data-converter.JSON`.
2. Leer `.github/instructions/contratos.instructions.md`.
3. Identificar el tipo de cambio descrito por el usuario.
4. Identificar si el cambio es documental, runtime o transversal.
5. Identificar si el cambio es normativo sobre estructura de commits y pull requests.
6. Clasificar el cambio según enums, reglas y criterios del contrato.
7. Construir `commitName`.
8. Construir `prTitle`.
9. Construir `prDescriptionMarkdown` usando el template completo del contrato.
10. Verificar que existen las líneas `Commit`, `Meta` y `Arch`.
11. Verificar que existen las tablas de `Metadatos` y `Tablero y Arquitectura`.
12. Verificar que `Acciones realizadas` contiene cambios concretos y no frases vagas.
13. Verificar que `Archivos modificados / añadidos` contiene rutas concretas.
14. Verificar que `Comprobaciones sugeridas` permite revisión real.
15. Verificar si el cambio exige contrato de sesión.
16. Si lo exige, asegurar que exista al menos 1 artefacto `.md.json` compatible con TiddlyWiki bajo `data/sessions/00_contratos/`.
17. Entregar la salida final en el orden exacto definido por `outputFormat.order`.

---

## Evidencia obligatoria en commit/PR

El commit o PR debe mencionar claramente, cuando aplique:

- la sesión;
- los artefactos de `data/sessions/` actualizados;
- el contrato de sesión asociado;
- si hubo o no líneas candidatas;
- si hubo o no absorción local al canon;
- si hubo o no cambios en el contrato JSON;
- si hubo o no cambios en instrucciones `.github/instructions/`;
- estado de validación: `strict`, `reverse-preflight`, reverse autoritativo y tests pertinentes;
- si el cambio es únicamente documental o si afecta runtime;
- si el cambio gobierna PRs futuros.

---

## Formato obligatorio de respuesta

El formato de respuesta debe ser exactamente el especificado en el contrato JSON.

Cuando el usuario escriba algo como:

```text
Lo que hicimos en esta sesión fue: ...
```

debes interpretar ese contenido como la base factual del cambio y producir los 3 artefactos obligatorios conforme al contrato.

Cuando la sesión implique cambios sustantivos, debes además asumir que la propuesta completa solo queda cerrada si existe el contrato de sesión `.md.json` correspondiente.

La respuesta final debe mantener este orden:

```text
commitName
prTitle
prDescriptionMarkdown
```

No agregar una cuarta sección salvo que el usuario lo pida explícitamente o que sea necesario declarar una advertencia crítica sobre falta de contrato de sesión, validaciones pendientes o información insuficiente.

---

## Regla de sincronización entre JSON y Markdown

`estructura_de_commits_tiddly-data-converter.JSON` sigue siendo la fuente de verdad contractual.

`PRcommits.instructions.md` funciona como una proyección operativa legible de esa fuente de verdad.

Si en el futuro cambia el template del `prDescriptionMarkdown` dentro del JSON, el mismo PR debe actualizar también la sección equivalente en `PRcommits.instructions.md`, o declarar explícitamente por qué no lo hace.

No debe existir divergencia silenciosa entre ambos archivos.

Si el cambio modifica:

- enums;
- campos;
- fallbacks;
- reglas de inferencia;
- orden de salida;
- wrappers;
- template de `commitName`;
- template de `prTitle`;
- template de `prDescriptionMarkdown`;

entonces el contrato JSON debe actualizarse o debe quedar una nota explícita justificando por qué el cambio solo afecta la instrucción operativa Markdown.
