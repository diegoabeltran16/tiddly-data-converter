---
description: >
  Dueño normativo del contenido epistemológico de las hipótesis: formulación,
  alcance, evidencia inicial, método de contraste, trayectoria y estatuto.
---

# Hipótesis

## Alcance

Esta instrucción gobierna:

- qué cuenta como hipótesis;
- cómo debe formularse;
- qué evidencia la origina;
- cómo debe contrastarse;
- qué resultados pueden confirmarla, refinarla o contradecirla;
- cómo se conserva su trayectoria;
- el contenido del entregable `Hipótesis de sesión`.

No gobierna:

- la interpretación factual del diagnóstico;
- la procedencia de la evidencia;
- la autorización de implementación;
- el resultado operativo;
- rutas, títulos o identidad documental;
- schema `.md.json`;
- candidatas o admisión canónica.

Aplicar:

- `procedencia_epistemologica.instructions.md` para origen y soporte;
- `contratos.instructions.md` para alcance autorizado;
- `canonical_session_family.instructions.md` para nombre, título, ruta,
  identidad y canonizabilidad;
- `tiddlers_sesiones.instructions.md` para formato y validación `.md.json`;
- `.agents/skills/tdc-session/SKILL.md` ante cambios materiales.

## Rol semántico

- `rol_principal`: `procedimiento`.
- `rol_secundario`: `definición`.

Una hipótesis es una afirmación provisional y contrastable.

Responde:

```text
¿Qué esperamos observar y qué evidencia permitiría evaluarlo?
````

No responde:

```text
¿Cuál es el estado actualmente observado?
```

Eso pertenece al diagnóstico.

Tampoco responde:

```text
¿Qué queda autorizado para intervenir?
```

Eso pertenece al contrato.

## Cuándo aplica

Registra una hipótesis cuando:

* existe una expectativa todavía no demostrada;
* una explicación tentativa necesita contrastarse;
* un comportamiento esperado guía una validación;
* una decisión depende de una condición incierta;
* una sesión debe distinguir supuesto y evidencia;
* aparece información que cambia el estatuto de una formulación previa.

No conviertas en hipótesis:

* hechos ya verificados;
* definiciones estabilizadas;
* decisiones humanas;
* obligaciones contractuales;
* descripciones vagas sin método de contraste;
* deseos sobre el resultado esperado.

## Formulación

Toda hipótesis debe ser:

* clara;
* delimitada;
* evaluable;
* vinculada con evidencia inicial;
* susceptible de confirmación o contradicción;
* relevante para el objetivo local.

Debe permitir identificar:

* qué se afirma;
* sobre qué superficie;
* bajo qué condiciones;
* qué se espera observar;
* cómo se contrastará;
* qué resultado la debilitaría o refutaría.

Evita formulaciones que puedan acomodarse a cualquier resultado.

Ejemplo de estructura conceptual:

```text
Dado <estado o evidencia inicial>,
se espera que <comportamiento observable>,
porque <razón provisional>.
La hipótesis se contrastará mediante <método>.
```

Esta estructura es orientativa. No introduce una plantilla rígida ni campos
nuevos en el schema.

## Evidencia inicial

Toda hipótesis debe derivarse de evidencia identificada en:

* `Procedencia de sesión`;
* `Diagnóstico de sesión`;
* inspecciones verificables;
* resultados previos pertinentes;
* decisiones humanas explícitas.

Distingue:

```text
evidencia inicial
→ observación que sustenta la formulación

supuesto
→ condición aceptada provisionalmente

interpretación
→ lectura construida desde la evidencia

expectativa
→ resultado que la hipótesis predice
```

No presentes una expectativa como evidencia.

No formules una hipótesis para justificar retrospectivamente una
implementación ya decidida.

## Método de contraste

Cada hipótesis debe declarar cómo será evaluada.

El contraste puede usar, según corresponda:

* inspección;
* comparación;
* test;
* conteo;
* validación de schema;
* preflight;
* dry-run;
* ejecución controlada;
* análisis de diff;
* comprobación de invariantes;
* evidencia humana documentada.

Debe quedar claro:

* qué se medirá u observará;
* con qué fuente o instrumento;
* qué resultado sería compatible;
* qué resultado exigiría refinamiento;
* qué resultado la contradiría;
* qué limitaciones impiden una conclusión definitiva.

La ausencia de evidencia contraria no equivale a confirmación.

## Condiciones de evaluación

Cada hipótesis debe definir, cuando corresponda:

### Confirmación

La evidencia observada coincide suficientemente con la formulación y con sus
condiciones de contraste.

### Confirmación parcial

Una parte de la formulación tiene soporte, pero otra permanece abierta o
depende de evidencia pendiente.

### Refinamiento

La evidencia conserva el núcleo de la hipótesis, pero obliga a precisar:

* alcance;
* condiciones;
* causalidad;
* superficie;
* mecanismo;
* resultado esperado.

### Contradicción

La evidencia observada es incompatible con una parte sustantiva de la
formulación.

### Descarte

La hipótesis deja de ser útil o queda sin soporte suficiente para seguir
orientando el trabajo.

### Evidencia insuficiente

No existe soporte suficiente para asignar un estado concluyente.

## Estados permitidos

Durante la sesión pueden usarse:

* `abierta`;
* `parcialmente_confirmada`;
* `refinada`;
* `contradicha`;
* `pendiente_por_evidencia_insuficiente`.

En el cierre deben usarse:

* `confirmada`;
* `parcialmente_confirmada`;
* `refinada`;
* `contradicha`;
* `descartada`;
* `abierta`;
* `pendiente_por_evidencia_insuficiente`.

Los estados describen el contenido epistemológico.

No introducen campos obligatorios adicionales en el `.md.json`.

## `Hipótesis de sesión`

El entregable canónico se denomina exactamente:

```text
Hipótesis de sesión
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

