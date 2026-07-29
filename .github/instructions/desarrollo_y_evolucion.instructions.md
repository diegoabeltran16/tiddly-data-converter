---
description: >
  Dueño normativo de la continuidad evolutiva de TDC: estados previos y
  actuales, transformaciones consolidadas, deuda, bloqueos y condiciones de
  continuidad entre sesiones.
---

# Desarrollo y evolución

## Alcance

Esta instrucción gobierna:

- la continuidad del tema o componente entre sesiones;
- la relación entre estados previos y actuales;
- la clasificación de transformaciones;
- la distinción entre actividad y cambio consolidado;
- la conservación de correcciones, contradicciones y deuda;
- las condiciones que habilitan continuidad futura.

No gobierna:

- la ejecución de una sesión;
- la bitácora de implementación;
- el estado epistemológico de hipótesis;
- la procedencia de las decisiones;
- la propuesta de siguiente sesión;
- rutas, títulos o schema de entregables;
- candidatas o admisión canónica.

Aplicar:

- `protocolo_de_sesion.instructions.md` para metodología;
- `sesiones.instructions.md` para ejecución operativa;
- `hipotesis.instructions.md` para formulaciones tentativas;
- `procedencia_epistemologica.instructions.md` para origen;
- `elementos_especificos.instructions.md` para recursos concretos;
- `detalles_del_tema.instructions.md` para contenido sustantivo;
- `canonical_session_family.instructions.md` para canonizabilidad y S66.

## Rol semántico

- `rol_principal`: `proceso`.
- `rol_secundario`: `contexto`.

Desarrollo y evolución responde:

```text
¿Cuál era el estado anterior,
qué cambió realmente,
qué estado queda vigente
y qué continuidad está habilitada?
````

No responde:

```text
¿Qué se hizo paso a paso durante la sesión?
```

Eso pertenece al entregable `Sesión`.

Tampoco responde:

```text
¿Qué debería hacerse después?
```

Eso pertenece a `Propuesta de sesión`.

## Cuándo aplica

Registra continuidad evolutiva cuando:

* una sesión modifica un estado previamente vigente;
* una decisión reemplaza, corrige o refina otra;
* una capacidad nueva queda consolidada;
* una hipótesis se promueve a una capa más estable;
* una línea de trabajo queda descartada;
* una intervención no logra consolidarse;
* aparece deuda o un bloqueo que condiciona trabajo posterior;
* una propuesta futura depende de precondiciones heredadas.

No registres como evolución toda actividad ejecutada.

## Unidad evolutiva

Toda actualización evolutiva debe relacionar, cuando corresponda:

```text
estado anterior
→ evidencia del cambio
→ tipo de transformación
→ estado resultante
→ deuda o continuidad
```

Debe quedar claro:

* qué permaneció;
* qué cambió;
* por qué cambió;
* con qué evidencia;
* qué autoridad sostuvo la decisión;
* qué permanece abierto.

No reescribas el estado actual como si no existiera historia previa.

## Estados de una transformación

Usa estas categorías cuando ayuden a describir la relación entre estados:

| Estado              | Significado                                          |
| ------------------- | ---------------------------------------------------- |
| `avance`            | Incorpora capacidad, estructura o conocimiento nuevo |
| `corrección`        | Repara un estado incorrecto                          |
| `refinamiento`      | Mejora precisión sin sustituir el núcleo válido      |
| `promoción`         | Eleva contenido validado a una capa más estable      |
| `descarte`          | Retira una línea que perdió soporte                  |
| `bloqueo`           | Impide consolidar por falta de condiciones           |
| `sin_consolidación` | Hubo actividad, pero no cambio durable               |

Estas categorías:

* describen la transformación;
* no sustituyen el veredicto de sesión;
* no sustituyen el estado de hipótesis;
* no introducen campos nuevos en el schema.

## Cambio consolidado

Un cambio puede considerarse consolidado cuando:

* fue ejecutado o formalizado;
* cuenta con evidencia verificable;
* respeta el contrato vigente;
* superó las validaciones aplicables;
* no depende de una condición abierta no declarada;
* el diagnóstico final reconoce el nuevo estado;
* el balance no identifica una contradicción bloqueante.

Una implementación no se consolida solo porque:

* existe en el working tree;
* pasó un test aislado;
* fue incluida en un commit;
* fue descrita en conversación;
* aparece en una propuesta;
* produjo una candidata.

Cuando el cambio depende de admisión canónica, la consolidación debe distinguir:

```text
implementado
≠ canonizable
≠ candidato
≠ admitido
```

## Estado anterior

Conserva el estado anterior cuando sea necesario para entender:

* una corrección;
* una incompatibilidad;
* un cambio de política;
* una migración;
* una hipótesis contradicha;
* una regresión;
* una deuda heredada;
* una decisión reemplazada.

No es necesario copiar todo el historial.

Registra solo la continuidad con incidencia sobre el estado vigente.

## Evidencia evolutiva

Toda transformación debe apoyarse en evidencia como:

* diagnóstico inicial y final;
* contrato contrastado;
* detalles de implementación;
* tests;
* validaciones;
* decisiones humanas;
* diff técnico o semántico;
* reportes;
* manifests;
* receipts;
* resultados de admisión, cuando apliquen.

Distingue:

```text
actividad
→ acción realizada

resultado
→ efecto observado

