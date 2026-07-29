---
description: >
  Dueño normativo de dependencias, toolchains, workflows, servicios externos,
  supply chain, accesos, seguridad y reproducibilidad de TDC.
---

# Dependencias y superficie externa

## Alcance

Esta instrucción gobierna:

- dependencias de código;
- runtimes e intérpretes;
- package managers y lockfiles;
- toolchains de construcción;
- acciones y workflows de CI/CD;
- servicios, APIs y almacenamiento externos;
- red, autenticación y credenciales;
- supply chain;
- versiones y compatibilidad;
- reproducibilidad entre entornos;
- incorporación, actualización, sustitución y retiro;
- autoridad y estado operativo de estas superficies.

No gobierna:

- recursos concretos ordinarios;
- arquitectura sustantiva del tema;
- metodología general de sesión;
- publicación específica de diagnósticos;
- schema de entregables;
- candidatas o admisión canónica;
- commits o pull requests.

Aplicar:

- `elementos_especificos.instructions.md` para archivos y recursos concretos;
- `principios_de_gestion.instructions.md` para criterios transversales;
- `detalles_del_tema.instructions.md` para arquitectura y componentes;
- `diagnosticos_no_sesionales.instructions.md` para publicación remota de
  diagnósticos;
- `contratos.instructions.md` para autorizar cambios en una sesión;
- `canonical_session_family.instructions.md` para candidatas y S66.

## Rol semántico

- `rol_principal`: `concepto`.
- `rol_secundario`: `proceso`.

Esta instrucción responde:

```text
¿Qué dependencia o superficie externa existe,
qué función cumple,
quién la consume,
qué autoridad tiene,
qué riesgo introduce
y cómo debe gobernarse?
```

No funciona como:

- copia de `requirements.txt`;
- copia de `package.json`;
- copia de lockfiles;
- SBOM manual;
- inventario indiscriminado;
- listado de herramientas instaladas.

Los manifests y lockfiles registran estado técnico.

Esta instrucción gobierna la decisión, autoridad, riesgo y continuidad de ese
estado.

## Cuándo aplica

Consulta esta instrucción cuando:

- se añade una dependencia;
- cambia una versión;
- se modifica un lockfile;
- cambia un runtime;
- se incorpora una action de CI;
- cambia un workflow;
- aparece una integración externa;
- se modifica autenticación o acceso;
- una herramienta puede escribir sobre superficies productivas;
- una dependencia pierde mantenimiento;
- se detecta una vulnerabilidad;
- dos herramientas compiten por la misma función;
- una dependencia deja de tener consumidores conocidos;
- un servicio remoto condiciona la operación local;
- debe retirarse infraestructura legacy.

No actives esta instrucción para cualquier archivo o recurso ordinario.

## Conceptos

### Dependencia

Componente externo requerido por código o tooling para ejecutar, construir,
validar o distribuir TDC.

Puede ser:

- librería;
- paquete;
- módulo;
- binario;
- action;
- runtime;
- sistema operativo;
- herramienta de construcción;
- cliente externo.

### Toolchain

Conjunto coordinado de herramientas necesarias para producir o validar una
salida.

Ejemplos conceptuales:

```text
runtime
→ package manager
→ dependencias
→ generador
→ validador
→ tests
```

### Superficie externa

Sistema fuera de la autoridad local directa de TDC que participa en su
operación.

Puede incluir:

- APIs;
- GitHub;
- OneDrive;
- registries;
- runners;
- servicios de autenticación;
- almacenamiento remoto;
- red;
- proveedores de modelos;
- repositorios externos.

### Supply chain

Cadena mediante la cual código, paquetes, acciones, imágenes o binarios
externos entran al entorno de TDC.

Incluye:

- origen;
- versión;
- integridad;
- mantenedor;
- distribución;
- transitive dependencies;
- proceso de actualización;
- validación.

## Registro mínimo

Una dependencia o integración relevante debe permitir identificar, cuando
corresponda:

