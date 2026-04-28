## Instrucción de contratos de sesión

Para toda propuesta técnica, cambio estructural, ajuste de implementación, corrección relevante, bootstrap, validación operativa, triage, decisión semántica o refinamiento documental generado en el repositorio `tiddly-data-converter`, debes producir y dejar explícito un **contrato de sesión** versionable bajo `data/sessions/00_contratos/`, coherente con la familia de artefactos ya existente en el sistema. Esta versión refuerza que el cierre mínimo debe incluir al menos un `.md.json` importable, no solo markdown libre.

Actúa como asistente contractual de desarrollo para `tiddly-data-converter`.

No operes como conversación libre cuando el objetivo ya esté claro. Opera como sesión dirigida por objetivo, con lectura situada, expansión contextual guiada, inferencia conservadora y cierre en artefactos estructurados compatibles con la arquitectura, el vocabulario y el Canon. Los contratos históricos compartidos muestran familias documentales distintas, pero todos conservan estructura técnica trazable y serialización compatible con TiddlyWiki.

### Fuente estructural obligatoria

Debes tomar como referencia estructural los contratos y reportes de sesión ya existentes en el sistema, especialmente los artefactos equivalentes a:
- contratos operativos de componente;
- registros operativos de validación;
- reportes estructurados de ejecución;
- reportes de política o decisión técnica.

Tu tarea no es inventar una plantilla nueva en cada sesión, sino producir un contrato nuevo compatible con esas familias ya estabilizadas en el repositorio. Los ejemplos previos incluyen contratos operativos como `m01-s01-extractor-contract` e `m01-s05-ingesta-contract`, registros operativos como `m01-s06-ingesta-go-env-wsl`, y reportes de política o ejecución como `m01-s08-ingesta-data-triage` y `m01-s09-ingesta-timestamp-policy`.

### Regla principal

Cada vez que el agente proponga cambios sustantivos en un pull request, debe existir **1 contrato de sesión** en `data/sessions/00_contratos/` que documente esa propuesta o ese cambio de forma estructurada.

Ese contrato de sesión debe:
- corresponder al objetivo real de la sesión;
- usar la familia documental correcta;
- quedar redactado con vocabulario técnico compatible con el sistema;
- ser trazable respecto del milestone, sesión, componente y alcance;
- dejar explícitos el alcance, los límites, lo realizado, lo no realizado, los riesgos y los pendientes cuando aplique.

### Qué se entiende por contrato de sesión

Un contrato de sesión es el artefacto estructurado que deja constancia técnica de una sesión de trabajo o de una propuesta concreta de cambio.

No todos los contratos de sesión tienen exactamente los mismos encabezados, pero sí deben respetar la lógica estructural ya consolidada en el repositorio.

### Tipos válidos de contrato de sesión

Cuando redactes el contrato, debes seleccionar explícitamente la familia correcta según la naturaleza del cambio.

#### 1. Contrato operativo
Úsalo cuando la sesión define o refina un componente, una frontera, una responsabilidad, una entrada/salida, un contrato técnico o una compuerta del sistema.

Debe incluir, cuando aplique:
- nombre del componente;
- rol dentro del sistema;
- objetivo;
- entradas;
- salidas;
- responsabilidades;
- límites;
- invariantes;
- fallos bloqueantes o decisiones de error;
- criterios de aceptación;
- pendientes o decisiones abiertas;
- scaffold o proyección mínima, si corresponde.

#### 2. Registro o reporte operativo
Úsalo cuando la sesión documenta validaciones de entorno, bootstrap técnico, ejecución real, pruebas operativas, acciones realizadas o evidencia reproducible.

Debe incluir, cuando aplique:
- nombre del registro o reporte;
- objetivo real de la sesión;
- contexto y restricciones;
- acciones ejecutadas;
- resultados observados;
- evidencia mínima o salidas verificables;
- artefactos creados o modificados;
- qué quedó explícitamente fuera;
- pendientes, próximos pasos o cierre operativo.

#### 3. Reporte de política o decisión técnica
Úsalo cuando la sesión cierra una política local, una decisión semántica, una regla de transformación, un criterio de clasificación o una apertura observacional.

Debe incluir, cuando aplique:
- decisión elegida;
- justificación técnica;
- evidencia mínima usada;
- razón de coherencia con la arquitectura y el carácter del componente;
- cambios aplicados o propuestos;
- límites explícitos;
- riesgos de implementar más de la cuenta;
- siguiente paso sugerido o criterio de cierre.

### Regla de selección

No fuerces un contrato operativo si la sesión fue realmente un registro operativo.
No fuerces un reporte de ejecución si la sesión cerró una política.
No mezcles arbitrariamente familias documentales distintas si el objetivo local no lo exige.

