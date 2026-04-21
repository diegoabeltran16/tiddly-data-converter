# 🧭🧱 Protocolo de Sesión
`## 🧭🧱 Protocolo de Sesión` funciona como el **núcleo madre** que orienta la apertura, conducción y registro de las sesiones dentro del sistema. No desarrolla el tema por sí mismo: ofrece una forma estable de trabajo para que cada sesión produzca conocimiento situado sin quedar desconectada de la arquitectura ya declarada.

## Propósito
- `rol_principal`: `procedimiento`.
- Abrir sesiones con marco local, propósito, modo activo y producción esperable.
- Convertir conversación y trabajo situado en artefactos integrables al sistema.
- Mantener trazabilidad suficiente para revisión, continuidad y canonización posterior.

## Cuándo aplica
- Al abrir, conducir y cerrar cualquier sesión.
- Cuando una sesión va a crear o modificar hipótesis, procedencias, elementos específicos, definiciones, contratos, parches o líneas canónicas.
- Cuando la sesión se desarrolla con asistencia de IA.
- Antes de actuar, para decidir qué lectura mínima y qué expansión contextual son realmente necesarias.

## Obligaciones
- Abrir la sesión como trabajo situado, no como conversación difusa.
- Declarar al menos `local_frame`, `purpose`, `mode` y `expected_output`.
- Revisar, antes de actuar, las hipótesis abiertas relevantes, las definiciones estabilizadas pertinentes, los elementos específicos recientes, las tensiones no resueltas y las decisiones previas que afectan el objetivo local.
- Registrar durante la sesión qué se produjo, qué se confirmó, qué se contradijo, qué se refinó y qué quedó pendiente.
- Cerrar la sesión de forma que lo trabajado pueda pasar al convertidor sin perder contexto humano.
- Mantener la autoridad semántica en el humano: la IA sugiere, estructura y facilita, pero no decide por sí sola las relaciones o estados finales.

### Modos de operación
- `teórico`: comprensión, análisis, lectura, distinción conceptual, formulación e interpretación.
- `desarrollo_pragmatico`: construcción, diseño operativo, decisión estructural, implementación, prueba y ajuste.

### Organización mínima de una sesión
- `session_title`: título corto y legible.
- `session_id` o `session_tag`: identificador humano-canónico de la sesión.
- `session_date`: fecha y hora de apertura.
- `local_frame`: ámbito temático trabajado.
- `purpose`: propósito local.
- `mode`: `teorico` | `desarrollo_pragmatico`.
- `expected_output`: tipo de producto esperado.
- `produced_nodes`: lista de nodos producidos o modificados.
- `notes_summary`: resumen breve de decisiones y pendientes.

### Preferencias de memoria declarables desde la sesión
- `memory_policy`.
- `memory_ttl`.
- `memory_tags`.

Estas preferencias son opcionales y su significado está gobernado por `## 🧠🧱 Política de Memoria Activa`.

### Plantilla recomendada para tiddler de sesión
```yaml
title: "🌀 Sesión — Título breve"
tags: ["session:2026-04-01-s07", "session", "topic:mi-tema"]
session_id: "session:2026-04-01-s07"
session_date: "2026-04-01T10:00:00Z"
local_frame: "Ámbito específico sobre X"
purpose: "Reformular hipótesis Y y decidir next-steps"
mode: "desarrollo_pragmatico"
expected_output: ["tiddler:hipotesis", "tiddler:procedimiento"]
produced_nodes: []
notes_summary: "Puntos clave y decisiones tomadas"
memory_policy: "active"
memory_ttl: "P30D"
memory_tags: ["project-x", "hypothesis"]
---
# Notas de la sesión

- Registro de acciones, decisiones y resultados.
- Para cada tiddler creado, añadir tag `session:2026-04-01-s07` y, si procede, `provisional_id: <slug>`.
```

### Contrato operativo de sesión asistida por IA
Toda sesión asistida debe declarar objetivo local, salida estructural esperada, lectura mínima de apertura y política de expansión contextual. La lectura mínima debe comenzar por `# 1_tiddly-data-converter`, `## 🧭🧱 Protocolo de Sesión` y `## 🧠🧱 Política de Memoria Activa`, y expandirse solo hacia los bloques que el objetivo local necesite realmente.

La sesión asistida se considera cumplida cuando produce el artefacto estructural esperado para su nivel de trabajo: líneas JSONL si recae sobre canon, JSON o patch estructurado si recae sobre un nodo o modificación localizada, o forma estructural equivalente si recae sobre reglas, contratos o transformaciones del convertidor.

## No hacer
- No iniciar una sesión como si el tema partiera de cero.
- No usar memoria libre o reconstrucción informal cuando hay contexto rastreable disponible.
- No expandir la lectura de forma indiscriminada.
- No cerrar una sesión sin dejar claro qué produjo y qué quedó pendiente.
- No confundir protocolo de sesión con política de memoria, contenido temático o motor de canonización.

## Interacción con otros nodos
- Requiere `## 🎯🧱 Detalles del tema` para situar la sesión dentro del marco del tema.
- Requiere `## 🌀🧱 Desarrollo y Evolución` para que la sesión quede integrada a la historia del proceso.
- Usa `## 🧪🧱 Hipótesis`, `## 🧾🧱 Procedencia epistemológica`, `## 🧰🧱 Elementos específicos` y `## 📚🧱 Glosario y Convenciones` según la naturaleza de lo producido.
- Se articula con `## 🧠🧱 Política de Memoria Activa`, que define cómo se interpretan las preferencias de memoria declaradas en sesión.
- Orienta nodos como `#### 🌀 Sesión ##`, `#### 🌀🧪 Hipótesis de sesión ##`, `#### 🌀🧾 Procedencia de sesión ##`, `#### 📚 Diccionario 🌀` y `#### referencias específicas 🌀`, pero no los reemplaza.
- `tiddly-data-converter` formaliza, valida y reporta; el protocolo solo gobierna cómo la sesión entra, trabaja y sale del sistema.

## Criterio de salida
- Debe quedar trazable qué se leyó, qué se trabajó, qué se produjo y qué quedó abierto.
- Debe quedar explícito el artefacto estructural esperado y si efectivamente se obtuvo.
- Un agente debe poder continuar la sesión o auditarla sin depender de conversación implícita ni de reconstrucción informal.

El protocolo de sesión no sustituye la evolución del tema, pero hace posible que esa evolución pueda registrarse con orden y continuidad.
