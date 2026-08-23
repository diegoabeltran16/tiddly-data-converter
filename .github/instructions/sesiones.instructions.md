---
description: >
  Dueño normativo de la unidad operativa de una sesión TDC, sus entregables,
  compuertas comunes, condiciones de intervención, validación y transferencia
  documental entre instrucciones.
---

# Ejecución operativa de sesiones

## Alcance

Esta instrucción gobierna las reglas operativas compartidas por todas las
instrucciones de una sesión TDC:

- unidad de trabajo;
- familia obligatoria de entregables;
- continuidad documental;
- compuerta común de entrada;
- atribución de cambios;
- condiciones generales de intervención;
- validación;
- transferencia entre instrucciones;
- salida común.

No gobierna:

- metodología conceptual de las macrofases;
- selección de la instrucción activa;
- transiciones, veredictos o detención;
- definición de cambio material;
- pasos particulares de cada instrucción;
- rutas y títulos canónicos;
- schema `.md.json`;
- compuertas detalladas de admisión.

Aplicar:

- `protocolo_de_sesion.instructions.md` para metodología;
- `.agents/skills/tdc-session/SKILL.md` para selección, transición, veredictos,
  cambio material y detención;
- la referencia activa de la skill para ejecución detallada;
- `canonical_session_family.instructions.md` para familia, rutas, títulos,
  identidad, candidatas y S66;
- `tiddlers_sesiones.instructions.md` para schema y validación `.md.json`.

## Unidad de trabajo

Una sesión corresponde a:

- una identidad de sesión;
- una rama, cuando aplique;
- una familia de siete entregables;
- una secuencia de instrucciones gobernada por la skill;
- un conjunto trazable de decisiones, acciones y resultados.

La skill ejecuta una sola instrucción por solicitud.

Todas las instrucciones pertenecen a la misma sesión y deben conservar su
identidad documental.

Una instrucción no constituye una sesión independiente.

## Familia obligatoria

Toda sesión ordinaria mantiene exactamente estos siete entregables:

1. `Contrato de sesión`;
2. `Procedencia de sesión`;
3. `Sesión`;
4. `Hipótesis de sesión`;
5. `Balance de sesión`;
6. `Propuesta de sesión`;
7. `Diagnóstico de sesión`.

`Sesión` es el nombre canónico del entregable operativo conocido
contextualmente como detalles de sesión.

Los siete entregables deben:

- pertenecer a la misma sesión;
- conservar identidad coherente;
- ocupar sus rutas oficiales;
- usar sus títulos canónicos;
- serializarse como objetos `.md.json`;
- cumplir el schema vigente;
- conservar contenido suficiente para la instrucción siguiente;
- ser canonizables.

Canonizable no significa candidato ni admitido.

Las definiciones exactas pertenecen a
`canonical_session_family.instructions.md` y
`tiddlers_sesiones.instructions.md`.

## Maduración operativa

Los entregables maduran progresivamente dentro de la misma familia.

| Instrucción | Producción principal |
|---|---|
| Reconocimiento | `Procedencia de sesión` y `Diagnóstico de sesión` |
| Formulación | `Hipótesis de sesión` y `Contrato de sesión` |
| Implementación | `Sesión`, implementación y validaciones |
| Cierre | `Balance de sesión`, `Propuesta de sesión` y consolidación familiar |

Una instrucción puede actualizar entregables producidos anteriormente cuando
aparezca evidencia nueva.

No debe crear una versión paralela.

La existencia física de un entregable no demuestra que su contenido esté
suficientemente maduro para habilitar la instrucción siguiente.

## Identidad documental

Durante toda la sesión:

- actualiza los mismos siete archivos;
- conserva `session_id`;
- conserva título y ruta;
- conserva `canonical_slug`;
- preserva `created`;
- actualiza `modified`;
- reconcilia el contenido existente;
- conserva la trayectoria de correcciones relevantes.

No crees variantes como:

```text
inicial
final
v2
revisado
corregido
nuevo
```

Una actualización no crea una nueva identidad.

Un cambio real de identidad requiere una nueva sesión o una migración
explícitamente autorizada.

## Compuerta común de entrada

Antes de ejecutar cualquier instrucción:

1. identifica la sesión activa;
2. confirma la rama, cuando aplique;
3. inspecciona el estado de Git;
4. identifica cambios preexistentes;
5. lee los entregables requeridos;
6. comprueba que pertenecen a la misma sesión;
7. confirma el último veredicto válido;
8. verifica las precondiciones de la instrucción activa.

No atribuyas a la sesión cambios preexistentes sin evidencia.

No sobrescribas modificaciones ajenas o no comprendidas.

