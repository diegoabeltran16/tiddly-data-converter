---
description: >
  Dueño normativo del contenido epistemológico de la procedencia: origen,
  actor, método, fuentes, autoridad, inferencias, participación de IA y
  limitaciones.
---

# Procedencia epistemológica

## Alcance

Esta instrucción gobierna:

- el origen de la evidencia;
- los actores que la producen o aportan;
- el método mediante el cual se obtiene;
- las fuentes y referencias utilizadas;
- la distinción entre observación e inferencia;
- la participación humana y de IA;
- las limitaciones de reconstrucción;
- el contenido del entregable `Procedencia de sesión`.

No gobierna:

- el recurso concreto;
- la interpretación diagnóstica;
- la formulación de hipótesis;
- la autorización contractual;
- rutas, títulos o identidad documental;
- schema `.md.json`;
- diagnósticos especializados;
- candidatas o admisión al canon.

Aplicar:

- `elementos_especificos.instructions.md` para recursos concretos;
- `diagnosticos_no_sesionales.instructions.md` para procedencia de diagnósticos
  especializados;
- `canonical_session_family.instructions.md` para nombre, título, ruta,
  identidad y canonizabilidad;
- `tiddlers_sesiones.instructions.md` para formato y validación `.md.json`.

## Rol semántico

- `rol_principal`: `procedimiento`.
- `rol_secundario`: `evidencia`.

La procedencia responde:

```text
¿De dónde proviene la evidencia y cómo llegó al trabajo?
````

No responde:

```text
¿Qué significa esa evidencia para el estado del sistema?
```

Esa interpretación pertenece al diagnóstico.

## Cuándo aplica

Registra procedencia cuando:

* una fuente, idea, decisión o recurso entra al trabajo;
* el origen no es evidente;
* una conclusión depende de evidencia verificable;
* participan humano, IA o fuentes externas;
* una sesión reconstruye continuidad previa;
* aparece evidencia nueva durante la implementación;
* una fuente cambia, contradice o limita el diagnóstico;
* el origen no puede verificarse completamente.

No documentes procedencia irrelevante para el objetivo local.

## Clasificación de fuentes

Cuando sea pertinente, distingue:

* `fuente_primaria`: evidencia directa del objeto estudiado;
* `fuente_auxiliar`: aporta contexto o apoyo;
* `fuente_derivada`: resultado calculado o transformado;
* `decision_humana`: instrucción, autorización o confirmación del operador;
* `inferencia_del_agente`: conclusión construida por razonamiento;
* `proyeccion_remota`: copia o representación externa no autoritativa;
* `fuente_no_verificada`: referencia conocida cuyo contenido no pudo comprobarse.

Estas categorías describen el contenido epistemológico. No introducen campos
nuevos en el schema `.md.json`.

## Obligaciones

Para cada fuente relevante, registra cuando corresponda:

* origen;
* actor;
* método de obtención;
* referencia o ruta;
* fecha o estado observado;
* autoridad;
* vigencia;
* propósito de consulta;
* modo de acceso;
* evidencia aportada;
* limitaciones;
* relación con la conclusión sustentada.

Toda conclusión importante debe poder vincularse con evidencia identificable.

No declares consultada una fuente que solo fue:

* mencionada;
* inferida;
* enlazada indirectamente;
* esperada;
* recordada sin verificación.

## Observación e inferencia

Distingue explícitamente:

```text
observación
→ contenido comprobado directamente

inferencia
→ interpretación construida desde observaciones

