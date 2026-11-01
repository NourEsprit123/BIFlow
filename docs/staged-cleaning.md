# Simple cleaning workflow

The model sees seven tools: inspect_data, test_builtin, test_generated, apply_candidate,
flag_for_review, complete_task, and finish. The shared prompt lives at dataCleaningTools/prompts/cleaning.md.
The LLM workflow uses the profiling-driven category queue in cleaning_tasks.py;
categories.json supplies only the active category's guidance. It handles one
finding/column at a time (a documented cross-column relationship can involve
several columns). Earlier task conversation is cleared from model context, not
from the audit. Missing-value handling follows type conversion; existing nulls
must stay missing during earlier categories. Advisory findings require an
assessment, and no-reported-findings categories are not certified clean.
In the agent loop, a passing test_builtin or test_generated is immediately followed by automatic
apply_candidate execution in the same turn. Testing and application remain separate
audit events. The result reports tested, applied, and remaining obligations; a
passing trial alone does not imply successful full-data application. Failed
trials do not trigger application. Full-data checks, approvals, version integrity,
and the run deadline still gate every commit.

Every model action requires its own nonblank explanation: inspection/review reason,
method hypothesis, manual application assessment, or finish summary. Missing
hypotheses are rejected rather than synthesized by the host. Prompts require
observations, method/parameter justification, expected effects and assumptions;
schema validation establishes presence, not the truth of that explanation.
Automatic applications retain the model hypothesis and are labeled separately
from model decisions in the trace and UI.

test_builtin puts hypothesis, columns, operation, parameters and optional checks at the top level. test_generated instead requires hypothesis, columns, complete transform(df) code and checks; it rejects operation/parameters. Only method options belong inside parameters. A shared
adapter moves an unambiguous parameters.columns to the top level, removes an
identical duplicate, and rejects conflicting declarations. No column target or
business rationale is guessed. Normalized tool events retain original arguments
when normalization occurred at dispatch.
There is no model-managed stage machine, evidence-ID contract or separate
review action. Profiler findings are advisory text; type and missing-value
obligations are computed from the current working data.

Each cleaning run saves cleaning_context.json alongside its trace. It contains an
independent copy of the validated profiling report and measured per-column step
status (pending, done, needs_review), current types, missing counts, completion
versions, and committed action history. The copy never overwrites the source report.
Progress is rechecked on persisted working data after tool events; trials alone
cannot complete a step. Regressions reopen steps, and review flags remain explicit.
The model receives current progress and completed actions every turn, independent
of trimmed conversation history. Resolved type/missing observations are omitted
from active context; other observations remain advisory, not automatically resolved.

dataCleaningTools/prompts/request_guide.md is included in the fresh context of every model
request, including provider regeneration attempts. It supplies complete layouts for
each action, builtin and generated method examples, and a final field/nesting check.
It reminds the model that passing trials are applied automatically. The guide is
counted in context budgeting and is not accumulated in conversation history.
This guidance does not change tool schemas, acceptance checks or retry behavior.

Candidate failure feedback includes an explicit rejection reason, failed checks,
and every populated-to-missing cell in lost_values, with column, row position,
original row index, original value and candidate value. This list is independent
of the five general changed-value examples and is not truncated. It is retained
in the audit/report, shown in the UI and preserved in compact model feedback,
including generated sample/holdout and full-data outcomes. Generated partition
evidence carries its partition name; positions refer to that invocation's data.
Duplicate requests reference the original candidate and distinguish failed,
passed-but-not-applied and already-applied trials. Failed duplicates retain their
original failure evidence and explicitly forbid application or unchanged retries.

A builtin trial runs its trusted function on a full-data copy, with independent
acceptance and any declared outcome checks. Generated code requires declared
checks and uses the existing isolated Docker sample/holdout runner. BIFlow adds
selected-column target-type and missing-value obligations to generated checks.
Generated code never runs on the host, including when Docker is unavailable.

Only apply_candidate commits model-proposed changes. It records a concise model
assessment, reruns the exact tested method on the full current data, rechecks
mandatory acceptance and declared outcomes, then commits. The public c1/c2 IDs
map to internal generated-experiment IDs; generated promotion uses the latter.
Version and content checks reject stale data or modified candidates. Content
checks remain because version files are writable, not physically immutable.

Approval IDs are hashes of the operation, columns and parameters. Only host UI
or CLI input populates approved_step_ids. A model cannot choose its own approval
ID or grant permission. A host-only trusted operation path supports the explicit
deterministic baseline and core tests; it is not reachable through model dispatch.

flag_for_review takes column names and reasons. Those columns are frozen for the
rest of the run and omitted from remaining obligations. Final validation reports
those reasons, unresolved comments and pending approvals as exceptions. A run
with no failing checked obligations but with exceptions has status partial, keeps
a WORKING dataset, and never satisfies validation.all_passed. Full success is
reserved for checked obligations passing without exceptions. A second unsuccessful
finish attempt ends the run rather than creating a completion loop.

Each finish call replaces the model's previous unresolved assessment (omission
defaults to an empty list). Finish events retain both previous_unresolved and the
new unresolved list with their summaries and validation results. Host failures,
review flags and approvals remain independent exceptions; actual dataset checks
still run on every finish and finalization. Clearing the model's list cannot
turn failing data or pending human review into a fully passed result.

Failed methods remain in audit traces but do not permanently poison later
validation. Identical candidates cannot be retested on the same version. Method
failure counts, repeat-call limits, total turns and wall time bound the run.
Errors go back to the model with their actual failed checks or exception; JSON
parser rejection reasons and truncation are also recorded and returned for repair.
Focused feedback templates for different error cases are described in
[Case-specific recovery prompts](recovery-prompts.md). They do not introduce
stages or change which tools are available.

Tests use controlled HTTP responses and trusted sandbox mocks. They verify the
application's control and acceptance boundaries, not live Qwen decision quality
or real Docker availability. A separate live behavioral evaluation is still needed.

After a failed builtin the model may revise its parameters, choose another builtin, or write generated code. Once generated execution is selected, no builtin fallback is permitted. Docker infrastructure errors stop the run. Four unsuccessful local corrections trigger Groq code generation, followed by the same independent Docker and full-data checks. See [Groq generation](expert-generation.md).

The blanket no_new_missing rejection is removed. Invalid entries may become NaN. The legacy lost_values audit field retains every affected original value for both accepted and rejected candidates. Committed new NaNs create missing-value obligations and tasks, including columns with no reported original missingness. Type conversion and missing-value handling remain separate; structural and unrelated-column checks still apply.
