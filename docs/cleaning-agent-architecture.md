# Current Data Cleaning & ETL Agent architecture

This describes the implemented code as of 1 November 2026. Agent 2 is a Python-controlled tool-calling loop using local Ollama, with optional Groq fallback code generation. The local model writes initial repairs; Groq can author a fallback after four failed local corrections; Python controls execution, validation, version commits and reporting.

The LLM loop now consumes a profiling-driven task queue in eight categories: understanding, formatting, types/invalid values, duplicates, missing values, outliers/inconsistent records, domain rules, and validation. `dataCleaningTools/cleaning_tasks.py` schedules reported findings without another LLM planning call. Only the active task's columns, observations and category guidance are sent; previous task conversation is removed from the next request while its full audit remains saved. Category prompts live in `dataCleaningTools/prompts/categories.json`.

Each model response executes at most one action. Dataset checks advance measured type/missing tasks only after commit; `complete_task` records assessments for advisory findings. Review needs and pending tasks remain visible to final validation. Non-missing tasks must preserve existing missing cells, so parsers cannot silently combine conversion with imputation. Categories without findings are recorded as `no_reported_findings`, not certified clean. Structural deletion/renaming still requires supported host approval; categorization does not enable destructive operations.

## Execution flow

Working-memory/scheduler ownership: explicit `working_context.refresh` measures the current dataset and synchronizes the queue. `model_context`, `active`, `context` and `summary` then project/read this state without hidden refreshes. `model_view` shares one freshly loaded frame across measurements, progress and value interpretation before selecting the active task. Examples describe current persisted values; the original profiling report remains a separate copy. New requirements are added once, removed measured requirements become `not_required`, and advisory reviews reopen after later committed changes to their columns. Stale inspection evidence cannot close a reopened review. A valid dtype alone does not resolve a separate invalid-value finding. Full category summaries stay in reports rather than being resent with every task prompt.

Controller/session ownership: every run uses its own manager through `state.manager`; the agent's `manager` attribute is only a convenience for last-run CLI access. The main loop prepares context, requests one action, and delegates correction/application to `_execute_action`. Terminal transitions use `state.stop`; stopped sessions cannot commit additional transformations. Snapshot persistence is read-only with respect to measurements; actual progress refresh occurs at event and validation boundaries. Trace and result share the same audit fields and final dataset reference. UI callback failures are logged without aborting cleaning. Report metadata lists recorded Docker image IDs instead of probing the unrelated legacy sandbox backend.

Known controller limitation: conversation budgeting still estimates tokens from character counts and retains the latest complete exchange. It does not guarantee a strict model-context token limit when a single exchange is very large; context sizing remains a separate item to inspect.

Current prompts are category-specific: type/missing tasks receive actual-column parser guidance; advisory tasks receive short inspection/assessment examples with their real task ID and column names. Parser mappings are omitted from advisory context so an outlier investigation does not suggest redoing type conversion. Example-coverage percentages are explicitly labelled as sample representation, with separate missing counts/percentages. Invalid tool arguments and scope errors are counted at the executor boundary before inspection execution; these attempts share the same consecutive-stall limit as redundant inspections. Actual generated-code trial failures continue through the existing correction pipeline.

`dataCleaningTools/investigation.py` enforces progress within an investigation. Inspection signatures include the dataset version, view, columns and effective parameters; explanations do not change a signature. Exact repeats within the same task reuse saved evidence and count as stalled; another task can consume that evidence once without a reread or penalty. Repeated pages of the same measurement with identical evidence are also stalled. Different predicates or views remain distinct questions, even if both return no rows. The required `reason` explains the remaining question and expected evidence; separate `question` and `expected_evidence` fields remain optional for compatibility. A genuinely different result resets the consecutive-stall count. Three consecutive stalled requests defer the task as `needs_review`; measured obligations additionally receive a review flag so they cannot pass by assertion. Other pending tasks can continue. Without a task queue, repeated stalls stop with `inspection_stalled`. Progress, cached-result references and deferrals are audited. A reviewed advisory task may retain all data unchanged.

