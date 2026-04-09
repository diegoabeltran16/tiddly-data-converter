# Contrato operativo: Ingesta
**Sesión:** `m01-s05-ingesta-contract`
**Milestone:** `M01 — Extracción e inspección crítica`
**Fecha:** 2026-04-09
**Estado:** borrador validado por sesión contractual

---

## 1. Nombre del componente

`Ingesta`

---

## 2. Rol dentro del sistema

**Zona arquitectónica:** `Canon y Reversibilidad`
**Posición en el pipeline:** tercera compuerta de la ruta HTML → Canon, inmediatamente posterior al Doctor y anterior a Canon JSONL.

La Ingesta es el **puente de transformación semántica** entre el artefacto raw validado y el núcleo canónico. Recibe tiddlers crudos (strings planos, campos sin tipado, sin identidad canónica) que ya superaron la auditoría estructural mínima del Doctor, y produce un modelo interno común listo para canonización.

**Ownership técnico dominante:** Go (declarado en `### 🎯 6. Componentes 🌀`).

> **Nota de frontera:** La Ingesta es el primer componente del pipeline que pertenece a la zona `Canon y Reversibilidad`, a diferencia de Extractor y Doctor que pertenecen a `Extracción e Inspección`. Esto marca también la frontera de ownership técnico: Rust produce el artefacto raw validado; Go lo recibe para operar sobre él.

---

## 3. Objetivo del componente

Recibir el artefacto raw validado por el Doctor (`raw.tiddlers.json`), aplicar las transformaciones semánticas mínimas necesarias para producir un modelo interno común tipado, y emitir un reporte de ingesta con un veredicto claro que indique si el artefacto está listo para su canonización.

La Ingesta **sí interpreta semánticamente los campos raw**, a diferencia del Doctor que solo los audita estructuralmente. Sin embargo, **no formaliza el Canon final** ni asigna la serialización determinística: eso pertenece al componente Canon JSONL.

---

## 4. Entrada recibida

| Tipo | Descripción | Obligatoriedad |
|------|-------------|----------------|
| Ruta de archivo local | Ruta al artefacto `raw.tiddlers.json` validado por el Doctor | Obligatoria |
| Metadatos de origen | Indicador del tipo de fuente (`html` / `json`) | Obligatoria |

**Forma esperada de `raw.tiddlers.json`:**

```json
[
  {
    "title": "string",
    "raw_fields": { "...": "..." },
    "raw_text": "string | null",
    "source_position": "string | null"
  }
]
```

> La Ingesta asume que este artefacto ya fue validado por el Doctor. La Ingesta no repite la auditoría estructural mínima del Doctor; confía en su veredicto.

**Precondición:** El `DoctorReport.verdict` fue `Ok` o `Warning` antes de que el Bridge active la Ingesta. Si el Doctor emitió `Error`, la Ingesta no debe invocarse.

---

## 5. Salidas producidas

| Artefacto | Forma | Condición |
|-----------|-------|-----------|
| Modelo interno común | Colección de tiddlers tipados en representación pre-canónica | Siempre que la ingesta pueda completarse |
| `IngestReport` | Estructura con veredicto, conteos, advertencias y errores semánticos | Siempre, incluso ante ingesta parcial recuperable |
| `IngestError` (Err) | Variante de error tipado que detiene el pipeline | Solo ante fallos que impiden toda ingesta |

### Forma de `IngestReport`

```json
{
  "verdict": "ok | warning | error",
  "tiddler_count": 0,
  "ingested_count": 0,
  "skipped_count": 0,
  "warnings": [],
  "errors": []
}
```

**Semántica del veredicto:**

| Veredicto | Significado | Decisión del pipeline |
|-----------|-------------|----------------------|
| `ok` | Todos los tiddlers fueron ingestados al modelo interno sin errores semánticos | Continúa hacia Canon JSONL |
| `warning` | Hay anomalías semánticas no bloqueantes; la ingesta puede continuar | Continúa con advertencias registradas |
| `error` | Hay fallos semánticos bloqueantes que impiden producir un modelo interno confiable | **El pipeline debe detenerse** |

> Un veredicto `error` en `IngestReport` indica que la validación semántica falló de forma irrecuperable. Esto es distinto de un `IngestError` (Err del Result), que indica que el archivo no pudo leerse o que ocurrió un fallo técnico previo a la ingesta.