decisión
→ selección o autorización confirmada por el humano
```

No presentes una inferencia como observación.

No atribuyas a una fuente una conclusión producida por síntesis del agente.

Cuando una inferencia sea necesaria, declara:

* observaciones de partida;
* razonamiento resumido;
* nivel de certeza;
* limitaciones;
* evidencia que permitiría verificarla.

## Participación de IA

Cuando la IA participe de forma relevante, distingue:

* información recuperada por la IA;
* transformación o resumen realizado por la IA;
* inferencia propuesta por la IA;
* decisión confirmada por el humano;
* contenido no verificado independientemente.

No es necesario conservar transcripciones completas.

Registra solo la intervención necesaria para reconstruir la procedencia de una
decisión o conclusión relevante.

## Autoridad y vigencia

Evalúa las fuentes según:

* autoridad;
* currentness;
* completitud;
* proximidad al objeto observado;
* propósito de la superficie;
* reproducibilidad.

La ubicación o fecha de un archivo no demuestra por sí sola que sea vigente.

Por defecto:

* el canon local tiene autoridad sobre sus derivados;
* staging conserva memoria operativa, no autoridad canónica;
* auditorías y derivados aportan evidencia, no verdad final;
* remoto representa proyección o intercambio;
* una decisión humana explícita debe quedar distinguida de evidencia técnica.

Si dos fuentes se contradicen:

1. registra la contradicción;
2. identifica autoridad y vigencia;
3. declara qué conclusión permanece abierta;
4. evita selección silenciosa;
5. actualiza el diagnóstico cuando la contradicción cambie su interpretación.

La ausencia de staging no demuestra ausencia histórica.

```text
ausencia de staging
≠ ausencia de evidencia
```

## `Procedencia de sesión`

El entregable canónico se denomina exactamente:

```text
Procedencia de sesión
```

No uses sinónimos ni variantes para sustituir este nombre.

Debe conservar durante toda la sesión:

* una sola identidad;
* un solo archivo `.md.json`;
* su título y ruta canónicos;
* su `session_id`;
* su `canonical_slug`;
* su fecha `created`.

Las reglas exactas pertenecen a
`canonical_session_family.instructions.md`.

### Reconocimiento

Durante el reconocimiento, produce o actualiza la procedencia para:

* identificar el origen de la sesión;
* recuperar decisiones y sesiones previas pertinentes;
* declarar las fuentes del diagnóstico;
* distinguir evidencia directa e inferencia;
* registrar vacíos y fuentes pendientes;
* establecer qué evidencia sostiene el preimpacto.

La procedencia debe ser suficiente antes de formular hipótesis y contrato.

Suficiente no significa completa de forma definitiva. Significa capaz de
sostener las decisiones actuales con evidencia rastreable.

### Impacto

Actualiza el mismo entregable cuando:

* aparece una fuente no identificada;
* una prueba produce evidencia nueva;
* una observación contradice la reconstrucción inicial;
* se consulta un reporte, manifest, receipt, journal o auditoría adicional;
* interviene una decisión humana relevante;
* un microajuste depende de evidencia nueva.

Relaciona cada incorporación con el hallazgo o decisión que produjo.

### Postimpacto

Durante el cierre:

* consolida las fuentes realmente utilizadas;
* elimina afirmaciones falsas de consulta;
* distingue evidencia inicial y evidencia surgida durante el impacto;
* conserva inferencias y limitaciones abiertas;
* permite reconstruir el fundamento del diagnóstico, balance y propuesta.

No conviertas inferencias en observaciones durante la consolidación.

## Contenido mínimo

La `Procedencia de sesión` debe permitir identificar:

* origen de la sesión;
* continuidad previa relevante;
* fuentes consultadas;
* clasificación de cada fuente;
* método de obtención;
* autoridad y vigencia;
* observaciones sustentadas;
* inferencias del agente;
* decisiones humanas relevantes;
* participación de IA;
* contradicciones;
* fuentes no disponibles;
* limitaciones;
* evidencia nueva surgida durante el impacto;
* conjunto final de fuentes utilizadas.

Esta lista gobierna el contenido del campo `text`.

No modifica el schema `.md.json`.

## Relación con otros entregables

```text
Procedencia de sesión
→ identifica la evidencia

Diagnóstico de sesión
→ interpreta el estado observado

Hipótesis de sesión
→ formula expectativas contrastables

Contrato de sesión
→ delimita la intervención autorizada

Sesión
→ registra acciones y evidencia producida

Balance de sesión
→ evalúa los resultados

Propuesta de sesión
→ deriva continuidad posible
```

La procedencia no reemplaza ninguno de estos entregables.

## Canonizabilidad

La `Procedencia de sesión` debe ser canonizable.

Esto requiere:

* nombre canónico exacto;
* ruta y título gobernados;
* `.md.json` válido;
* identidad estable;
* contenido verificable;
* referencias suficientes;
* compatibilidad con el productor autoritativo.

La canonizabilidad no equivale a admisión.

Para candidatas y S66, aplica
`canonical_session_family.instructions.md`.

## Prohibiciones

* No confundas procedencia con recurso concreto.
* No confundas fuente con interpretación.
* No presentes inferencias como hechos observados.
* No ocultes contribuciones humano-IA relevantes.
* No declares consultada una fuente no verificada.
* No copies todo el historial del proyecto.
* No acumules referencias sin relación con el objetivo.
* No crees versiones `inicial`, `final`, `v2` o equivalentes.
* No reescribas silenciosamente errores de reconstrucción.
* No trates staging, derivados o remoto como canon.
* No copies aquí reglas completas de schema o S66.
* No mezcles gobernanza de diagnósticos no sesionales.

## Criterio de cumplimiento

La procedencia es suficiente cuando:

* cada conclusión importante tiene una fuente rastreable;
* puede distinguirse observación, inferencia y decisión;
* las fuentes tienen autoridad y vigencia declaradas;
* la participación humana y de IA es comprensible;
* las contradicciones y limitaciones permanecen visibles;
* el diagnóstico puede reconstruirse desde la evidencia citada;
* el entregable conserva identidad única;
* el `.md.json` es válido y canonizable;
* la revisión no depende de memoria informal.

````

### Cambio estructural

La instrucción queda como dueño exclusivo de:

```text
origen
+ actor
+ método
+ fuente
+ autoridad
+ observación
+ inferencia
+ participación humano-IA
+ limitaciones
````