Read-only inspection views now include `distribution` (actual min/max, signs, quartiles, IQR counts), `extremes`, `filtered` (including missing/non-numeric/negative/IQR outlier examples and threshold comparisons), and `relationships` (paired examples and numeric correlation). Thresholds and correlation do not establish data errors or business rules. These views supply evidence rather than choosing a repair.

Task scheduling omits explicitly informational findings (`NONE`, `INFO`, `INFORMATIONAL`) while preserving them in the profiling report. Independently required type and missing-value checks remain scheduled regardless of issue severity; unspecified and low-severity findings are still assessed. In value interpretation, string targets receive `preserve`, absent targets receive `not_applicable`, and unsupported interpreters receive `unsupported`. These statuses do not assert business ambiguity or certify unrelated quality checks. Genuine ambiguity, such as fractional values requiring an integer rounding policy, still receives `needs_review`.

Before code generation, `dataCleaningTools/value_interpretation.py` scans the active columns and builds read-only raw-value/count-to-canonical-meaning guidance. Boolean targets recognize case/whitespace variants of Yes/No, True/False and 1/0; numeric targets reuse the independent numeric interpreter. Dates, categories and unknown representations remain unresolved instead of receiving guessed meanings. Up to 100 distinct mappings are shown with coverage and pagination; counts scan every row. No extra LLM call or dataset conversion occurs in this layer. Plans are recorded as versioned interpretation evidence and supplied to the local author, request/code correction and Groq.

The same boolean interpretation validates every recognized source cell during trial and full-data acceptance, blocking known values becoming missing or reversed even with a nullable boolean dtype. Independent checks are not limited to the displayed mappings. Genuine invalid values may still become missing under the existing policy. Business-specific date/category mappings remain model reasoning or human-review work, not universally inferred rules.

```mermaid
flowchart TD
    UI["Streamlit workspace or Python / CLI caller"] --> IN["Profiling report + source dataset"]
    IN --> SETUP["Validate report; create V0 and V1"]
    SETUP --> STATE["Per-run state and working report copy"]
    STATE --> QUEUE["Profiling-driven category queue: one finding at a time"]
    QUEUE --> LOOP["DataCleaningAgent control loop"]
    GUIDE["System prompt + request guide on every request"] --> LOOP
    LOOP --> MODEL["Local Ollama: choose and explain an action"]
    MODEL --> TOOLS["ToolExecutor + workflow dispatch"]
    TOOLS --> INSPECT["inspect_data: read current working data"]
    INSPECT --> LOOP
    TOOLS --> TEST["test_builtin / test_generated: explicit interfaces"]
    TEST --> BUILTIN["Builtin: trusted Python on full-data copy"]
    TEST --> DOCKER["Generated: Docker sample and holdout trials"]
    BUILTIN --> TRIAL["Independent trial checks"]
    DOCKER --> TRIAL
    TRIAL -->|"Rejected"| FEEDBACK["Measured errors + recovery prompt"]
    FEEDBACK --> LOOP
    TRIAL -->|"Passed"| APPLY["Automatic apply_candidate in same turn"]
    APPLY --> CHECK["Version / content / policy checks; rerun on full data"]
    CHECK -->|"Rejected or blocked"| FEEDBACK
    CHECK -->|"Accepted change"| VERSION["Commit next dataset version"]
    CHECK -->|"Identical values"| NOOP["No new version"]
    VERSION --> STATE
    NOOP --> STATE
    TOOLS --> REVIEW["flag_for_review: freeze selected columns"]
    REVIEW --> STATE
    TOOLS --> FINISH["finish: replace current model assessment"]
    FINISH --> VALIDATE["Independently validate actual dataset"]
    VALIDATE -->|"First unsuccessful finish"| FEEDBACK
    VALIDATE -->|"Finish accepted or retry exhausted"| RESULT["Passed / partial / failed result"]
    LOOP -->|"Budget, stall or provider stop"| RESULT
    RESULT --> FINAL["Final dataset validation; save result and export report"]
    TOOLS -. "Audit events" .-> TRACE["Trace + evidence + working-context files"]
    STATE -. "Progress snapshots" .-> TRACE
```