No continúes cuando:

- falta un entregable requerido;
- existe una contradicción de identidad;
- el estado real difiere materialmente del estado autorizado;
- una precondición crítica no puede verificarse;
- el último veredicto no habilita la instrucción solicitada.

La skill determina el veredicto y la transición resultante.

## Reglas comunes de ejecución

Durante cualquier instrucción:

- limita el trabajo al objetivo activo;
- actualiza solo artefactos habilitados;
- registra evidencia verificable;
- distingue observación, inferencia, decisión y propuesta;
- conserva errores y resultados adversos;
- respeta superficies autorizadas y protegidas;
- evita cambios incidentales;
- no avances automáticamente a la instrucción siguiente.

Toda afirmación sobre una acción, prueba o validación debe corresponder a una
operación realmente ejecutada.

No presentes una intención, simulación o recomendación como resultado
observado.

## Operaciones mutantes

Las operaciones mutantes solo pueden ejecutarse durante la instrucción de
implementación y cuando:

- el contrato vigente las autoriza;
- las precondiciones continúan siendo válidas;
- las superficies afectadas están identificadas;
- existe evidencia suficiente;
- se ejecutaron los preflights aplicables;
- existe autorización humana cuando sea obligatoria;
- existe respaldo o rollback cuando corresponda.

No reutilices una autorización vinculada a un estado anterior.

Cuando aparezca un cambio material, aplica la regresión definida en
`.agents/skills/tdc-session/SKILL.md`.

No amplíes silenciosamente el contrato.

## Diagnósticos

El `Diagnóstico de sesión` es obligatorio para toda sesión ordinaria.

Debe reflejar el estado observado relevante para la sesión y actualizarse
cuando aparezca evidencia que cambie esa lectura.

Los diagnósticos especializados se producen únicamente cuando:

- el usuario los solicita;
- constituyen el objetivo explícito del trabajo;
- su alcance excede el diagnóstico ordinario.

Se gobiernan en `diagnosticos_no_sesionales.instructions.md`.

No sustituyen el `Diagnóstico de sesión`.

## Validación común

Después de modificar entregables:

- valida los `.md.json` afectados;
- verifica identidad;
- comprueba títulos y rutas;
- confirma ausencia de variantes paralelas;
- revisa el diff;
- ejecuta las validaciones técnicas del frente modificado;
- registra comandos, resultados y fallos.

Durante el cierre debe validarse la familia completa.

No declares válida una comprobación que:

- no fue ejecutada;
- falló;
- produjo un resultado ambiguo;
- fue sustituida por una inferencia.

La validación del schema no equivale a cierre ni admisión canónica.

## Transferencia entre instrucciones

Los artefactos de sesión son el medio estructurado de transferencia entre
instrucciones.

Cada instrucción debe dejar explícitos:

- estado recibido;
- evidencia consumida;
- decisiones tomadas;
- artefactos actualizados;
- validaciones ejecutadas;
- bloqueos;
- pendientes;
- estado dejado para continuidad.

La conversación puede aportar contexto, pero no debe ser la única fuente para
reconstruir el trabajo.

La instrucción siguiente debe consumir el estado documental vigente, no una
reconstrucción informal de la conversación.

## Salida común

Al terminar una instrucción:

- aplica la salida definida por `SKILL.md`;
- informa los paths consumidos;
- informa los paths actualizados;
- declara las validaciones ejecutadas;
- conserva bloqueos y resultados parciales;
- emite el veredicto correspondiente;
- indica la instrucción habilitada, cuando exista;
- detente.

No ejecutes la instrucción siguiente dentro de la misma solicitud.

## Prohibiciones

- No mezcles varias instrucciones en una sola ejecución.
- No implementes fuera de la instrucción autorizada.
- No omitas entregables obligatorios.
- No crees familias o archivos paralelos.
- No produzcas Markdown libre como sustituto del `.md.json`.
- No atribuyas cambios preexistentes a la sesión.
- No declares éxito sin evidencia.
- No uses Git como mecanismo de admisión canónica.
- No confundas validación, canonizabilidad, candidatura y admisión.
- No dupliques reglas completas de otros dueños normativos.

## Criterio de cumplimiento

La ejecución operativa es correcta cuando:

- mantiene una sola sesión;
- conserva exactamente siete entregables;
- preserva sus identidades;
- separa las instrucciones;
- atribuye correctamente los cambios;
- limita las mutaciones al alcance autorizado;
- registra evidencia y validaciones reales;
- transfiere estado mediante artefactos;
- no confunde staging con canon;
- no avanza sin veredicto;
- permite reconstruir el trabajo sin depender de memoria conversacional.
