---
description: >
  Dueño normativo de los recursos concretos utilizados o producidos por TDC:
  identidad, ubicación, tipo, autoridad, vigencia, estado operativo, uso,
  preservación y relación con la evidencia.
---

# Elementos específicos

## Alcance

Esta instrucción gobierna:

- archivos;
- documentos;
- scripts;
- datasets;
- tablas;
- configuraciones;
- reportes;
- manifests;
- receipts;
- journals;
- snapshots;
- materiales concretos;
- referencias verificables;
- otros recursos identificables utilizados o producidos por el proyecto.

Define:

- identidad;
- ubicación;
- tipo;
- versión;
- autoridad;
- vigencia;
- estado operativo;
- uso;
- preservación;
- relación con decisiones y evidencia.

No gobierna:

- el origen epistemológico del recurso;
- la interpretación de su contenido;
- el desarrollo sustantivo del tema;
- la política transversal de dependencias;
- la bitácora completa de una sesión;
- rutas o schema de los siete entregables;
- candidatas o admisión canónica.

Aplicar:

- `procedencia_epistemologica.instructions.md` para origen, actor y método;
- `dependencia_y_superficie_externa.instructions.md` cuando el recurso sea una
  dependencia, toolchain, servicio o integración;
- `detalles_del_tema.instructions.md` para contenido sustantivo;
- `desarrollo_y_evolucion.instructions.md` para cambios de estado durables;
- `canonical_session_family.instructions.md` cuando una sesión deba conservar
  información canonizable sobre el recurso.

## Rol semántico

- `rol_principal`: `dato`.
- `rol_secundario`: `evidencia`.

Un elemento específico responde:

```text
¿Qué recurso concreto existe,
dónde está,
qué estado tiene
y cómo fue utilizado?
````

No responde:

```text
¿De dónde proviene?
```

Eso pertenece a la procedencia.

Tampoco responde:

```text
¿Qué conclusión demuestra?
```

Eso pertenece al diagnóstico, la hipótesis o el balance, según corresponda.

## Cuándo aplica

Registra un elemento específico cuando:

* un recurso entra al trabajo;
* un archivo sustenta una observación;
* una herramienta produce un resultado;
* un material debe preservarse para revisión;
* una sesión consume, modifica o genera un artefacto;
* debe distinguirse entre fuente autoritativa, derivada y temporal;
* un recurso cambia de estado o vigencia;
* una decisión depende de una referencia concreta.

No registres indiscriminadamente todos los archivos encontrados.

Incluye únicamente recursos con incidencia sobre:

* comprensión;
* implementación;
* validación;
* trazabilidad;
* continuidad;
* reproducibilidad;
* auditoría.

## Identidad mínima

Cada recurso relevante debe poder identificarse mediante los datos que
correspondan:

* nombre;
* ruta o referencia;
* tipo;
* formato;
* versión;
* hash;
* productor;
* fecha observada;
* consumidor;
* propósito;
* estado;
* autoridad;
* relación con la sesión o tema.

No todos los recursos requieren todos estos datos.

Registra solo los necesarios para distinguirlo y recuperarlo sin ambigüedad.

Una descripción como:

```text
el archivo anterior
el reporte
el script usado
la configuración
```

no constituye identidad suficiente.

## Recurso y procedencia

Mantén esta separación:

```text
Elemento específico
→ identifica el recurso

Procedencia epistemológica
→ explica su origen, actor y método de entrada

