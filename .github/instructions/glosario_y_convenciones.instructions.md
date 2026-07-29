---
description: >
  Dueño normativo del vocabulario de TDC: términos, definiciones, alias,
  convenciones de escritura, formas canónicas, ambigüedades, deprecaciones y
  cambios terminológicos.
---

# Glosario y convenciones

## Alcance

Esta instrucción gobierna:

- términos compartidos;
- definiciones;
- alias;
- abreviaturas;
- símbolos;
- convenciones de escritura;
- formas humanas y técnicas;
- diferencias entre conceptos próximos;
- introducción, modificación y deprecación de vocabulario;
- coherencia terminológica entre sesiones, código y documentación.

No gobierna:

- contenido sustantivo del tema;
- decisiones arquitectónicas;
- reglas operativas de sesión;
- rutas o títulos de entregables;
- schemas;
- enums técnicos ya definidos por otro contrato;
- candidatas o admisión canónica.

Aplicar:

- `detalles_del_tema.instructions.md` para desarrollo sustantivo;
- `principios_de_gestion.instructions.md` para reglas transversales;
- `desarrollo_y_evolucion.instructions.md` para trayectoria de cambios;
- la instrucción especializada cuando un término pertenezca a un dueño
  normativo concreto;
- `canonical_session_family.instructions.md` para nombres, títulos y estados
  de la familia de sesión.

## Rol semántico

- `rol_principal`: `concepto`.
- `rol_secundario`: `procedimiento`.

El glosario responde:

```text
¿Qué significa este término,
cuál es su forma preferida,
qué variantes existen
y cómo debe usarse sin ambigüedad?
```

No responde:

```text
¿Qué decisión técnica debe adoptarse?
```

Eso pertenece al dueño normativo o al contrato correspondiente.

## Principio rector

Un mismo término no debe nombrar silenciosamente conceptos distintos.

Un mismo concepto no debe recibir múltiples nombres sin una relación explícita
entre ellos.

```text
un concepto
→ una forma preferida
→ alias declarados
→ usos delimitados
```

La estabilidad terminológica no impide evolucionar el vocabulario.

Exige que los cambios sean explícitos, trazables y propagados a sus
consumidores.

## Cuándo aplica

Consulta o actualiza esta instrucción cuando:

- se introduce un término compartido;
- una palabra tiene más de un sentido;
- aparecen alias o abreviaturas;
- una convención afecta varias sesiones o componentes;
- una forma humana difiere de su identificador técnico;
- una traducción puede alterar el significado;
- un término vigente debe reemplazarse;
- código y documentación usan nombres incompatibles;
- una clasificación requiere distinguir conceptos próximos.

No registres aquí palabras ordinarias cuyo significado no afecte la
interpretación del sistema.

## Unidad terminológica

Cada término estable debe poder declarar, cuando corresponda:

- forma preferida;
- definición;
- categoría;
- ámbito;
- alias;
- abreviaturas;
- forma técnica;
- forma visible;
- términos relacionados;
- términos que no deben confundirse;
- ejemplos válidos;
- ejemplos inválidos;
- estado;
- fuente normativa;
- fecha o sesión de cambio.

No todos los términos requieren todos estos elementos.

Registra únicamente lo necesario para impedir ambigüedad real.

## Categorías

Un término puede clasificarse como:

- `concepto`;
- `proceso`;
- `estado`;
- `rol`;
- `artefacto`;
- `superficie`;
- `operacion`;
- `convencion`;
- `identificador`;
- `metadato`;
- `veredicto`;
- `alias`.

La categoría ayuda a distinguir usos, pero no crea un campo obligatorio en
los artefactos de sesión.

## Formas de representación

Cuando un concepto tenga varias formas, distingue:

### Forma humana

Nombre legible utilizado en documentación o conversación.

Ejemplo:

```text
Hipótesis de sesión
```

### Forma técnica

Identificador utilizado por código, configuración o metadatos.

Ejemplo:

```text
session_hypothesis
```

### Forma canónica

Forma normativa que debe usarse en la superficie gobernada.

Ejemplo:

```text
Hipótesis de sesión
```

### Alias

Variante aceptada para búsqueda, migración o compatibilidad, pero no preferida
para nueva producción.

Ejemplo:

```text
hipótesis operativa
```

### Forma obsoleta

Nombre que ya no debe introducirse en contenido nuevo.

Debe conservarse solo cuando sea necesario para:

- historia;
- migración;
- compatibilidad;
- búsqueda;
- interpretación de artefactos antiguos.

No sustituyas una forma canónica por un alias en superficies gobernadas.

## Convenciones de escritura

### Nombres humanos

Usa:

- español cuando el concepto normativo esté definido en español;
- mayúscula inicial solo cuando corresponda al nombre formal;
- tildes y signos correctos;
- nombres completos antes de introducir abreviaturas.

Evita variantes ortográficas para el mismo concepto.

### Identificadores técnicos

Usa la convención definida por el consumidor:

