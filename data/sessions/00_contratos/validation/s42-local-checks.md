# S42 Local Checks

## Session

- Session: `m02-s42-canon-minimal-deterministic-reverse-v0`
- Date: `2026-04-16`
- Scope: `bridge`, `reverse`, `canon`, `documentacion`, `evidencia-local`

## Commands Executed

### 1. Canon tests

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/go-build go test ./... -count=1
```

Result: `PASS`

### 2. Bridge tests

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go test ./... -count=1
```

Result: `PASS`

### 3. Negative collision test

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go test ./... -run TestReverseInsertOnlyHTML_RejectsCollision -count=1
```

Result: `PASS`

Observed negative evidence:

- fixture `tests/fixtures/s42/canon_with_collision.jsonl`
- reverse rejects the existing title with `existing-title-conflict`

### 4. Regenerate the current canon from the real HTML base

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

- extracted: `672`
- included: `597`
- excluded: `75`
- exported: `597`
- sha256: `sha256:6b5bfec440914ab275543999c1dbd193d8991c4b4e72bac51816d318a716c854`

### 5. Build the augmented canon for S42

```bash
cd /repositorios/tiddly-data-converter
cp out/tiddlers.jsonl out/s42-canon-augmented.jsonl
printf '\n%s\n' '{"schema_version":"v0","key":"#### 🌀 Sesión 42 = canon-minimal-deterministic-reverse-v0","title":"#### 🌀 Sesión 42 = canon-minimal-deterministic-reverse-v0","text":"## S42\n\nReverse mínimo controlado desde canon hacia HTML reabrible.","created":"20260416120000000","modified":"20260416121000000","source_type":"text/vnd.tiddlywiki","source_tags":["session:m02-s42","milestone:m02","topic:reverse"]}' >> out/s42-canon-augmented.jsonl
```

Observed note:

- the regenerated JSONL does not end with a final newline, so the explicit leading `\n` is required to append a real new line
- appended S42 line observed at `out/s42-canon-augmented.jsonl:599`

### 6. Reverse insert-only against the real HTML base

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go run ./cmd/reverse_tiddlers \
  --html "../../data/tiddly-data-converter (Saved).html" \
  --canon "../../out/s42-canon-augmented.jsonl" \
  --out-html "../../out/tiddly-data-converter.reversed.html" \
  --report "../../out/s42-reverse-report.json"
```

Result: `PASS`

Observed summary:

- mode: `insert-only`
- store blocks found: `1`
- canon lines read: `598`
- already present: `554`
- excluded: `43`
- inserted: `1`
- rejected: `0`

Observed interpretation:

- `43` entries were excluded explicitly because they are outside the S42 textual reverse subset, mainly binary PNG nodes
- no critical collision remained after regenerating the canon from the current HTML base

### 7. Re-export verification from the reversed HTML

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go run ./cmd/export_tiddlers \
  --html "../../out/tiddly-data-converter.reversed.html" \
  --out "../../out/roundtrip.tiddlers.jsonl" \
  --manifest "../../out/roundtrip.manifest.json" \
  --log "../../out/roundtrip.export.log"
```

Result: `PASS`

Observed summary:

- extracted: `673`
- included: `598`
- excluded: `75`
- exported: `598`
- sha256: `sha256:f4805341c0890c8f4e5fb038d26443e741a9b7e755969b5473db35cb317de07a`

### 8. Round-trip evidence query

```bash
cd /repositorios/tiddly-data-converter
rg -n 'Sesión 42 = canon-minimal-deterministic-reverse-v0|session:m02-s42|Reverse mínimo controlado desde canon hacia HTML reabrible' out/roundtrip.tiddlers.jsonl
```

Result: `PASS`

Observed evidence:

- the inserted tiddler reappears as line `598`
- the round-trip line preserves:
  - `title`
  - `text`
  - `created`
  - `modified`
  - `source_type`
  - `source_tags`

## Summary

- S42 reverse works locally in deterministic `insert-only` mode.
- Existing tiddlers are not rewritten.
- Out-of-scope nodes are excluded explicitly, not silently.
- Critical collisions remain fatal and are covered by fixture test.
- The real round-trip path `canon -> reverse -> HTML -> re-export` is verified with the S42 session tiddler.
