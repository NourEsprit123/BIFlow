"""
BiFlow Agent 2 — LLM Data Cleaning & ETL Agent

The agent is an LLM with tools. It reasons step-by-step, calls inspection /
cleaning / approval / sandbox tools, and stops via `finish`.

Ollama performs inference locally. Explicit use_llm=False selects the deterministic
baseline for offline comparisons.
"""

from __future__ import annotations

from dataCleaningTools.contracts import canonical_type, model_arguments

import json
import logging
import math
import time
import hashlib
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dataCleaningTools.agent1_adapter import (
    parse_profiling_report,
    propose_initial_steps,
    resolve_source_path,
)
from dataCleaningTools.models import (
    CleaningResult,
    DatasetStatus,
    ProfilingReport,
    ValidationReport,
    ValidationStatus,
)
from dataCleaningTools.policy import apply_policy
from dataCleaningTools.sandbox import sandbox_status
from dataCleaningTools.tool_registry import AgentSessionState, ToolExecutor
from dataCleaningTools.versioning import DatasetVersionManager
from dataCleaningTools import workflow
from dataCleaningTools.recovery import build_prompt
from dataCleaningTools.llm_client import chat_with_tools, default_model, llm_configured, positive_setting

logger = logging.getLogger("biflow.agent2")

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "cleaning.md"


def _load_system_prompt() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    return "You are BiFlow Agent 2. Clean datasets using tools only. Call finish when done."


def _report_context(report: ProfilingReport, max_chars: int = 6000) -> str:
    """Send the schema and actionable evidence once; full details stay inspectable."""
    columns = {}
    for name, prof in report.column_profiles.items():
        column = {"dtype": prof.dtype}
        if prof.etl_cast_to and prof.etl_cast_to.lower() != "none":
            column["target"] = canonical_type(prof.etl_cast_to)
        if prof.missing_count:
            column["missing"] = prof.missing_count
        if prof.issues:
            column["issues"] = [{"description": i.description[:120]} for i in prof.issues]
            column["samples"] = [str(v)[:60] for v in (prof.sample_values or [])[:3]]
        columns[name] = column
    compact = {"dataset": report.dataset_ref.file_name, "rows": report.dataset_ref.rows,
               "columns": columns, "cleaning_order": report.recommended_cleaning_order,
               "imputation_plan": {k: v.model_dump() for k, v in report.imputation_plan.items()},
               "cast_targets": {c: canonical_type(t) for c, t in report.etl_hints.type_casting_targets.items()},
               "recommendations": report.recommendation_summary[:400]}
    if len(json.dumps(compact, default=str)) > max_chars:
        for column in columns.values():
            column.pop("samples", None)
        compact["note"] = "Use inspection tools for additional evidence."
    return json.dumps(compact, default=str, separators=(",", ":"))


def _tool_feedback(result_json: str) -> str:
    """Keep feedback useful without resending the full audit trail every turn."""
    result = json.loads(result_json)
    # The focused prompt is sent once as a user message after the tool batch.
    # Its full copy remains in the saved event and UI.
    result.pop("recovery_prompt", None)
    if result.get("trials"):
        result["trials"] = [{"partition": t["partition"], "rows": t["rows"], "success": t["success"],
                             "error": t.get("error"), "setup": t.get("setup"),
                             "effect": {"accepted": t["effect"]["accepted"], "changed_cells": t["effect"]["changed_cells"],
                                        "failed_rules": [r for r in t["effect"]["rules"] if not r["passed"]],
                                        "column_metrics": t["effect"].get("column_metrics", {}),
                                        "changed_examples": t["effect"].get("changed_examples", [])} if t.get("effect") else None}
                            for t in result["trials"]]
    if isinstance(result.get("details"), dict) and result["details"].get("full_data_effect"):
        details = result["details"]
        result["details"] = {"candidate_id": details.get("candidate_id"), "code_hash": details.get("code_hash"),
                             "image_id": details.get("image_id"), "full_data_accepted": details["full_data_effect"]["accepted"],
                             "failed_rules": [r for r in details["full_data_effect"]["rules"] if not r["passed"]]}
    effect = result.get("effect")
    if effect:
        result["effect"] = {
            "accepted": effect["accepted"], "changed_cells": effect["changed_cells"],
            "rows_removed": effect["rows_removed"], "columns_removed": effect["columns_removed"],
            "changed_examples": effect.get("changed_examples", []),
            "failed_rules": [r for r in effect["rules"] if not r["passed"]],
            "column_metrics": effect.get("column_metrics", {}),
            "missing_before": effect["before"]["missing"], "missing_after": effect["after"]["missing"],
        }
    result.pop("evidence_ids", None)
    return json.dumps(result, default=str)