An explicit manual `apply_candidate` call also reaches the application path. Normally the host invokes it immediately after a passing trial, so the model does not need another turn to apply the candidate.

## Components and source files

Fallback generation is implemented in [expert_generator.py](../dataCleaningTools/expert_generator.py), with [generation instructions](../dataCleaningTools/prompts/expert_generation.md). Four unsuccessful local corrections trigger one complete Groq-authored replacement, tested through the same Docker and full-data boundaries. Invalid tool envelopes use the separate bounded [request correction](../dataCleaningTools/request_correction.py). Docker infrastructure failure stops the run, and generated tasks cannot fall back to builtins. See [configuration and limits](expert-generation.md).

Paths below are relative to the project directory containing this document's parent, `BIFlow/`.

| Component | Current responsibility | Files |
|---|---|---|
| Workspace entry point | Selects the dataset, loads a matching profiling report, invokes cleaning, passes settings and host approvals, and recovers saved results. Profiling runs only if no matching report is available or refresh is requested. | [dashboard/workspace.py](../dashboard/workspace.py), [dashboard/components.py](../dashboard/components.py) |
| Cleaning screens | Run actions, streaming progress, validation results, explanations, working progress, report downloads and Docker setup controls. | [dashboard/pages/4_Data_Quality.py](../dashboard/pages/4_Data_Quality.py), [dashboard/pages/3_Workflows.py](../dashboard/pages/3_Workflows.py), [dashboard/cleaning_review.py](../dashboard/cleaning_review.py) |
| Agent controller | `DataCleaningAgent.run()` initializes a run; `_run_llm_loop()` requests actions, matches tool responses, automatically applies passing trials, bounds retries and detects stalls. `_build_result()` performs final validation and saves outputs. Also supplies CLI and deterministic/dry-run modes. | [agents/dataCleaning_agent.py](../agents/dataCleaning_agent.py) |
| Profiling handoff | Parses the incoming report, resolves its source file, and supplies the deterministic baseline's initial proposals. | [dataCleaningTools/agent1_adapter.py](../dataCleaningTools/agent1_adapter.py) |
| Typed data contracts | Pydantic definitions for `ProfilingReport`, dataset references, transformation records, validation and the final `CleaningResult`. | [dataCleaningTools/models.py](../dataCleaningTools/models.py) |
| Instructions | Main behavioral instructions and the request-format guide included in the fresh context of every model request. They require model explanations and distinguish testing from application. | [dataCleaningTools/prompts/cleaning.md](../dataCleaningTools/prompts/cleaning.md), [dataCleaningTools/prompts/request_guide.md](../dataCleaningTools/prompts/request_guide.md) |
| Cleaning LLM adapter | Local Ollama HTTP requests, native tool-message translation, complete JSON-call fallback, request timeouts, progress callbacks, token usage and timing. Separate from Agent 1's client. | [dataCleaningTools/llm_client.py](../dataCleaningTools/llm_client.py) |
| Session state and executor | `AgentSessionState` owns current versions, candidates, evidence, flags, assessments and run limits. `ToolExecutor` dispatches tools, records events and controls the independently checked commit boundary. | [dataCleaningTools/tool_registry.py](../dataCleaningTools/tool_registry.py) |
| Working memory | Copies the validated profiling report per run and remeasures current types/missing values. Tracks pending, done and needs-review steps plus committed actions, independently of trimmed chat history. | [dataCleaningTools/working_context.py](../dataCleaningTools/working_context.py) |
| Public tool interface | Defines the seven model tools and their schemas. Implements scoped inspect/test/apply/review/assessment dispatch, candidate fingerprints, builtin trials, and stale-candidate checks. | [dataCleaningTools/workflow.py](../dataCleaningTools/workflow.py) |
| Category queue | Schedules one reported finding at a time, filters model context, verifies measured task progress and records advisory assessments. | [dataCleaningTools/cleaning_tasks.py](../dataCleaningTools/cleaning_tasks.py), [category prompts](../dataCleaningTools/prompts/categories.json) |
| Argument conventions | Canonical type names and safe normalization of unambiguous misplaced column lists. Missing explanations are not synthesized. | [dataCleaningTools/contracts.py](../dataCleaningTools/contracts.py) |
| Builtin transformations | Trusted implementations for whitespace, category normalization, numeric parsing, type conversion and imputation. Contains some additional operations for trusted callers. | [dataCleaningTools/cleaning.py](../dataCleaningTools/cleaning.py), [dataCleaningTools/method_catalog.py](../dataCleaningTools/method_catalog.py) |
| Inspection | Current schema, column values/statistics, duplicates and value-pattern inspection. Reads managed versions without committing changes. | [dataCleaningTools/inspection.py](../dataCleaningTools/inspection.py) |
| Acceptance and outcomes | Before/after measurements; structural preservation; unchanged unselected values; audited invalid-value-to-NaN conversions; type/imputation checks. Generated methods also require declared outcomes and row/index preservation. | [dataCleaningTools/effects.py](../dataCleaningTools/effects.py), [dataCleaningTools/experiments.py](../dataCleaningTools/experiments.py) |
| Numeric meaning checks | Independent expected values for supported currency punctuation, numeric multipliers and common English number phrases. Checks every recognized source cell during numeric conversion/imputation, including full-data application; unknown tokens may still become NaN. Reports input/expected/actual mismatches. | [dataCleaningTools/numeric_expectations.py](../dataCleaningTools/numeric_expectations.py) |
| Policy and approvals | Operation risk classification and host approval requirements, enforced before committing transformations. Model-supplied approval claims do not grant permission. | [dataCleaningTools/policy.py](../dataCleaningTools/policy.py), commit path in [tool_registry.py](../dataCleaningTools/tool_registry.py) |
| Generated-method Docker runner | Saves generated source, performs disjoint sample/holdout trials, pins the image, checks repeatability and reruns exact code on the full dataset before promotion. | [dataCleaningTools/experiments.py](../dataCleaningTools/experiments.py), [sandbox/Dockerfile](../sandbox/Dockerfile) |
| Recovery feedback | Selects focused instructions using actual failures: arguments, conversion, imputation, data loss, duplicate/no-change, sandbox, final validation and response format. Feedback guides the model; it does not execute a repair. | [dataCleaningTools/recovery.py](../dataCleaningTools/recovery.py), [dataCleaningTools/prompts/recovery/](../dataCleaningTools/prompts/recovery/) |
| Dataset persistence | Copies the source as V0, creates V1, commits accepted transformations as subsequent versions, and records metadata, rejected attempts and changelogs. | [dataCleaningTools/versioning.py](../dataCleaningTools/versioning.py) |
| Report exporter | Computes measured before/after summaries and exports the latest report plus a separate file for each run. Uses existing results; no extra LLM call. | [dataCleaningTools/reporting.py](../dataCleaningTools/reporting.py) |

