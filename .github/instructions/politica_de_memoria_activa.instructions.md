---
description: >
  Dueño normativo de la memoria activa en TDC: recuperabilidad, open loops,
  relevancia, recencia, TTL, preferencias humanas, señales computadas y
  acciones operativas de memoria.
---

# Política de memoria activa

## Alcance

Esta instrucción gobierna:

- memoria activa y recuperabilidad entre sesiones;
- `open_loop`;
- `relevance`;
- `recency`;
- preferencias de memoria;
- TTL;
- señales computadas;
- estados y acciones operativas de memoria;
- selección situada del contexto que vuelve a entrar en foco.

No gobierna:

- apertura o conducción de sesiones;
- contenido de hipótesis, procedencia, glosario o evolución;
- algoritmos concretos de scoring;
- ejecución automática de políticas de retención;
- schema general del canon;
- candidatas o admisión canónica.

Aplicar:

- `protocolo_de_sesion.instructions.md` para apertura situada;
- `desarrollo_y_evolucion.instructions.md` para continuidad histórica;
- `canonical_session_family.instructions.md` para candidatas y S66.

## Rol semántico

- `rol_principal`: `procedimiento`.

La memoria activa responde:

```text
¿Qué contenido debe permanecer recuperable,
por qué puede volver a ser relevante
y bajo qué condiciones debe reactivarse?
```

Recuperable no significa cargado permanentemente.

```text
memoria disponible
≠ memoria relevante
≠ memoria seleccionada
≠ contexto cargado
```

## Principios de selección

La recuperación debe ser situada: reentra el contexto que ayuda al objetivo
local, no todo el historial disponible.

Cuando existan señales en conflicto, aplica esta precedencia:

1. preferencia humana explícita;
2. relevancia para el objetivo local;
3. bucles abiertos y dependencias pendientes;
4. vigencia;
5. recencia;
6. frecuencia de referencia;
7. recuperabilidad general.

La preferencia humana tiene prioridad operativa, pero no convierte contenido
obsoleto o incorrecto en evidencia vigente.

## Conceptos canónicos

### `open_loop`

Asunto que conserva una condición concreta de seguimiento.

Puede originarse en:

- hipótesis abierta;
- contradicción pendiente;
- validación incompleta;
- bloqueo;
- riesgo no resuelto;
- deuda con incidencia conocida;
- autorización pendiente;
- propuesta condicionada.

No toda idea futura constituye un `open_loop`.

Debe existir una condición cuya resolución pueda cambiar una decisión
posterior.

### `relevance`

Incidencia del contenido sobre el objetivo local.

Es contextual y puede cambiar entre sesiones.

### `recency`

Proximidad temporal de creación, modificación, validación o uso.

Es una señal secundaria: contenido reciente puede ser irrelevante y contenido
antiguo puede seguir siendo crítico.

### Recuperabilidad

Capacidad de encontrar nuevamente un contenido con identidad, procedencia y
contexto suficientes para evaluarlo.

### TTL

Horizonte temporal para revisar utilidad o vigencia.

El vencimiento de un TTL no implica borrado automático. Activa revisión,
degradación o archivado según la política aplicable.

## Campos canónicos

Preferencias humanas declarables:

- `meta.memory_policy`: `active` | `ephemeral` | `archive`;
- `meta.memory_ttl`: duración ISO 8601 opcional;
- `meta.memory_tags`: lista de strings.

Señales computadas:

- `memory.last_used`: fecha ISO 8601;
- `memory.times_referenced`: contador;
- `memory.relevance_score`: valor normalizado;
- `memory.related_sessions`: lista de `session_id`;
- `memory.status`: `active` | `dormant` | `archived`.

Acción derivada y revisable:

- `memory_action`: `keep` | `demote` | `archive` | `delete` | `review`.

Las preferencias humanas, señales computadas y acciones operativas son capas
distintas.

```text
preferencia declarada
→ señal computada
→ decisión operativa revisable
```

## Semántica de políticas

### `active`

Mantener disponible para reactivación cuando sea relevante.

No implica cargarlo en toda sesión.

### `ephemeral`

Mantener temporalmente y revisar al vencer su TTL o condición de utilidad.

No implica eliminación automática.

### `archive`

Conservar para historia o auditoría, fuera de la recuperación ordinaria salvo
necesidad explícita.

## Responsabilidades

### Humano

Puede declarar:

- `memory_policy`;
- `memory_ttl`;
- `memory_tags`;
- prioridades;
- exclusiones;
- autorización para acciones irreversibles.

### TDC

Puede:

- preservar campos;
- computar métricas;
- relacionar sesiones;
- reportar señales.

No debe aplicar por sí mismo políticas irreversibles de retención.

### Gestor de memoria

Puede:

- seleccionar contexto;
- aplicar TTL;
- degradar prioridad;
- archivar;
- solicitar revisión;
- proponer acciones.

Debe conservar trazabilidad y autoridad humana.

## Reactivación entre sesiones

Antes de una sesión asistida, prioriza:

- hipótesis abiertas;
- contradicciones pendientes;
- definiciones recientemente estabilizadas;
- bloqueos;
- deuda con incidencia;
- resultados relevantes para el objetivo;
- recursos o dependencias directamente afectados;
- preferencias humanas explícitas.

Cada contenido reactivado debe poder explicar:

- por qué reentra;
- qué objetivo afecta;
- qué autoridad conserva;
- cuál es su vigencia;
- qué decisión puede modificar.

Las referencias específicas solo deben reactivarse cuando el objetivo local lo
requiera.

## Actualización después de una sesión

Una sesión puede cambiar la memoria futura cuando:

- abre o cierra un `open_loop`;
- confirma, refina o contradice una hipótesis;
- estabiliza una definición;
- introduce deuda;
- resuelve un bloqueo;
- cambia vigencia o autoridad;
- crea una dependencia futura;
- deja continuidad condicionada.

No toda salida de sesión debe permanecer activa.

## Acciones irreversibles

`memory_action: delete` nunca debe ejecutarse automáticamente.

Requiere:

- decisión humana explícita;
- revisión de referencias y consumidores;
- comprobación de autoridad;
- preservación de evidencia necesaria;
- trazabilidad de la acción.

## Relación con el canon

```text
recuperabilidad
≠ relevancia
≠ vigencia
≠ autoridad
≠ admisión canónica
```

Un contenido puede ser recuperable sin estar admitido, o estar admitido y no
ser relevante para la sesión actual.

Para candidatas y admisión aplica
`canonical_session_family.instructions.md`.

## Prohibiciones

- No reinyectes contexto por acumulación.
- No confundas recencia con relevancia.
- No confundas relevancia con verdad.
- No confundas recuperabilidad con admisión.
- No uses frecuencia como única señal.
- No borres contenido al vencer un TTL.
- No ejecutes `delete` automáticamente.
- No conviertas propuestas vagas en `open_loop`.
- No copies aquí algoritmos de scoring.
- No uses esta política como sustituto de hipótesis, procedencia, glosario o
  evolución.

## Criterio de cumplimiento

La política se cumple cuando:

- puede explicarse por qué un contenido permanece recuperable;
- el contexto seleccionado responde al objetivo local;
- `open_loop`, relevancia, recencia y recuperabilidad permanecen separados;
- los TTL activan revisión y no borrado automático;
- se distingue preferencia humana, señal computada y acción operativa;
- toda acción irreversible requiere autorización;
- la continuidad puede recuperarse sin cargar todo el historial.
````