transformación
→ cambio durable reconocido
```

No uses actividad como prueba automática de transformación.

## Relación con las sesiones

### Antes de intervenir

La continuidad debe permitir reconocer:

* estado vigente;
* decisiones estabilizadas;
* hipótesis abiertas;
* deuda heredada;
* restricciones;
* cambios que no deben reabrirse sin evidencia;
* precondiciones todavía pendientes.

La sesión consulta esta continuidad, pero no la modifica por anticipado.

### Durante la intervención

Los posibles cambios se registran en los entregables de sesión.

Todavía pueden resultar:

* confirmados;
* corregidos;
* revertidos;
* parciales;
* bloqueados;
* sin consolidación.

No declares evolución estable durante la ejecución sin evidencia suficiente.

### Después de intervenir

El cierre determina qué transformación queda reconocida.

Usa como base:

* `Diagnóstico de sesión`;
* `Contrato de sesión`;
* `Sesión`;
* `Balance de sesión`.

La `Propuesta de sesión` puede señalar continuidad futura, pero no demuestra
que esa continuidad ya esté habilitada.

## Trayectoria de correcciones

Cuando una decisión o implementación sea corregida, conserva:

* estado anterior;
* problema detectado;
* evidencia;
* corrección aplicada;
* estado resultante;
* efectos residuales.

No presentes la corrección como si hubiera sido la intención original.

No ocultes:

* errores;
* contradicciones;
* regresiones;
* decisiones descartadas;
* validaciones fallidas;
* rollback ejecutado.

La trayectoria debe permitir aprender del cambio, no solo mostrar el estado
final.

## Promoción

Una promoción ocurre cuando contenido provisional pasa a una capa más estable.

Puede aplicar a:

* una hipótesis;
* una definición;
* una política;
* una relación;
* una decisión arquitectónica;
* una convención.

Toda promoción debe declarar:

* contenido de origen;
* estado previo;
* evidencia acumulada;
* criterio de promoción;
* nueva capa;
* límites de validez;
* decisión humana cuando corresponda.

Una hipótesis confirmada no se promueve automáticamente.

La admisión canónica y la promoción semántica son decisiones diferentes.

## Deuda y bloqueos

Registra deuda cuando existe trabajo pendiente que:

* afecta mantenibilidad;
* limita una capacidad;
* reduce verificabilidad;
* deja una transición incompleta;
* compromete reproducibilidad;
* condiciona una sesión posterior.

Cada deuda relevante debe permitir identificar:

* origen;
* impacto;
* superficie afectada;
* condición de resolución;
* prioridad contextual;
* relación con continuidad futura.

Un bloqueo debe declarar:

* condición faltante;
* evidencia;
* efecto;
* trabajo impedido;
* criterio de desbloqueo.

No presentes continuidad habilitada mientras sus precondiciones permanezcan
abiertas.

## Continuidad futura

Una continuidad futura está habilitada cuando:

* deriva del estado real;
* sus precondiciones están satisfechas;
* no contradice decisiones vigentes;
* los riesgos heredados están declarados;
* existe evidencia suficiente para formular una nueva sesión.

Puede estar:

* `habilitada`;
* `condicionada`;
* `bloqueada`;
* `descartada`.

La `Propuesta de sesión` debe reflejar esta condición, no inventarla.

## Relación con los entregables

```text
Procedencia de sesión
→ explica de dónde surge el estado reconstruido

Diagnóstico de sesión
→ identifica el estado observado

Hipótesis de sesión
→ conserva formulaciones tentativas

Contrato de sesión
→ delimita la intervención autorizada

Sesión
→ registra acciones y resultados

Balance de sesión
→ evalúa aprendizaje y cumplimiento

Propuesta de sesión
→ formula continuidad futura

Desarrollo y evolución
→ conserva la transformación consolidada entre estados
```

No copies los siete entregables dentro de esta capa.

Conserva únicamente la síntesis evolutiva necesaria.

## Recursos y contenido temático

Cuando lo que cambia es un recurso concreto, aplica
`elementos_especificos.instructions.md`.

Cuando lo que cambia es el contenido sustantivo del tema, aplica
`detalles_del_tema.instructions.md`.

Cuando lo que cambia es una definición o convención, aplica
`glosario_y_convenciones.instructions.md`.

Esta instrucción conserva la relación temporal entre estados, no reemplaza sus
dueños semánticos.

## Evolución y canon

Una transformación puede ser:

* reconocida localmente;
* canonizable;
* candidata;
* admitida al canon.

Estos estados no son equivalentes.

Para familia, candidatas y admisión, aplica
`canonical_session_family.instructions.md`.

Un cambio de hash o conteo no constituye por sí mismo evolución válida ni
deriva anómala. Debe interpretarse mediante evidencia, autoridad y el proceso
que lo produjo.

## Prohibiciones

* No uses esta instrucción como bitácora de sesión.
* No copies todos los comandos o archivos modificados.
* No declares consolidación por actividad.
* No presentes una propuesta como estado vigente.
* No promociones hipótesis automáticamente.
* No borres estados previos relevantes.
* No ocultes correcciones o contradicciones.
* No reescribas retrospectivamente la intención original.
* No mezcles deuda abierta con estado consolidado.
* No dupliques principios transversales.
* No copies reglas completas de schema o S66.
* No confundas admisión canónica con evolución semántica.

## Criterio de cumplimiento

La continuidad evolutiva es suficiente cuando:

* el estado anterior es identificable;
* el cambio está respaldado por evidencia;
* la transformación está clasificada;
* actividad y consolidación están separadas;
* el estado vigente queda explícito;
* correcciones y contradicciones conservan trayectoria;
* deuda y bloqueos permanecen visibles;
* la continuidad futura declara sus precondiciones;
* puede reconstruirse la evolución sin depender de memoria circunstancial.

