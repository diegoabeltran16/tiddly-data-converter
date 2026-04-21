## 🧠🧱 Política de Memoria Activa

Este núcleo define qué significa memoria activa en el sistema, qué debe mantenerse recuperable entre sesiones y qué semántica gobierna los campos canónicos de memoria. No abre ni conduce sesiones: gobierna la continuidad contextual entre ellas.

## Propósito
- `rol_principal`: `procedimiento`.
- Definir la semántica de memoria activa, `open_loop`, `relevance`, `recency` y recuperabilidad.
- Establecer qué señales permiten que un nodo vuelva a entrar en contexto entre sesiones.
- Separar preferencias humanas, cómputo técnico y decisión operativa sobre memoria.

## Cuándo aplica
- Cuando una sesión declara `memory_policy`, `memory_ttl` o `memory_tags`.
- Cuando el convertidor o un gestor de memoria computan señales de reactivación, prioridad o decaimiento.
- Cuando hay que decidir qué contexto reaparece entre sesiones.
- Cuando confirmaciones, contradicciones o refinamientos alteran la relevancia futura de un nodo.

## Obligaciones
- Mantener la diferencia entre `open_loop`, `relevance`, `recency`, prioridad contextual y recuperabilidad.
- Exigir recuperación situada: reentra lo que ayuda al objetivo local, no todo el historial disponible.
- Tratar `memory_policy`, `memory_ttl` y `memory_tags` como preferencias declarables, no como decisión final automática.
- Hacer trazable cualquier cambio de estado o acción de memoria.
- Mantener visibles los campos canónicos y su semántica.

### Campos canónicos y recomendaciones
- `meta.memory_policy`: `active` | `ephemeral` | `archive`.
- `meta.memory_ttl`: duración ISO8601 opcional.
- `meta.memory_tags`: lista de strings para indexación y búsqueda.
- `memory.last_used`: fecha ISO8601 computada.
- `memory.times_referenced`: contador computado.
- `memory.relevance_score`: puntaje normalizado computado.
- `memory.related_sessions`: lista de `session_id` computada.
- `memory.status`: `active` | `dormant` | `archived`.
- `memory_action`: `keep` | `demote` | `archive` | `delete` | `review` como señal derivada y revisable.

### Responsabilidades técnicas
- Humano: declarar, si hace falta, `memory_policy`, `memory_ttl` y `memory_tags` como preferencias.
- `tiddly-data-converter`: computar y reportar métricas básicas de memoria sin aplicar por sí mismo políticas de retención.
- Gestor de memoria: aplicar TTLs, promover, degradar, archivar y solicitar revisión humana cuando corresponda.

### Ejemplo canónico mínimo
```json
"meta": {
	"memory_policy": "active",
	"memory_ttl": "P30D",
	"memory_tags": ["project-x", "hypothesis"]
},
"memory": {
	"last_used": "2026-04-01T10:12:00Z",
	"times_referenced": 3,
	"relevance_score": 0.78,
	"related_sessions": ["session:2026-04-01-s07"],
	"status": "active"
}
```

## No hacer
- No reinyectar contexto por inercia o acumulación indiscriminada.
- No confundir política semántica con algoritmo de scoring o con motor de retención.
- No aplicar acciones irreversibles sin trazabilidad y revisión suficiente.
- No usar esta política como sustituto del registro explícito en hipótesis, procedencia, glosario o desarrollo.

## Interacción con otros nodos
- `## 🧭🧱 Protocolo de Sesión` permite declarar preferencias de memoria y define la apertura informada de cada sesión.
- `## 🧠🧱 Política de Memoria Activa` define qué significan esas preferencias y cómo se interpretan.
- `## 🧪🧱 Hipótesis`, `## 📚🧱 Glosario y Convenciones`, `## 🌀🧱 Desarrollo y Evolución`, `## 🧾🧱 Procedencia epistemológica` y `## 🧰🧱 Elementos específicos` aportan el contenido que puede volver a entrar en foco.
- El convertidor registra, computa y reporta señales; el gestor de memoria decide y aplica.

### Interfaz entre memoria activa y sesiones asistidas por IA
Antes de una sesión asistida, la memoria activa debe orientar la selección de lo que reaparece, no inflar el contexto de forma indiscriminada. Debe priorizar hipótesis abiertas, definiciones recientemente estabilizadas, contradicciones pendientes, refinamientos recientes, nodos frecuentemente referenciados y resultados de alta incidencia sobre el objetivo local declarado.

Los resultados de una sesión asistida deben alimentar la recuperabilidad futura cuando abren bucles de seguimiento, cambian la prioridad contextual de un nodo, estabilizan definiciones antes abiertas, introducen señales de contradicción o confirmación, o generan dependencias con incidencia conocida sobre el trabajo posterior. Las referencias específicas solo deben reactivarse cuando el objetivo local de la sesión siguiente lo requiera de forma explícita.

## Criterio de salida
- Debe quedar claro por qué un nodo permanece recuperable entre sesiones y qué señales justifican esa decisión.
- Debe poder distinguirse entre preferencia declarada, señal computada y acción operativa.
- Un agente debe saber qué contexto reentra, por qué reentra y bajo qué revisión humana sigue siendo modificable.

Fin de `## 🧠🧱 Política de Memoria Activa`.

