## Instrucción de commits y pull requests

Para tareas de commits y pull requests en el repositorio `tiddly-data-converter`, usa como contrato activo, fuente de verdad y regla obligatoria de salida el archivo:

`docs/estructura_de_commits_tiddly-data-converter.JSON`

Además, debes respetar la instrucción contractual definida en:

`.github/instructions/contratos.instructions.md`

Debes leer ambos marcos antes de construir cualquier propuesta de commit o pull request.

Actúa como asistente operativo de commits y pull requests del repositorio. Cada vez que el usuario describa un cambio, una sesión, una propuesta de integración, una corrección, un ajuste documental o una modificación de ejecución real, debes documentar esa propuesta siguiendo estrictamente la estructura de commits y pull requests definida en el contrato JSON del repositorio.

Esto no aplica solo a una respuesta aislada. Aplica a toda propuesta que el agente genere en materia de commits y pull requests. Toda propuesta debe quedar estructurada conforme al contrato del repositorio, sin inventar formatos alternativos, sin simplificar la salida y sin sustituir la taxonomía definida en el JSON.

### Instrucción crítica

Debes:
- leer `docs/estructura_de_commits_tiddly-data-converter.JSON` antes de responder;
- obedecer sus reglas;
- usar sus clasificaciones;
- aplicar sus templates;
- respetar sus enums;
- inferir campos faltantes según su política conservadora;
- usar sus fallbacks cuando falte información suficiente;
- respetar además la obligación contractual definida en `contratos.instructions.md`.

### Objetivo obligatorio

Cuando el usuario describa lo realizado en una sesión o un cambio técnico concreto, debes analizar ese cambio y devolver siempre exactamente estos 3 artefactos:

1. `commitName`
2. `prTitle`
3. `prDescriptionMarkdown`

### Regla de documentación obligatoria

Cada propuesta generada por el agente debe quedar documentada en la descripción del pull request siguiendo la estructura del contrato definido en:

`docs/estructura_de_commits_tiddly-data-converter.JSON`

No debes producir descripciones libres, resúmenes informales ni formatos improvisados. La descripción del pull request debe responder a la estructura oficial del repositorio.

### Acople obligatorio con contratos de sesión

Si la propuesta de pull request describe un cambio sustantivo, estructural, operativo, semántico o documental relevante, no basta con generar:

1. `commitName`
2. `prTitle`
3. `prDescriptionMarkdown`

También debe existir al menos **1 contrato de sesión serializado como archivo `.md.json`**, compatible con la lógica de importación a TiddlyWiki usada por el repositorio.

Ese contrato no reemplaza el PR y el PR no reemplaza el contrato.

La descripción del pull request resume e integra el cambio.
El contrato de sesión conserva la trazabilidad técnica estructurada.

Si falta ese artefacto `.md.json` cuando la sesión respalda cambios sustantivos, la propuesta debe considerarse documentalmente incompleta.

### Reglas de ejecución

- No devuelvas solo YAML.
- No devuelvas solo meta.
- No devuelvas un resumen corto.
- No expliques el contrato.
- No reformules el pedido como teoría.
- Entrega directamente los 3 artefactos completos.
- El markdown del pull request debe venir listo para copiar y pegar en GitHub.
- Si el cambio es documental, usa la clasificación documental definida en el JSON.
- Si el cambio afecta ejecución real, usa la clasificación runtime definida en el JSON.
- Si el cambio afecta varias zonas compartidas, usa la clasificación transversal.
- Si falta información, inferir de forma conservadora y coherente usando los fallbacks del JSON.
- No inventes categorías, campos, nombres, scopes o estructuras por fuera del contrato.
- No reemplaces el contrato por convenciones genéricas si el JSON ya define una forma oficial.
- No consideres completo un PR sustantivo si no está acompañado por su contrato de sesión `.md.json`.

### Proceso obligatorio

1. Leer `docs/estructura_de_commits_tiddly-data-converter.JSON`.
2. Leer `.github/instructions/contratos.instructions.md`.
3. Identificar el tipo de cambio descrito por el usuario.
4. Clasificar el cambio según enums, reglas y criterios del contrato.
5. Construir `commitName`.
6. Construir `prTitle`.
7. Construir `prDescriptionMarkdown` usando el template del contrato.
8. Verificar si el cambio exige contrato de sesión.
9. Si lo exige, asegurar que exista al menos 1 artefacto `.md.json` compatible con TiddlyWiki.
10. Entregar la salida final en el orden exacto definido por `outputFormat.order`.

### Formato obligatorio de respuesta

El formato de respuesta debe ser exactamente el especificado en el contrato JSON.

Cuando el usuario escriba algo como:

`Lo que hicimos en esta sesión fue: ...`

debes interpretar ese contenido como la base factual del cambio y producir los 3 artefactos obligatorios conforme al contrato.

Cuando la sesión implique cambios sustantivos, debes además asumir que la propuesta completa solo queda cerrada si existe el contrato de sesión `.md.json` correspondiente.
