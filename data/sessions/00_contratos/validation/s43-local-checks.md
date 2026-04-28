# S43 Local Checks

## Session

- Session: `m03-s43-canon-robust-textual-reverse-v0`
- Date: `2026-04-16`
- Scope: `bridge`, `canon`, `documentacion`, `reverse`, `ci`, `evidencia-local`

## Commands Executed

### 1. Workspace-root Go check

```bash
cd /repositorios/tiddly-data-converter
env GOCACHE=/tmp/go-build go test ./...
```

Result: `FAIL`

Observed note:

- the repository is organized as a Go workspace without a root module
- from the repository root, `go test ./...` fails with:
  `pattern ./...: directory prefix . does not contain modules listed in go.work or their selected dependencies`
- S43 therefore records the equivalent module-local validation below, which is the effective local coverage of the workspace

### 2. Ingesta tests

```bash
cd /repositorios/tiddly-data-converter/go/ingesta
env GOCACHE=/tmp/go-build go test ./...
```

Result: `PASS`

### 3. Canon tests

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/go-build go test ./...
```

Result: `PASS`

### 4. Bridge tests

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go test ./...
```

Result: `PASS`

### 5. S43 positive fixture: mixed canon and multi-insert

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go test ./... -run TestReverseInsertOnlyHTML_MixedCanonInsertsMultipleRawTiddlers -count=1
```

Result: `PASS`

Observed evidence:

- mixed canon fixture: `tests/fixtures/s43/canon_mixed_multi.jsonl`
- evaluates only raw-tiddler candidates and skips non-raw exported lines
- inserts multiple new textual tiddlers deterministically in canon order
- preserves `source_fields` authority for explicit extra fields

### 6. S43 negative fixture: rejection matrix

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go test ./... -run TestReverseInsertOnlyHTML_RejectsInvalidRawCandidates -count=1
```

Result: `PASS`

Observed evidence:

- negative fixture: `tests/fixtures/s43/invalid_raw_candidates.jsonl`
- covered rejections:
  - reserved key inside `source_fields`
  - invalid `source_tags`
  - system title `$:/...`
  - unsupported type outside S43 textual scope
- existing title present in base is omitted, not overwritten

### 7. Regenerate the current canon from the real HTML base

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go run ./cmd/export_tiddlers \
  --html "../../data/tiddly-data-converter (Saved).html" \
  --out "../../out/tiddlers.jsonl" \
  --manifest "../../out/manifest.json" \
  --log "../../out/export.log"
```

Result: `PASS`

Observed summary:

- exported: `610`
- sha256: `sha256:47a864b3fdb8ab58df580e48bf07986ec92c07f142a47774b2d8f0094cabcc84`

### 8. Build the mixed canon used by S43

```bash
cd /repositorios/tiddly-data-converter
cp out/tiddlers.jsonl out/tiddlers.base.jsonl
cat out/tiddlers.base.jsonl out/s43-raw-tiddlers.jsonl > out/tiddlers.jsonl
```

Result: `PASS`

Observed summary:

- base export preserved in `out/tiddlers.base.jsonl`
- raw additions stored in `out/s43-raw-tiddlers.jsonl`
- mixed canon `out/tiddlers.jsonl` ends with 4 raw-tiddler lines for S43

### 9. Reverse insert-only against the real HTML base

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go run ./cmd/reverse_tiddlers \
  --html "../../data/tiddly-data-converter (Saved).html" \
  --canon "../../out/tiddlers.jsonl" \
  --out-html "../../out/tiddly-data-converter.derived.html" \
  --report "../../out/reverse-report.json" \
  --mode insert-only
```

Result: `PASS`

Observed summary:

- mode: `insert-only`
- store blocks found: `1`
- existing tiddlers: `685`
- canon lines read: `614`
- raw tiddlers evaluated: `4`
- non-raw records skipped: `610`
- inserted: `4`
- already present: `0`
- rejected: `0`
- processed source types:
  - `application/json`: `3`
  - `text/markdown`: `1`
- `source_fields` used: `true`
- `source_fields` candidate count: `4`

### 10. Re-export verification from the derived HTML

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go run ./cmd/export_tiddlers \
  --html "../../out/tiddly-data-converter.derived.html" \
  --out "../../out/roundtrip.tiddlers.jsonl" \
  --manifest "../../out/roundtrip.manifest.json" \
  --log "../../out/roundtrip.export.log"
```

Result: `PASS`

Observed summary:

- exported: `614`
- sha256: `sha256:8c9538080381a799dd8e04995f7933c434925044de70dd7274695ea34a64b910`
- content type counts include:
  - `application/json`: `162`
  - `text/markdown`: `392`
  - `text/plain`: `8`
  - `text/csv`: `1`
  - `text/vnd.tiddlywiki`: `8`

### 11. Round-trip evidence query

```bash
cd /repositorios/tiddly-data-converter
rg -n 'm03-s43-canon-robust-textual-reverse-v0|Sesión 43 = canon-robust-textual-reverse-v0|Hipótesis de sesión 43 = canon-robust-textual-reverse-v0|Procedencia de sesión 43|Existing Alpha|Existing Beta' out/roundtrip.tiddlers.jsonl
```

Result: `PASS`

Observed evidence:

- the round-trip export contains all four S43 insertions at lines `611` to `614`
- the base titles `Existing Alpha` and `Existing Beta` remain present in the round-trip export
- exported S43 lines preserve authoritative `source_type`, `source_tags` and explicit `source_fields` such as `caption`, `list` and `tmap.id`

### 12. CI workspace alignment check

Observed evidence in `.github/workflows/ci.yml`:

- `go-ingesta` now uses `actions/setup-go@v6` with `go-version-file: go.work`
- `go-canon` now uses `actions/setup-go@v6` with `go-version-file: go.work`
- other Go jobs running with the workspace visible were aligned the same way
- no `go.mod` or `go.work` version was downgraded

## Summary

- S43 reverse is local, deterministic and keeps `insert-only`.
- The real HTML base is preserved and only new raw textual tiddlers are appended.
- `source_fields` is supported as controlled optional authority.
- Derived canon fields remain non-authoritative.
- The reverse report is explicit and the real round-trip path is validated locally.
- CI Go jobs were aligned with `go.work`, which removes the previously observed toolchain drift in workspace-aware jobs.
