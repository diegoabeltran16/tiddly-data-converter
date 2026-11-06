# Diseño de datos

TDC separa el **código y las plantillas** de su **estado operacional y conocimiento durable**.

```text
REPOSITORY
<repository-root>/
├── babel/        # material humano, plantillas y superficies publicables
├── docs/         # documentación
├── src/          # código
├── tests/        # pruebas
├── tools/        # herramientas
└── ux/           # recursos de interfaz


WORKSPACE
<workspace-root>/
├── out/          # estado durable y derivados
├── refs/         # material de referencia
└── tmp/          # estado temporal
```

Principios:

```text
REPOSITORY != WORKSPACE
LOCATION != IDENTITY
INVENTORY != CANON
REFS != CANON
DERIVED != AUTHORITY
```

## Babel

`babel/` contiene material orientado al trabajo humano: plantillas, estructuras de conocimiento y otras superficies que TDC puede utilizar o publicar.

```text
babel/<idioma>/
```

La ubicación de un archivo dentro de Babel no lo convierte en Canon.

```text
BABEL != CANON
```

Algunas superficies pueden permanecer locales mediante `.gitignore`; otras pueden publicarse mediante la frontera de publicación de Babel.

## Workspace

El workspace contiene el estado operacional de TDC y puede vivir fuera del repositorio.

```text
<workspace-root>/
├── out/
├── refs/
└── tmp/
```

Su ubicación física se resuelve mediante la gobernanza de rutas.

El código no debe asumir rutas como:

```text
REPOSITORY_ROOT / "data" / ...
```

sino utilizar las capacidades y rutas gobernadas por TDC.

```text
WORKSPACE IDENTITY != WORKSPACE LOCATION
```

## Canon

El Canon representa conocimiento admitido como referencia vigente.

Su almacenamiento pertenece al workspace, no al repositorio.

Conceptualmente:

```text
<workspace-root>/out/local/canon/
```

Guardar, encontrar o derivar un artefacto no equivale a admitirlo:

```text
STORE
!=
VALIDATE
!=
AUTHORIZE
!=
ADMIT
```

## Otras superficies

El workspace puede contener, entre otras:

```text
out/local/
├── canon/
├── sessions/
├── audit/
├── pipeline/
├── inventory/
├── enriched/
├── export/
└── reverse_html/
```

Estas superficies cumplen responsabilidades diferentes.

```text
SESSION != CANON
AUDIT != CANON
DERIVED != CANON
```

`refs/` contiene referencias y `tmp/` contiene estado transitorio. Ninguna adquiere autoridad únicamente por su ubicación.

## Regla general

TDC debe poder mover almacenamiento, cambiar una ruta o generar una nueva representación sin redefinir la identidad del conocimiento.

```text
PATH != IDENTITY
FILESYSTEM LOCATION != AUTHORITY
```

El repositorio conserva aquello que define y desarrolla TDC.

El workspace conserva aquello que TDC opera, gobierna y deriva.
