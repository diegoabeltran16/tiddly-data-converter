# Plantilla de instruccion de sesion para agentes

## tiddly-data-converter — cierre por `data/sessions/`, candidatos canonicos y admision local reversible

---

## 0. Contexto minimo de la sesion

- **Sesion:** `mXX-sNN-<slug-de-la-sesion>`
- **Modo:** `local`
- **Repositorio:** `tiddly-data-converter`
- **Objetivo principal:** `<describir aqui el objetivo puntual de la sesion>`
- **Restriccion principal:** `<anotar aqui la restriccion mas importante si existe>`

Frase rectora por defecto:

> `data/sessions/` registra y ordena la memoria operativa de cada sesion; el canon conserva la autoridad final. El agente puede producir lineas candidatas, pero solo la validacion local, el strict check, el reverse sin rechazo y las pruebas permiten absorberlas al canon.

---

## 1. Layout operativo vigente

La sesion debe asumir como verdad operativa este layout:

- `data/sessions/` = superficie versionable de entrega, trazabilidad, staging y cierre operativo de sesiones.
- `data/in/` = entradas locales, incluido el HTML vivo.
- `data/out/local/` = canon local, derivados locales y reverse.
- `data/out/remote/` = proyeccion o intercambio remoto preparado, no autoritativo.
- `data/out/local/reverse_html/` = salida HTML de reverse y sus reportes.

Reglas centrales:

- `data/out/local/tiddlers_*.jsonl` es la fuente de verdad local cuando existe en la maquina.
- `data/sessions/` no es canon paralelo y no compite con `data/out/local/tiddlers_*.jsonl`.
- `data/out/local/proposals.jsonl` queda como artefacto legado o extraordinario, no como ruta diaria de cierre.
- `data/out/local/enriched/`, `data/out/local/ai/`, `data/out/local/audit/`, `data/out/local/export/` y `data/out/local/microsoft_copilot/` son capas derivadas.
- `data/out/local/reverse_html/` no es canon.
- `data/out/remote/` no habilita integracion cloud productiva por si sola.

---

## 2. Capa normativa activa minima

Antes de ejecutar cambios, leer integramente, respetar y usar como normativa activa de la sesion:

- `.github/instructions/contratos.instructions.md`
- `.github/instructions/PRcommits.instructions.md`, si la sesion toca commits o PR
- `.github/instructions/tiddlers_sesiones.instructions.md`
- `esquemas/canon/canon_guarded_session_rules.md`
- `esquemas/canon/derived_field_rules.md`
- `README.md`
- `data/README.md`, si existe en local
- contratos, artefactos de `data/sessions/` o reportes previos directamente relevantes al objetivo
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
- producir artefactos de sesion bajo `data/sessions/`;
- producir lineas candidatas en formato canon bajo `data/sessions/`.

Prohibido por defecto:

- modificar directamente `data/out/local/tiddlers_*.jsonl`;
- declarar admitida una linea candidata que no paso validacion local suficiente;
- usar `git add`, `git commit` o `git push` como mecanismo de admision canonica.

Excepcion:

- una sesion puede modificar canon final solo si el usuario autoriza explicitamente admision local y si pasan las compuertas requeridas. Si algo falla, no se modifica el canon.

---

## 4. Familia minima obligatoria de cierre de sesion

Toda sesion debe cerrar con un archivo propio por sesion y por familia de artefacto:

1. contrato de sesion;
2. procedencia de sesion;
3. detalles de sesion;
4. hipotesis de sesion;
5. balance de sesion;
6. propuesta de sesion;
7. diagnostico de sesion.

Rutas preferidas:

```text
data/sessions/00_contratos/<session>.md.json
data/sessions/01_procedencia/<session>.md.json
data/sessions/02_detalles_de_sesion/<session>.md.json
data/sessions/03_hipotesis/<session>.md.json
data/sessions/04_balance_de_sesion/<session>.md.json
data/sessions/05_propuesta_de_sesion/<session>.md.json
data/sessions/06_diagnoses/sesion/<session>.md.json
```

Convencion de titulo:

- todos los tiddlers producidos como resultado de sesion deben tener un `title` que empiece por `#### 🌀`;
- procedencia de sesion: `#### 🌀🧾 Procedencia de sesión ## = <session>`;
- detalles/sesion: `#### 🌀 Sesión ## = <session>`;
- hipotesis de sesion: `#### 🌀🧪 Hipótesis de sesión ## = <session>`;
- las demas familias deben conservar el mismo prefijo `#### 🌀` y nombrar su familia de cierre de forma explicita.

Reglas:

- no crear archivo acumulativo global de sesiones;
- no usar un archivo por cada linea individual salvo convencion explicita;
- no mover ni renombrar carpetas existentes sin justificacion explicita;
- respetar el orden logico: contrato -> procedencia -> detalles -> hipotesis -> balance -> propuesta -> diagnostico.