Selecciona el tipo documental que mejor corresponda al objetivo real de la sesión.

### Contrato activo de sesión

Cuando el usuario declare tiddlers contractuales activos de sesión, debes tratarlos como marco rector de lectura, inferencia y cierre.

Antes de producir el contrato de sesión, debes respetar:
- el objetivo local;
- el nivel de trabajo declarado;
- la lectura mínima obligatoria;
- la política de memoria activa;
- la arquitectura, vocabulario y Canon;
- la inferencia conservadora;
- la atomicidad del cambio;
- los quality gates mínimos.

### Obligación de lectura situada

Antes de redactar el contrato de sesión:
- lee primero los bloques contractuales mínimos ya definidos por el usuario para esa sesión;
- expándete solo hacia los bloques estructurales necesarios;
- no leas indiscriminadamente todo el sistema;
- no traigas contexto por acumulación;
- recupera solo lo que tenga incidencia directa sobre el objetivo local.

### Regla de trazabilidad

El contrato de sesión debe dejar trazable, de forma explícita:
- el nombre de la sesión;
- el milestone;
- la fecha;
- el estado;
- el componente o frente afectado;
- el alcance real;
- la frontera de responsabilidades;
- lo que sí cambió;
- lo que no cambió;
- lo que queda pendiente;
- la razón técnica de las decisiones tomadas.

### Regla de conservadurismo estructural

No inventes secciones porque sí.
No impongas headings nuevos sin necesidad fuerte.
No sustituyas la estructura del repositorio por una plantilla genérica.
No estabilices hipótesis como hechos.
No promociones una observación local a verdad del sistema sin base contractual suficiente.

Si falta información crítica, deja explícita la provisionalidad.

### Requisito no negociable de serialización para TiddlyWiki

El cierre mínimo de toda sesión que respalde cambios sustantivos de un pull request debe incluir **al menos 1 archivo `.md.json`** listo para importar en TiddlyWiki bajo `data/sessions/00_contratos/`.

No basta con entregar solo markdown plano, solo análisis conversacional o solo una propuesta de contrato en texto libre.

El archivo `.md.json` debe seguir la misma lógica estructural observable en los contratos versionados del repositorio:
- wrapper JSON importable;
- un objeto tiddler principal;
- un campo `text` que contenga el contrato completo en markdown estructurado;
- metadata mínima coherente con la línea documental activa del sistema.

### Regla adicional de staging canonico

Cuando una sesión cree o actualice su contrato `.md.json`, ese artefacto debe quedar en `data/sessions/00_contratos/`.

Si el contrato debe poder ingresar al canon, el agente debe producir una línea candidata en formato canon bajo `data/sessions/`. Esa línea debe apuntar al archivo fuente mediante `source_path` o campo equivalente no reservado, declarar la sesión de origen, declarar la familia `contrato_de_sesion` y conservar estado de candidato hasta que un proceso local la valide y la absorba.

El agente no debe escribir directamente el contrato en `data/out/local/tiddlers_*.jsonl` por defecto. La absorción canónica ocurre solo tras validación local, `strict`, `reverse-preflight`, reverse autoritativo con `Rejected: 0` y tests pertinentes.

Los contratos reales compartidos ya muestran la lógica de wrapper JSON con metadata de tiddler y contenido contractual dentro de `text`, lo que permite importarlos directamente a TiddlyWiki. S66 agrega que ese wrapper vive bajo `data/sessions/` y que su representación canónica comienza como candidata, no como autoridad final.

### Forma mínima obligatoria del `.md.json`

Cuando se produzca un contrato nuevo, debe serializarse como artefacto importable con una forma mínima equivalente a esta:

```json
[
  {
    "created": "YYYYMMDDHHmmssSSS",
    "text": "# ... contrato de sesión en markdown ...",
    "type": "text/markdown",
    "title": "mXX-sNN-<slug>.md",
    "modified": "YYYYMMDDHHmmssSSS",
    "tags": "[[#### referencias especificas 🌀]] [[## 🧰🧱 Elementos específicos]] [[#### 🌀 Sesión NN = <slug>]]",
    "tmap.id": "<uuid>"
  }
]
```

### Familia minima asociada al contrato

El contrato no cierra por si solo una sesion sustantiva. Debe existir tambien:

- procedencia de sesion en `data/sessions/01_procedencia/`;
- detalles de sesion en `data/sessions/02_detalles_de_sesion/`;
- hipotesis de sesion en `data/sessions/03_hipotesis/`;
- balance de sesion en `data/sessions/04_balance_de_sesion/`;
- propuesta de sesion en `data/sessions/05_propuesta_de_sesion/`;
- diagnostico de sesion en `data/sessions/06_diagnoses/sesion/`.

No crear archivo acumulativo global de contratos ni de sesiones.
