# Offline workflow audit

The audit exercises the application without starting Streamlit, a model server,
or Docker. HTTP transport is mocked in the adapter-level scenarios; generated
code uses trusted test implementations instead of executing on the host.

## Findings corrected

| Problem | Correction | Evidence |
| --- | --- | --- |
| Duplicate type/missing findings made issue binding ambiguous and could leave fixed work pending | Merge these findings into measured obligations, preserving evidence IDs | Telco-like adapter scenario has seven obligations, not duplicate findings |
| Too many redundant required proposal fields | Require hypothesis, columns, checks and method content; record derived metadata | Adapter scenario uses minimal proposals |
| Reviewing and separately applying consumed an extra model turn | Explicit review decision `apply` runs full-data checks before commit | Three accepted methods plus finish take seven calls |
| Five boolean columns required repeated singular calls | Broadcast a trusted method atomically across declared columns | All five flags convert in one candidate; one bad value prevents partial application |
| Catalog examples contained pipe-separated alternatives that could be copied literally | Provide valid example objects and separate option lists | Catalog is included in stage context |
| Parseable strings counted as completed conversions | Require numeric/boolean values of the appropriate representation | Focused tests reject text numerals and text booleans as completed types |
| Recovery user messages could interrupt a tool batch | Defer them until all tool responses are matched | Adapter scenario verifies native Ollama history ordering |
| Stage messages/tools were excluded from context estimates | Account for actual stage tools and added prompt messages when trimming history | The request builder now reserves their serialized size |
| Legacy tool suggestions contradicted the small live interface | Remove those suggestions from model progress | Adapter scenario checks live progress contains no legacy call catalog |
| Any changed value could resolve an arbitrary profiling finding | Require a declared column check to improve from failing to passing | Unrelated-change regression keeps the finding pending |

## Verification

The full regression suite passed 134 tests during the audit. The final focused
run passed 19 tests after adding the grouped-failure, unrelated-finding and
batched-history checks. Four existing pandas deprecation warnings appeared in
the full run.

The Telco-like test uses four synthetic rows, one missing charge, five Yes/No
columns, and duplicate profiling findings. It exercises the actual cleaning
loop, tool schemas, JSON validation, Ollama history translation, trusted method
execution, review, full-data checks, versioning and final validation. The mock
chooses the methods, including an explicitly justified synthetic-test median.
This verifies that the application can complete the path, not that Qwen will
independently choose it correctly.

## Limits still requiring separate work

- Live Qwen tool selection, latency, context tokenization and real Docker
  execution remain unverified. Context sizing uses a conservative character
  estimate, not the model's exact tokenizer.
- Checks cannot establish business meaning, appropriate imputation or absence
  of every possible error. Unsupported semantic findings remain unresolved.
- Structural changes are routed to human review. A complete user-driven review
  resolution/resume flow is not implemented by this audit.
- The ledger starts with profiling findings. Discovering and registering wholly
  new issue types needs a separate explicit design.
- Adaptive sample/holdout trials are development feedback; a separate evaluation
  dataset is needed to assess cleaning quality and generalization.
