# Case-specific recovery prompts

## Value review before method selection

`inspect_data(view="column")` now includes `value_overview`: a full-column scan
with frequency counts, common/rare syntax examples and explicit raw-value
coverage. Up to 50 distinct values are shown initially. The `values` view accepts
`offset` and `limit` (1–100) for additional pages. Nulls are counted separately.
Counts over all rows do not imply that every raw value was displayed. Large
format vocabularies show the largest and rarest groups with explicit group/row
coverage; syntax signatures do not establish business meaning.

The prompts ask the model to include `value_assessment` in `test_builtin/test_generated`, covering
observed evidence/coverage, justified interpretation, information preservation,
and ambiguity before implementing a repair. This optional structured field is
retained in events/candidates and supplied to correction requests when present.
It guides and exposes the model's decision without certifying its semantics or
overriding independent acceptance checks. No extra LLM calls are made by the
column scan.

The focused seven-tool workflow uses a profiling-driven category queue. `dataCleaningTools/prompts/cleaning.md` supplies
common instructions; `dataCleaningTools/recovery.py` selects one focused prompt
from `dataCleaningTools/prompts/recovery/` when an action fails or makes no change.

| Case | Focus |
| --- | --- |
| arguments | Repair the contract without inventing a data problem |
| imputation | Diagnose incompatible dtypes, entirely missing columns, unresolved nulls and strategy ambiguity |
| conversion | Inspect representations and revise the parser |
| data_loss | Legacy diagnostic: new NaNs alone no longer reject a candidate; inspect the actual remaining failed checks |
| sandbox_execution | Correct generated code/signatures using the actual exception |
| sandbox_unavailable | Report infrastructure limits; never use a host execution fallback |
| validation | Revise against measured failed candidate checks |
| final_validation | Address only outstanding obligations or explicitly report blockers |
| no_change | Reassess why the method had no effect |
| duplicate_method | Distinguish failed, passing and already-applied candidates; retain original failed-trial evidence |
| stale_candidate | Test again after data or method changes |
| approval_required | Respect host-only authorization |
| response_format | Return a complete registered action with valid arguments |
| truncated_response | Shorten the response so a complete action fits |
| general | Diagnose other failures without silently repeating them |

For an imputation failure, the prompt includes the requested strategy, selected
columns, actual error, failed checks, working dtypes, missing counts and small
value examples. Failed applications resolve their original method from the
candidate, so imputation guidance remains specific even though the public tool
was `apply_candidate`. Generated runner failures distinguish infrastructure from
Python execution using structured error kinds.

The chosen case, instruction and measured context are stored in the tool event
as `recovery_prompt` and shown in the UI. The model receives that prompt once as
a user message, after every tool response in the batch has been matched. Raw
trial/error data stays in the tool response; the instruction is not duplicated
there. Model-response repair prompts are recorded in `step_log`.

Generated trial failures have a bounded self-correction loop (up to three model
revisions per invocation). Request errors use `repair_request` so invalid fields
such as check names can be corrected without changing the algorithm. Valid
existing checks and the intended outcomes of recognized type aliases remain
required. Syntax/runtime failures use `repair_method`; infrastructure, approval,
stale-candidate and duplicate failures return to the main agent without code-repair
calls. Docker setup/input/output transfer exceptions are infrastructure failures;
a nonzero Python exit remains an execution failure.

Correction schemas are internal controller contracts. The live Ollama correction
request uses its JSON-schema `format` parameter with no tool selection, and the
client validates the returned JSON before adapting it to that contract. Normal
agent tool calls remain unchanged. Invalid/truncated JSON never executes. Raw
correction responses, finish reasons, parser diagnostics and usage remain in the
audit log. Correction context contains one diagnostic, relevant observations,
all reported loss evidence, required outcomes and compact recent history;
duplicated tracebacks and nested recovery prompts are excluded.

After a data-validation failure the repair tool requires a concrete `proposal`
covering supported interpretations, information preservation and ambiguity. The
model implements and explains the repair; the controller never supplies the
cleaning algorithm. A proposal does not bypass measured acceptance checks.

Run-scoped `repair_history` retains attempted methods, outcomes and diagnostics
in the execution trace and cleaning report. A compact recent summary is included
with each main-model and correction request. The controller checks the entire
history on the same dataset version, independent of chat trimming. Generated
implementations use an AST fingerprint to ignore formatting/comments; builtin
implementations use canonical parameters. Explanations and outcome checks do not
make a failed implementation new. Invalid requests may be corrected without
changing their code. Repeated blocked tests return feedback so other pending work
can continue, within the existing run/turn limits. Mandatory acceptance, approval
and resource limits remain in force.

Tests verify prompt selection, invalid-argument robustness, persistence, and a
mocked model loop where a real median-on-text failure reaches the next request
as imputation-specific guidance. They do not establish live model compliance.
