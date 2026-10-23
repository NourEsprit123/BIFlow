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
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

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
    ValidationRuleResult,
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
        "dataset": report.dataset_ref.model_dump(),
        "health_scores": report.health_scores.model_dump(),
        "recommended_cleaning_order": report.recommended_cleaning_order,
        "imputation_plan": {k: v.model_dump() for k, v in report.imputation_plan.items()},
        "etl_hints": report.etl_hints.model_dump(),
        "metadata": report.metadata.model_dump(),
        "agent_summary": report.agent_summary,
        "recommendation_summary": report.recommendation_summary,
        "columns": {},
    }
    for name, prof in report.column_profiles.items():
        compact["columns"][name] = {
            "dtype": prof.dtype,
            "inferred_role": prof.inferred_role,
            "missing_pct": prof.missing_pct,
            "severity": prof.severity,
            "sample_values": (prof.sample_values or [])[:8],
            "issues": [
                {
                    "issue_id": i.issue_id,
                    "severity": i.severity,
                    "description": i.description,
                    "evidence": i.evidence,
                }
                for i in prof.issues
            ],
            "imputation_strategy": prof.imputation_strategy,
            "etl_cast_to": prof.etl_cast_to,
        }
    text = json.dumps(compact, indent=2, default=str)
    if len(text) > max_chars:
        return text[:max_chars] + "\n… [truncated]"
    return text


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
    ) -> CleaningResult:
        report = parse_profiling_report(profiling_payload)
        source_path = resolve_source_path(report, search_roots=self.search_roots)
        dataset_id = Path(report.dataset_ref.file_name).stem

        v0 = self.manager.register_original(
            source_path,
            dataset_id=dataset_id,
            metadata={
                "agent1_path": report.dataset_ref.file_path,
                "user_request": user_request,
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
        )

        if self.dry_run:
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

        for turn in range(1, self.max_turns + 1):
            if state.finished:
                break

            logger.info("--- LLM turn %d ---", turn)
            try:
                response = chat_with_tools(
                    messages, TOOL_SCHEMAS, model=self.model, temperature=0.1
                )
            except Exception as e:
                logger.exception("LLM call failed")
                state.unresolved.append(f"LLM error: {e}")
                state.finished = True
                state.finish_summary = f"Aborted: LLM error ({e})"
                break

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
                if turn >= 3:
                    state.finished = True
                    state.finish_summary = content or "Stopped: no tool calls"
                    break
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Continue by calling tools, or call `finish` with a summary "
                            "if the dataset is ready or you are blocked."
                        ),
                    }
                )
                continue

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
                        "content": result_str,
                    }
                )
                if name == "finish" or state.finished:
                    state.finished = True
                    break

        if not state.finished:
            state.finished = True
            state.finish_summary = state.finish_summary or (
                f"Reached max_turns={self.max_turns} without finish()"
            )
            state.unresolved.append("max_turns reached")

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
            {"numeric_columns": ["Revenue", "MonthlyCost", "Quantity"]},
        )
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
        import pandas as pd

        final = self.manager.mark_validated(
            state.current_ref,
            status=DatasetStatus.VALIDATED
            if not state.unresolved
            else DatasetStatus.WORKING,
        )
        changelog = self.manager.get_changelog(state.dataset_id)

        df = self.manager.load(final)
        rules = [
            ValidationRuleResult(
                rule_name="non_empty",
                passed=len(df) > 0,
                message=f"rows={len(df)}",
            )
        ]
        for col in ("Revenue", "MonthlyCost", "Quantity"):
            if col in df.columns:
                ratio = float(pd.to_numeric(df[col], errors="coerce").notna().mean())
                rules.append(
                    ValidationRuleResult(
                        rule_name=f"numeric_parseable:{col}",
                        passed=ratio >= 0.5,
                        message=f"parseable_ratio={ratio:.2f}",
                    )
                )
        failed = [r for r in rules if not r.passed]
        status = (
            ValidationStatus.PASSED
            if not failed
            else ValidationStatus.PARTIAL
            if len(failed) < len(rules)
            else ValidationStatus.FAILED
        )
        validation = ValidationReport(
            dataset_ref=final,
            status=status,
            rules=rules,
            quality_ok=not failed,
            unresolved_issues=[r.message for r in failed],
        )

        return CleaningResult(
            source_dataset=state.source_ref,
            final_dataset=final,
            change_log=changelog,
            validation=validation,
            unresolved_issues=state.unresolved
            + [f"APPROVAL: {p}" for p in state.pending_approvals],
            metadata={
                "mode": "llm" if self.use_llm else "deterministic",
                "finish_summary": state.finish_summary,
                "step_log": state.step_log,
                "sandbox": sandbox_status(),
                "user_request": user_request,
                "agent1_summary": report.agent_summary,
            },
        )


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