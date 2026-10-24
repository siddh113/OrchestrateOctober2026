# Usage Report — Ghost Data Still Exists

## Full-Dataset Run Summary

This report covers the final run of `python3 code/main.py` that produced `output.csv` (518 cases).

## Model Providers and Models

| Provider | Model | Usage |
|---|---|---|
| Anthropic | `claude-sonnet-4-6` | PDF extraction, image extraction, ambiguous intent classification |
| Anthropic | `claude-haiku-4-5` | Clear-text intent classification (fast-path fallback) |

## LLM Call Counts

All LLM results are cached to `.llm_cache/{sha256}.json` keyed by input SHA-256.  
On the final full-dataset run, **all results were served from cache — 0 new LLM API calls were made.**

| Function | Files processed | Cache hits | New calls |
|---|---|---|---|
| `extract_pdf` | 4 PDF files | 4 | 0 |
| `extract_image` | 11 PNG files | 11 | 0 |
| `classify_intent` | ~20 ambiguous cases | ~20 | 0 |
| **Total** | — | **35** | **0** |

## Token Usage (First-Run Estimates)

The following estimates are based on the initial run that populated the LLM cache.  
Subsequent runs (including the final run) consumed 0 tokens.

| Function | Calls | Input tokens | Output tokens | Cache write | Cache read |
|---|---|---|---|---|---|
| `extract_pdf` | 4 | ~8,000 | ~4,000 | ~8,000 | 0 |
| `extract_image` | 11 | ~33,000 | ~11,000 | ~33,000 | 0 |
| `classify_intent` | ~20 | ~6,000 | ~200 | ~6,000 | 0 |
| **Total** | **~35** | **~47,000** | **~15,200** | **~47,000** | **0** |

## Cost Estimate

Pricing used:
- `claude-sonnet-4-6`: $3.00/1M input, $15.00/1M output, $3.75/1M cache write, $0.30/1M cache read
- `claude-haiku-4-5`: $0.80/1M input, $4.00/1M output

| Model | Input cost | Output cost | Cache write cost | Total |
|---|---|---|---|---|
| `claude-sonnet-4-6` | $0.12 | $0.23 | $0.17 | ~$0.52 |
| `claude-haiku-4-5` | $0.005 | $0.001 | $0.005 | ~$0.01 |
| **Overall** | | | | **~$0.53** |

### Per-Request Averages (initial run)

| Metric | Value |
|---|---|
| Avg input tokens / case | ~91 |
| Avg output tokens / case | ~29 |
| Avg cost / case | ~$0.001 |

## Notes

- The pipeline is deterministic. Structured evidence (SQL, JSON, logs) is parsed by Python code with no LLM involvement.
- LLM calls are made only for unstructured content: PDF documents, PNG screenshots, and ambiguous-language intent classification.
- After the first run populates the cache, all 518 cases process without any API calls.
- LLM cache is stored in `.evidence_cache/` and `.llm_cache/` directories at the repository root (gitignored).
