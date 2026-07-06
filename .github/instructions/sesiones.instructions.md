# Plantilla de instruccion de sesion para agentes

## tiddly-data-converter — cierre por `data/out/local/sessions/`, candidatos canonicos y admision local reversible

---

## 0. Contexto minimo de la sesion

- **Sesion:** `mXX-sNN-<slug-de-la-sesion>`
- **Modo:** `local`
- **Repositorio:** `tiddly-data-converter`
- **Objetivo principal:** `<describir aqui el objetivo puntual de la sesion>`
- **Restriccion principal:** `<anotar aqui la restriccion mas importante si existe>`

Frase rectora por defecto:

> `data/out/local/sessions/` registra y ordena la memoria operativa de cada sesion; el canon conserva la autoridad final. El agente puede producir lineas candidatas, pero solo la validacion local, el strict check, el reverse sin rechazo y las pruebas de validacion JSONL y de estructura canonica permiten absorberlas al canon.

---

## 1. Layout operativo vigente

La sesion debe asumir como verdad operativa este layout:

- `data/out/local/sessions/` = superficie versionable de entrega, trazabilidad, staging y cierre operativo de sesiones.
- `data/in/` = entradas locales, incluido el HTML vivo.
- `data/out/local/` = canon local, derivados locales y reverse.
- `data/out/remote/` = proyeccion o intercambio remoto preparado, no autoritativo.
- `data/out/local/reverse_html/` = salida HTML de reverse y sus reportes.

Reglas centrales:

| Categoria | Ruta | Rol |
|---|---|---|
| Canon (fuente de verdad) | `data/out/local/tiddlers_*.jsonl` | Fuente de verdad local cuando existe en la maquina |
| Staging de sesion | `data/out/local/sessions/` | No es canon paralelo; no compite con el canon |
| Artefacto legado | `data/out/local/proposals.jsonl` | Solo extraordinario; no es ruta diaria de cierre |
| Capas derivadas | `enriched/`, `ai/`, `audit/`, `export/`, `microsoft_copilot/` | Derivadas del canon; no son fuente de verdad |
| Reverse | `data/out/local/reverse_html/` | Salida de reverse; no es canon |
| Remoto | `data/out/remote/` | No habilita integracion cloud productiva por si sola |

---

## 2. Capa normativa activa minima

Antes de ejecutar cambios, leer integramente, respetar y usar como normativa activa de la sesion:

- `.github/instructions/contratos.instructions.md`
- `.github/instructions/PRcommits.instructions.md`, si la sesion toca commits o PR
- `.github/instructions/canonical_session_family.instructions.md`
- `.github/instructions/tiddlers_sesiones.instructions.md`
- `esquemas/canon/canon_guarded_session_rules.md`
- `esquemas/canon/derived_field_rules.md`
- `README.md`
- `data/README.md`, si existe en local
- contratos, artefactos de `data/out/local/sessions/` o reportes previos directamente relevantes al objetivo
- shards canonicos pertinentes dentro de `data/out/local/tiddlers_*.jsonl`, solo cuando el objetivo requiera leer canon

Tratamiento obligatorio:

- considerar estos artefactos normativa activa;
- priorizar la lectura situada sobre la lectura indiscriminada;
- expandirse solo hacia contexto con impacto real sobre el objetivo local.

Si la sesion toca dependencias, toolchains, CI/CD, supply chain, librerias, seguridad o superficie externa, leer ademas los nodos y contratos de dependencias que ya existan y sean pertinentes.

---

## 3. Autoridad del canon y responsabilidad del agente

El canon local sigue mandando, pero el agente no escribe directamente en el canon final por defecto.

Permitido por defecto:

- leer `data/out/local/tiddlers_*.jsonl`;
- derivar diagnostico desde canon;
- producir artefactos de sesion bajo `data/out/local/sessions/`;
- producir lineas candidatas en formato canon bajo `data/out/local/sessions/`.

Prohibido por defecto:

- modificar directamente `data/out/local/tiddlers_*.jsonl`;
- declarar admitida una linea candidata que no paso validacion local suficiente;
- usar `git add`, `git commit` o `git push` como mecanismo de admision canonica.

Excepcion:

- una sesion puede modificar canon final solo si el usuario autoriza explicitamente admision local y si pasan las compuertas requeridas. Si algo falla, no se modifica el canon.

---

## 4. Nota de cumplimiento S66

La familia mínima, rutas oficiales, convención `#### 🌀`, numeración de 4 dígitos,
líneas candidatas y compuertas de admisión se definen en
`.github/instructions/canonical_session_family.instructions.md`.

Este archivo solo gobierna cómo conducir la sesión: leer lo necesario, actuar
sobre el objetivo local, registrar evidencia y cerrar sin inventar familias,
rutas, numeración ni formatos alternos.

---

## 5. Balance de sesion

El balance de sesion no es comentario informal. Es memoria operativa de aprendizaje del proyecto.

Debe contener esta estructura base:

```md
## Balance de sesion

- aciertos:
  - ...

- errores:
  - ...

- decisiones_a_conservar:
  - ...

- riesgos_detectados:
  - ...

- ajustes_sugeridos:
  - ...

- impacto_en_proxima_sesion:
  - ...
```