### Forma del modelo interno común (pre-canónico)

Cada tiddler ingestado se transforma a una estructura tipada que incluye, al menos:

| Campo | Tipo | Origen |
|-------|------|--------|
| `title` | `string` (no vacío) | `raw.title` |
| `fields` | mapa tipado | Parseo de `raw.raw_fields` |
| `text` | `string | null` | `raw.raw_text` |
| `source_position` | `string | null` | Preservado del raw |
| `tags` | `[]string` | Parseo del campo `tags` de `raw_fields` |
| `created` | `timestamp | null` | Parseo del campo `created` de `raw_fields` |
| `modified` | `timestamp | null` | Parseo del campo `modified` de `raw_fields` |
| `type` | `string | null` | `raw_fields["type"]` |
| `origin_format` | `"html" | "json"` | Metadato de origen de la ejecución |

> Esta forma es **provisional**. El shape exacto del modelo interno común debe cerrarse cuando el contrato del Canon JSONL exista, para garantizar compatibilidad de salida. Los campos listados son el mínimo derivable del shape raw actual del Extractor.

---

## 6. Límites formales

La Ingesta **no debe**:

- Serializar el Canon JSONL final ni escribir `canon.jsonl`.
- Asignar UUIDs canónicos estables (UUIDv5); eso pertenece al componente Canon JSONL.
- Ejecutar reverse ni producir HTML de salida.
- Definir consumidores derivados del Canon.
- Sustituir al componente Canon JSONL como fuente de verdad.
- Repetir la auditoría estructural mínima del Doctor.
- Modificar el artefacto raw de entrada.
- Retener estado entre ejecuciones: cada invocación es independiente.
- Absorber lógica de orquestación que corresponda al Bridge.

---

## 7. Invariantes mínimas

1. **No modifica el artefacto raw:** la Ingesta lee `raw.tiddlers.json` y no lo altera.
2. **Siempre hay reporte:** si la ingesta termina (con cualquier resultado), debe existir un `IngestReport` con `verdict` definido.
3. **Veredicto `error` detiene el pipeline:** si `verdict` es `error`, el Bridge no puede autorizar la continuación hacia Canon JSONL.
4. **Determinismo:** el mismo `raw.tiddlers.json` bajo las mismas reglas y metadatos de origen produce el mismo `IngestReport` y la misma colección de tiddlers pre-canónicos.
5. **No contamina Canon:** la Ingesta no escribe directamente en el artefacto `canon.jsonl` ni decide el esquema final del Canon.
6. **Validación semántica, no estructural:** la Ingesta asume que el artefacto raw ya pasó el Doctor. Sus validaciones operan sobre el nivel semántico (tipos, formatos, coherencia de campos) y no sobre la estructura mínima del JSON.
7. **Independencia de ruta:** el componente funciona si la ruta indicada es válida y accesible; no asume ubicación fija del artefacto raw.

---

## 8. Fallos bloqueantes

Los siguientes fallos devuelven `IngestError` y detienen el pipeline antes de producir un `IngestReport`:

| Condición | Código |
|-----------|--------|
| Archivo raw no encontrado en la ruta indicada | `ERR_INGEST_FILE_NOT_FOUND` |
| Archivo raw no legible (permisos, I/O) | `ERR_INGEST_FILE_NOT_READABLE` |
| Archivo raw no es JSON válido (si el Doctor no corrió o fue bypasseado) | `ERR_INGEST_NOT_VALID_JSON` |
| Fallo técnico irrecuperable durante la transformación | `ERR_INGEST_FATAL` |

> A diferencia del Doctor, los errores semánticos de tiddlers individuales no producen `IngestError`. Producen errores dentro del `IngestReport` y afectan el veredicto. Un `IngestError` se reserva para fallos técnicos que impiden toda ingesta.

---

## 9. Casos borde prioritarios

