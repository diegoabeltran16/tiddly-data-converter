---
applyTo: "data/out/local/sessions/00_contratos/**/*.md.json"
description: >
  Dueño normativo del contenido contractual de las sesiones TDC: objetivo,
  alcance, superficies autorizadas, invariantes, riesgos, validaciones,
  detención, aceptación y contraste final.
---

# Contratos de sesión

## Alcance

Esta instrucción gobierna:

- qué autoriza una sesión;
- su objetivo y alcance;
- las superficies permitidas y protegidas;
- entradas y salidas;
- responsabilidades y límites;
- invariantes;
- riesgos;
- validaciones;
- condiciones de detención;
- criterios de aceptación;
- el contenido del entregable `Contrato de sesión`.

No gobierna:

- la procedencia de la evidencia;
- la formulación epistemológica de hipótesis;
- la ejecución detallada de una fase;
- las rutas, títulos o identidad documental;
- el schema `.md.json`;
- las líneas candidatas;
- la admisión al canon;
- commits o pull requests.

Aplicar:

- `procedencia_epistemologica.instructions.md` para origen y evidencia;
- `hipotesis.instructions.md` para afirmaciones contrastables;
- `.agents/skills/tdc-session/SKILL.md` para transiciones y cambios materiales;
- `canonical_session_family.instructions.md` para nombre, título, ruta,
  identidad y canonizabilidad;
- `tiddlers_sesiones.instructions.md` para formato y validación `.md.json`;
- `PRcommits.instructions.md` solo cuando el usuario solicite commit o PR.

## Rol contractual

El contrato responde:

```text
¿Qué trabajo queda autorizado,
sobre qué superficies,
bajo qué condiciones,
con qué límites
y cómo se determinará su resultado?
````

El contrato transforma una intención en una frontera operativa verificable.

No demuestra que una hipótesis sea correcta.

No reemplaza la autorización humana exigida por una operación gobernada.

No convierte una propuesta en implementación ejecutada.

## Cuándo aplica

Toda sesión ordinaria debe mantener un `Contrato de sesión`, incluso cuando su
objetivo sea teórico, documental o diagnóstico.

El contrato puede autorizar:

* análisis no mutante;
* formulación conceptual;
* inspección o diagnóstico;
* modificación documental;
* implementación técnica;
* validación operativa;
* una operación gobernada;
* cierre sin implementación.

El nivel de detalle debe corresponder al riesgo y a la superficie afectada.

Una sesión de bajo riesgo puede usar un contrato breve, pero no puede omitir:

* objetivo;
* alcance;
* límites;
* validación;
* criterio de cierre.

## `Contrato de sesión`

El entregable canónico se denomina exactamente:

```text
Contrato de sesión
```

No uses sinónimos ni variantes para sustituir este nombre.

Debe conservar durante toda la sesión:

* una sola identidad;
* un solo archivo `.md.json`;
* su título y ruta canónicos;
* su `session_id`;
* su `canonical_slug`;
* su fecha `created`.

Las reglas exactas pertenecen a
`canonical_session_family.instructions.md`.

## Precondiciones de formulación

Antes de formular o renovar el contrato:

1. consume `Procedencia de sesión`;
2. consume `Diagnóstico de sesión`;
3. consume `Hipótesis de sesión`;
4. verifica que pertenecen a la misma sesión;
5. confirma que reflejan el estado vigente;
6. identifica incertidumbres y bloqueos;
7. delimita qué trabajo puede autorizarse con la evidencia disponible.

No construyas un contrato desde una especificación ideal desconectada del
repositorio.

No autorices superficies no inspeccionadas.

Cuando la evidencia sea insuficiente, formula un contrato limitado a:

* investigación;
* validación;
* producción de evidencia;
* resolución de bloqueos.

## Perfiles contractuales

Todo archivo sigue siendo un `Contrato de sesión`.

El perfil interno puede variar según el trabajo autorizado.

### Contrato operativo

Úsalo cuando la sesión define o modifica:

* componentes;
* fronteras;
* productores o consumidores;
* entradas y salidas;
* responsabilidades;
* pipelines;
* compuertas;
* comportamiento runtime.

Debe priorizar:

* superficie técnica;
* invariantes;
* fallos bloqueantes;
* pruebas;
* rollback;
* criterios de aceptación.

### Contrato de verificación

Úsalo cuando la sesión se concentra en:

* diagnóstico;
* bootstrap;
* preflight;
* validación de entorno;
* reproducción de un fallo;
* inspección;
* auditoría;
* comprobación de una condición.

Debe priorizar:

* estado de entrada;
* método;
* evidencia esperada;
* operaciones permitidas;
* prohibición de mutaciones no autorizadas;
* criterio de suficiencia.

### Contrato de política o decisión

Úsalo cuando la sesión busca estabilizar:

* una regla;
* una clasificación;
* una convención;
* una decisión semántica;
* un criterio arquitectónico;
* una política documental.

Debe priorizar:

* alternativas consideradas;
* decisión autorizada;
* evidencia;
* alcance normativo;
* compatibilidad;
* consecuencias;
* límites de aplicación.

No crees familias documentales diferentes para estos perfiles.

El entregable continúa llamándose `Contrato de sesión`.

## Contenido mínimo

El contrato debe permitir identificar:

* sesión;
* objetivo;
* estado de entrada relevante;
* hipótesis que se contrastarán;
* alcance incluido;
* asuntos fuera de alcance;
* entradas;
* salidas esperadas;
* archivos o superficies autorizadas;
* archivos o superficies protegidas;
* responsabilidades;
* invariantes;
* restricciones;
* riesgos;
* operaciones permitidas;
* operaciones prohibidas;
* validaciones;
* criterios de aceptación;
* condiciones de detención;
* pendientes conocidos;
* autorización humana requerida;
* estado final del contrato.

Cuando corresponda, debe incluir también:

* comportamiento `fail-closed`;
* snapshot;
* backup;
* receipt o journal;
* rollback;
* conteos esperados;
* hashes o manifests;
* preflights;
* condiciones que invalidan una autorización.

Esta lista gobierna el contenido del campo `text`.

No modifica el schema `.md.json`.

## Objetivo y alcance

El objetivo debe expresar el resultado que la sesión busca dejar, no solo la
actividad que ejecutará.

Evita objetivos como:

```text
actualizar archivos
hacer pruebas
revisar el código
realizar ajustes
```

Prefiere una formulación verificable:

```text
Delimitar y validar el admission gate para impedir que candidatas
desactualizadas compitan con el canon vigente.
```

El alcance debe distinguir:

* incluido;
* excluido;
* protegido;
* condicionado a evidencia;
* condicionado a autorización humana.

No uses expresiones abiertas como:

```text
y cualquier otro archivo necesario
ajustes relacionados
cambios adicionales
lo que resulte conveniente
```

Si una superficie no está identificada, no queda autorizada por defecto.

## Frontera de autorización

El contrato autoriza únicamente las acciones descritas dentro de su alcance.

La implementación debe poder responder:

```text
¿Esta acción está autorizada por el contrato vigente?
```

Cuando la respuesta sea desconocida, detente.

El contrato no sustituye una autorización humana explícita cuando la operación
afecte:

* canon;
* dependencias de producción;
* servicios externos;
* credenciales;
* publicación remota;
* datos irreversibles;
* commits o pull requests;
* operaciones declaradas como gobernadas.

Una autorización humana debe vincularse al estado exacto validado.

## Invariantes

Una invariante es una condición que debe conservarse durante la intervención.

Puede referirse a:

* identidad;
* formato;
* compatibilidad;
* conteos;
* determinismo;
* idempotencia;
* procedencia;
* autoridad;
* reversibilidad;
* aislamiento;
* comportamiento `fail-closed`.

Cada invariante debe ser comprobable.

Evita invariantes vagas como:

```text
mantener la calidad
no romper nada
conservar la arquitectura
```

Declara qué propiedad concreta debe mantenerse y cómo será validada.

## Riesgos

Registra riesgos con incidencia real sobre el trabajo autorizado.

Cada riesgo debe permitir identificar:

* condición que lo activa;
* impacto;
* señal de detección;
* mitigación;
* efecto sobre el cierre.

No conviertas el contrato en una lista genérica de riesgos posibles.

Prioriza los que puedan:

* invalidar evidencia;
* ampliar alcance;
* producir pérdida;
* comprometer autoridad;
* impedir rollback;
* dejar resultados no reproducibles;
* hacer ambigua la aceptación.

## Validaciones y aceptación

Toda obligación relevante debe asociarse con una comprobación.

Las validaciones pueden incluir:

* inspección;
* test focal;
* regresión;
* validación de schema;
* análisis de diff;
* preflight;
* dry-run;
* comprobación de determinismo;
* comprobación de idempotencia;
* rollback check;
* revisión humana.

El contrato debe distinguir:

```text
validación
→ comprobación que debe ejecutarse

