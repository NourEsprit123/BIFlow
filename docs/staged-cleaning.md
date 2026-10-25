# Staged cleaning and method experimentation

The local LLM follows an issue ledger through understand, propose, evaluate,
revise, apply and conclude stages. Stage prompts live in
`agents/prompts/cleaning_stages/`. `dataCleaningTools/workflow.py` owns the small
model-facing interface. Legacy tools remain internal for trusted execution and
the explicit deterministic baseline.

The six visible tools are `inspect_data`, `test_method`, `review_candidate`,
`apply_candidate`, `request_review`, and `finish`. Only the tools relevant to
the current stage are sent to Ollama. Builtin methods are described by a compact
catalog, including their parameter shapes.

Every proposal names issue IDs, evidence, a hypothesis, assumptions, expected
effects, affected columns, and outcome checks. Builtins run on independent data
copies; generated `transform(df)` functions run only inside the existing isolated
Docker runner. Both paths report disjoint sample/holdout effects and preserve the
working version during trials. A one-row dataset explicitly lacks a holdout.

The LLM reviews trial outcomes before application. Successful trials and an
accepting review are prerequisites, not proof of full-data correctness. Applying
reruns the unchanged candidate on the full current dataset, checks its effects,
and commits only if accepted. Changed methods, checks, source bytes or versions
require fresh testing. Existing independent validation remains authoritative.

Data errors, invalid requests, failed trials, full-data failures and no-op
transformations produce a `revision_feedback` object in the trace and an explicit
user-role prompt in the next model context. This includes measured failures and
asks for a concrete changed method or further inspection. It never executes a
suggested repair automatically. Model HTTP failures remain provider failures,
with the existing bounded formatting retry; they are not disguised as data errors.

Each issue permits three failed trials/full-data attempts within the existing
overall turn/time budget. An unchanged candidate on unchanged data cannot be
retested. Ambiguous business decisions are marked awaiting review; overlapping
experiments cannot bypass that state. Failed applications remain in the audit
trail; their active failure flags are cleared only after a subsequent accepted
candidate resolves their associated issues.

The UI displays hypotheses, assumptions, stages, trial measurements, candidate
assessments, returned revision prompts and the issue ledger. Detailed decisions
and candidate specifications are persisted in both trace and result artifacts.

Current scope: the unified trial path supports nonstructural cleaning. Row/column
removal is routed to human review rather than silently enabled through generated
code. Profiling findings without automatic postconditions require a tested,
reviewed candidate or remain unresolved; model-declared expectations cannot
override application checks. Sample/holdout feedback is development evidence,
not a substitute for a separate held-out behavioral evaluation dataset.

`tests/test_staged_cleaning.py` verifies builtin rejection followed by generated
revision, explicit error prompts, mandatory review, full-data rejection,
immutability, issue budgets and review blocking. Docker and Ollama are mocked;
these tests establish control-loop correctness, not live model reliability or
real container availability. Live local-model evaluation remains a separate step.
