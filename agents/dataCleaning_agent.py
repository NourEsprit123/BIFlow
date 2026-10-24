"""
BiFlow Agent 2 — LLM Data Cleaning & ETL Agent

The agent is an LLM with tools. It reasons step-by-step, calls inspection /
cleaning / approval / sandbox tools, and stops via `finish`.

Fallback: if no LLM is configured, a deterministic planner runs the same tools
so tests still work offline.
"""

from __future__ import annotations

import json
import logging
import re
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
    TransformationStatus,
    ValidationReport,
    ValidationStatus,
)
from dataCleaningTools.policy import apply_policy, requires_approval
from dataCleaningTools.sandbox import sandbox_status
from dataCleaningTools.tool_registry import TOOL_SCHEMAS, AgentSessionState, ToolExecutor
from dataCleaningTools.versioning import DatasetVersionManager
from dataCleaningTools.llm_client import chat_with_tools, default_model, llm_configured

logger = logging.getLogger("biflow.agent2")

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "data_cleaning_system.md"


def _load_system_prompt() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    return "You are BiFlow Agent 2. Clean datasets using tools only. Call finish when done."


def _report_context(report: ProfilingReport, max_chars: int = 12000) -> str:
    compact = {
        "schema_version": report.schema_version,
        "dataset": {"file_name": report.dataset_ref.file_name, "rows": report.dataset_ref.rows, "columns": report.dataset_ref.columns},
        "health_scores": report.health_scores.model_dump(),
        "recommended_cleaning_order": report.recommended_cleaning_order,
        "imputation_plan": {k: v.model_dump() for k, v in report.imputation_plan.items()},
        "etl_hints": report.etl_hints.model_dump(),
        "agent_summary": report.agent_summary[:400],
        "recommendation_summary": report.recommendation_summary[:600],
        "columns": {},
    }
    for name, prof in report.column_profiles.items():
        compact["columns"][name] = {
            "dtype": prof.dtype,
            "inferred_role": prof.inferred_role,
            "missing_pct": prof.missing_pct,
            "severity": prof.severity,
            "sample_values": [str(v)[:100] for v in (prof.sample_values or [])[:3]],
            "issues": [
                {
                    "issue_id": i.issue_id,
                    "severity": i.severity,
                    "description": i.description[:200],
                }
                for i in prof.issues
            ],
            "imputation_strategy": prof.imputation_strategy,
            "etl_cast_to": prof.etl_cast_to,
        }
    text = json.dumps(compact, default=str)
    if len(text) > max_chars:
        # Keep every column's issue/type/missing signals and keep the JSON valid.
        for column in compact["columns"].values():
            column.pop("sample_values", None)
            for issue in column["issues"]:
                issue["description"] = issue["description"][:240]
                issue.pop("evidence", None)
        compact["detail_note"] = "Some samples/evidence omitted; use inspection tools and the evidence catalog."
    return json.dumps(compact, default=str)


def _tool_feedback(result_json: str) -> str:
    """Keep feedback useful without resending the full audit trail every turn."""
    result = json.loads(result_json)
    if result.get("trials"):
        result["trials"] = [{"partition": t["partition"], "rows": t["rows"], "success": t["success"],
                             "error": t.get("error"), "setup": t.get("setup"),
                             "effect": {"accepted": t["effect"]["accepted"], "changed_cells": t["effect"]["changed_cells"],
                                        "failed_rules": [r for r in t["effect"]["rules"] if not r["passed"]],
                                        "changed_examples": t["effect"].get("changed_examples", [])} if t.get("effect") else None}
                            for t in result["trials"]]
    if isinstance(result.get("details"), dict) and result["details"].get("full_data_effect"):
        details = result["details"]
        result["details"] = {"candidate_id": details["candidate_id"], "code_hash": details["code_hash"],
                             "image_id": details["image_id"], "full_data_accepted": details["full_data_effect"]["accepted"],
                             "failed_rules": [r for r in details["full_data_effect"]["rules"] if not r["passed"]]}
    effect = result.get("effect")
    if effect:
        result["effect"] = {
            "accepted": effect["accepted"], "changed_cells": effect["changed_cells"],
            "rows_removed": effect["rows_removed"], "columns_removed": effect["columns_removed"],
            "changed_examples": effect.get("changed_examples", []),
            "failed_rules": [r for r in effect["rules"] if not r["passed"]],
            "missing_before": effect["before"]["missing"], "missing_after": effect["after"]["missing"],
        }
    return json.dumps(result, default=str)