Diagnóstico o Sesión
→ registra qué se observó o hizo con él
```

La existencia del recurso no demuestra:

* que sea vigente;
* que sea autoritativo;
* que esté completo;
* que tenga consumidores activos;
* que su contenido sea correcto.

Una referencia debe poder relacionarse con la observación que sustenta.

## Autoridad

Clasifica el recurso, cuando corresponda, como:

* `autoritativo`;
* `fuente_primaria`;
* `auxiliar`;
* `derivado`;
* `staging`;
* `proyeccion_remota`;
* `temporal`;
* `historico`;
* `desconocido`.

Estas categorías describen su función.

No introducen campos obligatorios en el schema de sesión.

La autoridad debe evaluarse según:

* productor;
* consumidores;
* flujo vigente;
* validaciones;
* currentness;
* propósito de la superficie;
* relación con el canon.

La ubicación de un archivo no garantiza su autoridad.

La fecha reciente tampoco garantiza que esté vigente.

## Vigencia

Cuando la vigencia importe, declara uno de estos estados:

* `current`: representa el estado vigente;
* `stale`: existe, pero representa un estado anterior;
* `desconocido`: no existe evidencia suficiente para decidir;
* `incompatible`: no corresponde al estado o contrato vigente;
* `superseded`: fue reemplazado por otro recurso identificable.

La vigencia debe apoyarse en evidencia como:

* productor actual;
* manifest;
* hash;
* timestamp;
* consumidor;
* prueba;
* diff;
* relación con el canon;
* confirmación humana.

No uses solo la fecha de modificación como prueba de currentness.

## Estados operativos

Cuando sea útil, describe el recurso como:

| Estado         | Significado                                         |
| -------------- | --------------------------------------------------- |
| `identificado` | Existe y puede referenciarse                        |
| `verificado`   | Su identidad y estado fueron comprobados            |
| `consumido`    | Fue utilizado como entrada o evidencia              |
| `modificado`   | Cambió durante el trabajo                           |
| `producido`    | Fue generado como resultado                         |
| `temporal`     | No debe conservarse como salida durable             |
| `protegido`    | No está autorizado modificarlo                      |
| `candidato`    | Puede alimentar un proceso posterior de admisión    |
| `descartado`   | No debe seguir utilizándose para el objetivo actual |

Un recurso puede tener más de una característica compatible, por ejemplo:

```text
producido + temporal
verificado + protegido
consumido + stale
```

No confundas estado operativo con autoridad o vigencia.

## Recursos durante una sesión

### Reconocimiento

Durante el reconocimiento:

* identifica los recursos necesarios;
* verifica su existencia;
* determina su posible autoridad;
* distingue current, stale y desconocido;
* registra recursos ausentes;
* identifica superficies protegidas;
* vincula recursos con procedencia y diagnóstico.

No modifiques recursos durante esta instrucción.

La ausencia de un archivo esperado debe registrarse como observación, no como
prueba automática de pérdida histórica.

### Formulación

Durante la formulación:

* identifica qué recursos pueden consumirse;
* declara cuáles pueden modificarse;
* declara cuáles permanecen protegidos;
* vincula cada modificación prevista con el contrato;
* identifica outputs esperados;
* establece validaciones pertinentes.

La mención de un recurso en una hipótesis no autoriza su modificación.

### Impacto

Durante la implementación, registra en el entregable `Sesión`:

* recursos consumidos;
* recursos creados;
* recursos modificados;
* productor utilizado;
* estado anterior relevante;
* estado resultante;
* comandos o acciones;
* validaciones;
* hashes, conteos o manifests;
* recursos temporales;
* errores;
* descartes;
* snapshots, receipts o journals.

Cuando aparezca un recurso no contemplado que altere materialmente la
intervención, aplica la regresión definida en `SKILL.md`.

### Postimpacto

Durante el cierre, determina si cada recurso relevante:

* permanece vigente;
* queda como evidencia;
* debe regenerarse;
* requiere formalización;
* debe conservarse como temporal;
* debe descartarse;
* puede producir memoria canonizable;
* condiciona una sesión posterior.

La propuesta puede recomendar acciones futuras sobre el recurso, pero no debe
presentarlas como ejecutadas.

## Recursos producidos

Todo recurso producido debe permitir identificar:

* qué lo generó;
* con qué entradas;
* bajo qué versión o configuración;
* en qué ruta quedó;
* qué validación superó;
* si es reproducible;
* si es durable o temporal;
* qué consumidor lo utiliza;
* si depende de un estado específico del canon.

Un output sin productor conocido o sin relación con sus entradas debe
considerarse insuficientemente trazado.

## Recursos modificados

Cuando un recurso cambie, registra cuando corresponda:

* estado anterior;
* cambio aplicado;
* razón;
* productor o agente;
* validación;
* estado resultante;
* compatibilidad;
* efecto sobre consumidores;
* necesidad de regenerar derivados.

No ocultes regeneraciones, reemplazos o descartes relevantes.

No presentes un archivo regenerado como si fuera idéntico al anterior sin
verificarlo.

## Recursos temporales

Un recurso temporal debe declarar:

* propósito;
* ubicación;
* periodo de utilidad;
* condición de eliminación;
* si contiene información necesaria para auditoría;
* si debe preservarse hasta completar rollback o validación.

No conviertas outputs temporales en dependencias implícitas.

No borres evidencia necesaria para reconstruir una operación gobernada.

## Duplicación

Evita duplicar un recurso cuando una referencia estable sea suficiente.

Una copia adicional solo está justificada cuando existe una diferencia
verificable de:

* versión;
* estado;
* formato;
* autoridad;
* propósito;
* ubicación operativa;
* historia;
* aislamiento de seguridad.

Cuando existan copias, declara:

* fuente;
* derivación;
* sincronización;
* autoridad;
* riesgo de divergencia.

## Relación con los siete entregables

Los elementos específicos pueden sustentar todos los entregables:

```text
Procedencia de sesión
→ identifica de dónde proviene el recurso

