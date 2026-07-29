---
description: >
  Dueño normativo del contenido sustantivo de cada tema TDC: identidad,
  alcance, objetivos, requisitos, flujo, arquitectura, componentes,
  algoritmos e ingeniería asistida por IA.
---

# Detalles del tema

## Alcance

Esta instrucción gobierna:

- la identidad sustantiva de un tema;
- su propósito;
- su alcance;
- sus objetivos;
- sus requisitos;
- sus tensiones y análisis DOFA;
- su flujo de interacción;
- su arquitectura;
- sus componentes;
- sus algoritmos y fundamentos matemáticos;
- su relación con ingeniería asistida por IA;
- la coherencia entre esos bloques.

No gobierna:

- la ejecución de una sesión;
- el entregable canónico `Sesión`;
- principios normativos transversales;
- procedencia epistemológica;
- hipótesis todavía tentativas;
- recursos concretos;
- continuidad histórica;
- rutas, títulos o schema de entregables;
- candidatas o admisión al canon.

Aplicar:

- `protocolo_de_sesion.instructions.md` para metodología de sesión;
- `procedencia_epistemologica.instructions.md` para origen y evidencia;
- `hipotesis.instructions.md` para formulaciones tentativas;
- `principios_de_gestion.instructions.md` para normativa transversal;
- `desarrollo_y_evolucion.instructions.md` para continuidad entre estados;
- `elementos_especificos.instructions.md` para recursos concretos;
- `glosario_y_convenciones.instructions.md` para vocabulario;
- `canonical_session_family.instructions.md` para canonizabilidad y S66.

## Rol semántico

- `rol_principal`: `concepto`.
- `rol_secundario`: `procedimiento`.

`Detalles del tema` responde:

```text
¿Qué es este tema,
qué busca resolver,
qué pertenece a su alcance
y cómo se organiza su desarrollo sustantivo?
```

No responde:

```text
¿Qué ocurrió durante una sesión concreta?
```

Eso pertenece al entregable canónico `Sesión`.

Tampoco responde:

```text
¿Qué regla transversal gobierna todo el proyecto?
```

Eso pertenece a `principios_de_gestion.instructions.md`.

## Principio rector

El tema debe poder comprenderse como una estructura coherente y no como una
acumulación de notas.

```text
identidad
→ objetivos
→ requisitos
→ flujo
→ arquitectura
→ componentes
→ algoritmos
→ asistencia de IA
```

Los bloques no son independientes.

Una modificación en una capa superior puede exigir reconciliar las capas que
dependen de ella.

## Cuándo aplica

Consulta o actualiza esta instrucción cuando:

- se crea un tema;
- cambia su identidad o alcance;
- se estabiliza contenido sustantivo;
- una sesión modifica objetivos o requisitos;
- cambia el flujo funcional;
- se introduce una decisión arquitectónica temática;
- aparece, cambia o desaparece un componente;
- se formaliza un algoritmo;
- se define el papel de la IA en el desarrollo;
- se detectan contradicciones entre bloques.

No actualices el desarrollo temático por actividad puramente operativa,
documental o administrativa.

## Fuentes de arranque

Un tema puede comenzar desde:

- `# 2_🧾 Procedencia inicial`;
- `# 3_🧪 Hipótesis inicial`;
- evidencia técnica;
- necesidad humana;
- problema identificado;
- decisión de diseño;
- recurso concreto;
- continuidad de otro tema.

Estas fuentes orientan el arranque, pero no sustituyen el desarrollo
sustantivo.

La procedencia explica de dónde surge el tema.

La hipótesis conserva lo que todavía debe contrastarse.

`Detalles del tema` estructura aquello que ya puede formularse como contenido
temático explícito.

## Estructura temática

El desarrollo se distribuye en estos ocho bloques:

1. `### 🎯 1. Objetivos 🧱`
2. `### 🎯 2. Requisitos 🧱`
3. `### 🎯 3. DOFA 🧱`
4. `### 🎯 4. Flujo de interaccion 🧱`
5. `### 🎯 5. Arquitectura 🌀`
6. `### 🎯 6. Componentes 🌀`
7. `### 🎯 7. Algoritmos y matematicas 🌀`
8. `### 🎯 8. Ingeniería asistida por IA 🌀`

No todos los temas requieren el mismo nivel de profundidad en cada bloque.