## The seven model tools

| Tool | Required request information | Effect |
|---|---|---|
| `inspect_data` | `reason`, `view`; `column` for column/pattern views | Reads current data. No mutation. |
| `test_builtin` | `hypothesis`, `columns`, builtin `operation`, `parameters`; optional `checks` | Tests catalog operations only; no Python code. |
| `test_generated` | `hypothesis`, `columns`, complete `code`, `checks` | Explicit Docker execution of generated transform(df); no operation/parameters. Infrastructure failure stops the run. |
| `apply_candidate` | Returned `candidate_id`, evidence-based `assessment` | Reruns a passing candidate on current full data and commits only after checks. Normally called automatically by the host. |
| `flag_for_review` | `columns`, `reason` | Freezes those columns for the rest of the run and records explicit exceptions. |
| `complete_task` | Active `task_id`, `disposition` (`reviewed` or `needs_review`), `reason` | Records an advisory assessment after inspection or validated application; cannot certify a pending type/missing obligation. |
| `finish` | `summary`; optional `unresolved` list | Replaces the model's current unresolved assessment, then independently validates the working dataset. Earlier assessments remain in events. |

The builtin operations available through `test_builtin` are `trim_whitespace`, `normalize_values`, `clean_numeric_string`, `convert_data_types`, and `handle_missing_values`. Available outcome checks include numeric, integer, boolean, datetime, string, no_missing, non_negative and unique.