- `snake_case`;
- `kebab-case`;
- `camelCase`;
- `PascalCase`;
- mayúsculas para constantes.

No traduzcas identificadores existentes sin una migración explícita.

No mezcles convenciones dentro de una misma familia técnica.

### Slugs

Los slugs deben ser:

- estables;
- descriptivos;
- en minúsculas;
- separados por guiones;
- sin tildes;
- sin caracteres decorativos;
- sin estados temporales como `final`, `nuevo` o `v2`.

La forma exacta de los slugs de sesión pertenece a
`canonical_session_family.instructions.md`.

### Abreviaturas

Toda abreviatura compartida debe:

- expandirse en su primera aparición;
- tener un significado único dentro del ámbito;
- evitar colisión con identificadores existentes;
- conservar mayúsculas y puntuación consistentes.

No introduzcas una abreviatura si no reduce una repetición significativa.

## Distinciones obligatorias

### Dato, evidencia e interpretación

```text
dato
→ unidad disponible u observada

evidencia
→ dato usado para sustentar una afirmación

interpretación
→ lectura construida desde la evidencia
```

Un dato no se convierte automáticamente en evidencia.

Una evidencia no determina una única interpretación.

### Recurso y procedencia

```text
recurso
→ objeto concreto

procedencia
→ origen, actor y método de entrada
```

El recurso se gobierna en `elementos_especificos.instructions.md`.

La procedencia se gobierna en
`procedencia_epistemologica.instructions.md`.

### Diagnóstico e hipótesis

```text
diagnóstico
→ estado observado

hipótesis
→ expectativa contrastable
```

El diagnóstico no debe escribirse como expectativa.

La hipótesis no debe presentarse como observación.

### Hipótesis y contrato

```text
hipótesis
→ qué se espera comprobar

contrato
→ qué queda autorizado hacer
```

Una hipótesis no autoriza implementación.

### Actividad, resultado y evolución

```text
actividad
→ acción ejecutada

resultado
→ efecto observado

evolución
→ transformación consolidada entre estados
```

Una actividad no demuestra consolidación.

### Artefacto válido, canonizable y admitido

```text
válido
→ cumple su schema

canonizable
→ puede producir una representación candidata

candidato
→ representación pendiente de admisión

admitido
→ incorporado al canon mediante el proceso gobernado
```

Estos estados no son equivalentes.

### Staging, canon y derivado

```text
staging
→ superficie operativa o temporal

canon
→ memoria local autoritativa

derivado
→ representación producida desde otra fuente
```

La existencia en staging o en un derivado no concede autoridad canónica.

### Sesión, macrofase e instrucción

```text
sesión
→ unidad completa de trabajo con una identidad

macrofase
→ preimpacto, impacto o postimpacto

instrucción ejecutable
→ una de las cuatro intervenciones de la skill
```

El preimpacto contiene dos instrucciones ejecutables.

Las macrofases no son sesiones independientes.

### Entregable y archivo

```text
entregable
→ función documental dentro de la familia

archivo
→ representación física del entregable
```

El entregable conserva identidad aunque su contenido sea actualizado.

### Autorización contractual y humana

```text
autorización contractual
→ operación incluida dentro del alcance

autorización humana
→ decisión explícita requerida para ejecutar una acción gobernada
```

El contrato no sustituye la autorización humana cuando esta sea obligatoria.

### Cambio y cambio material

```text
cambio
→ modificación dentro del trabajo autorizado

cambio material
→ modificación que altera una condición sustantiva del contrato
```

La definición operativa de cambio material pertenece a
`.agents/skills/tdc-session/SKILL.md`.

No la redefinas aquí.

## Vocabulario canónico de sesión

Usa exactamente estos nombres para los siete entregables:

1. `Contrato de sesión`;
2. `Procedencia de sesión`;
3. `Sesión`;
4. `Hipótesis de sesión`;
5. `Balance de sesión`;
6. `Propuesta de sesión`;
7. `Diagnóstico de sesión`.

`Sesión` es el nombre canónico del entregable operativo conocido
contextualmente como detalles de sesión.

No sustituyas esos nombres por:

- reporte;
- acta;
- bitácora;
- resumen;
- ficha;
- registro;

salvo cuando esas palabras describan contenido interno y no el nombre formal
del entregable.

Las rutas y títulos exactos pertenecen a
`canonical_session_family.instructions.md`.

## Estados terminológicos

Todo término gobernado puede tener uno de estos estados:

- `propuesto`;
- `vigente`;
- `deprecado`;
- `obsoleto`;
- `experimental`;
- `reservado`.

### `propuesto`

Todavía requiere validación antes de uso transversal.

### `vigente`

Es la forma preferida en el ámbito declarado.

### `deprecado`

Sigue siendo reconocible, pero no debe usarse en producción nueva.

Debe declarar su reemplazo.

### `obsoleto`

Solo se conserva para historia o migración.

### `experimental`

Puede utilizarse en un ámbito limitado y explícito.

