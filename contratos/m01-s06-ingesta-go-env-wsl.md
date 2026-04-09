# Registro operativo: Validación toolchain Go en WSL (Sesión S06)
**Sesión:** `m01-s06-ingesta-go-env-wsl`
**Milestone:** `M01 — Extracción e inspección crítica`
**Fecha:** 2026-04-09
**Estado:** registro operativo finalizado (borrador)

---

## 1. Nombre del registro

Validación del toolchain Go en WSL para permitir futuros scaffolds de la Ingesta.

---

## 2. Objetivo

Documentar de forma reproducible las acciones, resultados y artefactos generados durante la sesión técnica dedicada a validar e instalar una versión nativa de `go` en WSL (Ubuntu), sin usar privilegios `sudo`, y sin crear el scaffold productivo de la Ingesta.

---

## 3. Resumen ejecutivo

Se instaló y validó una versión nativa de Go dentro del entorno WSL (Linux) en la ruta de usuario `~/.local/go`. Se aplicaron cambios idempotentes en los archivos de inicio del shell (`~/.bashrc`, `~/.profile`) para exponer el binario en `PATH`. Se verificó la capacidad de inicializar un módulo, ejecutar `go run` y ejecutar tests (`go test`). Se crearon artefactos temporales en `/tmp/tdc-go-env-check` para las pruebas y se limpiaron al finalizar. Se registró la operación en memoria de repositorio.

Resultado clave: `which go` → `/home/ohana_linux/.local/go/bin/go`; `go version` → `go1.24.6 linux/amd64`; `go run` y `go test` sobre un módulo de validación pasaron correctamente.

---

## 4. Contexto y restricciones previas

- Entorno: WSL (Ubuntu) sobre máquina del usuario.
- No había `go` en `PATH` inicialmente en WSL.
- Se detectó una instalación de Go en Windows (`/mnt/c/Program Files/Go/bin/go.exe`) pero no es utilizable como herramienta nativa dentro de WSL.
- No se dispone de `sudo` interactivo no-privilegiado en el entorno (por política de la sesión); por tanto se optó por una instalación local en el espacio de usuario.

---

## 5. Acciones ejecutadas (comandos principales)

Las acciones y comandos ejecutados, en orden aproximado, fueron:

- Inspección inicial: búsqueda de `go` en `PATH` y localización de `go.exe` en el disco de Windows.
- Descarga del tarball oficial de Go (ej. `go1.24.6.linux-amd64.tar.gz`) a `/tmp`.
- Extracción del tarball en `~/.local/go` (instalación en espacio de usuario).
- Añadido idempotente al `PATH` en `~/.bashrc` y `~/.profile` apuntando a `~/.local/go/bin`.
- Creación de un módulo temporal de validación en `/tmp/tdc-go-env-check` con `main.go`, `main_test.go` y `go.mod`.
- `go mod init example.com/tdc-go-env-check`.
- `go run .` → comprobación de ejecución correcta.
- `go test ./... -v` → comprobación de test harness correcta.
- Eliminación de artefactos temporales y del tarball descargado.

Comandos (extracto representativo):

```sh
# ejemplo de comandos ejecutados (resumen)
which go || true
/bin/ls -la "/mnt/c/Program Files/Go/bin/go.exe" || true
wget -O /tmp/go1.24.6.linux-amd64.tar.gz https://golang.org/dl/go1.24.6.linux-amd64.tar.gz
mkdir -p "$HOME/.local"
tar -C "$HOME/.local" -xzf /tmp/go1.24.6.linux-amd64.tar.gz
# añadir idempotentemente $HOME/.local/go/bin al PATH (en ~/.bashrc / ~/.profile)
mkdir -p /tmp/tdc-go-env-check && cd /tmp/tdc-go-env-check
cat > main.go <<'EOF'
package main

import "fmt"

func main() {
    fmt.Println("tdc-go-env-check ok")
}
EOF

cat > main_test.go <<'EOF'
package main

import "testing"

func TestEnvironment(t *testing.T) {}
EOF

go mod init example.com/tdc-go-env-check
go run .
go test ./... -v
cd ~
rm -rf /tmp/tdc-go-env-check
rm -f /tmp/go1.24.6.linux-amd64.tar.gz
```

---

## 6. Salidas y evidencia (capturas relevantes)

- `which go`:

```
/home/ohana_linux/.local/go/bin/go
```

- `go version`:

```
go version go1.24.6 linux/amd64
```

- `go env` (claves relevantes):

```
GOROOT=/home/ohana_linux/.local/go
GOPATH=/home/ohana_linux/go
GOMODCACHE=/home/ohana_linux/go/pkg/mod
GOOS=linux
GOARCH=amd64
```

- `go run .` (salida del binario de validación):

```
tdc-go-env-check ok
```

- `go test ./... -v` (salida resumida):

```
=== RUN   TestEnvironment
--- PASS: TestEnvironment (0.00s)
PASS
ok      example.com/tdc-go-env-check    0.002s
```

---

## 7. Artefactos creados, modificados y limpiados

Creado temporalmente (luego eliminado):

