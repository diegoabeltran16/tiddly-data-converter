## 🧠🧱 Política de Memoria Activa

Propósito: definir qué significa "memoria activa" en este sistema, qué criterios determinan que un nodo deba mantenerse accesible entre sesiones, y qué campos y procesos deben usarse para que el convertidor y el gestor de memoria puedan operar con trazabilidad y control humano.

Alcance
- Aquí viven las reglas de retención, priorización y decaimiento de contenido. No regula la apertura ni conducción de sesiones (eso lo hace `## 🧭🧱 Protocolo de Sesión`).
- Esta política contiene definiciones, valores permitidos y los campos canónicos que el convertidor podrá leer/escribir como metadatos.
- Este núcleo gobierna la semántica de los campos de memoria; los documentos de sesión pueden declarar preferencias, pero no definen el significado operativo de los estados, señales o acciones de memoria.
- Este núcleo define la semántica y las reglas interpretativas de memoria, pero no constituye por sí mismo un motor de decisión ni una política ejecutada directamente sobre el Canon.

Definiciones clave
- `open_loop`: un asunto o pendiente que requiere seguimiento futuro.
- `relevance`: evaluación contextual de cuánto ayuda un nodo a trabajar el `local_frame` actual.
- `recency`: cuánto tiempo ha pasado desde la última referencia o modificación.
- `confirmación`, `contradicción` y `refinamiento`: señales interpretativas que pueden afectar la revisión de memoria, aunque su detección operativa y su cómputo pertenecen a las capas técnicas.

Campos canónicos y recomendaciones (representación canónica en el Canon)
- `meta.memory_policy`: `active` | `ephemeral` | `archive` — preferencia declarada por el autor/humano.
- `meta.memory_ttl`: ISO8601 duration (opcional) — preferencia de tiempo de retención sugerida.
- `meta.memory_tags`: lista de strings — etiquetas para indexación y búsqueda en subsistemas de memoria.
- `memory.last_used`: ISO8601 — última fecha en que el nodo fue referenciado/consultado (computado).
- `memory.times_referenced`: integer — contador de referencias (computado).
- `memory.relevance_score`: number (0..1) — puntaje normalizado calculado por el convertidor/servicio de memoria.
- `memory.related_sessions`: lista de `session_id` — sesiones que produjeron o usaron el nodo (computado).
- `memory.status`: `active` | `dormant` | `archived` — estado práctico aplicado por el gestor de memoria.
- `memory_action`: `keep` | `demote` | `archive` | `delete` | `review` — señal computada para informes del convertidor o del gestor de memoria. No es un campo declarativo de sesión; si en el futuro se preserva dentro del Canon, deberá quedar marcado como valor derivado y revisable.

Principios operativos
- Preferencia humana vs. decisión operativa: la sesión puede declarar `meta.memory_policy` como preferencia; la decisión operativa final la toma el gestor de memoria tras evaluar métricas computadas y políticas organizativas.
- Trazabilidad: toda acción de cambio de estado debe registrar `changed_by` y `changed_at` en `meta`/`memory` o en el informe del gestor.
- Transparencia: el convertidor debe emitir en su informe pre/post los valores `memory.*` calculados y la `memory_action` sugerida; el gestor aplicará (o solicitará revisión humana) antes de aplicar cambios irreversibles.

Frontera de responsabilidades
- `## 🧭🧱 Protocolo de Sesión` permite declarar preferencias de memoria en contexto de trabajo situado.
- `## 🧠🧱 Política de Memoria Activa` define qué significan esas preferencias y bajo qué reglas se interpretan.
- `tiddly-data-converter` registra, computa y reporta las señales canónicas de memoria sin aplicar por sí mismo políticas de retención.

Responsabilidades técnicas
- Humano (autor de sesión): indicar, opcionalmente, `memory_policy`, `memory_ttl` y `memory_tags` como preferencias al crear/editar nodos.
- Convertidor (`tiddly-data-converter`): debe computar y anexar (en el informe) métricas básicas (`memory.last_used`, `memory.times_referenced`, `memory.relevance_score`, `related_sessions`) y detectar contradicciones/confirmaciones relevantes; no debe aplicar políticas de retención por sí mismo.
- Gestor de memoria (servicio/función separada): aplica TTLs, promueve/archiva nodos, programa recordatorios y expone interfaces para revisión humana.

Ejemplo (snippet de metadatos en un nodo canónico)
```json
"meta": {
	"memory_policy": "active",
	"memory_ttl": "P30D",
	"memory_tags": ["project-x","hypothesis"]
},
"memory": {
	"last_used": "2026-04-01T10:12:00Z",
	"times_referenced": 3,
	"relevance_score": 0.78,
	"related_sessions": ["session:2026-04-01-s07"],
	"status": "active"
}
```

Notas de implementación y recomendaciones
- El algoritmo de `relevance_score` queda fuera de este documento. Cualquier detalle de cálculo, fórmula o heurística debe documentarse en el repositorio del convertidor, no aquí.
- Mantener un mecanismo humano de revisión (`memory_action: review`) antes de borrar o archivar definitivamente contenidos con `memory.times_referenced` bajos.
- Documentar en el repositorio del convertidor qué campos computará y en qué formato aparecerán en el informe (para que posteriores integraciones del gestor de memoria sean deterministas).

Relación con el `## 🧭🧱 Protocolo de Sesión`
- El protocolo de sesión especifica qué debe declarar el autor en la sesión. La `Política de Memoria Activa` especifica cómo esas preferencias se interpretan y aplican.

## Interfaz entre memoria activa y sesiones asistidas por IA

Antes de una sesión asistida, la memoria activa debe orientar la selección de lo que reaparece, no inflar el contexto de forma indiscriminada. En términos operativos, esto significa priorizar las hipótesis aún abiertas, las definiciones recientemente estabilizadas, las contradicciones pendientes de resolución, los refinamientos recientes de afirmaciones previas, los nodos frecuentemente referenciados y los resultados de alta incidencia sobre el objetivo local declarado. Esta selección no es una recuperación exhaustiva: es una orientación dirigida que permite a la sesión comenzar con el contexto necesario sin incorporar materiales cuya relevancia contextual no ha sido verificada.

Los resultados de una sesión asistida deben alimentar la recuperabilidad futura cuando la sesión abre bucles de seguimiento, cambia la prioridad contextual de un nodo, estabiliza definiciones que antes permanecían abiertas, introduce señales de contradicción o confirmación sobre afirmaciones previas, o genera dependencias con incidencia conocida sobre el trabajo posterior. Las referencias específicas, en cambio, solo deben reactivarse cuando el objetivo local de la siguiente sesión lo requiera de forma explícita. La memoria activa no es un registro de todo lo ocurrido, sino la capa normativa que asegura que lo relevante permanezca recuperable entre sesiones sin convertirse en ruido contextual.
Fin de `## 🧠🧱 Política de Memoria Activa`.