## Builtin execution and Docker execution

**Builtin methods:** run trusted Python functions on a full-data copy in the host process. Docker is not involved. Passing candidates are rerun and independently checked before a version is committed.

**Generated methods:** the model supplies a complete `transform(df)` function with an explanation and outcome checks. Python validates its structure but executes generated source only in Docker. Trials use disjoint sample and holdout partitions, up to 500 rows each, with 200 as the default limit. A one-row input cannot provide an independent holdout. Every invocation checks repeatability by executing twice with fresh namespaces and fixed seeds. A passing candidate is rerun on full data in the pinned image before commitment.

The container has no network or host mounts, a read-only root filesystem, a nonroot user, dropped capabilities, bounded temporary storage, 768 MB memory, one CPU, 64 processes and a 60-second invocation timeout. It is removed afterward. Generated code never falls back to host execution.

The default image is `biflow-cleaning-sandbox:latest`, built using `sandbox/Dockerfile`; `BIFLOW_EXPERIMENT_IMAGE` can select another compatible image. The last environment check found Docker running but this image missing. This is an environment prerequisite, not an always-running service. The recent successful Telco run used builtin methods and did not exercise this Docker route.

## Validation and completion

There are three separate boundaries:

1. **Trial checks:** establish whether the candidate meets its measured trial conditions. They never mark an uncommitted change as completed work.
2. **Application checks:** verify current version/content, policy, selected columns, full-data effects and remaining run time before commitment. An unchanged result creates no extra version.
3. **Final validation:** independently checks nonempty data, expected columns, required types and reported missing-value obligations. Model claims cannot override these results.

The working memory rechecks persisted data, so a regression can reopen a previously completed step. Other advisory profiler observations are not certified resolved merely because a type or missing-value check passed.

| Validation status | Meaning |
|---|---|
| `passed` | All required checked obligations pass, with no unresolved exceptions. Final dataset is marked validated. |
| `partial` | Checked obligations pass, but model concerns, review flags, approvals or host concerns remain. Dataset remains working. |
| `failed` | A required checked obligation fails. Final dataset is marked failed. |
| `not_run` | Dry run; no final cleaning certification. |

Each `finish` replaces only `model_unresolved`. Host failures, human-review flags and approvals are independent. The first unsuccessful finish allows continuation; the second unsuccessful finish ends the run. Default LLM limits are 24 turns, 300 seconds per cleaning run and a 90-second maximum per model request, further bounded by remaining run time. Repeated identical calls on unchanged data, three consecutive unusable responses, provider errors and expired budgets can also stop execution. Finalization still checks the actual final dataset.

## Saved artifacts

These are the dashboard's paths; Python/CLI callers may configure different version/report roots.

```text
data/
  raw/<dataset>.<format>                       Original uploaded source
  reports/
    profilingReports/<dataset>_profiling_report.json
    cleaningReports/<dataset>_cleaning_report.json
    cleaningReports/<dataset>_<result_run_id>_cleaning_report.json
  versions/dashboard/<run_folder>/<dataset>/
    V0_original.<format>                      Registered source copy
    V1_working.<format>                       Initial working copy
    V2_transform.<format> ...                 Accepted changes
    V0_meta.json, V1_meta.json ...             Version references and metadata
    changelog.json                            Applied and rejected transformations
    execution_trace.json                      Events, evidence, assessments and errors
    cleaning_context.json                     Profiling-report copy and working progress
    cleaning_result.json                      Final typed result used for recovery
    experiments/<candidate_id>/               Generated source and trial reports, when used
```

The short version-directory identifier (`run_folder`) and the final `CleaningResult.run_id` are separately generated IDs. Candidate IDs exposed to the model (`c1`, `c2`, ...) map to internal experiment IDs for generated methods.

## Scope distinctions