Diagnóstico de sesión
→ registra qué indica su estado

Hipótesis de sesión
→ formula expectativas sobre su comportamiento

Contrato de sesión
→ autoriza su consumo o modificación

Sesión
→ registra qué se hizo con el recurso

Balance de sesión
→ evalúa el resultado

Propuesta de sesión
→ plantea continuidad futura
```

`Elementos específicos` no es un octavo entregable de sesión.

Los recursos deben referenciarse dentro de los siete entregables que
correspondan.

## Canonizabilidad

Un recurso concreto no entra al canon automáticamente.

Cuando información sobre ese recurso deba conservarse canónicamente:

1. regístrala en el entregable de sesión correspondiente;
2. conserva procedencia verificable;
3. produce un `.md.json` válido y canonizable;
4. genera una línea candidata cuando corresponda;
5. aplica S66.

La canonización conserva conocimiento sobre el recurso, no necesariamente el
archivo binario o material completo.

No incorpores recursos indiscriminadamente al canon.

## Prohibiciones

* No confundas recurso con procedencia.
* No confundas disponibilidad con autoridad.
* No confundas fecha reciente con vigencia.
* No registres todos los archivos sin criterio.
* No dejes recursos relevantes sin identidad.
* No trates derivados o temporales como fuente de verdad.
* No ocultes modificaciones o regeneraciones.
* No dupliques recursos sin diferencia verificable.
* No crees dependencias implícitas sobre archivos temporales.
* No uses esta instrucción como inventario de paquetes.
* No copies aquí schema, rutas o compuertas completas de S66.
* No conviertas `Elementos específicos` en un entregable adicional.

## Criterio de cumplimiento

La gestión de un recurso es suficiente cuando:

* puede identificarse y recuperarse;
* su tipo y propósito son claros;
* su autoridad y vigencia están declaradas cuando importan;
* puede distinguirse recurso, procedencia e interpretación;
* su uso o modificación queda trazado;
* su productor y consumidor son reconocibles cuando corresponda;
* los recursos temporales tienen ciclo de vida explícito;
* las duplicaciones tienen justificación;
* la evidencia que aporta puede relacionarse con una observación;
* cualquier memoria canonizable se conserva mediante los siete entregables.