En el estado actual del repositorio pueden existir subcarpetas historicas en ingles bajo `data/sessions/06_diagnoses/` (`project`, `module`). No crear variantes nuevas si la ruta real ya existe; documentar la ruta real usada.

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

Cuando la sesion produzca memoria que deba poder entrar al canon, el agente debe dejar lineas candidatas en formato canon bajo `data/sessions/`.

Las lineas candidatas deben:

- ser JSONL valido;
- respetar la estructura interna exigida por el canon;
- tener identificacion estable;
- tener `title` o `key` coherente con la convencion del proyecto;
- declarar sesion de origen;
- declarar familia de artefacto;
- declarar procedencia;
- apuntar al archivo fuente bajo `data/sessions/`;
- poder pasar `strict`;
- poder pasar `reverse-preflight`;
- poder ser procesadas por reverse autoritativo sin rechazo;
- no reclamar autoridad final si aun no fueron absorbidas al canon.

No inventar campos nuevos si el canon ya tiene campos equivalentes. Si se agregan campos de trazabilidad en `source_fields`, deben ser no reservados por reverse y quedar justificados en el informe tecnico o en el diagnostico de sesion.

---

## 8. Admision local al canon

La admision al canon debe ocurrir localmente porque el canon bajo `data/out/` es salida local ignorada por Git.

Flujo recomendado:

1. El agente produce artefactos en `data/sessions/`.
2. El agente produce lineas candidatas en formato canon bajo `data/sessions/`.
3. Un proceso local o manual toma esas lineas.
4. El proceso copia el canon actual a una zona temporal.
5. Inserta las lineas candidatas en esa copia temporal.
6. Ejecuta validaciones.
7. Ejecuta verificacion de reversibilidad.
8. Si todo pasa, aplica los cambios al canon local.
9. Si algo falla, no modifica el canon.

No crear automatizaciones complejas salvo que la sesion lo pida o exista un script equivalente que solo requiera ajuste menor.

---

## 9. Compuertas minimas antes de admitir lineas

Ninguna linea candidata debe considerarse admitida al canon hasta pasar, como minimo:

1. validacion JSONL;
2. validacion de estructura canonica;
3. validacion de campos obligatorios;
4. validacion de identificadores;
5. validacion de procedencia;
6. validacion de relaciones si aplica;
7. canon strict;
8. reverse-preflight;
9. reverse autoritativo sin `rejected`;
10. tests existentes relacionados con canon, reverse y derivados.

Comandos reales disponibles:

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode strict \
  --input <canon-temporal-o-jsonl>
```

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode reverse-preflight \
  --input <canon-temporal-o-jsonl>
```

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/tdc-go-build go run ./cmd/reverse_tiddlers \
  --html ../../data/in/'tiddly-data-converter (Saved).html' \
  --canon <canon-temporal> \
  --out-html /tmp/<session>.reverse.html \
  --report /tmp/<session>.reverse-report.json \
  --mode authoritative-upsert
```

Si `reverse_tiddlers` reporta `Rejected: 0`, la compuerta de reversibilidad pasa para esa copia temporal. Si reporta `rejected > 0` o termina con error, la linea candidata no esta admitida.

Tests utiles segun alcance:

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go test ./... -count=1
```

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/tdc-go-build go test ./... -count=1
```

```bash
python3 python_scripts/validate_corpus_governance.py \
  --canon-dir data/out/local \
  --ai-dir data/out/local/ai
```

Si un comando real no existe o no puede ejecutarse, no inventarlo. Registrar en el diagnostico: que no se ejecuto, por que, que falta y que debe hacer la siguiente sesion.

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
6. producir la familia minima bajo `data/sessions/`;
7. producir diagnostico de sesion;
8. producir lineas candidatas si la sesion genera memoria que debe poder entrar al canon;
9. validar con comandos reales cuando existan;
10. dejar evidencia clara de lo que paso, lo que no paso y lo pendiente.

---

## 12. Lo que el agente no debe hacer

1. reabrir decisiones cerradas sin razon tecnica fuerte;
2. crear archivo acumulativo global de sesiones;
3. convertir `data/sessions/` en canon paralelo;
4. usar `data/out/local/proposals.jsonl` como cierre diario;
5. insertar lineas en canon final por defecto;
6. declarar lineas admitidas sin `strict`, `reverse-preflight` y reverse autoritativo sin rechazo;
7. inventar rutas, relaciones o clasificaciones no sustentadas;
8. declarar integracion cloud productiva viva si no existe;
9. tratar `data/out/remote/` como fuente de verdad;
10. declarar exito sin familia minima, diagnostico y evidencia de validacion.

---

## 13. Contenido minimo del contrato

El contrato en `data/sessions/00_contratos/` debe contener como minimo:

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