No debe presentarse como convención general.

### `reservado`

Su uso está restringido por una regla, contrato o consumidor específico.

## Introducción de un término

Antes de introducir vocabulario transversal:

1. busca términos existentes;
2. identifica el concepto;
3. confirma que no exista una forma equivalente;
4. determina su dueño semántico;
5. define ámbito y categoría;
6. declara forma preferida;
7. registra alias necesarios;
8. distingue conceptos próximos;
9. identifica consumidores;
10. valida que el término reduzca ambigüedad.

No crees un término nuevo solo para renombrar una idea existente.

Cuando el término sea local a una sesión, puede permanecer en sus entregables
sin promoverse al glosario transversal.

## Cambio de definición

Una definición vigente solo debe modificarse cuando exista evidencia de:

- ambigüedad;
- insuficiencia;
- contradicción;
- cambio arquitectónico;
- nueva distinción necesaria;
- incompatibilidad entre consumidores.

El cambio debe registrar:

- definición anterior;
- problema;
- nueva definición;
- razón;
- ámbito;
- términos afectados;
- consumidores que requieren actualización;
- compatibilidad;
- estrategia de migración.

No reescribas silenciosamente una definición previa.

## Deprecación

Para deprecar un término:

1. declara la forma deprecada;
2. identifica su reemplazo;
3. explica la razón;
4. determina consumidores;
5. define periodo o criterio de transición;
6. conserva alias de búsqueda cuando sea necesario;
7. evita introducirlo en contenido nuevo.

No elimines inmediatamente una forma que aún aparezca en:

- código;
- artefactos históricos;
- canon;
- contratos;
- APIs;
- documentación vigente.

## Traducción

Cuando exista una forma en varios idiomas:

- conserva un concepto único;
- declara la forma preferida por idioma;
- evita traducciones literales que cambien el alcance;
- no traduzcas identificadores técnicos;
- distingue traducción de alias conceptual.

Una traducción no crea automáticamente un término nuevo.

## Relación con código y documentación

Cuando un término afecte código, identifica:

- funciones;
- clases;
- campos;
- enums;
- rutas;
- schemas;
- CLI;
- tests;
- documentación;
- consumidores externos.

No renombres identificadores técnicos únicamente para coincidir con una mejora
de redacción.

Determina primero si el cambio es:

- semántico;
- cosmético;
- incompatible;
- migratorio.

Un cambio terminológico puede ser material si altera interpretación, schema,
API o comportamiento.

## Ambigüedad

Cuando un término tenga varios sentidos:

1. identifica los sentidos;
2. delimita su ámbito;
3. selecciona una forma preferida para cada concepto;
4. declara los alias;
5. añade ejemplos;
6. actualiza consumidores relevantes.

No resuelvas ambigüedad dependiendo solo del contexto implícito.

Ejemplo:

```text
sesión
→ unidad completa de trabajo

instrucción
→ ejecución individual dentro de la sesión
```

## Relación con principios y contenido

Cuando una definición implique una regla transversal, aplica
`principios_de_gestion.instructions.md`.

Cuando defina contenido sustantivo de un tema, aplica
`detalles_del_tema.instructions.md`.

Cuando cambie a través del tiempo, registra su trayectoria mediante
`desarrollo_y_evolucion.instructions.md`.

El glosario estabiliza el lenguaje; no absorbe las responsabilidades de esos
archivos.

## Canonizabilidad

Una definición puede convertirse en memoria canonizable cuando:

- tiene forma preferida;
- su ámbito es claro;
- sus diferencias semánticas están delimitadas;
- conserva procedencia;
- cuenta con evidencia suficiente;
- su estado es explícito;
- no contradice un dueño normativo vigente.

La canonizabilidad no equivale a admisión.

Para candidatas y S66, aplica
`canonical_session_family.instructions.md`.

## Prohibiciones

- No uses el mismo término con sentidos distintos sin declararlo.
- No crees sinónimos innecesarios.
- No introduzcas abreviaturas sin definición.
- No traduzcas identificadores técnicos.
- No cambies una definición silenciosamente.
- No elimines términos todavía consumidos.
- No presentes vocabulario experimental como vigente.
- No uses el glosario para tomar decisiones arquitectónicas.
- No copies aquí schemas, rutas o enums gobernados por otros dueños.
- No redefinas nombres canónicos de sesión.
- No conviertas cada término local en vocabulario transversal.
- No uses lenguaje decorativo cuando reduzca precisión.

## Criterio de cumplimiento

El vocabulario es coherente cuando:

- cada concepto tiene una forma preferida;
- los alias están declarados;
- conceptos próximos pueden distinguirse;
- forma humana, técnica y canónica no se confunden;
- los términos tienen ámbito y estado;
- los cambios conservan trayectoria;
- las deprecaciones identifican reemplazo;
- los consumidores afectados pueden localizarse;
- el lenguaje reduce ambigüedad entre humano, código y canon;
- no existen definiciones duplicadas entre dueños normativos.
````
