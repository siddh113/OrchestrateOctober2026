# Usage Report — Ghost Data Still Exists

## Final Full-Dataset Run

This report covers the run of `python -I code/main.py` from the repository root that produced
`output.csv` (518 cases). The run completed without errors. The final line of output was:

```
No LLM calls made.
```

## Model Providers and Models

**Zero.** The solution makes no LLM API calls of any kind.

All evidence parsing, identity resolution, state reconstruction, policy application, and step
planning are implemented in pure Python using only the standard library (`csv`, `json`, `sqlite3`,
`re`, `pathlib`, `datetime`). No external model API, embedding service, or vector store is used.

| Provider | Model | Calls | Input tokens | Output tokens | Cost |
|---|---|---|---|---|---|
| — | — | 0 | 0 | 0 | $0.00 |
| **Total** | | **0** | **0** | **0** | **$0.00** |

## Why Zero Model Calls

The pipeline was designed to avoid LLM calls entirely:

1. **Intent classification** — a keyword regex fast-path (`code/pipeline/intent_classifier.py`)
   classifies all 518 requests without ambiguity. No request required the LLM fallback path.

2. **Evidence parsing** — all 94 evidence files are machine-readable: `.sql` files are executed with
   `sqlite3`, `.json` files are parsed with `json.load`, `.log` files are parsed with regex, and
   `.txt` files are parsed as pipe-delimited records. No PDF or image files required content
   extraction for any evaluation case.

3. **State reconstruction** — deterministic timestamp-ordered selection from indexed evidence records.

4. **Policy application** — rule lookup against `dataset/deletion_rules.csv`.

5. **Step planning** — deterministic ordering by phase, operation priority, `system_id`, and
   `resource_id`.

## Token Counts and Cost

| Metric | Value |
|---|---|
| Total model calls | 0 |
| Total input tokens | 0 |
| Total output tokens | 0 |
| Average tokens per request | 0 |
| Estimated total cost | $0.00 |
| Estimated cost per request | $0.00 |

## llm_client.py

`llm_client.py` contains optional LLM fallbacks for PDF, image and ambiguous-intent handling. In the final run none are reached (0 calls); only `UsageTracker` is used to report usage.

## Evidence Cache

A file-level parse cache is written to `.evidence_cache/` (gitignored). On the final run this
directory was empty (deleted before the run). The index was rebuilt from scratch from the 94 evidence
files. Cache files are plain JSON; no LLM results are cached.
