# Terminal Cat States — v0.1 (semilla UI)

## Razón de la mascota

`tiddly-data-converter` tiene un operador local en terminal (`tdc.sh` →
`operator_menu.py`) que ya funciona bien operativamente. Para darle una
identidad visual propia, coherente y evolutiva, se introduce un gato negro
como mascota del sistema.

El gato no decora el menú: **comunica estado**.
La salida operativa sigue siendo la fuente de evidencia.

Esta regla es no negociable en todas las versiones.

---

## Estados definidos (v0.1)

### `open`

```
 /\_/\
( o_o )
 > ^ <
```

Uso: menú principal en espera de input, estado idle, pausa segura.

### `loading`

```
 /\_/\
( o_o )
 > ^ <

Estado: loading
Accion: <nombre de la acción>
```

Uso: antes de lanzar una operación. Se muestra mientras el proceso
corre (salida capturada). El parpadeo natural (ver sección "Blink")
solo se activa en zonas TTY seguras.

### `success`

```
 /\_/\
( ^_^ )
 > ^ <

Estado: success
<mensaje breve>
```

Uso: operación completada con exit 0 y sin hallazgos bloqueantes.

### `warning`

```
 /\_/\
( o_o )
 > ! <

Estado: warning
<mensaje breve>
```

Uso: operación terminada pero con hallazgos, advertencias o validación
pendiente. No es un fallo pero requiere revisión.

### `error`

```
 /\_/\
( x_x )
 > ^ <

Estado: error
Revisar stderr / salida anterior.
```

Uso: fallo real — exit != 0, validación bloqueante o flujo detenido.

---

## Estado intermedio: `blink`

```
 /\_/\
( -_- )
 > ^ <
```

Solo para animación. No se usa como estado visible por sí mismo.

Ritmo sugerido para loading natural:

```
ojos abiertos: 3.0 s
ojos cerrados: 0.16 s
vuelve a abiertos
```

---

## Regla central (no negociable)

```
La mascota comunica estado.
La salida operativa sigue siendo la fuente de evidencia.
```

El gato nunca reemplaza ni oculta:

- `$ <comando>` — comando ejecutado
- `cwd: <directorio>` — directorio de trabajo
- `exit: <código>` — código de salida
- `stdout:` — salida estándar completa
- `stderr:` — errores completos

El gato aparece **antes** de la operación (loading) y **después** de la
salida (success / warning / error). Nunca en medio.

---

## Regla de animación (zona segura)

El parpadeo solo se permite donde no interfiera con salida activa:

- Espera de input del usuario
- Mientras se ejecuta un subprocess con `capture_output=True`
- Pausas explícitas sin output activo

**Prohibido:**

- Usar `clear` durante ejecución de comandos
- Animar mientras se imprime stdout/stderr en tiempo real
- Mover el cursor mientras hay output activo

---

## Regla de colores

**v0.1: sin colores como requisito funcional.**

El menú debe ser legible en terminales monocromáticas y en modo pipe.
Los colores son un plus futuro, no una dependencia.

---

## Implementación v0.1

### Archivo fuente

`python_scripts/tdc_cat.py`

Funciones exportadas:

| Función | Descripción |
|---|---|
| `tdc_cat_open(label?)` | Estado idle / menú |
| `tdc_cat_loading(action)` | Antes de operación |
| `tdc_cat_success(message?)` | Exit 0, sin bloqueos |
| `tdc_cat_warning(message?)` | Terminado con hallazgos |
| `tdc_cat_error(message?)` | Exit != 0 o fallo real |
| `tdc_cat_loading_start(action)` | Blink con thread daemon (TTY only) |
| `tdc_cat_loading_stop(stop_event)` | Para el blink antes de imprimir output |

### Integración en `operator_menu.py`

- `main_menu()`: `tdc_cat_open()` al inicio de cada iteración del loop
- `option_extract_html()`: loading → output → success/error
- `option_validate_canon()`: loading → output → success/error
- `option_shard_jsonl()`: loading → output → success/warning/error
- `option_reverse()`: loading → output → success/warning/error

---

## Proyección futura hacia Tauri

Esta sesión es la semilla. La gramática visual establecida aquí debe
mantenerse coherente en versiones futuras:

**Estética proyectada:**

- Retro + terminal (base)
- Cyberpunk / solarpunk (acento)
- Morado tipo Ubuntu terminal como color dominante
- Contraste alto estilo Kali/Parrot
- Legibilidad prioritaria, bajo cansancio visual

**Lo que NO cambia al migrar a Tauri:**

- Los 5 estados del gato (mismo significado semántico)
- La regla de no ocultar salidas operativas
- El orden de prioridad de evidencia

**Lo que puede mejorar en Tauri:**

- Animación fluida del gato
- Color y tema
- Panel separado para salida operativa vs estado del gato
- Historial visual de operaciones

---

## Sesión de origen

`S91 = terminal-cat-states-ui-seed` (2026-05-04)

Esta documentación no promete una UI Tauri implementada. Es el contrato
visual mínimo que debe respetarse en toda iteración futura.