- `/tmp/tdc-go-env-check/main.go` — ejecutable de verificación (ver Anexo).
- `/tmp/tdc-go-env-check/main_test.go` — test minimal para `go test` (ver Anexo).
- `/tmp/tdc-go-env-check/go.mod` — inicializado con `go mod init`.
- `/tmp/go1.24.6.linux-amd64.tar.gz` — tarball de instalación (eliminado luego).

Modificado de forma persistente:

- `~/.local/go/` — nuevos ficheros binarios y estructura de Go (instalación local).
- `~/.bashrc` — añadido bloque idempotente para exponer `$HOME/.local/go/bin` en `PATH`.
- `~/.profile` — añadido bloque idempotente para exponer `$HOME/.local/go/bin` en `PATH`.

Registro en memoria del repositorio:

- `/memories/repo/go-toolchain-wsl.md` — memoria creada para dejar constancia de la validación (registro operativo).

Nota: Los artefactos temporales se eliminaron como parte del procedimiento de limpieza; la instalación en `~/.local/go` quedó como persistente para sesiones futuras.

---

## 8. Fragmento agregado a `~/.bashrc` y `~/.profile`

Se documenta a continuación el bloque idempotente añadido para exponer el binario Go instalado en `~/.local/go/bin` (ejemplo usado en la sesión):

```sh
if [ -d "$HOME/.local/go/bin" ] && [[ ":$PATH:" != *":$HOME/.local/go/bin:"* ]]; then
  export PATH="$HOME/.local/go/bin:$PATH"
fi
```

Este fragmento fue añadido en ambos archivos de inicio para asegurar que las shells de login e interactivas vean el binario.

---

## 9. Problemas encontrados y decisiones técnicas

- No había `go` en WSL; se tomó la decisión deliberada de instalar Go en el espacio de usuario para evitar uso de `sudo` y cambios globales del sistema.
- Se detectó `go.exe` en Windows, pero descartado como solución debido a que no es una herramienta nativa de WSL y puede introducir inconsistencias en `GOROOT`/`GOMODCACHE`.
- Respuesta al problema de permisos: la opción de instalación local permite controles mínimos y es idempotente.
- El scaffold `go/ingesta/` no se creó en esta sesión por decisión deliberada (fuera de alcance de S06). La validación del toolchain es un prerrequisito para el scaffold.

---

## 10. Criterios de aceptación de S06 (verificados)

Se consideran cumplidos los siguientes criterios para esta sesión de validación:

- [x] `go` disponible en `PATH` desde la cuenta de usuario en WSL (`which go` resolvió a `~/.local/go/bin/go`).
- [x] `go version` muestra una versión Linux coherente (`go1.24.6 linux/amd64`).
- [x] Capacidad de inicializar un módulo (`go mod init`) en un directorio temporal sin errores.
- [x] Ejecución de binario con `go run` produce la salida esperada.
- [x] Ejecución de `go test` sobre la validación pasa sin fallos.
- [x] Instalación realizada sin uso de `sudo` y sin modificar paquetes del sistema.

---

## 11. Qué quedó explícitamente fuera de S06

- No se creó el scaffold productivo `go/ingesta/`.
- No se escribió lógica de ingesta ni tests de integración con el repositorio.
- No se hicieron commits en la rama del repositorio para estos cambios de entorno (la rama de trabajo fue creada localmente: `m01-s06-ingesta-go-env-wsl`).

---

## 12. Pendientes y próximos pasos (recomendados)

1. `m01-s07-ingesta-bootstrap`: crear el scaffold minimal `go/ingesta/` en una sesión separada y validar su compilación usando esta toolchain ya instalada.
2. Añadir un fixture `tests/fixtures/raw_tiddlers_minimal.json` y tests de integración que usen la Ingesta scaffold.
3. Revisar y versionar los cambios del entorno (decidir si persistir `~/.local/go` en dotfiles de equipo o documentar como prerequisito para colaboradores).
4. (Opcional) Commitear y push de la documentación creada en `contratos/` y del registro de memoria si el equipo lo aprueba.

---

## 13. Anexos — contenidos usados en la validación

main.go (módulo temporal):

```go
package main

import "fmt"

func main() {
    fmt.Println("tdc-go-env-check ok")
}
```

main_test.go (módulo temporal):

```go
package main

import "testing"

func TestEnvironment(t *testing.T) {}
```

Ejemplo `go.mod` (creado con `go mod init example.com/tdc-go-env-check`):

```
module example.com/tdc-go-env-check

go 1.24
```

---

## 14. Registro de memoria (operación realizada)

Se dejó constancia en la memoria del repositorio en `/memories/repo/go-toolchain-wsl.md` con un resumen de la instalación, versión y comandos básicos para reproducir la validación.

---

## 15. Registro de branch y contexto git

La sesión técnica se ejecutó desde una rama de trabajo creada para este propósito: `m01-s06-ingesta-go-env-wsl` (no se hicieron commits que modifiquen el repositorio de código fuente en esta sesión).

---

## 16. Firma

Operación realizada por el agente técnico durante la sesión S06: validación e instalación del toolchain Go en WSL, según alcance definido por el contrato S05 y los límites operativos acordados.

---

Fin del registro.
