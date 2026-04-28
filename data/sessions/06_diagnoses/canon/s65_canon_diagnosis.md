# S65 — Diagnóstico de canon

**Sesión:** `m03-s65-microsoft-copilot-execution-surface-and-readme-hardening-v0`  
**Fecha local:** `2026-04-23`  
**Canon auditado:** `data/out/local/tiddlers_*.jsonl`  
**Estado final:** `7` shards, `702` líneas, `strict` y `reverse-preflight` en verde.

## 1. Familia mínima S65 absorbida

| Artefacto | Title canónico | Shard | Línea actual | ID | Tipo |
|---|---|---|---|---|---|
| Sesión S65 | `#### 🌀 Sesión 65 = microsoft-copilot-execution-surface-and-readme-hardening-v0` | `tiddlers_2.jsonl` | `64` | `05396183-29b4-55ad-b2f2-71dd2aa3068a` | `application/json` |
| Hipótesis S65 | `#### 🌀🧪 Hipótesis de sesión 65 = microsoft-copilot-execution-surface-and-readme-hardening-v0` | `tiddlers_3.jsonl` | `68` | `f2fedcf9-8106-57b9-b75c-f0fd9f0333e2` | `application/json` |
| Procedencia S65 | `#### 🌀🧾 Procedencia de sesión 65 = microsoft-copilot-execution-surface-and-readme-hardening-v0` | `tiddlers_4.jsonl` | `73` | `fcfd80f4-ba15-5001-a13f-eed8badc5c2c` | `application/json` |
| Contrato path-like S65 | `contratos/m03-s65-microsoft-copilot-execution-surface-and-readme-hardening-v0.md.json` | `tiddlers_5.jsonl` | `145` | `9a11d57a-d972-55ca-834c-3d1a8c034938` | `text/markdown` |

## 2. Coherencia estructural observada

| Dimensión | Estado final |
|---|---|
| Total de shards | `7` |
| Total de líneas | `702` |
| `tiddlers_1.jsonl` | `64` líneas |
| `tiddlers_2.jsonl` | `64` líneas |
| `tiddlers_3.jsonl` | `68` líneas |
| `tiddlers_4.jsonl` | `73` líneas |
| `tiddlers_5.jsonl` | `145` líneas |
| `tiddlers_6.jsonl` | `144` líneas |
| `tiddlers_7.jsonl` | `144` líneas |

Observaciones:

- La familia S65 no quedó en un solo shard; siguió la distribución ya estabilizada por tipo de nodo:
  - sesión en shard `2`,
  - hipótesis en shard `3`,
  - procedencia en shard `4`,
  - contrato path-like en shard `5`.
- La absorción añadió exactamente el nodo contractual faltante y reescribió las tres líneas S65 existentes para corregir contenido, timestamps y `raw_payload_ref`.

## 3. Reversibilidad preservada

Comandos ejecutados:

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight --mode strict --input ../../data/out/local
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight --mode reverse-preflight --input ../../data/out/local
```

Resultado:

- `STRICT PASSED — 702 line(s) valid`
- `REVERSE-PREFLIGHT PASSED — 702 line(s) ready`

Reverse autoritativo ejecutado:

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/tdc-go-build go run ./cmd/reverse_tiddlers \
  --html ../../data/in/'tiddly-data-converter (Saved).html' \
  --canon ../../data/out/local \
  --out-html ../../data/out/local/reverse_html/tiddly-data-converter.derived.html \
  --report ../../data/out/local/reverse_html/reverse-report.json \
  --mode authoritative-upsert
```

Resultado:

- `Canon lines: 702`
- `Eligible: 659`
- `Already present: 655`
- `Inserted: 4`
- `Rejected: 0`

Implicación: lo añadido por S65 sigue siendo reversible y no rompió ni la validación estricta ni el reverse autoritativo.

## 4. Coherencia con el contrato importable

- El archivo [contratos/m03-s65-microsoft-copilot-execution-surface-and-readme-hardening-v0.md.json](/repositorios/tiddly-data-converter/contratos/m03-s65-microsoft-copilot-execution-surface-and-readme-hardening-v0.md.json:1) existe en disco.
- Su representación canónica quedó absorbida como nodo path-like con `title = contratos/m03-s65-microsoft-copilot-execution-surface-and-readme-hardening-v0.md.json`.
- La sesión, la hipótesis y la procedencia S65 apuntan al contrato correcto dentro de su `text` canónico.

## 5. Deudas abiertas en canon

| Deuda | Estado | Impacto |
|---|---|---|
| `data/out/local/export/` ausente | Warning opcional | No bloquea S65 |
| `data/out/local/proposals.jsonl` ausente | Warning opcional | No bloquea S65; sigue siendo ruta extraordinaria |
| Predominio de `corpus_state` heurístico por ausencia de tags `state:*` / `status:*` explícitos | Histórico | No es regresión de S65; queda para sesión posterior |
