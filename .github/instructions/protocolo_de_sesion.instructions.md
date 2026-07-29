# Protocolo de sesión

## Alcance

Gobierna la metodología conceptual de las sesiones TDC:

- apertura situada;
- secuencia de trabajo;
- separación entre decisión, intervención y evaluación;
- continuidad entre sesiones.

No gobierna:

- selección de la instrucción ejecutable;
- rutas o títulos de entregables;
- schema `.md.json`;
- admisión canónica;
- contenido especializado de cada artefacto.

Esas responsabilidades pertenecen a la skill y a sus dueños normativos.

## Modelo metodológico

Toda sesión se desarrolla mediante tres macrofases:

1. preimpacto;
2. impacto;
3. postimpacto.

El preimpacto contiene dos instrucciones ejecutables. Por tanto, la ejecución
asistida usa cuatro instrucciones en total.

La selección, transición y detención de esas instrucciones se gobierna en:

`.agents/skills/tdc-session/SKILL.md`

Las macrofases pertenecen a una sola sesión y conservan la misma identidad
documental.

## Apertura situada

Antes de actuar:

- identifica la sesión y su objetivo local;
- inspecciona el estado real;
- recupera solo la continuidad pertinente;
- declara el producto esperado;
- distingue evidencia, inferencia y decisión;
- comienza por el preimpacto.

No reconstruyas el contexto desde memoria informal cuando exista evidencia
verificable.

La apertura debe declarar, cuando corresponda:

- `local_frame`;
- `purpose`;
- `mode`;
- `expected_output`.

## Preimpacto

El preimpacto reúne las decisiones anteriores a la intervención.

### Reconocimiento

Debe:

- reconstruir la procedencia relevante;
- diagnosticar el estado actual;
- identificar superficies, riesgos y bloqueos;
- distinguir observación e inferencia;
- delimitar qué necesita verificarse.

Produce o actualiza procedencia y diagnóstico.

No implementa ni ejecuta operaciones mutantes.

### Formulación

Debe:

- formular hipótesis contrastables;
- delimitar objetivo y alcance;
- definir límites, invariantes y validaciones;
- establecer condiciones de detención y cierre;
- producir o actualizar hipótesis y contrato.

No habilita implementación con evidencia insuficiente.

## Impacto

El impacto ejecuta la intervención autorizada.

Debe:

- respetar el alcance contratado;
- modificar solo superficies autorizadas;
- ejecutar validaciones reales;
- registrar acciones, resultados y errores;
- contrastar hipótesis y contrato;
- producir evidencia reproducible;
- actualizar los detalles de sesión;
- aplicar microajustes no materiales cuando proceda.

Ante un cambio material, aplica la regresión definida en `SKILL.md`.

No amplíes el contrato silenciosamente.

## Postimpacto

El postimpacto evalúa y consolida la sesión.

Debe:

- fijar el estado final de las hipótesis;
- contrastar el contrato con el resultado;
- consolidar procedencia y diagnóstico cuando sea necesario;
- producir balance y propuesta;
- validar la coherencia documental;
- declarar limitaciones, riesgos y deuda residual.

No implementa cambios nuevos.

Un hallazgo técnico surgido durante el cierre se registra como bloqueo,
pendiente o continuidad futura.

## Modos de operación

Una sesión puede declarar:

- `teorico`: análisis, comprensión, formulación o interpretación;
- `desarrollo_pragmatico`: diseño, implementación, prueba o ajuste.

El modo no reemplaza las macrofases.

Toda sesión, independientemente del modo, mantiene la secuencia:

```text
preimpacto
→ impacto
→ postimpacto
````

## Continuidad

Usa los artefactos de sesión como memoria estructurada entre instrucciones.

* No reconstruyas toda la conversación.
* No repitas análisis sin evidencia nueva.
* Actualiza los mismos entregables.
* Conserva decisiones previas todavía vigentes.
* Declara contradicciones y refinamientos.
* No presentes una propuesta futura como estado ya alcanzado.

La continuidad temática se gobierna en
`desarrollo_y_evolucion.instructions.md`.

La recuperabilidad entre sesiones se gobierna en
`politica_de_memoria_activa.instructions.md`.

## Autoridad y límites

* El humano conserva la autoridad semántica final.
* La IA puede analizar, proponer, estructurar y validar.
* La conversación no equivale a autorización operativa.
* Git no equivale a admisión canónica.
* Una implementación terminada no equivale a cierre de sesión.
* Una propuesta no abre automáticamente otra sesión.

Para familia, identidad y admisión, aplica
`canonical_session_family.instructions.md`.

Para schema, aplica `tiddlers_sesiones.instructions.md`.

## No hacer

* No iniciar la sesión como si el proyecto partiera de cero.
* No cargar contexto por acumulación.
* No implementar durante el preimpacto.
* No cerrar durante el impacto.
* No implementar durante el postimpacto.
* No tratar macrofases como sesiones independientes.
* No avanzar automáticamente entre instrucciones.
* No ocultar cambios, errores o evidencia contradictoria.
* No duplicar reglas pertenecientes a otros dueños normativos.

## Criterio de cumplimiento

El protocolo se cumple cuando:

* la sesión conserva una identidad única;
* la secuencia metodológica es trazable;
* cada intervención deriva de evidencia previa suficiente;
* los resultados pueden contrastarse con hipótesis y contrato;
* los cambios y pendientes quedan explícitos;
* la continuidad no depende de conversación implícita;
* cada instrucción se detiene antes de la siguiente transición.

