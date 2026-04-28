# 📚🧱 Glosario y Convenciones
`## 📚🧱 Glosario y Convenciones` funciona como el **núcleo madre** encargado de estabilizar el lenguaje del tema. No desarrolla por sí mismo el contenido temático: conserva términos, definiciones, alias y convenciones para que el sistema mantenga coherencia semántica a lo largo del tiempo.

## Propósito
- `rol_principal`: `concepto`.
- `rol_secundario`: `procedimiento`.
- Estabilizar vocabulario, alias, signos, abreviaturas y formas preferidas de nombrar.
- Reducir ambigüedad entre lenguaje humano, arquitectura del sistema y formalización posterior.
- Mantener visibles las convenciones de uso que afectan lectura, escritura y clasificación.

## Cuándo aplica
- Antes de introducir un término nuevo o ambiguo.
- Cuando un mismo término empieza a usarse con más de un sentido.
- Cuando una convención de nombre, tag, rol, estado o símbolo afecta varios nodos o varias sesiones.
- Cuando hace falta distinguir forma humana, forma canónica y uso contextual de un mismo término.

## Obligaciones
- Definir los términos antes de usarlos extensivamente.
- Mantener consistencia entre nombre humano, forma canónica y uso contextual.
- Declarar diferencias entre términos cercanos que puedan confundirse.
- Registrar alias, equivalencias y formas preferidas.
- Consultar este nodo antes de introducir vocabulario nuevo que afecte capas, roles, tags, estados o funciones.
- Conservar aquí convenciones de escritura, nombrado y lectura cuando tengan valor estable y transversal.

## No hacer
- No redefinir términos ad hoc por sesión.
- No usar el mismo término con dos sentidos sin marcar la diferencia.
- No confundir capas, roles, tags, estados y funciones.
- No usar este nodo como lugar para tomar decisiones técnicas que pertenecen a `## 🗂🧱 Principios de Gestión` o a un bloque temático específico.

## Regla transversal S66
- Usar `data/sessions/` para nombrar artefactos de cierre de sesión: contrato, procedencia, detalles, hipótesis, balance, propuesta y diagnóstico.
- Nombrar todo tiddler resultado de sesión con `title` iniciado por `#### 🌀`; las formas preferidas son `#### 🌀🧾 Procedencia de sesión ## = <session>`, `#### 🌀 Sesión ## = <session>` y `#### 🌀🧪 Hipótesis de sesión ## = <session>`.
- Distinguir siempre `línea candidata`, `canon local` y `derivado`; `data/sessions/` no es canon paralelo.
- No crear nombres alternos para carpetas de sesión si ya existe una ruta real en el repositorio.

## Interacción con otros nodos
- Requiere `## 🎯🧱 Detalles del tema` para situar el vocabulario dentro del contenido sustantivo.
- Requiere `## 🗂🧱 Principios de Gestión` cuando una convención también tiene implicaciones operativas.
- Usa `## 🌀🧱 Desarrollo y Evolución` para conservar cambios o estabilizaciones terminológicas a lo largo del tiempo.
- Usa `## 🗂🧱 Reglas de relaciones` cuando la convención afecta la forma en que los nodos se vinculan.
- Da soporte a `## 🧭🧱 Protocolo de Sesión`, `## 🧪🧱 Hipótesis` y `## 🧾🧱 Procedencia epistemológica`, pero no los reemplaza.

## Criterio de salida
- Debe quedar claro qué término es preferido, qué alias existen y qué diferencias semánticas importan.
- Debe poder reconocerse cuándo una palabra nombra un concepto, una convención o una categoría operativa.
- Un agente debe poder leer el sistema sin introducir ambigüedad terminológica evitable.

El glosario no agota el contenido conceptual del tema, pero sí ayuda a que ese contenido pueda leerse y desarrollarse con mayor precisión, continuidad y consistencia.