## Maduración durante la sesión

### Reconocimiento

No formules hipótesis definitivas durante el reconocimiento.

Primero deben existir procedencia y diagnóstico suficientes.

Pueden registrarse preguntas o supuestos provisionales, pero no deben
presentarse como hipótesis contratables hasta contar con evidencia diagnóstica.

### Formulación

Durante la formulación:

* deriva las hipótesis del diagnóstico;
* declara evidencia inicial;
* delimita alcance;
* define método de contraste;
* establece condiciones de evaluación;
* identifica riesgo si resultan falsas;
* conserva estatuto tentativo.

La hipótesis no autoriza implementación.

### Impacto

Durante la implementación:

* contrasta cada hipótesis con evidencia real;
* registra resultados favorables y adversos;
* conserva evidencia insuficiente;
* relaciona el contraste con tests y observaciones;
* actualiza el estatuto;
* registra refinamientos sin borrar la formulación anterior.

Cuando una contradicción afecte una parte material del contrato, aplica la
regresión definida en `SKILL.md`.

No reescribas la hipótesis para hacerla coincidir con el resultado.

### Postimpacto

Durante el cierre:

* asigna un estado explícito;
* vincula el estado con evidencia observada;
* conserva formulación inicial y refinamientos;
* declara incertidumbre residual;
* refleja el resultado en `Balance de sesión`;
* identifica líneas abiertas para `Propuesta de sesión`.

Una hipótesis confirmada no se convierte automáticamente en hecho, definición,
principio o contenido canónico consolidado.

Esa promoción requiere su propia gobernanza.

## Trayectoria

Cuando una hipótesis cambie, conserva:

* formulación inicial;
* evidencia inicial;
* evidencia nueva;
* formulación refinada, si existe;
* razón del cambio;
* estado anterior;
* estado nuevo;
* impacto sobre contrato e implementación.

La trayectoria debe permitir distinguir:

```text
lo que se esperaba
→ lo que se observó
→ cómo cambió la interpretación
```

No borres contradicciones, errores ni formulaciones previas relevantes.

## Contenido mínimo

Cada hipótesis relevante debe permitir identificar:

* identificador local o nombre legible;
* formulación;
* contexto;
* procedencia relacionada;
* alcance;
* evidencia inicial;
* supuesto relevante;
* método de contraste;
* condición de confirmación;
* condición de refinamiento;
* condición de contradicción;
* riesgo si resulta falsa;
* estado inicial;
* evidencia observada;
* cambios de formulación;
* estado final;
* incertidumbre o pendiente.

Esta lista gobierna el contenido del campo `text`.

No modifica el schema `.md.json`.

## Relación con los entregables

```text
Procedencia de sesión
→ identifica el origen de la evidencia

Diagnóstico de sesión
→ establece el estado observado

Hipótesis de sesión
→ formula expectativas contrastables

Contrato de sesión
→ autoriza cómo intervenir

Sesión
→ registra acciones y evidencia

Balance de sesión
→ evalúa el contraste

Propuesta de sesión
→ conserva continuidad pendiente
```

Una hipótesis no autoriza implementación.

Un contrato no convierte una hipótesis en verdadera.

Un test exitoso no confirma una hipótesis si no evalúa realmente su
formulación.

## Canonizabilidad

La `Hipótesis de sesión` debe ser canonizable.

Esto requiere:

* nombre canónico exacto;
* ruta y título gobernados;
* `.md.json` válido;
* identidad estable;
* formulación contrastable;
* evidencia y procedencia verificables;
* trayectoria explícita;
* estado final declarado;
* compatibilidad con el productor autoritativo.

La canonizabilidad no equivale a admisión.

Para candidatas y S66, aplica
`canonical_session_family.instructions.md`.

## Prohibiciones

* No presentes hipótesis como hechos.
* No confundas expectativa con evidencia.
* No formules hipótesis imposibles de refutar.
* No uses lenguaje ambiguo que acepte cualquier resultado.
* No ocultes incertidumbre.
* No cambies silenciosamente una formulación.
* No declares confirmación por falta de evidencia contraria.
* No elimines hipótesis contradichas.
* No promuevas automáticamente una hipótesis confirmada.
* No crees archivos `inicial`, `final`, `v2` o equivalentes.
* No copies aquí reglas completas de schema, identidad o S66.
* No uses la hipótesis como sustituto del diagnóstico o del contrato.

## Criterio de cumplimiento

La hipótesis es suficiente cuando:

* deriva de evidencia identificable;
* distingue evidencia, supuesto e interpretación;
* tiene alcance delimitado;
* puede confirmarse, refinarse o contradecirse;
* declara un método de contraste real;
* conserva su formulación y trayectoria;
* tiene estado explícito;
* las contradicciones permanecen visibles;
* puede relacionarse con contrato, detalles y balance;
* el entregable conserva identidad única;
* el `.md.json` es válido y canonizable.

