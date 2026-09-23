# Data Layout

TDC separa deliberadamente el código del proyecto de su estado operacional y de conocimiento.

```text
REPOSITORY
<repository-root>/
├── src/
└── data/
    └── in/          # inputs y bootstrap asociados al checkout


WORKSPACE
<workspace-root>/
├── out/             # estado durable gobernado
├── refs/            # material de referencia del workspace
└── tmp/             # estado operacional transitorio
````

La ubicación física del workspace no forma parte de la identidad del conocimiento.

Principios:

```text
CODE LOCATION != WORKSPACE DATA LOCATION
LOCATION != IDENTITY
INVENTORY != CANON
REFS != CANON
DERIVED != AUTHORITY
```

## Workspace root

La ubicación activa del workspace es resuelta por la capa de gobernanza de rutas de TDC.

De forma conceptual:

```text
environment override > persisted workspace configuration > project default
```

El código no debe asumir que el workspace vive dentro del repositorio ni construir rutas operacionales mediante:

```text
REPOSITORY_ROOT / "data" / ...
```

Las superficies operacionales deben resolverse mediante `path_governance.py`.

Entre otras:

```text
WORKSPACE_ROOT
DEFAULT_OUT_DIR
DEFAULT_REFS_DIR
DEFAULT_TMP_DIR
```

Esto permite cambiar la ubicación material del workspace sin redefinir identidad, procedencia o autoridad.

## Repository-owned data

`data/in/` pertenece al checkout del repositorio.

Contiene entradas, plantillas y material de bootstrap cuyo significado está relacionado con la versión del software o con operaciones explícitas de importación.

```text
<repository-root>/data/in/
```

El contenido operacional producido por TDC no debe depender de esta ubicación.

## Workspace-owned data

### `out/`

```text
<workspace-root>/out/
```

Contiene el estado durable producido y gobernado por TDC.

La superficie local principal es:

```text
<workspace-root>/out/local/
```

Puede contener, entre otras familias:

```text
tiddlers_*.jsonl
sessions/
audit/
enriched/
ai/
export/
reverse_html/
pipeline/
microsoft_copilot/
```

La presencia de un artefacto bajo `out/` no implica por sí sola autoridad canónica.

## Canon

El Canon corresponde a los estados admitidos como referencia vigente por TDC.

Su representación operacional principal es:

```text
<workspace-root>/out/local/tiddlers_*.jsonl
```

El Canon no equivale a:

```text
all stored files
all session artifacts
all references
all derived representations
all AI outputs
```

La autoridad canónica depende de las transiciones y contratos de admisión aplicables, no únicamente de la ubicación o formato de un archivo.

## Sessions

```text
<workspace-root>/out/local/sessions/
```

Las sesiones conservan contratos, procedencia, hipótesis, diagnósticos, balances, propuestas y otros artefactos de trabajo.

Pueden producir candidatas para incorporación posterior al Canon, pero no constituyen un Canon paralelo.

Una candidata solo puede adquirir autoridad mediante el flujo de validación y admisión correspondiente.

## References

```text
<workspace-root>/refs/
```

Contiene material de referencia utilizado por TDC.

Las referencias pueden ser importantes, durables y formar parte de procesos de análisis sin adquirir por ello autoridad canónica.

```text
REFS != CANON
```

## Temporary state

```text
<workspace-root>/tmp/
```

Contiene estado operacional temporal, staging, intermediarios de validación y otras superficies de trabajo.

El contenido de `tmp/` no debe utilizarse como fuente durable de autoridad.

Cuando un workflow necesita conservar evidencia más allá de su ejecución, debe producir un artefacto durable bajo una superficie gobernada apropiada.

## Derived representations

TDC puede generar representaciones especializadas para distintos consumidores.

Ejemplos:

```text
<workspace-root>/out/local/reverse_html/
<workspace-root>/out/local/enriched/
<workspace-root>/out/local/ai/
<workspace-root>/out/local/export/
<workspace-root>/out/local/tiddlers-export/
<workspace-root>/out/local/microsoft_copilot/
<workspace-root>/out/local/pipeline/
```

Estas representaciones pueden facilitar búsqueda, análisis, interoperabilidad, recuperación contextual o consumo por herramientas externas.

Su utilidad no las convierte en autoridad.

```text
DERIVED != CANON
```

Cuando sea posible, los derivados deben conservar suficiente procedencia para identificar el estado y las condiciones bajo las cuales fueron generados.

Las representaciones regenerables deberían poder eliminarse y reconstruirse sin pérdida del conocimiento durable subyacente.

## Authority model

Las distintas superficies cumplen responsabilidades diferentes:

| Surface                                | Responsibility                             |
| -------------------------------------- | ------------------------------------------ |
| `data/in/`                             | Inputs y bootstrap asociados al checkout   |
| `workspace/out/local/tiddlers_*.jsonl` | Canon admitido                             |
| `workspace/out/local/sessions/`        | Trabajo de sesión, evidencia y candidatas  |
| `workspace/refs/`                      | Material de referencia                     |
| `workspace/tmp/`                       | Estado operacional transitorio             |
| `workspace/out/local/audit/`           | Evidencia y auditoría durable              |
| derived layers                         | Proyecciones especializadas y regenerables |

Guardar un artefacto no equivale a admitirlo.

```text
STORE
!=
PARSE
!=
INTERPRET
!=
VALIDATE
!=
REVIEW
!=
AUTHORIZE
!=
ADMIT
```

## Material inventory

El inventario material puede observar distintas superficies sin convertirlas en Canon.

La observación del repositorio y la observación del workspace son scopes independientes.

Esto permite que mover una representación fuera del checkout no la vuelva invisible para TDC y evita utilizar Git como definición implícita de aquello que existe materialmente.

```text
INVENTORY != AUTHORITY
```

## Local-first storage

TDC está diseñado para que la ubicación material pueda evolucionar sin redefinir el conocimiento.

Un workspace puede residir, por ejemplo, en:

```text
local Linux filesystem
external filesystem
mounted storage
other governed filesystem location
```

siempre que satisfaga los contratos operacionales correspondientes.

La ubicación concreta es una decisión de despliegue.

```text
WORKSPACE IDENTITY != WORKSPACE LOCATION
```

Los servicios remotos, mirrors o sistemas externos pueden complementar esta arquitectura, pero no deben convertirse implícitamente en la única fuente de autoridad sobre el conocimiento durable.

## Path governance

Los consumidores productivos deben obtener las rutas operacionales desde la gobernanza central de paths.

No deben inferir la ubicación del workspace a partir de:

```text
current working directory
repository location
historical paths
machine-specific absolute paths
```

Un locator durable debería expresar significado dentro del workspace y no depender innecesariamente de una ubicación física específica.

```text
WORKSPACE-RELATIVE LOCATOR
!=
ABSOLUTE PHYSICAL PATH
```

Esta separación permite que código, conocimiento y almacenamiento evolucionen a ritmos diferentes sin perder continuidad.