def _tool_generation_failed(error) -> bool:
    body = getattr(error, "body", None)
    if getattr(error, "status_code", None) != 400 or not isinstance(body, dict):
        return False
    detail = body.get("error", body)
    return isinstance(detail, dict) and detail.get("code") == "tool_use_failed"


def _request_context(messages, state, *, tools=None, reserved_chars=0):
    """Keep complete recent tool exchanges; current progress is sent separately."""
    tools = workflow.SCHEMAS_LIST if tools is None else tools
    budget = max(1000, (positive_setting("BIFLOW_OLLAMA_NUM_CTX",8192,integer=True)
        - positive_setting("BIFLOW_OLLAMA_NUM_PREDICT",1024,integer=True))*3
        - len(json.dumps(tools))-reserved_chars)
    groups = []
    for message in messages[2:]:
        if message["role"] == "assistant" or not groups: groups.append([])
        groups[-1].append(message)
    recent = groups[-3:]
    while len(recent)>1 and len(json.dumps(messages[:2]+[m for g in recent for m in g]))>budget:
        recent.pop(0)
    return messages[:2]+[m for group in recent for m in group]


class DataCleaningAgent:
    """LLM agent with tool access for data cleaning."""

    def __init__(
        self,
        data_root: Union[str, Path] = "data/versions",
        search_roots: Optional[List[Union[str, Path]]] = None,
        use_llm: Optional[bool] = None,
        max_turns: Optional[int] = None,
        max_seconds: Optional[float] = None,
        approve_all: bool = False,
        dry_run: bool = False,
        model: Optional[str] = None,
    ):
        self.data_root = Path(data_root)
        self.manager = DatasetVersionManager(root=data_root)
        self.search_roots = search_roots or [
            Path("data/raw"),
            Path("data"),
            _ROOT / "data" / "raw",
            _ROOT / "data",
        ]
        self.max_turns = max_turns if max_turns is not None else positive_setting("BIFLOW_CLEANING_MAX_TURNS", 12, integer=True)
        self.max_seconds = max_seconds if max_seconds is not None else positive_setting("BIFLOW_CLEANING_MAX_SECONDS", 300)
        if self.max_turns < 1 or self.max_seconds <= 0 or not math.isfinite(self.max_seconds):
            raise ValueError("Cleaning turn and time budgets must be positive")
        self.approve_all = approve_all
        self.dry_run = dry_run
        self.model = model

        if use_llm is None:
            use_llm = llm_configured()
        self.use_llm = use_llm

    def run(
        self,
        profiling_payload: Union[str, Path, Dict[str, Any], ProfilingReport],
        *,
        approved_step_ids: Optional[List[str]] = None,
        user_request: str = "",
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> CleaningResult:
        report = parse_profiling_report(profiling_payload)
        self.manager = DatasetVersionManager(self.data_root / uuid4().hex[:12])
        source_path = resolve_source_path(report, search_roots=self.search_roots)
        dataset_id = Path(report.dataset_ref.file_name).stem

        v0 = self.manager.register_original(
            source_path,
            dataset_id=dataset_id,
            metadata={
                "agent1_path": report.dataset_ref.file_path,
                "user_request": user_request,
                "source_signature": [str(source_path.resolve()), source_path.stat().st_mtime_ns, source_path.stat().st_size],
            },
        )
        working = self.manager.create_working_copy(v0)

        run_started = time.monotonic()
        def emit(event):
            if on_event:
                on_event({**event, "turn": state.current_turn, "max_turns": self.max_turns,
                          "elapsed_seconds": time.monotonic() - run_started, "max_seconds": self.max_seconds})

        state = AgentSessionState(
            manager=self.manager,
            dataset_id=dataset_id,
            current_ref=working,
            source_ref=v0,
            profiling_summary=report.recommendation_summary,
            approve_all=self.approve_all,
            approved_step_ids=set(approved_step_ids or []),
            on_event=emit if on_event else None,
            run_started=run_started,
            deadline=run_started + self.max_seconds,
            expected_columns=list(v0.columns),
            required_targets={**report.etl_hints.type_casting_targets,
                              **{c: p.etl_cast_to for c, p in report.column_profiles.items()
                                 if p.etl_cast_to and p.etl_cast_to.lower() != "none"}},
            required_missing=[c for c, p in report.column_profiles.items() if p.missing_count > 0],
        )


        state.persist_trace()
        if self.dry_run:
            state.stop_reason = "dry_run"
            state.finish_summary = "dry_run — no mutations"
            state.finished = True
        elif self.use_llm:
            logger.info("Running LLM tool-calling agent (max_turns=%d)", self.max_turns)
            self._run_llm_loop(state, report, user_request)
        else:
            logger.info("Explicit deterministic tool baseline (use_llm=False)")
            self._run_deterministic(state, report, approved_step_ids or [])

        return self._build_result(state, report, user_request)

    def _run_llm_loop(self, state, report, user_request):
        messages = [{"role":"system","content":_load_system_prompt()},
                    {"role":"user","content":self._build_user_message(report,state,user_request)}]
        executor = ToolExecutor(state)
        empty_responses = 0
        repeated = {}
        for turn in range(1,self.max_turns+1):
            if state.finished: break
            if time.monotonic() >= state.deadline:
                state.stop_reason = "time_budget"
                state.finish_summary = f"Stopped: reached the {self.max_seconds:.0f}s run budget."
                state.unresolved.append(state.finish_summary)
                break
            state.current_turn = turn
            if state.on_event: state.on_event({"phase":"Ollama · choosing next action","stage":"model"})
            response = None
            for attempt in range(2):
                try:
                    context = [{"role":"user","content":json.dumps({"outstanding":executor.progress(),
                        "flagged":state.flagged,"profiler_findings":[i.description for profile in report.column_profiles.values() for i in profile.issues],"turn":turn,"max_turns":self.max_turns,
                        "candidates":{key:{"tested":c["tested"],"base_version":c["base_version"],"columns":c["columns"]}
                                      for key,c in list(state.method_candidates.items())[-4:]}})}]
                    response = chat_with_tools(_request_context(messages,state,tools=workflow.SCHEMAS_LIST,
                        reserved_chars=len(json.dumps(context)))+context,workflow.SCHEMAS_LIST,model=self.model,
                        temperature=0.1,on_provider_event=state.on_event,timeout=state.deadline-time.monotonic())
                    for error in state.provider_errors:
                        if error.get("retrying"): error.update(recovered=True,retrying=False)
                    break
                except Exception as exc:
                    retry = _tool_generation_failed(exc) and attempt == 0
                    state.provider_errors.append({"turn":turn,"type":type(exc).__name__,"status_code":getattr(exc,"status_code",None),
                        "message":str(exc),"retrying":retry})
                    state.persist_trace()
                    if retry:
                        guidance = build_prompt(executor, "model_response", {}, {"success":False,"error":str(exc)})
                        messages.append({"role":"user","content":json.dumps(guidance)})
                        state.step_log.append({"turn":turn,"recovery_prompt":guidance})
                        continue
                    state.stop_reason = ("time_budget" if time.monotonic()>=state.deadline else "request_timeout") if isinstance(exc,TimeoutError) else "provider_error"
                    state.unresolved.append(f"Ollama error: {exc}")
                    state.finish_summary = f"Stopped: {state.stop_reason} ({exc})"
                    break
            if response is None: break
            state.llm_provider = response.get("provider",state.llm_provider)
            state.llm_model = response.get("model",state.llm_model)
            state.step_log.append({"turn":turn,"provider":response.get("provider"),"model":response.get("model"),
                "response_finish_reason":response.get("finish_reason"),"tool_call_source":response.get("tool_call_source"),
                "usage":response.get("usage"),"timing":response.get("timing"),"options":response.get("options"),"response_issue":response.get("response_issue")})
            content, calls = response.get("content") or "", response.get("tool_calls") or []
            if content: state.step_log.append({"turn":turn,"reasoning":content})
            assistant = {"role":"assistant","content":content or None}
            if calls:
                assistant["tool_calls"] = [{"id":c["id"],"type":"function","function":{"name":c["name"],
                    "arguments":json.dumps(model_arguments(c["name"],c["arguments"]))}} for c in calls]
            messages.append(assistant)
            if not calls:
                empty_responses += 1
                if empty_responses >= 3:
                    state.stop_reason = "no_tool_calls"
                    state.finish_summary = "Stopped after three consecutive responses without a usable tool call."
                    state.unresolved.append(state.finish_summary)
                    break
                issue = response.get("response_issue") or {"message":"No usable tool call was received"}
                guidance = build_prompt(executor, "model_response", {}, {"success":False,
                    "error":issue.get("message"),"error_kind":issue.get("kind")})
                messages.append({"role":"user","content":json.dumps(guidance)})
                state.step_log.append({"turn":turn,"recovery_prompt":guidance})
                state.persist_trace()
                continue
            empty_responses = 0
            feedback = []
            halted = False
            for call in calls:
                name, args = call["name"], call["arguments"] if isinstance(call["arguments"],dict) else {}
                signature = (state.current_ref.version,name,json.dumps(model_arguments(name,args),sort_keys=True))
                repeated[signature] = repeated.get(signature,0)+1
                if halted or state.finished:
                    result = {"success":False,"error":"Skipped after stop or finish"}
                elif time.monotonic() >= state.deadline:
                    state.stop_reason="time_budget"; state.finish_summary="Run budget expired before tool execution"
                    state.unresolved.append(state.finish_summary); halted=True
                    result={"success":False,"error":state.finish_summary}
                elif name != "finish" and repeated[signature]>=3:
                    state.stop_reason="stalled"; state.finish_summary=f"Stopped: repeated {name} on unchanged {state.current_ref.version}."
                    state.unresolved.append(state.finish_summary); halted=True
                    result={"success":False,"error":state.finish_summary}
                else:
                    result = json.loads(executor.execute(name,args))
                    state.step_log.append({"turn":turn,"tool":name,"args":args,"result_preview":json.dumps(result)[:300]})
                    if result.get("recovery_prompt"):
                        feedback.append({"role":"user","content":json.dumps(result["recovery_prompt"])})
                messages.append({"role":"tool","tool_call_id":call["id"],"content":_tool_feedback(json.dumps(result))})
            messages.extend(feedback)
            state.persist_trace()
            if halted: break
            if state.finished:
                state.stop_reason = "completed" if state.validation.all_passed else "completed_with_exceptions" if state.validation.status==ValidationStatus.PARTIAL else "incomplete"
                break
        else:
            state.stop_reason="max_turns"
            state.finish_summary=f"Stopped: reached max_turns={self.max_turns} before finish."
            state.unresolved.append("max_turns reached")
        state.finished=True
        state.persist_trace()

    def _build_user_message(
        self,
        report: ProfilingReport,
        state: AgentSessionState,
        user_request: str,
    ) -> str:
        parts = [
            "## User objective",
            user_request or "(none — improve data quality for downstream BI)",
            "",
            "## Dataset versions",
            f"- source (immutable): {state.source_ref.version} @ {state.source_ref.path}",
            f"- working: {state.current_ref.version}",
            "",
            "## Agent 1 profiling report (evidence)",
            _report_context(report),
            "BIFlow automatically links problems and observations by column. Do not supply issue or evidence IDs.",
            "",
            "## Instructions",
            "Inspect as needed, test on a copy, then apply a passing candidate with an assessment of its measured results.",
            "Use generated transform(df) experiments when existing methods are insufficient. Data errors require reconsideration and a concrete revision.",
            "Use flag_for_review for ambiguous business decisions. Findings are advisory; current type and missing obligations are measured each turn.",
        ]
        if self.approve_all:
            parts.append(
                "\n(TEST MODE: approve_all=True — you may treat high-risk tools as approved.)"
            )
        return "\n".join(parts)

    def _run_deterministic(
        self,
        state: AgentSessionState,
        report: ProfilingReport,
        approved_step_ids: List[str],
    ) -> None:
        plan = propose_initial_steps(report, state.source_ref)
        plan.steps = [apply_policy(s) for s in plan.steps]
        approved = set(approved_step_ids)
        executor = ToolExecutor(state)

        op_map = {
            "trim_whitespace": "trim_whitespace",
            "normalize_values": "normalize_values",
            "convert_data_types": "convert_data_types",
            "clean_numeric_string": "clean_numeric_string",
            "handle_missing_values": "handle_missing_values",
            "remove_duplicates": "remove_duplicates",
            "drop_column": "drop_column",
        }

        for step in plan.steps:
            tool_name = op_map.get(step.operation)
            if not tool_name:
                state.unresolved.append(f"No tool mapping for {step.operation}")
                continue

            args = dict(step.parameters or {})
            args["step_id"] = step.step_id
            args["rationale"] = step.rationale
            if tool_name in (
                "normalize_values",
                "convert_data_types",
                "clean_numeric_string",
            ):
                if "column" not in args and step.columns:
                    args["column"] = step.columns[0]
            elif tool_name in ("trim_whitespace", "handle_missing_values"):
                if "columns" not in args and step.columns:
                    args["columns"] = step.columns
            elif tool_name == "remove_duplicates":
                if "subset" not in args and step.columns:
                    args["subset"] = step.columns
            elif tool_name == "drop_column":
                if "columns" not in args and step.columns:
                    args["columns"] = step.columns

            if tool_name == "handle_missing_values":
                strat = args.get("strategy", "mode")
                args["strategy"] = {
                    "median": "fill_median",
                    "mean": "fill_mean",
                    "mode": "fill_mode",
                    "drop": "drop_rows",
                }.get(strat, strat)

            result_str = executor.execute_trusted(tool_name, args)
            result = json.loads(result_str)
            if not result.get("success"):
                state.unresolved.append(
                    f"Failed {tool_name}: {result.get('error') or result.get('message')}"
                )

        executor.execute_trusted(
            "validate_dataset",
            {},
        )
        state.stop_reason = "deterministic_completed"
        executor.execute_trusted(
            "finish",
            {
                "summary": "Deterministic pipeline completed",
                "unresolved": list(state.unresolved),
            },
        )

    def _build_result(
        self,
        state: AgentSessionState,
        report: ProfilingReport,
        user_request: str,
    ) -> CleaningResult:
        if self.dry_run:
            validation = ValidationReport(dataset_ref=state.current_ref, status=ValidationStatus.NOT_RUN)
            final = state.current_ref
        else:
            # Always validate the actual final version, including early exits and errors.
            ToolExecutor(state)._validate_dataset({})
            validation = state.validation
            final = state.current_ref if validation.status == ValidationStatus.PARTIAL else self.manager.mark_validated(
                state.current_ref, status=DatasetStatus.VALIDATED if validation.all_passed else DatasetStatus.FAILED)
            validation.dataset_ref = final
        changelog = self.manager.get_changelog(state.dataset_id)

        result_path = self.manager.root / state.dataset_id / "cleaning_result.json"
        result = CleaningResult(
            source_dataset=state.source_ref,
            final_dataset=final,
            change_log=changelog,
            validation=validation,
            unresolved_issues=list(dict.fromkeys(state.unresolved
                + [f"APPROVAL: {p}" for p in state.pending_approvals]
                + validation.unresolved_issues + validation.exceptions)),
            metadata={
                "mode": "llm" if self.use_llm else "deterministic",
                "limits": {"max_turns": self.max_turns, "max_seconds": self.max_seconds},
                "elapsed_seconds": time.monotonic() - state.run_started,
                "turns_used": state.current_turn,
                "model": (state.llm_model or self.model or default_model()) if self.use_llm else None,
                "provider": state.llm_provider,
                "stop_reason": state.stop_reason,
                "provider_errors": state.provider_errors,
                "result_path": str(result_path.resolve()),
                "source_signature": state.source_ref.metadata.get("source_signature"),
                "profiling_report_hash": hashlib.sha256(json.dumps(report.model_dump(mode="json"), sort_keys=True).encode()).hexdigest(),
                "finish_summary": state.finish_summary,
                "step_log": state.step_log,
                "events": state.events,
                "evidence": state.evidence,
                "experiments": state.experiments,
                "flagged": state.flagged,
                "failures": state.failures,
                "method_candidates": state.method_candidates,
                "decisions": state.decisions,
                "sandbox": sandbox_status(),
                "user_request": user_request,
                "agent1_summary": report.agent_summary,
            },
        )
        result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        state.persist_trace()
        return result


def main():
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="BiFlow Agent 2 — LLM Data Cleaning")
    parser.add_argument(
        "report",
        nargs="?",
        default=str(_ROOT / "tests/fixtures/agent1_report_dirty_sales.json"),
    )
    parser.add_argument("--data-root", default=str(_ROOT / "data" / "versions_llm_run"))
    parser.add_argument("--llm", action="store_true", help="Force LLM mode")
    parser.add_argument("--no-llm", action="store_true", help="Force deterministic mode")
    parser.add_argument("--approve-all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model", default=None)
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument("--max-seconds", type=float, default=None)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    use_llm = None
    if args.llm:
        use_llm = True
    if args.no_llm:
        use_llm = False

    print("Sandbox:", json.dumps(sandbox_status(), indent=2))
    effective = use_llm if use_llm is not None else llm_configured()
    print(
        f"LLM configured: {llm_configured()}  model={args.model or default_model()}  "
        f"mode={'llm' if effective else 'deterministic'}"
    )

    agent = DataCleaningAgent(
        data_root=args.data_root,
        use_llm=use_llm,
        max_turns=args.max_turns,
        max_seconds=args.max_seconds,
        approve_all=args.approve_all,
        dry_run=args.dry_run,
        model=args.model,
    )
    result = agent.run(args.report)

    print("\n=== CleaningResult ===")
    print(f"Mode   : {result.metadata.get('mode')}")
    print(f"Source : {result.source_dataset.version}")
    print(f"Final  : {result.final_dataset.version} → {result.final_dataset.path}")
    print(f"Validation: {result.validation.status.value}")
    for r in result.validation.rules:
        print(f"  {'✓' if r.passed else '✗'} {r.rule_name}: {r.message}")
    print(f"Summary: {result.metadata.get('finish_summary')}")
    print(f"Changelog: {len(result.change_log.entries)} entries")
    for e in result.change_log.entries:
        print(
            f"  {e.source_version}→{e.result_version} {e.operation} "
            f"ok={e.success} rows={e.affected_rows}"
        )
    if result.unresolved_issues:
        print("Unresolved:")
        for u in result.unresolved_issues:
            print(f"  - {u}")

    trail = result.metadata.get("step_log") or []
    if trail:
        print("\n=== Reasoning / tool trail (truncated) ===")
        for item in trail[:30]:
            if "reasoning" in item:
                print(f"  [think] {item['reasoning'][:240]}")
            elif "tool" in item:
                print(
                    f"  [tool]  {item['tool']} → {str(item.get('result_preview', ''))[:160]}"
                )

    if args.out:
        Path(args.out).write_text(result.model_dump_json(indent=2), encoding="utf-8")
        print(f"Wrote {args.out}")

    try:
        df = agent.manager.load(result.final_dataset)
        print("\nFinal head:")
        print(df.head(8).to_string())
    except Exception:
        pass


if __name__ == "__main__":
    main()
