# 🧾🧱 Procedencia epistemológica
**`## 🧾🧱 Procedencia epistemológica`** funciona como el **núcleo madre** que orienta la declaración de procedencia dentro del sistema. No conserva el recurso concreto ni desarrolla el contenido del tema: mantiene explícito de dónde surge una idea, un nodo, una interpretación o un material incorporado al trabajo.

## Propósito
- `rol_principal`: `procedimiento`.
- Hacer visible la genealogía del conocimiento trabajado.
- Distinguir entre producción humana, asistencia de IA, fuente externa y combinaciones mixtas.
- Registrar origen, método y referencia suficiente para revisión, validación y explotación posterior.

## Cuándo aplica
- Cuando el origen de un contenido no es obvio o no debe quedar implícito.
- Cuando una idea, decisión, nodo o recurso entra al sistema.
- Cuando hubo intervención humana, de IA, externa o combinada.
- Cuando una sesión necesita dejar trazable de dónde surgió una formulación relevante.

## Obligaciones
- Declarar, cuando corresponda, origen, actor, método y referencia rastreable.
- Distinguir entre observación, inferencia, generación, compilación, estimación y otras mediaciones relevantes.
- Separar con claridad el recurso concreto de la explicación sobre su entrada al sistema.
- Registrar de forma suficiente el papel de la IA cuando participe, sin inflar el nodo con transcripciones innecesarias.
- Usar `# 2_🧾 Procedencia inicial` y `#### 🌀🧾 Procedencia de sesión ##` cuando la procedencia pertenezca a esas escalas.
- Mantener trazabilidad suficiente para que una decisión importante no dependa de memoria tácita.

## No hacer
- No confundir procedencia con contenido temático.
- No usar este nodo como contenedor del recurso concreto.
- No presentar como observación directa lo que en realidad es inferencia o síntesis.
- No ocultar contribuciones mixtas humano-IA cuando afectan el contenido.

## Regla transversal S66
- Toda sesión debe producir procedencia de sesión en `data/out/local/sessions/01_procedencia/<session>.md.json`.
- El `title` de procedencia de sesión debe usar `#### 🌀🧾 Procedencia de sesión <NN> = <slug>`, por ejemplo `#### 🌀🧾 Procedencia de sesión 69 = canon-admission-hardening-and-docs-v0`.
- Las líneas candidatas deben declarar procedencia suficiente y apuntar al archivo fuente bajo `data/out/local/sessions/`.
- No admitir al canon líneas cuya procedencia, sesión de origen o familia de artefacto no sean verificables localmente.

## Gobernanza de procedencia diagnóstica

Cuando una sesión produce diagnósticos por ciclos, la procedencia debe separar
fuente primaria, fuente auxiliar e inferencia del agente.

Jerarquía operativa:

1. **Diagnósticos previos específicos**: un mesociclo consume primero
   microdiagnósticos ya producidos y válidos.
2. **Sessions local**: `data/out/local/sessions/` conserva staging y memoria
   reciente cuando existe.
3. **Canon local**: `data/out/local/tiddlers_*.jsonl` sostiene memoria durable
   cuando `sessions/` fue depurado.
4. **Auditorías y derivados**: `data/out/local/audit/`, `enriched/` y `ai/`
   se consultan solo para hipótesis concretas.
5. **Repositorio**: código, tests, workflows e instrucciones validan el estado
   arquitectónico actual.
6. **Espejo remoto**: OneDrive o superficies remotas son paridad operativa, no
   autoridad superior al canon local por defecto.

Todo diagnóstico de ciclo debe declarar:

- completitud en staging local;
- completitud canónica;
- fuente usada para cada conclusión importante;
- si hubo consulta remota, si fue dry-run, estática o real.

Si `sessions/` está ausente o depurado, no se debe concluir pérdida histórica
sin revisar canon local. La ausencia de staging y la ausencia de evidencia
histórica son estados distintos.

## Interacción con otros nodos
- Requiere `## 🎯🧱 Detalles del tema` para situar la procedencia dentro del marco del tema.
- Se articula con `## 🧰🧱 Elementos específicos` cuando existe un recurso concreto que también debe preservarse.
- Se articula con `## 🌀🧱 Desarrollo y Evolución` porque la genealogía del conocimiento se despliega en el tiempo.
- Se articula con `## 🧭🧱 Protocolo de Sesión` cuando la procedencia local aparece durante una sesión concreta.
- Puede acompañar a `## 🧪🧱 Hipótesis`, pero no la reemplaza.

## Criterio de salida
- Debe quedar claro de dónde surge el contenido, cómo fue obtenido y qué referencia permite rastrearlo.
- Debe poder distinguirse recurso, contenido, hipótesis y procedencia como capas distintas.
- Un agente debe poder reconstruir origen suficiente sin recurrir a memoria informal.

La procedencia no reemplaza el contenido, pero evita que su origen se vuelva opaco.