def _rate_limit_delay(error) -> float | None:
    if getattr(error, "status_code", None) != 429:
        return None
    headers = getattr(getattr(error, "response", None), "headers", {})
    value = headers.get("retry-after") or headers.get("x-ratelimit-reset-tokens")
    if not value:
        return None
    try:
        delay = float(value)
    except ValueError:
        match = re.fullmatch(r"(?:(\d+(?:\.\d+)?)m)?(\d+(?:\.\d+)?)s", value)
        if not match:
            return None
        delay = float(match.group(1) or 0) * 60 + float(match.group(2))
    return delay + 0.5 if 0 < delay <= 44 else None


def _tool_generation_failed(error) -> bool:
    body = getattr(error, "body", None)
    if getattr(error, "status_code", None) != 400 or not isinstance(body, dict):
        return False
    detail = body.get("error", body)
    return isinstance(detail, dict) and detail.get("code") == "tool_use_failed"


def _request_context(messages, state):
    """Retain complete recent exchanges and a factual summary of older actions."""
    groups = []
    for message in messages[2:]:
        if message["role"] == "assistant" or not groups:
            groups.append([])
        groups[-1].append(message)
    if len(groups) <= 6:
        return messages
    summary = {
        "current_version": state.current_ref.version,
        "accepted_actions": [{"operation": e["tool"], "columns": e["arguments"].get("columns") or [e["arguments"].get("column")], "version": e["version"]}
                             for e in state.events if e["result"].get("accepted")],
        "failed_actions": state.failed_actions,
        "pending_approvals": state.pending_approvals,
        "tested_candidates": {key: {"tested": item["tested"], "base_version": item["base_version"], "columns": item["columns"]}
                              for key, item in state.experiments.items()},
        "inspection_evidence": {key: {"tool": item["tool"], "version": item["version"], "arguments": item["arguments"]}
                                for key, item in state.evidence.items() if item.get("source") == "inspection"},
    }
    return messages[:2] + [{"role": "user", "content": "Earlier execution summary: " + json.dumps(summary, default=str)}] + [m for group in groups[-6:] for m in group]