1. **Array vacío `[]`:** produce `IngestReport` con `verdict: ok`, `tiddler_count: 0`, `ingested_count: 0`. Coherente con la política que se decida para el Doctor sobre este caso.
2. **Tiddler con campo `tags` como string (ej. `"[[tag1]] tag2"`):** debe parsearse al formato `[]string` según la convención TiddlyWiki 5. Si falla, se registra como `warning` y el tiddler se ingesta sin tags.
3. **Tiddler con campo `created` o `modified` malformado:** se registra como `warning`; el campo se ingesta como `null` en lugar de causar error bloqueante.
4. **Tiddler con campo `type` ausente:** se tolera; el campo queda como `null`.
5. **Tiddler con `raw_fields` conteniendo JSON-en-string (ej. `tmap.edges = "{}"`):** se preserva como string en `fields`; la Ingesta no intenta parsear valores anidados en esta fase.
6. **Tiddler con `title` que comienza con `$:/`:** se ingesta normalmente; la distinción entre tiddlers de sistema y de usuario no corresponde a la Ingesta.
7. **Campos extra no declarados en el shape pre-canónico:** se preservan en `fields` como strings sin interpretación adicional.
8. **Tiddlers duplicados por `title`:** se registra como `warning`; ambos se ingestan. La deduplicación pertenece al Canon.

---

## 10. Criterios de aceptación de S05

El contrato de la Ingesta se considera aceptable para el cierre de S05 cuando cumpla **todos** los siguientes:

- [ ] Existe un documento contractual versionado (`contratos/m01-s05-ingesta-contract.md`) que define rol, entradas, salidas, límites, invariantes, fallos bloqueantes y casos borde.
- [ ] El contrato separa explícitamente responsabilidades de la Ingesta frente a Doctor y frente a Canon.
- [ ] Los tipos de error (`IngestError`) y la estructura del reporte (`IngestReport`) quedan definidos con suficiente claridad para iniciar implementación.
- [ ] El shape del modelo interno pre-canónico queda declarado como provisional con los campos mínimos derivables del shape raw actual.
- [ ] Las decisiones de alcance (qué sí, qué no) quedan documentadas.
- [ ] El contrato es coherente con la arquitectura (`### 🎯 5. Arquitectura 🌀`), los componentes (`### 🎯 6. Componentes 🌀`) y los contratos previos de Extractor y Doctor.

---

## 11. Scaffold propuesto

```
go/
  ingesta/                             ← módulo Go de la Ingesta (pendiente validación del toolchain Go en WSL)

contratos/
  m01-s05-ingesta-contract.md          ← este documento
```

**Estado del scaffold técnico:**
El scaffold de código Go **no se crea todavía** en esta sesión por dos razones:

1. **Go no está instalado en el entorno WSL actual.** La validación del toolchain Go es un requisito previo análogo a lo que S03 fue para Rust. Crear módulos Go sin poder compilar ni testear reproduce exactamente la fricción que S03 resolvió para Rust.
2. **El contrato es el deliverable de S05.** El scaffold de código corresponde a una sesión de implementación posterior (ej. `m01-s06-ingesta-bootstrap` o equivalente), tal como S02 fue el bootstrap del Extractor después de S01 (contrato).

---

## 12. Qué queda explícitamente fuera de S05

- Implementación de la lógica de ingesta.
- Scaffold de código Go (pendiente validación de toolchain).
- Definición final del shape canónico (pertenece al contrato del Canon JSONL).
- Asignación de UUIDs canónicos estables.
- Serialización determinística a `canon.jsonl`.
- Integración del pipeline completo (Bridge → Extractor → Doctor → Ingesta → Canon).
- Reverse HTML.
- CLI para la Ingesta.
- Deduplicación de tiddlers (pertenece al Canon).
- Validación operativa del toolchain Go en WSL.
- Fixture `raw_tiddlers_minimal.json` validado (puede crearse al inicio de la implementación).
- Cualquier refactor del Extractor o del Doctor.

---

## 13. Decisiones abiertas

| Decisión | Estado | Nota |
|----------|--------|------|
| Shape exacto del modelo interno pre-canónico | Provisional | Depende del contrato del Canon JSONL; los campos §5 son mínimos derivables |
| Validación del toolchain Go en WSL | Pendiente | Requisito previo para scaffold de código; análogo a S03 para Rust |
| Tratamiento de `[]` en Doctor vs Ingesta | Abierta | Debe ser coherente entre ambos componentes; pendiente decisión en Doctor |
| Interfaz inter-proceso Rust → Go | Abierta | File-based (`raw.tiddlers.json`) es suficiente para ahora; pipeline in-memory es futuro |
| Parseo de tags TW5 (`[[tag1]] tag2`) | Provisional | Regla propuesta en §9.2; sujeta a validación contra datos reales |
| Tratamiento de campos `tmap.*` | Diferida | JSON-en-string se preserva; interpretación real corresponde al Canon o posterior |

---