- nombre;
- categoría;
- versión o rango;
- origen;
- manifest;
- lockfile;
- consumidor;
- propósito;
- responsable técnico;
- autoridad;
- estado;
- criticidad;
- superficie de escritura;
- permisos;
- riesgo;
- estrategia de actualización;
- estrategia de retiro;
- validaciones;
- fallback;
- modo offline;
- compatibilidad conocida.

No todos los elementos requieren todos los campos.

Registra solo la información necesaria para gobernar su uso.

## Consumidor conocido

Toda dependencia activa debe tener al menos un consumidor reconocible.

Un consumidor puede ser:

- módulo runtime;
- script;
- test;
- workflow;
- generador;
- validador;
- CLI;
- pipeline;
- componente de desarrollo.

La mera aparición en un manifest no demuestra consumo vigente.

Cuando no existan consumidores conocidos, clasifica la dependencia como:

- pendiente de investigación;
- huérfana;
- legacy;
- candidata a retiro.

No la elimines únicamente por falta de referencias textuales sin verificar:

- carga dinámica;
- plugins;
- entry points;
- workflows;
- imports indirectos;
- compatibilidad histórica.

## Estados normativos

Usa estos estados cuando corresponda:

| Estado | Significado |
|---|---|
| `autoritativa` | Implementación o herramienta oficial para una función |
| `activa` | Tiene consumidores vigentes |
| `auxiliar` | Apoya el flujo sin gobernarlo |
| `compatibilidad` | Conserva comportamiento histórico necesario |
| `experimental` | Uso limitado y no productivo |
| `test_only` | Solo participa en pruebas |
| `deprecada` | Debe dejar de usarse en trabajo nuevo |
| `legacy` | Permanece por historia o migración |
| `huérfana` | No tiene consumidores conocidos |
| `bloqueada` | No debe utilizarse por riesgo o incompatibilidad |
| `proyectada` | Preparación futura todavía no activa |

Estos estados no son mutuamente excluyentes en todos los casos.

Ejemplo:

```text
activa + auxiliar
compatibilidad + legacy
experimental + test_only
deprecada + activa
```

Cuando coincidan varios estados, declara cuál determina el comportamiento
operativo.

## Autoridad

Para cada función técnica relevante debe existir una implementación
autoritativa o una decisión explícita de coexistencia.

Ejemplos de funciones:

- generar canon;
- validar schema;
- producir reverse;
- exportar estructura;
- sincronizar;
- publicar;
- construir;
- ejecutar tests;
- resolver dependencias.

Dos herramientas que parecen producir la misma salida no deben competir
silenciosamente.

Cuando existan varias implementaciones, declara:

- cuál es autoritativa;
- cuál es auxiliar;
- cuál es experimental;
- cuál conserva compatibilidad;
- qué rutas puede escribir cada una;
- qué consumidores tiene;
- qué condición permite retirar una de ellas.

Una implementación no autoritativa no debe escribir sobre rutas productivas
por defecto.

## Incorporación

Antes de incorporar una dependencia o integración, verifica:

1. necesidad real;
2. consumidor conocido;
3. alternativas existentes;
4. compatibilidad con la arquitectura;
5. coste de mantenimiento;
6. licencia;
7. estado de mantenimiento;
8. superficie de ataque;
9. impacto sobre reproducibilidad;
10. impacto sobre instalación y distribución;
11. posibilidad de aislamiento;
12. estrategia de actualización;
13. estrategia de retiro.

Una dependencia no se justifica solo por:

- popularidad;
- comodidad;
- familiaridad;
- reducción de pocas líneas;
- tendencia tecnológica.

La incorporación debe resolver una necesidad identificable sin introducir una
carga desproporcionada.

## Versiones

Toda estrategia de versión debe equilibrar:

- reproducibilidad;
- seguridad;
- compatibilidad;
- mantenimiento;
- capacidad de actualización.

Distingue:

```text
versión declarada
→ restricción del manifest

versión resuelta
→ versión concreta instalada

versión bloqueada
→ versión fijada en lockfile

versión observada
→ versión comprobada en el entorno
```

No asumas que estas versiones coinciden.

Cuando la versión exacta afecte el resultado, registra la versión observada.

## Pinning

Usa pinning cuando sea necesario para:

- reproducibilidad;
- seguridad;
- evitar cambios silenciosos;
- conservar compatibilidad;
- estabilizar CI;
- controlar una migración.

No fijes indefinidamente una versión sin:

- estrategia de revisión;
- evidencia de necesidad;
- vigilancia de seguridad;
- criterio de actualización.

Para acciones de CI/CD, prefiere referencias inmutables cuando la política del
repositorio así lo requiera.

Una etiqueta mutable no demuestra identidad estable del código ejecutado.

## Manifests y lockfiles

Los manifests declaran intención de dependencia.

Los lockfiles registran una resolución concreta.

```text
manifest
≠ lockfile
≠ entorno instalado
```

Cuando cambie un manifest:

- actualiza el lockfile correspondiente;
- revisa dependencias transitivas;
- valida el entorno;
- ejecuta pruebas;
- revisa el diff de resolución.

No edites manualmente un lockfile salvo que la herramienta oficial y el
contrato lo autoricen.

No regeneres lockfiles de forma incidental desde un entorno no controlado.

## Dependencias transitivas

Una dependencia transitiva puede introducir:

- vulnerabilidades;
- incompatibilidades;
- cambios de licencia;
- binarios;
- scripts de instalación;
- acceso de red;
- comportamiento no determinista.

Cuando una dependencia transitiva sea crítica, debe poder identificarse
mediante:

- lockfile;
- reporte;
- árbol de dependencias;
- scanner;
- evidencia reproducible.

No es necesario documentar manualmente cada dependencia transitiva.

Registra las que tengan incidencia real.

## Supply chain

Toda fuente externa relevante debe evaluarse según:

- origen;
- integridad;
- mantenedor;
- canal de distribución;
- firma o hash cuando exista;
- historial de versiones;
- permisos;
- scripts ejecutados;
- proceso de actualización.

No ejecutes código externo no inspeccionado sobre superficies autoritativas
cuando exista un riesgo material.

Cuando se descarguen binarios o artefactos:

- verifica su origen;
- usa canales oficiales;
- conserva versión;
- valida integridad cuando sea posible;
- evita URLs o artefactos ambiguos;
- registra excepciones.

## Seguridad

Evalúa como mínimo:

- vulnerabilidades conocidas;
- permisos;
- ejecución de código;
- acceso a filesystem;
- acceso de red;
- secretos;
- exposición de datos;
- dependencia de servicios externos;
- capacidad de escribir sobre canon o derivados.

Una vulnerabilidad debe clasificarse por su incidencia real sobre TDC.

No declares una dependencia segura solo porque:

- no produjo errores;
- es ampliamente usada;
- está actualizada;
- fue instalada desde un registry conocido.

Cuando exista un riesgo bloqueante:

```text
riesgo no mitigado
→ no promoción

validación insuficiente
→ no escritura productiva
```

## Credenciales y secretos

Las credenciales:

- no deben almacenarse en el repositorio;
- no deben aparecer en logs;
- no deben copiarse a artefactos de sesión;
- no deben incluirse en prompts;
- no deben exponerse en errores;
- deben tener el alcance mínimo necesario.

Usa mecanismos apropiados como:

- variables de entorno;
- secret stores;
- credenciales del runner;
- configuración local ignorada por Git.

La existencia de una variable no demuestra que la autenticación sea válida.

No uses credenciales reales durante dry-runs cuando no sean necesarias.

## Servicios externos

Toda integración externa debe declarar:

- propósito;
- proveedor;
- datos enviados;
- datos recibidos;
- autenticación;
- permisos;
- límites;
- timeout;
- reintentos;
- comportamiento ante indisponibilidad;
- evidencia de ejecución;
- autoridad de la respuesta;
- estrategia local o fallback.

Una respuesta de un servicio externo no adquiere autoridad canónica por sí
misma.

No confundas:

```text
solicitud enviada
≠ solicitud aceptada
≠ operación completada
≠ resultado verificado
```

## Local-first

TDC debe conservar operación local cuando su arquitectura lo permita.

Una superficie externa no debe convertirse silenciosamente en requisito
obligatorio para:

- leer el canon;
- validar artefactos locales;
- ejecutar funciones centrales;
- reconstruir procedencia disponible localmente.

Cuando una función dependa de red, declara:

- razón;
- datos afectados;
- modo de fallo;
- fallback;
- comportamiento offline;
- efecto sobre reproducibilidad.

Remoto es una proyección o dependencia operativa, no autoridad superior por
defecto.

## Workflows y CI/CD

Todo workflow debe tener:

- propósito;
- evento de activación;
- permisos;
- inputs;
- outputs;
- acciones utilizadas;
- superficies leídas;
- superficies escritas;
- secrets requeridos;
- criterio de éxito;
- comportamiento ante fallo.

No otorgues permisos globales cuando basten permisos limitados.

No uses CI como prueba automática de autoridad semántica.

Distingue:

```text
workflow definido
≠ workflow ejecutado
≠ workflow exitoso
≠ resultado publicado
```

Cuando un workflow produzca artefactos, identifica:

- productor;
- versión;
- inputs;
- retención;
- ubicación;
- autoridad;
- verificación posterior.

## Runners

Un runner puede ser:

- local;
- hospedado;
- remoto;
- efímero;
- persistente.

Registra cuando sea relevante:

- sistema operativo;
- arquitectura;
- runtime;
- permisos;
- workspace;
- persistencia;
- red;
- secretos;
- aislamiento.

Crear un archivo dentro de un runner no demuestra que haya llegado a una
superficie externa.

## Reproducibilidad

Una operación que dependa de infraestructura externa debe permitir reconstruir:

- entorno;
- versiones;
- inputs;
- comandos;
- configuración;
- variables no secretas;
- dependencias;
- resultado;
- limitaciones.

La reproducibilidad puede clasificarse como:

- `local`;
- `cross-platform`;
- `runner-specific`;
- `network-dependent`;
- `best-effort`;
- `no_reproducible`.

No declares reproducibilidad cross-platform después de validar un solo entorno.

## Compatibilidad

Cuando una dependencia o toolchain soporte varias plataformas, declara:

- plataformas objetivo;
- plataformas verificadas;
- limitaciones;
- diferencias de comandos;
- paths;
- encoding;
- permisos;
- comportamiento de filesystem.

Distingue:

```text
soportado
→ existe compromiso técnico

verificado
→ fue comprobado

esperado
→ se infiere compatibilidad
```

No presentes compatibilidad esperada como verificada.

## Cambios de dependencia

Todo cambio debe registrar:

- estado anterior;
- estado propuesto;
- razón;
- consumidores;
- archivos afectados;
- riesgo;
- compatibilidad;
- plan de validación;
- impacto en lockfiles;
- impacto en CI/CD;
- rollback;
- estado resultante.

Un cambio es material cuando altera una condición sustantiva del contrato.

La definición y regresión operativa pertenecen a:

```text
.agents/skills/tdc-session/SKILL.md
```

## Validación

Según la superficie afectada, valida:

- instalación limpia;
- resolución de dependencias;
- integridad del lockfile;
- imports;
- CLI;
- tests focales;
- regresión;
- build;
- workflows;
- permisos;
- dry-run;
- comportamiento offline;
- compatibilidad;
- vulnerabilidades;
- reproducibilidad;
- rollback.

No declares validada una dependencia solo porque la instalación terminó.

Toda validación debe relacionarse con un consumidor o riesgo identificado.

## Deprecación

Una dependencia puede deprecarse cuando:

- existe sustituto;
- perdió mantenimiento;
- introduce riesgo;
- no tiene consumidores vigentes;
- duplica una función;
- contradice la arquitectura;
- dificulta reproducibilidad.

La deprecación debe declarar:

- razón;
- reemplazo;
- consumidores;
- periodo o condición de transición;
- compatibilidad;
- riesgo residual;
- criterio de retiro.

Una dependencia deprecada puede seguir activa temporalmente.

Debe quedar explícito.

## Retiro

Antes de retirar una dependencia:

1. confirma consumidores;
2. revisa imports directos e indirectos;
3. revisa workflows y tests;
4. elimina configuración asociada;
5. actualiza manifests y lockfiles;
6. valida instalación limpia;
7. ejecuta regresión;
8. revisa documentación;
9. confirma que no produzca salidas vigentes;
10. registra deuda residual.

No retires una dependencia únicamente porque parezca no usada.

## Implementaciones legacy

El código legacy puede conservarse cuando:

- sostiene compatibilidad;
- permite migración;
- conserva historia operativa;
- todavía tiene consumidores.

Debe declarar:

- estado;
- consumidores;
- superficies de escritura;
- relación con la implementación autoritativa;
- criterio de retiro.

Un componente legacy no debe competir silenciosamente con el pipeline vigente.

## Relación con las sesiones

### Reconocimiento

Identifica:

- dependencias relevantes;
- versiones observadas;
- consumidores;
- autoridad;
- estado;
- riesgos;
- diferencias de entorno;
- superficies externas requeridas.

No modifiques dependencias durante esta instrucción.

### Formulación

El contrato debe delimitar:

- incorporación, actualización o retiro;
- manifests y lockfiles autorizados;
- consumidores afectados;
- tests;
- riesgos;
- rollback;
- autorización humana;
- superficies protegidas.

### Impacto

Registra:

- comandos;
- cambios de versión;
- resolución;
- archivos modificados;
- dependencias transitivas relevantes;
- validaciones;
- fallos;
- diferencias de entorno.

No amplíes el cambio a otras dependencias sin autorización.

### Postimpacto

Determina:

- estado final;
- consumidores reconciliados;
- compatibilidad;
- riesgos residuales;
- deuda;
- reproducibilidad;
- continuidad futura.

No implementes cambios adicionales durante el cierre.

## Relación con los entregables

```text
Procedencia de sesión
→ identifica origen y versión de la dependencia

Diagnóstico de sesión
→ determina su estado y riesgo

Hipótesis de sesión
→ formula comportamientos esperados

Contrato de sesión
→ autoriza el cambio

Sesión
→ registra ejecución y validaciones

Balance de sesión
→ evalúa el resultado

Propuesta de sesión
→ conserva continuidad pendiente
```

Esta instrucción no crea un octavo entregable.

## Canonizabilidad

Una decisión sobre dependencias puede conservarse como memoria canonizable
cuando:

- tiene alcance;
- identifica consumidores;
- declara autoridad y estado;
- conserva procedencia;
- registra riesgo;
- tiene evidencia de validación;
- distingue estado vigente y propuesta.

La dependencia o binario completo no entra necesariamente al canon.

Para candidatas y S66, aplica
`canonical_session_family.instructions.md`.

## Prohibiciones

- No incorpores dependencias sin consumidor conocido.
- No uses popularidad como justificación suficiente.
- No copies manifests o lockfiles como documentación normativa.
- No ocultes dependencias transitivas críticas.
- No regeneres lockfiles incidentalmente.
- No trates una etiqueta mutable como identidad inmutable.
- No almacenes credenciales en el repositorio.
- No expongas secretos en logs o artefactos.
- No confundas ejecución remota con publicación verificada.
- No trates servicios externos como autoridad canónica.
- No declares compatibilidad no comprobada.
- No retires dependencias sin revisar consumidores.
- No permitas que código legacy compita con el pipeline vigente.
- No copies aquí schemas, rutas o compuertas completas de S66.
- No uses esta instrucción como inventario plano.

## Criterio de cumplimiento

La superficie externa está gobernada cuando:

- cada dependencia relevante tiene propósito y consumidor;
- su autoridad y estado son explícitos;
- versiones declaradas y observadas pueden distinguirse;
- manifests, lockfiles y entorno están reconciliados;
- los riesgos de supply chain son visibles;
- credenciales y permisos conservan mínimo privilegio;
- servicios externos tienen comportamiento de fallo;
- CI/CD declara inputs, outputs y superficies;
- la operación puede reproducirse dentro de sus límites declarados;
- código legacy y experimental no compiten silenciosamente;
- actualizaciones y retiros tienen validación y rollback;
- remoto permanece como dependencia o proyección, no como autoridad automática.
````
