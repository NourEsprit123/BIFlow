# Simple cleaning workflow

The model sees five fixed tools: inspect_data, test_method, apply_candidate,
flag_for_review, and finish. One prompt lives at agents/prompts/cleaning.md.
There is no stage machine, issue tracker, evidence-ID contract or separate
review action. Profiler findings are advisory text; type and missing-value
obligations are computed from the current working data.

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
