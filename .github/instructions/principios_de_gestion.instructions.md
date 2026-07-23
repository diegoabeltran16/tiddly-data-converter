# 🗂🧱 Principios de Gestión
`## 🗂🧱 Principios de Gestión` funciona como el **núcleo madre** que articula la capa normativa transversal del sistema. No desarrolla contenido temático ni registra producción situada: mantiene disponibles los criterios estables con los que debe conducirse el trabajo a lo largo del tiempo.

## Propósito
- `rol_principal`: `procedimiento`.
- `rol_secundario`: `definición`.
- Reunir principios reutilizables de calidad, diseño, trazabilidad y gobernanza.
- Sostener una capa normativa transversal que no dependa de cada sesión.
- Resolver desde aquí los conflictos normativos que afectan varios bloques o varias sesiones.

## Cuándo aplica
- Cuando una regla afecta más de un bloque temático o más de una sesión.
- Cuando una decisión de diseño, trazabilidad, modularidad, robustez o relaciones necesita criterio estable.
- Cuando una norma local parece entrar en conflicto con otra capa del sistema.
- Cuando hace falta distinguir principios duraderos de tácticas circunstanciales.

## Obligaciones

**Registro normativo:**
- Registrar aquí las reglas estables y transversales.
- Distinguir principios duraderos de tácticas locales o pasajeras.
- Dejar explícito cuando una regla afecta varios bloques o varias sesiones.

**Resolución de conflictos:**
- Usar este nodo para resolver conflictos normativos entre capas.
- Remitir al principio específico correspondiente cuando ya exista un nodo dedicado.
- Si ningún principio existente resuelve el conflicto, declarar explícitamente la ausencia de norma, registrar la decisión provisional tomada y crear una nota en este nodo para que una sesión futura pueda estabilizarla como principio.

**Cohesión:**
- Mantener visible la familia normativa reutilizable del sistema sin duplicar innecesariamente su contenido.

## Principio de evolución canónica gobernada

El canon de TDC es evolutivo por diseño. A medida que el proyecto desarrolla
funciones, tests, contratos, documentación y sesiones, el canon debe
acompañar esa evolución como representación estructurada, trazable y
computacionalmente recuperable de su estado.

Su estabilidad no consiste en conservar inmutablemente el conteo o el hash,
sino en cambiar mediante mecanismos gobernados, trazables, validables y
reversibles. La creación de artefactos puede incorporar registros nuevos y la
modificación de artefactos ya representados puede actualizar registros sin
aumentar el conteo; ambos casos pueden cambiar el hash global.

Por tanto, un cambio de conteo o de hash no constituye por sí mismo una
anomalía. El crecimiento canónico aumenta el número de registros; la evolución
canónica cambia contenido, estructura, procedencia o hash, con o sin
crecimiento.

Todo consumidor ligado a una versión concreta del canon —por ejemplo,
candidatas relacionales, manifests, bindings o reportes de currentness— debe
reconciliarse, regenerarse o revalidarse contra el canon vigente antes de una
escritura gobernada. Un cambio legítimo mantiene esa obligación: evolución
canónica gobernada no equivale a reutilización automática de dependencias.

Solo un cambio sin mecanismo autorizado, procedencia suficiente o coherencia
con el flujo operativo esperado se clasifica como deriva canónica no
explicada y justifica una investigación específica.

## No hacer
- No convertir este nodo en bitácora de sesión.
- No llenarlo de detalles tácticos o pasajeros.
- No introducir principios incompatibles con la arquitectura sin una nota escrita en este mismo nodo que justifique la incompatibilidad y declare su carácter provisional o experimental.
- No usarlo como sustituto de `## 🎯🧱 Detalles del tema`, `## 🧭🧱 Protocolo de Sesión` o `## 🌀🧱 Desarrollo y Evolución`.

## Nota de cumplimiento S66
- La regla completa de cierre, autoridad de canon y admisión local vive en `.github/instructions/canonical_session_family.instructions.md`.
- Este archivo conserva el principio transversal: cuando haya conflicto normativo, aplicar dueño único de regla y evitar definiciones duplicadas.

## Interacción con otros nodos
- Requiere `## 🎯🧱 Detalles del tema` para aplicar principios sobre un marco temático real.
- Usa `## 🌀🧱 Desarrollo y Evolución` para evaluar cambios y continuidad con criterios estables.
- Incide especialmente sobre `### 🎯 5. Arquitectura 🌀`, `### 🎯 6. Componentes 🌀`, `### 🎯 7. Algoritmos y matemáticas 🌀` y `### 🎯 8. Ingeniería asistida por IA 🌀`.
- Articula la familia formada por `## 🗂🧱 Arquitectura (del desarrollo)`, `## 🗂🧱 Buen gusto`, `## 🗂🧱 Calidad de referencias`, `## 🗂🧱 Complejidad Esencial vs Accidental`, `## 🗂🧱 Diseño`, `## 🗂🧱 Epigenética Computacional`, `## 🗂🧱 Estilo Mosston y Ashworth`, `## 🗂🧱 Estructura de trazabilidad`, `## 🗂🧱 Evolución Semántica`, `## 🗂🧱 Modularidad y Estado`, `## 🗂🧱 Reglas de relaciones` y `## 🗂🧱 Usabilidad y Robustez`.
- No reemplaza a esos principios específicos: los coordina.

## Criterio de salida
- Debe quedar claro qué principios transversales gobiernan la decisión en curso.
- Debe poder distinguirse qué regla es estable y cuál es solo táctica local.
- Un agente debe poder remitirse desde aquí al principio correcto sin duplicar ni improvisar normativa.

Este nodo no produce resultados temáticos por sí mismo, pero sí hace posible que dichos resultados se desarrollen dentro de un marco coherente, reutilizable y defendible.
