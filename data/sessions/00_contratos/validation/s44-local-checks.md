# S44 Local Checks

## Session

- Session: `m03-s44-canon-sharded-homogeneous-records-and-robust-reverse-v0`
- Date: `2026-04-17`
- Scope: `canon`, `reverse`, `shards`, `documentacion`, `evidencia-local`

## Commands Executed

### 1. Ingesta tests

```bash
cd /repositorios/tiddly-data-converter/go/ingesta
env GOCACHE=/tmp/go-build go test ./... -count=1
```

Result: `PASS`

### 2. Canon tests

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/go-build go test ./... -count=1
```

Result: `PASS`

Observed note:

- includes the new shard-aware loader, shard preflight and `shard_canon` helper

### 3. Bridge tests

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go test ./... -count=1
```

Result: `PASS`

Observed note:

- includes shard-directory reverse and `authoritative-upsert` coverage

### 4. Canon source strict preflight on the authoritative shard set

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/go-build go run ./cmd/canon_preflight --input ../../out --mode strict
```

Result: `PASS`

Observed summary:

- canon source: `../../out`
- shard count: `7`
- lines read: `621`
- strict valid: `621`

### 5. Reverse preflight on the authoritative shard set

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/go-build go run ./cmd/canon_preflight --input ../../out --mode reverse-preflight
```

Result: `PASS`

Observed summary:

- lines read: `621`
- reverse ready: `621`
- not ready: `0`

### 6. Shard layout and repaired/new record placement

```bash
cd /repositorios/tiddly-data-converter
wc -l out/tiddlers_1.jsonl out/tiddlers_2.jsonl out/tiddlers_3.jsonl out/tiddlers_4.jsonl out/tiddlers_5.jsonl out/tiddlers_6.jsonl out/tiddlers_7.jsonl
python3 - <<'PY'
import json
checks = [
  ('out/tiddlers_2.jsonl', [
    '#### 🌀 Sesión 19 = canon-jsonl-gate-v0',
    '#### 🌀 Sesión 20 = canon-gate-e2e-smoke',
    '#### 🌀 Sesión 21 = canon-gate-acceptance-matrix',
    '#### 🌀 Sesión 22 = canon-gate-ci-integration',
    '#### 🌀 Sesión 44 = canon-sharded-homogeneous-records-and-robust-reverse-v0',
  ]),
  ('out/tiddlers_3.jsonl', [
    '#### 🌀🧪 Hipótesis de sesión 44 = canon-sharded-homogeneous-records-and-robust-reverse-v0',
  ]),
  ('out/tiddlers_4.jsonl', [
    '#### 🌀🧾 Procedencia de sesión 44',
  ]),
]
for path, titles in checks:
    seen = {}
    with open(path, encoding='utf-8') as f:
        for lineno, line in enumerate(f, 1):
            obj = json.loads(line)
            title = obj.get('title')
            if title in titles:
                seen[title] = (
                    lineno,
                    obj.get('content_type'),
                    obj.get('modality'),
                    obj.get('role_primary'),
                    obj.get('source_type'),
                )
    print(path)
    for title in titles:
        print(title, seen[title])
PY
```

Result: `PASS`

Observed summary:

- shard counts: `44 / 44 / 48 / 53 / 144 / 144 / 144`
- repaired main session S19 now lives at `out/tiddlers_2.jsonl:19`
- repaired main session S20 now lives at `out/tiddlers_2.jsonl:20`
- repaired main session S21 now lives at `out/tiddlers_2.jsonl:21`
- repaired main session S22 now lives at `out/tiddlers_2.jsonl:22`
- new S44 session now lives at `out/tiddlers_2.jsonl:44`
- new S44 hypothesis now lives at `out/tiddlers_3.jsonl:48`
- new S44 provenance now lives at `out/tiddlers_4.jsonl:43`
- all repaired/new records above are `content_type=application/json`, `modality=metadata`, `role_primary=config`, `source_type=application/json`

### 7. Reverse from authoritative shards

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go run ./cmd/reverse_tiddlers \
  --html "../../data/tiddly-data-converter (Saved).html" \
  --canon ../../out \
  --out-html ../../out/tiddly-data-converter.derived.html \
  --report ../../out/reverse-report.json \
  --mode authoritative-upsert
```

Result: `PASS`

Observed summary:

- mode: `authoritative-upsert`
- store blocks: `1`
- canon lines: `621`
- eligible: `578`
- out-of-scope skipped: `43`
- already present: `571`
- inserted: `3`
- updated: `4`
- rejected: `0`
- source fields used: `true (578 candidates)`
- report: `out/reverse-report.json`
- output html: `out/tiddly-data-converter.derived.html`

### 8. Round-trip export from the derived HTML

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/go-build go run ./cmd/export_tiddlers \
  --html ../../out/tiddly-data-converter.derived.html \
  --out /tmp/s44-roundtrip-final.jsonl \
  --log /tmp/s44-roundtrip-final.log \
  --manifest /tmp/s44-roundtrip-final.manifest.json
```

Result: `PASS`

Observed summary:

- extracted: `696`
- included: `621`
- excluded: `75`
- ingested: `621`
- exported: `621`
- sha256: `sha256:1e003222d7bdfb4b1391d3d5fe8c6c05542d8c96ca3463c224dd5e8fca47fd38`

Observed interpretation:

- the derived HTML remains re-openable enough to be re-exported by the project pipeline without loss or ambiguity in the canonical subset

### 9. Re-shard the round-trip export as a temporary local view

```bash
cd /repositorios/tiddly-data-converter/go/canon
rm -rf /tmp/s44-roundtrip-final-shards
env GOCACHE=/tmp/go-build go run ./cmd/shard_canon \
  --input /tmp/s44-roundtrip-final.jsonl \
  --out-dir /tmp/s44-roundtrip-final-shards
```

Result: `PASS`

Observed summary:

- lines read: `621`
- session count: `44`
- hypothesis count: `48`
- provenance count: `53`
- remaining count: `476`
- shard counts reproduced exactly: `44 / 44 / 48 / 53 / 144 / 144 / 144`

### 10. Verify that the temporary resharded view is derived and matches the authoritative shards

```bash
cd /repositorios/tiddly-data-converter
for n in 1 2 3 4 5 6 7; do
  cmp -s "out/tiddlers_${n}.jsonl" "/tmp/s44-roundtrip-final-shards/tiddlers_${n}.jsonl" &&
    echo "tiddlers_${n}.jsonl:same" ||
    echo "tiddlers_${n}.jsonl:diff"
done
```

Result: `PASS`

Observed evidence:

- `tiddlers_1.jsonl:same`
- `tiddlers_2.jsonl:same`
- `tiddlers_3.jsonl:same`
- `tiddlers_4.jsonl:same`
- `tiddlers_5.jsonl:same`
- `tiddlers_6.jsonl:same`
- `tiddlers_7.jsonl:same`

## Summary

- S44 leaves the shard set in `out/` as the unique operational source of truth.
- The reverse now runs directly from shards with preflight before write.
- S19–S22 were repaired into homogeneous canonical records without silently collapsing the historical ambiguity of S22.
- S44 session, hypothesis and provenance live directly in the authoritative shards.
- The derived HTML round-trips back to a shard set identical to `out/`.
- The temporary monolithic and resharded artifacts remain local derivatives in `/tmp`, not new authority.