- [dataCleaningTools/ETL.py](../dataCleaningTools/ETL.py) implements selection/renaming, filtering, derivation, joins, aggregation and export. These functions are **not wired into the current seven-tool model dispatch**. Current engineering work primarily covers data representation, normalization, imputation and versioned output. The UI's ETL node shares cleaning's status; it is not a separate ETL execution engine. See [dashboard/pipeline.py](../dashboard/pipeline.py).
- [dataCleaningTools/sandbox.py](../dataCleaningTools/sandbox.py) is the older general sandbox helper, also used for profiling's read-only checks. Its backend availability is recorded by the agent, but it is **not** the generated-cleaning execution route. The older helper has a development host fallback; generated cleaning does not use it.
- [agents/llm_client.py](../agents/llm_client.py) is Agent 1's profiling client. Cleaning uses [dataCleaningTools/llm_client.py](../dataCleaningTools/llm_client.py), which is local Ollama only.
- `use_llm=False` selects the explicit trusted deterministic baseline. It uses adapter proposals and policy checks, rather than model decisions. `dry_run=True` creates run artifacts without applying transformations.
- The live cleaning controller is `DataCleaningAgent`; the empty [orchestration/graph.py](../orchestration/graph.py) is not its orchestration mechanism.
- Passing technical checks establishes the specified conditions. It does not establish business meaning, the appropriateness of an imputation or correctness on every dataset.

## Verification map

| Behavior | Relevant tests |
|---|---|
| Tool schemas, candidates, stale data, declared checks | [tests/test_simple_workflow.py](../tests/test_simple_workflow.py), [tests/test_tool_registry.py](../tests/test_tool_registry.py) |
| Loop, automatic application, finish assessments, limits | [tests/test_cleaning_loop.py](../tests/test_cleaning_loop.py), [tests/test_workflow_audit.py](../tests/test_workflow_audit.py) |
| Working copy, completed steps and preserved source report | [tests/test_working_context.py](../tests/test_working_context.py) |
| Acceptance and generated method boundaries | [tests/test_cleaning_acceptance.py](../tests/test_cleaning_acceptance.py), [tests/test_cleaning_experiments.py](../tests/test_cleaning_experiments.py) |
| Provider adapter and focused feedback | [tests/test_llm_client.py](../tests/test_llm_client.py), [tests/test_recovery_prompts.py](../tests/test_recovery_prompts.py) |
| Report exports and profiling reuse | [tests/test_cleaning_reports.py](../tests/test_cleaning_reports.py), [tests/test_dashboard_workspace.py](../tests/test_dashboard_workspace.py) |

Offline tests use mocked model responses and trusted sandbox mocks. Their success does not by itself prove live model quality or Docker runtime readiness.

Invalid-value policy: the blanket no_new_missing rule has been removed. Invalid nonsensical entries may become NaN, while valid numeric formats should be parsed. All affected original values remain in the audit (`lost_values` is the retained legacy field name), and the report counts `values_coerced_to_missing`. Committed new NaNs register missing-value obligations and category tasks; trials alone do not. Existing missing values cannot be silently imputed during earlier categories.

Numeric meaning checks are independent of generated code. For supported representations, `expected:numeric_values:<column>` records every mismatching row, source value, expected magnitude and actual result. It rejects `1.5k -> 1.5` and `$450.00 -> NaN`, while `banana -> NaN` remains permitted. The bounded grammar covers conventional decimal/scientific notation, standard thousands separators/currency punctuation, k/m/b multipliers, and common English number/scale/fraction phrases. It does not infer arbitrary text, regional numeric conventions, exchange rates or domain rules. Host-selected formatting/outlier/domain tasks can intentionally change numeric meaning and do not automatically inherit this preservation check; their own required checks still apply.

Docker logs are retained in failed-trial and full-data feedback and supplied to local correction and Groq generation. `ChainedAssignmentError` adds actionable guidance to assign a filled Series back to its DataFrame column. Other warnings remain diagnostic evidence rather than unconditional rejection rules. Run `python scripts/test_semantic_validation.py` for live Docker regressions without LLM/API calls.


