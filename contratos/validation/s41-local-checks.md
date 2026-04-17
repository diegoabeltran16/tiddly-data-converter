# S41 Local Checks

## Session

- Session: `m02-s41-canon-minimal-derived-hardening-for-reverse-v0`
- Date: `2026-04-16`
- Scope: `canon`, `convertidor`, `documentacion`, `debug`

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

### 3. Controlled local export

```bash
cd /repositorios/tiddly-data-converter/go/bridge
mkdir -p ../../out
env GOCACHE=/tmp/go-build go run ./cmd/export_tiddlers \
  --html "../../data/tiddly-data-converter (Saved).html" \
  --out  "../../out/tiddly-data-converter.jsonl" \
  --log  "../../out/export.log" \
  --manifest "../../out/manifest.json"
```

Result: `PASS`

Observed summary:

- extracted: `664`
- filtered included: `589`
- exported: `589`
- excluded: `0`
- sha256: `sha256:476f67c36636cea1c97699a797a55db93dda12c60b0131b9423a4746a9d2e6c5`

## Output Review

### `content.plain`

- Present on textual nodes in `out/tiddly-data-converter.jsonl`.
- Derived deterministically by whitespace-normalized projection from `text`.
- Example confirmed on first exported markdown node: `content.plain` present.
- Binary PNG sample confirmed without `content.plain`.

### `normalized_tags`

- Present on exported nodes with tag evidence.
- Lowercasing and diacritic stripping observed.
- Emoji preserved in normalized output.
- Duplicate-equivalent values collapse in tests; original `tags` and `source_tags` remain intact.

### No-regression checks

- `text` remains present and unchanged as canonical reversible source.
- `source_tags` remain present and unchanged when available.
- Manifest and export log were emitted successfully.
- No reverse writer was introduced or executed.

## Limits / Notes

- `content.plain` is intentionally conservative: it does not render Markdown/TiddlyWiki/HTML semantics, summarize, or rewrite content.
- `normalized_tags` is a helper projection for comparison/filtering. Reverse authority remains on `source_tags`.
- Existing unrelated local changes in the worktree were left untouched.