criterio de aceptación
→ resultado necesario para considerar cumplida una obligación
```

No declares aceptación cuando la validación correspondiente:

* no se ejecutó;
* falló;
* produjo evidencia ambigua;
* fue sustituida por una inferencia.

## Condiciones de detención

Declara cuándo debe detenerse el trabajo.

Como mínimo, detente cuando:

* falta una precondición;
* aparece evidencia contradictoria material;
* la acción requerida queda fuera de alcance;
* una superficie protegida debe modificarse;
* falla una validación bloqueante;
* una autorización deja de corresponder al estado actual;
* no puede garantizarse rollback cuando es obligatorio;
* el resultado amenaza una invariante.

Ante un cambio material, aplica la regresión definida en `SKILL.md`.

No redefinas aquí la lista completa de cambios materiales.

## Maduración durante la sesión

### Reconocimiento

Durante el reconocimiento no se formula todavía el contrato ejecutable.

Pueden identificarse:

* restricciones preliminares;
* superficies probables;
* operaciones que deben permanecer bloqueadas;
* evidencia faltante para contratar.

### Formulación

Durante la formulación:

* consume procedencia, diagnóstico e hipótesis;
* delimita objetivo y alcance;
* identifica superficies autorizadas y protegidas;
* declara invariantes;
* define riesgos y validaciones;
* establece detención y aceptación;
* fija el contrato vigente.

La implementación solo se habilita cuando el contrato es suficiente y el
veredicto correspondiente lo autoriza.

### Impacto

Durante la implementación, el contrato funciona como frontera.

Contrasta continuamente:

* acciones realizadas;
* archivos modificados;
* invariantes;
* validaciones;
* desviaciones;
* bloqueos;
* operaciones omitidas.

Un ajuste no material puede precisar el contrato sin ampliar la intervención.

Un cambio material obliga a detenerse y regresar al preimpacto.

### Postimpacto

Durante el cierre, contrasta el contrato con la evidencia real.

Registra:

* obligaciones cumplidas;
* obligaciones parcialmente cumplidas;
* obligaciones no cumplidas;
* desviaciones;
* validaciones ejecutadas;
* validaciones pendientes;
* criterios alcanzados;
* riesgos materializados;
* estado final.

Estados finales permitidos:

* `cumplido`;
* `cumplido_con_reservas`;
* `parcial`;
* `bloqueado`;
* `no_ejecutado`.

El contrato no se reemplaza por el `Balance de sesión`.

El balance evalúa el aprendizaje y el resultado global; el contrato registra
el cumplimiento de obligaciones autorizadas.

## Trazabilidad de ajustes

Cuando el contrato sea ajustado, conserva:

* formulación anterior;
* evidencia nueva;
* cambio realizado;
* razón;
* impacto sobre alcance;
* impacto sobre riesgos;
* impacto sobre validaciones;
* necesidad o no de nueva autorización.

No reescribas el contrato como si la formulación final hubiera sido siempre la
original.

## Relación con los entregables

```text
Procedencia de sesión
→ identifica la evidencia de origen

Diagnóstico de sesión
→ establece el estado observado

Hipótesis de sesión
→ define qué debe contrastarse

Contrato de sesión
→ delimita qué puede hacerse

Sesión
→ registra qué se hizo realmente

Balance de sesión
→ evalúa el resultado y el aprendizaje

Propuesta de sesión
→ deriva continuidad posible
```

El contrato no reemplaza los detalles de ejecución.

Los detalles no amplían el contrato.

La propuesta no modifica retroactivamente lo autorizado.

## Canonizabilidad

El `Contrato de sesión` debe ser canonizable.

Esto requiere:

* nombre canónico exacto;
* ruta y título gobernados;
* `.md.json` válido;
* identidad estable;
* alcance verificable;
* límites explícitos;
* validaciones y aceptación trazables;
* contraste final;
* compatibilidad con el productor autoritativo.

La canonizabilidad no equivale a admisión.

Para candidatas y S66, aplica
`canonical_session_family.instructions.md`.

## Prohibiciones

* No implementes sin contrato vigente.
* No formules el contrato antes de contar con evidencia suficiente.
* No autorices superficies no inspeccionadas.
* No uses alcance abierto o implícito.
* No conviertas hipótesis en obligaciones demostradas.
* No estabilices observaciones provisionales como hechos.
* No amplíes el contrato durante el impacto.
* No reutilices autorizaciones después de un cambio material.
* No ocultes incumplimientos o desviaciones.
* No uses el contrato como bitácora de ejecución.
* No crees variantes `inicial`, `final`, `v2` o equivalentes.
* No copies aquí el schema `.md.json`.
* No copies las compuertas completas de S66.
* No uses esta instrucción para gobernar commits o PR.

## Criterio de cumplimiento

El contrato es suficiente cuando:

* deriva de procedencia, diagnóstico e hipótesis vigentes;
* expresa un objetivo verificable;
* delimita incluido, excluido y protegido;
* identifica superficies autorizadas;
* declara invariantes y riesgos;
* asocia obligaciones con validaciones;
* define aceptación y detención;
* distingue autorización contractual y autorización humana;
* puede contrastarse contra evidencia real;
* conserva la trayectoria de sus ajustes;
* tiene estado final explícito;
* el entregable conserva identidad única;
* el `.md.json` es válido y canonizable.