class DataCleaningAgent:
    """LLM agent with tool access for data cleaning."""

    def __init__(
        self,
        data_root: Union[str, Path] = "data/versions",
        search_roots: Optional[List[Union[str, Path]]] = None,
        use_llm: Optional[bool] = None,
        max_turns: int = 25,
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
        self.max_turns = max_turns
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

        state = AgentSessionState(
            manager=self.manager,
            dataset_id=dataset_id,
            current_ref=working,
            source_ref=v0,
            profiling_summary=report.recommendation_summary,
            approve_all=self.approve_all,
            approved_step_ids=set(approved_step_ids or []),
            on_event=on_event,
            expected_columns=list(v0.columns),
            required_targets={**report.etl_hints.type_casting_targets,
                              **{c: p.etl_cast_to for c, p in report.column_profiles.items()
                                 if p.etl_cast_to and p.etl_cast_to.lower() != "none"}},
            required_missing=[c for c, p in report.column_profiles.items() if p.missing_count > 0],
            evidence={f"profile:{c}:{i.issue_id}:{n}": {
                "source": i.source, "column": c, "issue_id": i.issue_id,
                "description": i.description, "evidence": i.evidence,
            } for c, p in report.column_profiles.items() for n, i in enumerate(p.issues)},
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
            logger.info("No LLM configured — deterministic tool pipeline")
            self._run_deterministic(state, report, approved_step_ids or [])

        return self._build_result(state, report, user_request)

    def _run_llm_loop(
        self,
        state: AgentSessionState,
        report: ProfilingReport,
        user_request: str,
    ) -> None:
        system = _load_system_prompt()
        user_msg = self._build_user_message(report, state, user_request)

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]
        executor = ToolExecutor(state)
        empty_responses = 0
        incomplete_finishes = 0

        for turn in range(1, self.max_turns + 1):
            if state.finished:
                break

            logger.info("--- LLM turn %d ---", turn)
            if state.on_event:
                state.on_event({"phase": f"choosing next action (turn {turn}/{self.max_turns})"})
            response = None
            rate_retries = format_retries = 0
            for attempt in range(5):
                try:
                    response = chat_with_tools(
                        _request_context(messages, state), TOOL_SCHEMAS, model=self.model, temperature=0.1,
                        provider=state.llm_provider, on_provider_event=state.on_event
                    )
                    for error in state.provider_errors:
                        if error.get("retrying"):
                            error["recovered"] = True
                            error["retrying"] = False
                    break
                except Exception as e:
                    logger.exception("LLM call failed")
                    status = getattr(e, "status_code", None)
                    # A subsequent HTTP response other than 429 proves the
                    # prior rate-limit wait worked, even if generation fails.
                    if status is not None and status != 429:
                        for error in state.provider_errors:
                            if error.get("retrying") and error.get("status_code") == 429:
                                error.update(recovered=True, retrying=False)
                    delay = _rate_limit_delay(e) if rate_retries < 2 and attempt < 4 else None
                    repair = _tool_generation_failed(e) and format_retries < 2 and attempt < 4
                    state.provider_errors.append({"turn": turn, "type": type(e).__name__,
                                                  "status_code": status,
                                                  "message": str(e), "retrying": delay is not None or repair})
                    state.persist_trace()
                    if delay is not None:
                        rate_retries += 1
                        if state.on_event:
                            state.on_event({"phase": f"provider rate limit; retrying in {delay:.0f}s"})
                        time.sleep(delay)
                        continue
                    if repair:
                        format_retries += 1
                        # Ask the provider to regenerate. Never parse/execute
                        # failed_generation or silently rewrite a tool name.
                        messages.append({"role": "user", "content": (
                            "The provider rejected your generated tool call. Regenerate one valid call "
                            "using the exact, case-sensitive registered function name and JSON arguments. "
                            "Do not append channel markers, commentary, XML, or other text to tool names. "
                            "The rejected call was not executed."
                        )})
                        if state.on_event:
                            state.on_event({"phase": "regenerating malformed provider tool call"})
                        continue
                    for error in state.provider_errors:
                        error["retrying"] = False
                    state.stop_reason = "provider_error"
                    state.unresolved.append(f"LLM error: {e}")
                    state.finished = True
                    state.finish_summary = f"Aborted: LLM error ({e})"
                    state.persist_trace()
                    break
            if response is None:
                break

            if response.get("provider"):
                if response.get("fallback_reason"):
                    state.provider_switches.append({"turn": turn, "provider": response["provider"],
                                                    "model": response.get("model"), "reason": response["fallback_reason"]})
                state.llm_provider = response["provider"]
                state.llm_model = response.get("model")
            state.step_log.append({"turn": turn, "provider": response.get("provider"), "model": response.get("model"),
                                   "response_finish_reason": response.get("finish_reason"),
                                   "usage": response.get("usage")})
            content = response.get("content") or ""
            tool_calls = response.get("tool_calls") or []

            if content:
                logger.info("Reasoning: %s", content[:500])
                state.step_log.append({"turn": turn, "reasoning": content})

            assistant_msg: Dict[str, Any] = {"role": "assistant", "content": content or None}
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    for tc in tool_calls
                ]
            messages.append(assistant_msg)

            if not tool_calls:
                empty_responses += 1
                state.persist_trace()
                if empty_responses >= 3:
                    state.finished = True
                    state.stop_reason = "no_tool_calls"
                    state.finish_summary = "Stopped after three consecutive responses without a tool call."
                    state.unresolved.append(state.finish_summary)
                    break
                messages.append({"role": "user", "content": (
                    "No tool was called. Cleaning is not complete merely because a response ended. "
                    "Continue with registered tools, or call finish with explicit unresolved items if blocked."
                )})
                continue
            empty_responses = 0

            for tc in tool_calls:
                name = tc["name"]
                args = tc["arguments"] if isinstance(tc["arguments"], dict) else {}
                logger.info("Tool call: %s(%s)", name, json.dumps(args)[:200])
                result_str = executor.execute(name, args)
                logger.info("Tool result: %s", result_str[:400])
                state.step_log.append(
                    {
                        "turn": turn,
                        "tool": name,
                        "args": args,
                        "result_preview": result_str[:300],
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": _tool_feedback(result_str),
                    }
                )
                if name == "finish":
                    validation_ok = state.validation is not None and state.validation.all_passed
                    blocked = bool(args.get("unresolved") or state.pending_approvals or state.unresolved)
                    if not validation_ok and not blocked and incomplete_finishes < 2:
                        incomplete_finishes += 1
                        state.finished = False
                        messages.append({"role": "user", "content": (
                            "Final validation failed. Continue cleaning using the failed rules above. "
                            "If a remaining issue cannot be resolved safely, call finish with an explicit "
                            "unresolved explanation. Do not claim completion after just one operation."
                        )})
                    else:
                        state.finished = True
                        state.stop_reason = "completed" if validation_ok else "incomplete"
                        break

        if not state.finished:
            state.finished = True
            state.finish_summary = f"Stopped: reached max_turns={self.max_turns} before a validated finish."
            state.unresolved.append("max_turns reached")
            state.stop_reason = "max_turns"
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
            "Evidence catalog (cite relevant IDs when applying a transformation):",
            json.dumps({key: {field: item.get(field) for field in ("column", "issue_id", "source")}
                        for key, item in state.evidence.items()}, default=str),
            "",
            "## Instructions",
            "1. Reason briefly about the main issues.",
            "2. Use inspection tools if you need more evidence.",
            "3. Apply cleaning tools in a sensible order (see recommended_cleaning_order).",
            "4. Use run_custom_check only when a specific uncertain column needs a "
            "read-only check that the registered tools cannot answer.",
            "5. Use request_approval for high-risk or ambiguous actions.",
            "6. Call validate_dataset when major columns are cleaned.",
            "7. Call finish with a summary when done or blocked.",
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
            if requires_approval(step) and not self.approve_all and step.step_id not in approved:
                state.unresolved.append(
                    f"Awaiting approval: {step.operation} {step.columns} — {step.rationale}"
                )
                step.status = TransformationStatus.PROPOSED
                continue

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

            result_str = executor.execute(tool_name, args)
            result = json.loads(result_str)
            if not result.get("success"):
                state.unresolved.append(
                    f"Failed {tool_name}: {result.get('error') or result.get('message')}"
                )

        executor.execute(
            "validate_dataset",
            {},
        )
        state.stop_reason = "deterministic_completed"
        executor.execute(
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
            ToolExecutor(state).execute("validate_dataset", {})
            validation = state.validation
            final = self.manager.mark_validated(
                state.current_ref,
                status=DatasetStatus.VALIDATED if validation.all_passed else DatasetStatus.FAILED,
            )
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
                + validation.unresolved_issues)),
            metadata={
                "mode": "llm" if self.use_llm else "deterministic",
                "model": (state.llm_model or self.model or default_model()) if self.use_llm else None,
                "provider": state.llm_provider,
                "provider_switches": state.provider_switches,
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
    parser.add_argument("--max-turns", type=int, default=25)
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
