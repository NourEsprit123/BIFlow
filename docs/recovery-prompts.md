# Case-specific recovery prompts

The flat five-tool workflow is unchanged. `agents/prompts/cleaning.md` supplies
common instructions; `dataCleaningTools/recovery.py` selects one focused prompt
from `agents/prompts/recovery/` when an action fails or makes no change.

| Case | Focus |
| --- | --- |
| arguments | Repair the contract without inventing a data problem |
| imputation | Diagnose incompatible dtypes, entirely missing columns, unresolved nulls and strategy ambiguity |
| conversion | Inspect representations and revise the parser |
| data_loss | Preserve populated information; do not fill over values erased by coercion |
| sandbox_execution | Correct generated code/signatures using the actual exception |
| sandbox_unavailable | Report infrastructure limits; never use a host execution fallback |
| validation | Revise against measured failed candidate checks |
| final_validation | Address only outstanding obligations or explicitly report blockers |
| no_change | Reassess why the method had no effect |
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

Routing selects feedback, not an automatic repair. The model still decides
whether to inspect, change the method, use generated code, flag for review or
finish. Mandatory acceptance, approval and resource limits are unchanged.

Tests verify prompt selection, invalid-argument robustness, persistence, and a
mocked model loop where a real median-on-text failure reaches the next request
as imputation-specific guidance. They do not establish live model compliance.