Un bloque puede permanecer mínimo cuando no exista evidencia suficiente, pero
no debe rellenarse con contenido especulativo para aparentar completitud.

## Identidad del tema

Todo tema debe poder declarar:

- nombre;
- propósito;
- problema o necesidad;
- ámbito;
- actores o consumidores;
- límites;
- relación con otros temas;
- estado de madurez;
- vocabulario principal.

La identidad debe permitir distinguirlo de:

- una sesión;
- un componente;
- una herramienta;
- un recurso;
- una política;
- una hipótesis;
- una propuesta.

No uses el nombre del tema para describir una actividad temporal.

## Alcance

El alcance debe distinguir:

- contenido incluido;
- contenido excluido;
- fronteras con otros temas;
- dependencias conceptuales;
- preguntas abiertas;
- aspectos todavía tentativos.

Cuando un asunto pertenezca a otro dueño:

- referencia ese dueño;
- no lo dupliques;
- conserva solo la relación necesaria para comprender el tema.

Una frontera temática no equivale a una frontera contractual.

El contrato delimita una intervención concreta.

El tema delimita un dominio de desarrollo.

## Objetivos

`### 🎯 1. Objetivos 🧱` debe declarar qué resultados sustantivos busca el
tema.

Los objetivos deben ser:

- comprensibles;
- coherentes con el propósito;
- delimitados;
- evaluables;
- distinguibles de actividades;
- suficientemente estables para orientar requisitos.

Evita objetivos como:

```text
analizar el sistema
hacer mejoras
trabajar con IA
actualizar componentes
```

Prefiere formulaciones que expresen una capacidad o estado esperado.

Cuando cambie un objetivo, revisa como mínimo:

- requisitos;
- flujo;
- arquitectura;
- componentes;
- algoritmos;
- papel de la IA.

## Requisitos

`### 🎯 2. Requisitos 🧱` debe convertir los objetivos en condiciones
necesarias.

Distingue, cuando corresponda:

- requisitos funcionales;
- requisitos semánticos;
- requisitos de datos;
- requisitos de arquitectura;
- requisitos operativos;
- requisitos de seguridad;
- requisitos de trazabilidad;
- requisitos de usabilidad;
- restricciones;
- criterios de aceptación temática.

Cada requisito debe relacionarse con:

- un objetivo;
- una necesidad;
- un consumidor;
- una restricción;
- una evidencia.

No presentes como requisito una preferencia sin declarar su autoridad.

No conviertas una implementación existente en requisito solo porque ya existe.

## DOFA

`### 🎯 3. DOFA 🧱` debe registrar tensiones estratégicas relevantes:

- debilidades;
- oportunidades;
- fortalezas;
- amenazas.

El DOFA debe:

- relacionarse con el estado real;
- distinguir condiciones internas y externas;
- identificar incidencia sobre objetivos;
- evitar afirmaciones genéricas;
- actualizarse cuando cambien las condiciones.

No uses DOFA como sustituto del diagnóstico técnico.

El diagnóstico observa un estado concreto.

El DOFA interpreta tensiones estratégicas del tema.

## Flujo de interacción

`### 🎯 4. Flujo de interaccion 🧱` debe explicar cómo circulan:

- actores;
- entradas;
- decisiones;
- transformaciones;
- estados;
- salidas;
- errores;
- retroalimentación.

El flujo debe poder responder:

```text
quién inicia
→ qué entra
→ qué ocurre
→ qué decisión se toma
→ qué sale
→ qué pasa si falla
```

Distingue:

- flujo humano;
- flujo computacional;
- flujo de datos;
- flujo de control;
- flujo de autorización.

No describas una secuencia ideal si el sistema real funciona de otra manera.

Cuando exista diferencia entre flujo vigente y flujo objetivo, declara ambos.

## Arquitectura

`### 🎯 5. Arquitectura 🌀` debe explicar la organización estructural del
tema.

Puede incluir:

- capas;
- fronteras;
- responsabilidades;
- productores;
- consumidores;
- contratos;
- superficies de autoridad;
- flujos de datos;
- dependencias;
- puntos de extensión;
- mecanismos de fallo.

La arquitectura debe derivarse de objetivos y requisitos.

No debe limitarse a enumerar carpetas o archivos.

Toda decisión arquitectónica relevante debe explicar:

