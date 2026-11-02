# Groq fallback code generation

Groq now authors a complete method after four unsuccessful local corrections; it no longer acts as a reviewer. Local Ollama remains the first code author. The initial failed generated candidate is not one of the four corrections. Malformed or unchanged local correction replies count as unsuccessful attempts, but are not recorded as executed Docker trials. Request-envelope correction is a separate, two-attempt process.

After four failures, the controller sends one generation request with the current complete method, all four correction outcomes, precise diagnostics and loss evidence, selected-column value inventories (up to 100 distinct values plus common/rare format examples and coverage), relevant profiling context, schema, active category, requirements and the Docker execution contract. Only selected-column value examples are sent; the schema may name other columns.

`expert_context.py` groups repeated mismatches/lost values by their raw/expected/actual evidence, preserving counts and two row examples per group. Duplicate failed checks are removed, and malformed replies carry output previews instead of full local reasoning transcripts. The complete audit context remains in `audit_context`; `context` is the evidence actually sent. The request is budgeted against the provider's token limit: the text Groq tokenizes (system prompt, user context and response schema) must stay within `(BIFLOW_CLEANING_EXPERT_TOKEN_LIMIT - BIFLOW_CLEANING_EXPERT_MAX_COMPLETION_TOKENS) × 3.6` characters, because Groq counts the reserved completion against its per-minute limit (8,000 tokens for gpt-oss-120b on the free tier) and refuses larger requests with HTTP 413. The HTTP body keeps a 60,000-byte ceiling. To fit, duplicated evidence is removed first (diagnostic checks repeated in the failure summary, value patterns repeated from the value interpretation, identical correction code, inventory values beyond 10, related rows beyond 5, sandbox logs beyond the last 2,000 characters), then evidence groups decrease from 100 to 20, 5 or 1 with explicit omitted-group counts. This is an estimate, not a tokenizer guarantee; on a provider error the trace records the provider's own message, which states the actual limit and request size. Executable code, required checks and mappings are never cut to force a fit. If essential content still cannot fit, HTTP dispatch is blocked with a precise error. Request size and budget are recorded in the trace.

Profiling context is filtered to business meaning, reasoning, uncertainty and issues, with type targets or imputation suggestions included only for the relevant active category. The conflicting inferred-role label is omitted. The obsolete dashboard instruction allowing builtin fallback is migrated in historical objectives. Malformed local replies include their raw response, finish reason and response issue so Groq can distinguish truncation from executed-code failures.

The execution contract includes the container image ID and Python/pandas/numpy versions observed during sandbox execution; unobserved versions are explicitly unknown, never inferred from host packages. It explains compatible missing sentinels and output dtypes, including the prohibition on directly casting an object Series containing pd.NA to NumPy float64. These instructions do not replace Docker or independent dataset checks.

The default is `openai/gpt-oss-120b` through Groq, using strict JSON-schema output. The response contains a complete `transform(df)`, a concise explanation and assumptions, or an explicit `needs_review` decision. Structured output validates shape, not algorithm correctness. The method must pass syntax validation, Docker sample/holdout trials, data-preservation/outcome checks, and an exact-code full-data rerun before application. Existing checks cannot be weakened. Ambiguity, unavailable generation, invalid/truncated output, rejected code, or failed final testing ends the generated path with a visible error. There is no builtin or alternate-provider fallback.

## Configuration

```dotenv
GROQ_API_KEY=your_key_here
BIFLOW_CLEANING_EXPERT_ENABLED=true
BIFLOW_CLEANING_EXPERT_MODEL=openai/gpt-oss-120b
BIFLOW_CLEANING_EXPERT_MAX_CALLS=2
BIFLOW_CLEANING_EXPERT_TIMEOUT=60
# Provider tokens per request/minute, and the share reserved for the reply
BIFLOW_CLEANING_EXPERT_TOKEN_LIMIT=8000
BIFLOW_CLEANING_EXPERT_MAX_COMPLETION_TOKENS=2000
```

Raise `BIFLOW_CLEANING_EXPERT_TOKEN_LIMIT` if your Groq plan allows more tokens per minute; more evidence is then sent ungrouped.

Restart the app after changes. Previous `BIFLOW_CLEANING_REVIEWER_*` settings have been replaced. Tokens for other providers are not used by this path. Failed HTTP requests count against the per-run call budget. Identical generation contexts reuse the recorded result. API/account quotas and the overall cleaning deadline still apply; there is no promise that one generation will succeed.

Generated code requires Docker. If Docker, its image, or input/output infrastructure is unavailable, the run stops immediately; no local correction, Groq request or builtin fallback is attempted for that infrastructure error. Already committed earlier repairs remain in version history.

Requests, returned methods, usage and safe errors are recorded under `expert_generations` in the trace and cleaning report. Bearer tokens and provider exception bodies are not logged; only the provider's error message text (for example which token limit was exceeded) is recorded.

## Diagnostics

`python scripts/test_expert_generation.py` runs local corrections with the configured synthetic diagnostic. `--inject-local-failures` deliberately injects four distinct runtime failures to exercise one real Groq request and real Docker validation without relying on local-model behavior. It checks exact expected numeric values, full-data acceptance and additional unseen examples; it does not apply the result to a user dataset. Diagnostic deadlines/settings are process-local.

Groq API details: [structured outputs](https://console.groq.com/docs/structured-outputs), [API reference](https://console.groq.com/docs/api-reference).

Invalid-value policy: Groq may generate code that maps nonsensical tokens to NaN. It must still parse standard numeric representations, preserve unrelated data and explain its classification. The blanket no_new_missing check is removed. Affected values remain audited and committed NaNs become missing-value tasks; genuine unit/date/business ambiguity still requires review. The live diagnostic supports `--include-invalid-values` to test this policy alongside ordinary number parsing.

Generation context now includes captured Docker warnings and full-data logs. Independent numeric-meaning failures supply original/expected/actual values for supported representations; these checks run on trials and full data. A method cannot pass merely by producing a numeric dtype or an all-NaN column. Logs containing ChainedAssignmentError include explicit assignment guidance; warnings themselves remain evidence, not blanket failures.
