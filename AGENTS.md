# AGENTS.md

## Alcance

Estas instrucciones aplican a todo el repositorio
`tiddly-data-converter`.

TDC es una infraestructura local-first de ingeniería del conocimiento con
canon JSONL, derivados, auditoría, trazabilidad y reversibilidad.

Este archivo contiene reglas globales y enruta hacia instrucciones
especializadas. No reemplaza las skills ni `.github/instructions/`.

## Trabajo situado

Antes de modificar el repositorio:

1. inspecciona la rama y el estado de Git;
2. identifica cambios preexistentes;
3. delimita la superficie afectada;
4. lee el `README.md` pertinente;
5. carga solo las instrucciones necesarias.

No leas toda `.github/instructions/` por defecto.

No atribuyas a la tarea cambios que ya existían.

## Propiedad normativa

Cada regla debe tener un único dueño.

- `AGENTS.md` contiene reglas globales y enrutamiento.
- Las skills coordinan flujos reutilizables.
- `.github/instructions/` contiene reglas especializadas.
- Los ejecutables y validadores comprueban resultados.

Cuando una regla especializada sea necesaria:

1. identifica su dueño;
2. lee el archivo correspondiente;
3. aplícala dentro de su alcance;
4. no copies su definición en otro archivo.

Ante una contradicción, aplica la regla más específica y detente si la
autoridad no puede resolverse.

## Enrutamiento

### Sesiones

Para abrir, continuar, implementar, evaluar o cerrar una sesión usa:

`.agents/skills/tdc-session/SKILL.md`

La skill selecciona una sola instrucción ejecutable y su referencia operativa.

### Instrucciones especializadas

Carga únicamente cuando corresponda:

| Superficie | Dueño |
|---|---|
| Metodología de sesión | `.github/instructions/protocolo_de_sesion.instructions.md` |
| Ejecución de sesiones | `.github/instructions/sesiones.instructions.md` |
| Familia, identidad, admisión y S66 | `.github/instructions/canonical_session_family.instructions.md` |
| Schema de sesión | `.github/instructions/tiddlers_sesiones.instructions.md` |
| Procedencia | `.github/instructions/procedencia_epistemologica.instructions.md` |
| Hipótesis | `.github/instructions/hipotesis.instructions.md` |
| Contratos | `.github/instructions/contratos.instructions.md` |
| Continuidad | `.github/instructions/desarrollo_y_evolucion.instructions.md` |
| Recursos concretos | `.github/instructions/elementos_especificos.instructions.md` |
| Tema y vocabulario | `.github/instructions/detalles_del_tema.instructions.md` y `.github/instructions/glosario_y_convenciones.instructions.md` |
| Memoria activa | `.github/instructions/politica_de_memoria_activa.instructions.md` |
| Principios transversales | `.github/instructions/principios_de_gestion.instructions.md` |
| Dependencias externas | `.github/instructions/dependencia_y_superficie_externa.instructions.md` |
| Commits y pull requests | `.github/instructions/PRcommits.instructions.md` |
| Diagnosticos no sesionales | `.github/instructions/diagnosticos_no_sesionales.instructions.md` |

## Reglas globales

- Limita los cambios al objetivo solicitado.
- Conserva arquitectura, vocabulario e identidades vigentes.
- Usa productores, consumidores y validadores autoritativos.
- No alteres trabajo preexistente ajeno.
- No inventes archivos, comandos, resultados o evidencia.
- No declares superada una validación que no ejecutaste.
- No ocultes errores, bloqueos o deuda residual.
- Detente ante falta de autorización o cambio material.
- Evita refactors y limpiezas fuera de alcance.
- No crees pipelines paralelos cuando exista uno autoritativo.
- No agregues dependencias de producción sin autorización.
- No modifiques secretos, credenciales ni archivos `.env`.

## Canon y memoria

- `data/out/local/sessions/` es staging y memoria operativa.
- No lo trates como canon paralelo.
- No escribas directamente en el canon por defecto.
- No declares admitida una candidata por su existencia.
- Git no determina autoridad canónica.
- Cuando una tarea afecte candidatas, admisión o canon, aplica la gobernanza
  definida en `canonical_session_family.instructions.md`.

## Git y superficies externas

No ejecutes sin solicitud explícita:

- `git add`;
- `git commit`;
- `git push`;
- apertura de pull request;
- operaciones externas mutantes.

Usa dry-run, preflight, respaldo y rollback cuando correspondan.

## Validación

Después de modificar:

- ejecuta pruebas focales;
- ejecuta regresiones relacionadas cuando apliquen;
- valida formatos, schemas, rutas e identificadores afectados;
- revisa el diff completo;
- registra comandos, resultados y fallos.

Cuando una validación no pueda ejecutarse, declara la razón, el riesgo y el
pendiente.

## Salida

Al terminar, informa:

- trabajo realizado;
- archivos afectados;
- validaciones ejecutadas;
- resultados y fallos;
- bloqueos y pendientes;
- siguiente acción habilitada.

Cuando la tarea pertenezca a una sesión, aplica además la salida definida por
la skill activa.