- problema que resuelve;
- alternativas;
- límites;
- consecuencias;
- consumidores;
- validación;
- deuda introducida.

Los principios transversales pertenecen a
`principios_de_gestion.instructions.md`.

## Componentes

`### 🎯 6. Componentes 🌀` debe identificar unidades con responsabilidad
reconocible.

Cada componente relevante debe permitir reconocer:

- nombre;
- propósito;
- responsabilidad;
- entradas;
- salidas;
- consumidores;
- autoridad;
- dependencias;
- estado;
- errores;
- pruebas;
- relación con la arquitectura.

No declares como componente cualquier archivo o función.

Un componente debe tener una responsabilidad estructural identificable.

Cuando existan implementaciones:

- autoritativas;
- auxiliares;
- legacy;
- experimentales;
- de compatibilidad;
- deprecadas;

declara su estado y evita competencia silenciosa.

## Algoritmos y matemáticas

`### 🎯 7. Algoritmos y matematicas 🌀` debe explicar la lógica formal
necesaria para el tema.

Puede incluir:

- transformaciones;
- reglas;
- heurísticas;
- métricas;
- funciones;
- estructuras de datos;
- modelos;
- complejidad;
- invariantes;
- condiciones de convergencia;
- supuestos matemáticos.

Todo algoritmo debe declarar cuando corresponda:

- entradas;
- salida;
- precondiciones;
- procedimiento;
- complejidad;
- determinismo;
- casos límite;
- errores;
- validación;
- límites.

No uses formalización matemática como decoración.

No conviertas una heurística en ley determinista.

Distingue:

```text
regla
→ comportamiento definido

heurística
→ aproximación práctica

métrica
→ medida

hipótesis
→ expectativa todavía contrastable
```

## Ingeniería asistida por IA

`### 🎯 8. Ingeniería asistida por IA 🌀` debe definir cómo participa la IA
en el tema.

Puede incluir:

- recuperación de contexto;
- análisis;
- clasificación;
- generación;
- transformación;
- validación;
- asistencia de implementación;
- revisión;
- interacción humano-IA.

Debe declarar:

- tarea delegada;
- inputs;
- outputs;
- autoridad;
- límites;
- validación;
- riesgo;
- revisión humana;
- trazabilidad.

No presentes la IA como autoridad final.

Distingue:

```text
asistencia
→ propone o transforma

automatización
→ ejecuta un procedimiento definido

decisión
→ selecciona una acción con autoridad

autorización
→ habilita una operación gobernada
```

Una salida de IA debe poder verificarse antes de adquirir autoridad.

## Coherencia entre bloques

Aplica esta dirección principal de dependencia:

```text
Objetivos
→ Requisitos
→ Flujo
→ Arquitectura
→ Componentes
→ Algoritmos
→ Ingeniería asistida por IA
```

DOFA aporta tensiones que pueden afectar cualquier bloque.

Cuando aparezca una contradicción:

1. identifica los bloques implicados;
2. determina cuál posee mayor precedencia;
3. revisa evidencia y procedencia;
4. corrige primero el bloque superior;
5. propaga el cambio hacia dependientes;
6. registra la transformación en desarrollo y evolución;
7. evita dejar consumidores temáticos en estados incompatibles.

Ejemplos:

- un componente sin requisito conocido debe justificarse o retirarse;
- un algoritmo sin consumidor debe cuestionarse;
- una automatización de IA sin flujo definido no está suficientemente situada;
- una arquitectura incompatible con los objetivos debe revisarse desde los
  objetivos y requisitos;
- un requisito sin objetivo debe tratarse como deuda o exceso de alcance.

## Estado temático

Cuando sea útil, un bloque o formulación puede describirse como:

- `propuesto`;
- `tentativo`;
- `vigente`;
- `parcial`;
- `deprecado`;
- `bloqueado`;
- `superseded`.

### `propuesto`

Existe una formulación inicial, pero todavía requiere evaluación.

### `tentativo`

Depende de una hipótesis o evidencia insuficiente.

### `vigente`

Representa el estado temático aceptado.

### `parcial`

Solo una parte está desarrollada o validada.

### `deprecado`

Sigue siendo reconocible, pero no debe orientar trabajo nuevo.

### `bloqueado`

No puede madurar por falta de evidencia o precondiciones.

### `superseded`

Fue reemplazado por una formulación más reciente y trazable.