Su funcion es reducir errores repetidos, conservar decisiones correctas y preparar la siguiente sesion.

---

## 6. Diagnosticos

El diagnostico de sesion es obligatorio por defecto.

Diagnosticos especializados posibles, solo bajo solicitud explicita o cuando la instruccion de sesion lo requiera:

- diagnostico de canon;
- diagnostico de derivados;
- diagnostico de hipotesis;
- diagnostico de modulo;
- diagnostico de proyecto;
- diagnostico de repositorio;
- diagnostico de reverse;
- diagnostico de tema.

No inflar el cierre con diagnosticos especializados si no aportan al objetivo declarado.

---

## 7. Lineas candidatas en formato canon

Usar la definición completa de `.github/instructions/canonical_session_family.instructions.md`.
Durante la conducción de sesión, registrar si se produjeron candidatas, dónde
quedaron y qué validación se ejecutó o quedó pendiente.

---

## 8. Admision local al canon

La admisión local se define en `.github/instructions/canonical_session_family.instructions.md`.
En esta plantilla, el agente solo debe dejar evidencia de si la sesión quedó en
staging, si hubo candidatos y si la admisión fue explícitamente autorizada o no.

---

## 9. Validacion

Las compuertas de admisión pertenecen a `.github/instructions/canonical_session_family.instructions.md`.
Aquí solo aplica la regla operativa: ejecutar comandos reales cuando existan y
registrar en el diagnóstico qué pasó, qué no se ejecutó, por qué y qué falta.

---

## 10. Flujo operativo cuando la sesion toca export o reverse

### 10.1 Exportacion

Flujo correcto:

1. `export_tiddlers` desde `go/bridge` para producir un JSONL temporal.
2. `shard_canon` desde `go/canon` para escribir una copia canonica local cuando la operacion este autorizada.
3. `canon_preflight --mode strict` para validar el canon local o temporal.

### 10.2 Reverse

Flujo correcto:

1. `canon_preflight --mode reverse-preflight` sobre canon local o temporal.
2. `reverse_tiddlers` desde `go/bridge`.
3. salida en `data/out/local/reverse_html/` cuando se trabaja sobre canon local autorizado, o `/tmp` cuando se valida una copia temporal.

Regla:

- `reverse_tiddlers` nunca debe tratarse como escritor del canon.

---

## 11. Lo que el agente debe hacer

1. entender el objetivo puntual de la sesion;
2. inspeccionar el estado real del repositorio;
3. detectar rutas y artefactos implicados;
4. modificar, mover o crear solo lo necesario;
5. respetar la arquitectura vigente;
6. producir la familia minima bajo `data/out/local/sessions/`;
7. producir diagnostico de sesion;
8. producir lineas candidatas si la sesion genera memoria que debe poder entrar al canon;
9. validar con comandos reales cuando existan;
10. dejar evidencia clara de lo que paso, lo que no paso y lo pendiente.

---

## 12. Lo que el agente no debe hacer

1. reabrir decisiones cerradas sin razon tecnica fuerte;
2. crear archivo acumulativo global de sesiones;
3. convertir `data/out/local/sessions/` en canon paralelo;
4. usar `data/out/local/proposals.jsonl` como cierre diario;
5. insertar lineas en canon final por defecto;
6. declarar lineas admitidas sin `strict`, `reverse-preflight` y reverse autoritativo sin rechazo;
7. inventar rutas, relaciones o clasificaciones no sustentadas;
8. declarar integracion cloud productiva viva si no existe;
9. tratar `data/out/remote/` como fuente de verdad;
10. declarar exito sin familia minima, diagnostico y evidencia de validacion.

---

## 13. Contenido minimo del contrato

El contrato en `data/out/local/sessions/00_contratos/` debe contener como minimo:

- identidad de la sesion;
- objetivo real;
- alcance;
- archivos o rutas implicadas;
- restricciones y riesgos;
- decisiones tomadas;
- validaciones esperadas;
- resultado final esperado;
- lo que no se hizo o quedo fuera, si aplica.

Seleccionar la familia documental correcta:

- contrato operativo;
- registro o reporte operativo;
- reporte de politica o decision tecnica.

---

## 14. Salida final obligatoria del agente

### A. Trabajo realizado

- que hizo exactamente.

### B. Archivos afectados

- que archivos modifico;
- que archivos creo;
- que archivos no toco por restriccion.

### C. Validacion

- que tests ejecuto;
- que verificaciones corrio;
- si pasaron o no;
- que quedo pendiente y por que.

### D. Cierre de sesion

- path del contrato de sesion;
- path de procedencia, detalles, hipotesis, balance, propuesta y diagnostico;
- path de lineas candidatas si existen.

### E. Estado canonico

- confirmar si hubo o no lineas candidatas;
- confirmar si hubo o no absorcion local al canon;
- confirmar si el reverse autoritativo reporto `Rejected: 0` cuando se ejecuto admision temporal o canonica;
- no declarar admision canonica si no hubo validacion suficiente.
