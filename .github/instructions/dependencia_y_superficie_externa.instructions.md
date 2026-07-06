# 📦🧱 Dependencias y Superficie Externa

Núcleo técnico transversal del sistema. Gobierna dependencias, toolchains,
workflows, CI/CD, supply chain, servicios externos, accesos, seguridad,
reproducibilidad y toda superficie externa que afecte estabilidad, riesgo o
continuidad.

No funciona como inventario plano de paquetes ni como copia de lockfiles: opera
como capa normativa de decisión, trazabilidad y control.

## Propósito
- `rol_principal`: `concepto`.
- `roles_secundarios`: `proceso`.
- Gobernar dependencias, toolchains, workflows, acciones de CI/CD, servicios externos, accesos, red, supply chain, seguridad y reproducibilidad.
- Convertir dependencias y superficies externas en políticas documentadas explícitas de decisión, trazabilidad, riesgo y control.

## Cuándo aplica
- Cuando se propone incorporar, actualizar, fijar, sustituir o retirar una dependencia.
- Cuando un workflow, action, runtime, servicio externo o integración cambia la superficie del proyecto.
- Cuando una dependencia se vuelve crítica por arquitectura, seguridad, reproducibilidad o mantenimiento.
- Cuando hay que distinguir entre infraestructura viva, proyección remota y preparación futura.

## Obligaciones

**Registro y justificación:**
- Justificar cada dependencia o integración relevante.
- Registrar versión, origen, impacto, criticidad, razón de permanencia y estrategia de vigilancia cuando corresponda.
- Distinguir necesidad real, conveniencia local y deuda técnica futura.

**Diseño y gobernanza:**
- Favorecer soluciones reversibles, auditables y reproducibles.
- Separar la superficie externa activa de los artefactos derivados o de intercambio no autoritativo.
- Si una dependencia ya no tiene mantenimiento activo o tiene vulnerabilidades conocidas, documentar el riesgo en el registro crítico y proponer pasos de mitigación o sustitución antes de continuar usándola.

**Organización de nodos:**
- Usar `#### 🌀📦 Política de dependencias`, `#### 🌀📦 Registro de dependencias críticas`, `#### 🌀📦 Hipótesis de dependencias = m##` y `#### 🌀📦 Procedencia de dependencias = m##` cuando el asunto se vuelve transversal.
- Evitar proliferación prematura de nodos por paquete: comenzar por política, registro crítico y seguimiento por milestone.

## No hacer
- No introducir dependencias por moda o comodidad no justificada.
- No usar este nodo como SBOM manual, copia de lockfiles, manifest paralelo o volcado automático de paquetes.
- No mezclar decisiones de infraestructura con conclusiones temáticas sin frontera explícita.
- No ocultar costos de mantenimiento, riesgo, supply chain o superficie de ataque.
- No duplicar normas que pertenecen a `## 🗂🧱 Principios de Gestión`, `## 🧪🧱 Hipótesis`, `## 🧾🧱 Procedencia epistemológica` o `## 🧭🧱 Protocolo de Sesión`.

## Nota de cumplimiento S66
- Si una sesión toca dependencias o superficie externa, cerrar evidencia según `.github/instructions/canonical_session_family.instructions.md`.
- No promover cambios de dependencia al canon final por escritura directa del agente; usar líneas candidatas si deben poder absorberse.
- Registrar en el diagnóstico de sesión qué validaciones de entorno, seguridad o reproducibilidad pasaron y cuáles quedaron pendientes.

## Interacción con otros nodos
- Se articula con `## 🗂🧱 Principios de Gestión` para criterios de calidad, diseño y gobernanza técnica.
- Usa `## 🧪🧱 Hipótesis` cuando una dependencia, integración o superficie externa todavía requiere validación.
- Usa `## 🧾🧱 Procedencia epistemológica` para explicar de dónde surge una decisión relevante sobre dependencias.
- Usa `## 🧭🧱 Protocolo de Sesión` para registrar el trabajo situado que detecta, corrige o escala un problema de dependencias.
- Recibe hallazgos desde sesiones y los promueve aquí solo cuando dejan de ser puramente locales.

## Criterio de salida
- Debe poder explicarse por qué una dependencia o integración existe, qué aporta, qué riesgo introduce y cómo se gobierna.
- Debe quedar claro si el asunto sigue siendo local a una sesión o si ya pertenece a la capa transversal de dependencias.
- La superficie externa relevante debe permanecer visible, justificable y compatible con estabilidad, seguridad y reproducibilidad.

Las dependencias y superficies externas no deben tratarse como simple inventario
de cosas instaladas, sino como fronteras técnicas de confianza, decisión y
riesgo que merecen gobernanza explícita cuando afectan la estabilidad,
seguridad, reproducibilidad o evolución del proyecto.