Estos estados no sustituyen los estados de sesión ni añaden campos obligatorios
al schema.

## Maduración del contenido

Una formulación puede avanzar mediante:

```text
idea
→ hipótesis
→ evidencia
→ formulación temática
→ validación
→ estado vigente
```

No toda idea debe entrar al desarrollo temático.

No toda hipótesis confirmada se estabiliza automáticamente.

Antes de incorporar contenido como vigente, verifica:

- procedencia;
- evidencia;
- coherencia;
- alcance;
- consumidores;
- contradicciones;
- autoridad humana cuando corresponda.

## Relación con las sesiones

Una sesión puede:

- observar el tema;
- formular hipótesis;
- modificar contenido;
- validar una decisión;
- corregir una contradicción;
- proponer continuidad.

Los cambios temáticos deben surgir de los siete entregables de sesión, pero no
deben copiarse mecánicamente.

El postimpacto debe permitir distinguir:

- actividad local;
- resultado;
- cambio temático consolidado;
- continuidad futura.

La actualización estable del tema se registra mediante
`desarrollo_y_evolucion.instructions.md`.

## Relación con `Sesión`

No confundas:

```text
Detalles del tema
→ contenido sustantivo durable

Sesión
→ entregable operativo de una intervención concreta
```

`Detalles del tema` no es uno de los siete entregables de sesión.

El entregable `Sesión` puede registrar cambios realizados sobre el tema, pero
no reemplaza su estructura sustantiva.

## Relación con elementos específicos

Los recursos concretos se gobiernan en
`elementos_especificos.instructions.md`.

Cuando un archivo, tabla, script o dataset sea relevante:

- referencia el recurso;
- declara su papel;
- evita copiarlo completo;
- distingue recurso y conclusión temática.

La existencia de un recurso no demuestra la validez de una afirmación.

## Relación con glosario

Todo término compartido, ambiguo o transversal debe estabilizarse mediante
`glosario_y_convenciones.instructions.md`.

El tema puede usar vocabulario especializado, pero debe:

- definirlo;
- distinguirlo de conceptos próximos;
- respetar formas canónicas;
- evitar sinónimos silenciosos.

## Relación con principios

Cuando una regla afecte varios temas, componentes o sesiones, debe promoverse
a `principios_de_gestion.instructions.md`.

No conviertas una decisión local del tema en principio transversal sin:

- evidencia;
- ámbito;
- estabilidad;
- consumidores;
- límites.

## Canonizabilidad

El contenido temático puede producir memoria canonizable cuando:

- tiene identidad;
- posee alcance explícito;
- conserva procedencia;
- distingue estado vigente y formulación tentativa;
- mantiene coherencia entre bloques;
- está vinculado con evidencia;
- no contradice dueños normativos;
- puede representarse mediante un entregable de sesión válido.

La canonizabilidad no equivale a admisión.

Para candidatas y S66, aplica
`canonical_session_family.instructions.md`.

## Prohibiciones

- No uses este archivo como bitácora de sesión.
- No copies los siete entregables dentro del tema.
- No presentes hipótesis como contenido vigente.
- No conviertas propuestas en estado alcanzado.
- No mezcles principios transversales con contenido local.
- No introduzcas componentes sin responsabilidad.
- No introduzcas requisitos sin objetivo.
- No introduzcas algoritmos sin entradas, salida o consumidor.
- No describas IA sin límites ni validación.
- No conserves contradicciones silenciosas entre bloques.
- No rellenes bloques sin evidencia.
- No confundas recurso y conocimiento.
- No copies schemas, rutas o compuertas S66.
- No uses `Detalles del tema` como sustituto del entregable `Sesión`.

## Criterio de cumplimiento

El desarrollo temático es suficiente cuando:

- la identidad y el alcance son claros;
- los objetivos orientan los requisitos;
- los requisitos justifican el flujo y la arquitectura;
- los componentes tienen responsabilidades y consumidores;
- los algoritmos están situados y son verificables;
- el papel de la IA está delimitado;
- las tensiones DOFA tienen incidencia reconocible;
- las contradicciones se propagan desde su bloque de mayor precedencia;
- lo tentativo se distingue de lo vigente;
- puede reconstruirse el tema sin depender de una sesión aislada;
- el contenido puede evolucionar sin perder coherencia ni procedencia.
````