Value interpretation and prompt assembly audit (1 November 2026): `value_interpretation.py` shares missing-marker definitions with independent checks, distinguishes actual nulls from effective missing markers, and reports whether conversion is needed. Conversion plans show twenty mappings by default; already-typed columns receive at most five examples; counts still scan every row, partial coverage remains explicit, and common/rare format groups remain available. Supported numeric/boolean meanings are independently checked across all relevant rows; this helper does not guess dates, units or business meanings.

`prompts/cleaning.md` owns policy; `prompts/request_guide.md` owns concise tool construction guidance; category guidance and measured context are attached for the active finding. The initial user message carries the objective and version context, rather than repeating system policy. Historical recovery messages carry case/instruction only because their measured evidence is already in tool feedback and fresh context. Full recovery payloads remain in the audit. Prompt assembly keeps at most three complete exchanges and drops older exchanges before grouping oversized row-failure lists by meaning. Code and current requirements are never cut. If the essential request still exceeds the host character estimate, execution stops as `context_budget` before dispatch. The estimate uses four serialized characters per available input token, including tool schemas and reserved current context; it is not an exact tokenizer limit. Groq retains its separate full-request byte budget.


Local adapter and dispatch audit (1 November 2026): `llm_client.py` uses one envelope decoder for native calls and complete JSON fallback calls. It preserves argument objects for executor validation and the raw/canonical audit; a well-formed call with bad action arguments reaches the same request-correction route in both formats. `validated_json` now identifies a validated call envelope, not validated action arguments. Structured code-correction replies still validate their dedicated response schema in the adapter. Truncated responses return no executable calls, even when a native call is present. Malformed response shapes and unmatched/duplicate historical tool replies raise a controlled `ToolResponseError`; output budgets must leave room for input.

`ToolExecutor.execute` normalizes public arguments and calls `workflow.validate_request` before failed-method lookup. Public schema validators are reused, and dispatch performs scope checks and invokes handlers without repeating public schema validation. Failed-method memory no longer revalidates the same request. Nested-column compatibility and obsolete reference-field removal remain centralized in `contracts.model_arguments`; explanations are never invented. Builtin parameters use documented option names and operation-specific checks; unreachable alias repair and silent removal of unrelated options were removed. Unexpected handler exceptions stop as `tool_execution_error` and are audited with their actual exception type, instead of being described as a missing model argument or an inspection stall. Fatal errors bypass model recovery and dataset rereads during event recording, so an unavailable working file cannot obscure the original failure. Expected invalid-value/argument `ValueError` feedback remains recoverable. Docker and independent commit checks remain in force.


Inspection and investigation audit (1 November 2026): `inspection.inspection_query` defines effective view options/defaults for both execution and cache identity. Irrelevant options and missing filter/comparison/relationship inputs are rejected rather than ignored. Duplicate inspection now honors a single `column` or compound `subset`, defaults to full rows, and reports exact duplicate groups separately from redundant row counts. Duplicate keys remain observations, not authorization to remove records. Key columns follow active-task scope; unscoped findings can inspect the dataset's columns.

Column statistics perform one numeric conversion and exclude infinities from finite statistics. Duplicate index labels cannot corrupt targeted examples: examples report original labels plus physical row positions. Missing-marker counts are distinguished from physical nulls; empty columns have finite, JSON-safe percentages. Frequent values live in `value_overview` rather than a duplicate `top_values` field. Format groups retain only four representative values while maintaining full counts; case-variant output is bounded and reports total group counts and display limits. Direct file inspection reuses versioning's reader.

Successful read-only inspection events no longer refresh the unchanged dataset. A fresh inspection reads once; an exact repeated query can return saved evidence with zero reads. Deferrals still refresh measured review flags, and changed dataset versions invalidate cached evidence. Investigation uses the existing event history instead of a separate cache or task ledger. Three consecutive stalled requests still defer a focused task for review, or stop an unscoped run; useful evidence and valid cross-task evidence reuse reset that counter. No inspection marks a repair as committed or bypasses independent dataset checks.
