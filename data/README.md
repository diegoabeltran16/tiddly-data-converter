# Data Layout

`data/` has three operative roots:

1. `data/in/`
   Local HTML input and other human-provided inputs.
2. `data/out/`
   Governed output root split into `local/` and `remote/`.
3. `data/reverse_html/`
   Reverse HTML outputs and reverse reports.

Core rule:

- `data/out/local/tiddlers_*.jsonl` is the canonical source of truth.
- Agents may read canon and derive from it.
- Local derived layers live under `data/out/local/`.
- Remote exchange or cloud-oriented outputs live under `data/out/remote/`.
- Proposals are emitted as canonized JSONL lines in `data/out/local/proposals.jsonl`.
- `data/out/local/ai/chunks_ai_*.jsonl` is a derived retrieval layer with chunk-level traceability back to canon.
- Historical artifacts may remain in canon while being excluded from general chunking when tagged or treated as archival-only.
