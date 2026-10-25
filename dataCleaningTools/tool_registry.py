"""Tool schemas and execution for the data-cleaning agent."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

import pandas as pd
from jsonschema import Draft202012Validator

from analytics.data_quality import run_sandboxed_check
from .cleaning import (
    clean_numeric_string,
    convert_data_types,
    drop_column,
    handle_missing_values,
    normalize_values,
    remove_duplicates,
    trim_whitespace,
)
from .inspection import (
    check_value_patterns,
    inspect_column,
    inspect_duplicates,
    inspect_schema,
)
from .models import (DatasetReference, TransformationStep, ValidationReport,
                     ValidationRuleResult, ValidationStatus)
from .effects import assess_candidate, snapshot, present, target_matches
from .policy import requires_approval
from .versioning import DatasetVersionManager
from .experiments import experiment, promote
from .contracts import canonical_type


def _tool(
    name: str,
    description: str,
    properties: Dict[str, Any],
    required: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


_STRING = {"type": "string"}
_STRING_LIST = {"type": "array", "items": _STRING}
_ERROR_MODE = {"type": "string", "enum": ["coerce", "raise", "ignore"]}

TOOL_SCHEMAS = [
    _tool("inspect_schema", "Inspect the current dataset schema and null counts.", {}),
    _tool(
        "inspect_column",
        "Inspect sample values and statistics for one column.",
        {"column": _STRING, "sample_size": {"type": "integer", "minimum": 1}},
        ["column"],
    ),
    _tool(
        "inspect_duplicates",
        "Inspect duplicate rows, optionally by key columns.",
        {"subset": _STRING_LIST},
    ),
    _tool(
        "check_value_patterns",
        "Inspect common formats and inconsistent values in one column.",
        {"column": _STRING},
        ["column"],
    ),
    _tool(
        "run_custom_check",
        "Run an LLM-generated, read-only column check in the isolated sandbox.",
        {
            "column": _STRING,
            "description": _STRING,
            "code": {"type": "string", "maxLength": 8000},
        },
        ["column", "description", "code"],
    ),
    _tool(
        "trim_whitespace",
        "Trim whitespace in string columns.",
        {"columns": _STRING_LIST},
    ),
    _tool(
        "normalize_values",
        "Edit text spelling, whitespace or case in one column. Does NOT convert types. For boolean flags use convert_data_types with target_type boolean instead. Requires singular column; target_type is unsupported here.",
        {
            "column": _STRING,
            "mapping": {"type": "object", "additionalProperties": {"type": "string"}},
            "strip_whitespace": {"type": "boolean"},
            "case": {"type": ["string", "null"], "enum": ["lower", "upper", "title", None]},
        },
        ["column"],
    ),
    _tool(
        "convert_data_types",
        "Convert a column to a supported dtype. For Yes/No flags use target_type boolean directly; True/False and 1/0 are also supported. Use canonical types; profiling aliases such as float64/int64 are normalized by the executor.",
        {
            "column": _STRING,
            "target_type": {
                "type": "string",
                "enum": ["numeric", "integer", "float", "string", "boolean", "datetime"],
            },
            "errors": _ERROR_MODE,
            "date_format": {"type": ["string", "null"]},
        },
        ["column", "target_type"],
    ),
    _tool(
        "clean_numeric_string",
        "Parse currency and abbreviated numeric text in a column.",
        {"column": _STRING, "errors": _ERROR_MODE},
        ["column"],
    ),
    _tool(
        "handle_missing_values",
        "Handle missing values in explicit columns. Mean/median require numeric columns; inspect and convert numeric strings first. Choose separately justified strategies for text/date columns.",
        {
            "columns": {**_STRING_LIST, "minItems": 1},
            "strategy": {
                "type": "string",
                "enum": [
                    "drop_rows",
                    "drop_columns",
                    "fill_constant",
                    "fill_mean",
                    "fill_median",
                    "fill_mode",
                ],
            },
            "fill_value": {},
        },
        ["columns", "strategy"],
    ),
    _tool(
        "remove_duplicates",
        "Remove duplicate rows, optionally by key columns.",
        {
            "subset": _STRING_LIST,
            "keep": {"type": "string", "enum": ["first", "last"]},
        },
    ),
    _tool(
        "drop_column",
        "Drop specified columns. Requires explicit approval.",
        {"columns": _STRING_LIST},
        ["columns"],
    ),
    _tool(
        "request_approval",
        "Request approval before a high-risk transformation.",
        {
            "step_id": _STRING,
            "operation": _STRING,
            "columns": _STRING_LIST,
            "rationale": _STRING,
        },
        ["operation"],
    ),
    _tool(
        "validate_dataset",
        "Validate required schema, target types, missing values and unresolved actions on the current version. All populated numeric values must parse.",
        {
            "numeric_columns": _STRING_LIST,
        },
    ),
    _tool(
        "finish",
        "Finish the run with a concise summary and unresolved items.",
        {"summary": _STRING, "unresolved": _STRING_LIST},
        ["summary"],
    ),
]


TOOL_SCHEMAS.extend([
    _tool("experiment_cleaning_method",
          "Test generated Python in isolated Docker on disjoint sample and holdout copies. The code must define exactly one top-level function named transform with one df argument. Example:\ndef transform(df):\n    df['amount'] = pd.to_numeric(df['amount'], errors='coerce')\n    return df\nNo working-data changes; return a candidate ID and measured effects. Preserve rows, index, columns and unselected values.",
          {"code": {"type": "string", "maxLength": 8000, "description": "Python source defining exactly one top-level `def transform(df): ...` function that returns a DataFrame. Do not name it clean_data or another name. Example:\ndef transform(df):\n    df['amount'] = pd.to_numeric(df['amount'], errors='coerce')\n    return df\npd, np, re, math are provided; installed pandas/numpy/sklearn can be imported. No host files/network."},
           "columns": _STRING_LIST, "rationale": _STRING, "expected_effect": _STRING,
           "evidence_ids": _STRING_LIST, "sample_size": {"type": "integer", "minimum": 1, "maximum": 500},
           "checks": {"type": "array", "minItems": 1, "items": {"type": "object", "additionalProperties": False,
                      "properties": {"column": _STRING, "kind": {"type": "string", "enum": ["no_missing", "numeric", "integer", "boolean", "datetime", "string", "non_negative", "unique"]}},
                      "required": ["column", "kind"]}}},
          ["code", "columns", "rationale", "expected_effect", "evidence_ids", "checks"]),
    _tool("apply_experimental_method",
          "Apply an unchanged, successfully tested candidate to the full CURRENT dataset inside its pinned sandbox image. Recheck full output before committing a new version. No code argument is accepted.",
          {"candidate_id": _STRING}, ["candidate_id"]),
])


# Shared decision metadata is exposed on every mutation tool.
_MUTATIONS = {"trim_whitespace", "normalize_values", "convert_data_types",
              "clean_numeric_string", "handle_missing_values", "remove_duplicates", "drop_column", "apply_experimental_method"}
for _schema in TOOL_SCHEMAS:
    if _schema["function"]["name"] in _MUTATIONS - {"apply_experimental_method"}:
        _params = _schema["function"]["parameters"]
        _params["properties"].update({
            "step_id": _STRING,
            "rationale": {"type": "string", "description": "Why this action follows from the evidence"},
            "evidence_ids": {"type": "array", "items": _STRING,
                             "description": "IDs of relevant profiling findings or inspection observations"},
        })
        _params["required"] = list(dict.fromkeys(_params["required"] + ["rationale", "evidence_ids"]))


@dataclass
class AgentSessionState:
    manager: DatasetVersionManager
    dataset_id: str
    current_ref: DatasetReference
    source_ref: DatasetReference
    profiling_summary: str = ""
    approve_all: bool = False
    approved_step_ids: Set[str] = field(default_factory=set)
    pending_approvals: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    step_log: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    experiments: Dict[str, Any] = field(default_factory=dict)
    workflow_stage: str = "understand"
    workflow_used: bool = False
    issues: Dict[str, Any] = field(default_factory=dict)
    method_candidates: Dict[str, Any] = field(default_factory=dict)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    failed_actions: Dict[str, str] = field(default_factory=dict)
    required_targets: Dict[str, str] = field(default_factory=dict)
    required_missing: List[str] = field(default_factory=list)
    expected_columns: Optional[List[str]] = None
    validation: Optional[ValidationReport] = None
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None
    finished: bool = False
    finish_summary: str = ""
    run_started: float = field(default_factory=time.monotonic)
    deadline: float = float("inf")
    current_turn: int = 0
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    stop_reason: str = "running"
    provider_errors: List[Dict[str, Any]] = field(default_factory=list)

    def persist_trace(self) -> None:
        path = self.manager.root / self.dataset_id / "execution_trace.json"
        payload = {"current_dataset": self.current_ref.model_dump(mode="json"),
                   "stop_reason": self.stop_reason, "finish_summary": self.finish_summary,
                   "elapsed_seconds": time.monotonic() - self.run_started, "current_turn": self.current_turn,
                   "llm_provider": self.llm_provider, "llm_model": self.llm_model,
                   "events": self.events, "evidence": self.evidence, "experiments": self.experiments,
                   "workflow_stage": self.workflow_stage, "issues": self.issues,
                   "method_candidates": self.method_candidates, "decisions": self.decisions,
                   "step_log": self.step_log, "provider_errors": self.provider_errors,
                   "unresolved": self.unresolved, "pending_approvals": self.pending_approvals}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        # Windows file indexers can briefly hold the existing trace open.
        # Preserve atomic replacement and propagate persistent access failures.
        for attempt in range(4):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 3:
                    raise
                time.sleep(0.05)


class ToolExecutor:
    """Validate, authorize, and execute one registered tool call."""

    def __init__(self, state: AgentSessionState):
        self.state = state

    def progress(self, include_suggestions=True):
        """Measure outstanding requirements against the persisted working data."""
        frame = self.state.manager.load(self.state.current_ref)
        targets = {c: canonical_type(t) for c, t in self.state.required_targets.items()}
        pending_types = {c: t for c, t in targets.items()
                         if c not in frame or not target_matches(frame[c], t)}
        progress = {
            "version": self.state.current_ref.version,
            "pending_types": pending_types,
            "completed_types": [c for c, t in targets.items()
                                if c in frame and target_matches(frame[c], t)],
            "pending_missing": {c: int((~present(frame[c])).sum()) if c in frame else "column absent"
                                for c in self.state.required_missing
                                if c not in frame or not present(frame[c]).all()},
        }
        if include_suggestions:
            progress["suggested_type_calls"] = [self.type_call(c, t) for c, t in pending_types.items() if c in frame][:8]
        return progress

    def type_call(self, column, target):
        evidence = [key for key, item in self.state.evidence.items()
                    if item.get("column") == column or item.get("arguments", {}).get("column") == column]
        return {"tool": "convert_data_types", "arguments": {
            "column": column, "target_type": canonical_type(target), "errors": "raise",
            "rationale": f"The profiling target for {column} is {canonical_type(target)}; convert its type and check the effect.",
            "evidence_ids": evidence,
        }}

    def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        from .workflow import revision_feedback
        source_stage = self.state.workflow_stage
        source_version = self.state.current_ref.version
        if self.state.on_event:
            self.state.on_event({"phase": f"running {name} on {source_version}"})
        started = time.monotonic()
        def operation_args(args):
            return {k: v for k, v in args.items() if k not in {"rationale", "evidence_ids", "step_id"}}
        previous = next((event for event in reversed(self.state.events)
                         if event["tool"] == name and event["source_version"] == source_version
                         and operation_args(event["arguments"]) == operation_args(arguments)
                         and not event["result"].get("success")
                         and not event["result"].get("approval_required")), None) if name in _MUTATIONS else None
        if previous:
            result = {**previous["result"], "repeat_skipped": True,
                      "message": "Identical failed operation on unchanged data was not executed again. Correct the arguments or choose another method."}
        else:
            result = json.loads(self._dispatch(name, arguments))
        feedback = revision_feedback(self.state, name, arguments, result)
        if feedback:
            result["revision_feedback"] = feedback
        if name in _MUTATIONS and not result.get("success") and not result.get("approval_required"):
            columns = arguments.get("columns") or ([arguments["column"]] if arguments.get("column") else [])
            result["recovery"] = {
                "instruction": "Do not repeat this call unchanged. Inspect the named columns, correct the arguments, or test a new transform(df) with experiment_cleaning_method. If no justified repair is possible, finish with explicit unresolved items. Never coerce populated values to missing to pass validation.",
                "next_actions": [{"tool": "inspect_column", "arguments": {"column": c}} for c in columns],
                "missing_value_contract": "Explicit nonempty columns required. fill_mean/fill_median require numeric columns. Text/date imputation needs a separately justified strategy; do not invent replacement values.",
                "supported_types": ["numeric", "integer", "float", "string", "boolean", "datetime"],
            }
        if name == "normalize_values" and (not result.get("success") or result.get("no_op")):
            progress = self.progress()
            result["recovery"] = {
                "instruction": "normalize_values only edits text values; it cannot convert types. Use convert_data_types for the pending type targets. These suggested calls are not executed automatically. If conversion fails, inspect the values before changing them.",
                "next_actions": progress["suggested_type_calls"],
                "pending_types": progress["pending_types"],
            }
        event_id = f"event-{len(self.state.events) + 1}"
        if name.startswith("inspect_") or name in ("check_value_patterns", "run_custom_check"):
            self.state.evidence[event_id] = {
                "source": "inspection", "tool": name, "arguments": arguments,
                "version": source_version, "result": result,
            }
        event = {"duration_seconds": time.monotonic() - started, "event_id": event_id, "tool": name, "arguments": arguments,
                 "source_stage": source_stage, "stage": self.state.workflow_stage,
                 "source_version": source_version, "version": self.state.current_ref.version,
                 "result": result,
                 "evidence": {key: self.state.evidence[key] for key in result.get("evidence_ids", [])}}
        self.state.events.append(event)
        self.state.persist_trace()
        if self.state.on_event:
            self.state.on_event(event)
        return self._json({**result, "event_id": event_id})

    def _dispatch(self, name: str, arguments: Dict[str, Any]) -> str:
        from .workflow import NAMES, dispatch
        if name in NAMES:
            self.state.workflow_used = True
            try:
                return self._json(dispatch(self, name, arguments))
            except (KeyError, TypeError, ValueError) as exc:
                return self._json({"success": False, "error": str(exc)})
        handlers = {
            "inspect_schema": self._inspect_schema,
            "inspect_column": self._inspect_column,
            "inspect_duplicates": self._inspect_duplicates,
            "check_value_patterns": self._check_value_patterns,
            "run_custom_check": self._run_custom_check,
            "trim_whitespace": self._trim_whitespace,
            "normalize_values": self._normalize_values,
            "convert_data_types": self._convert_data_types,
            "clean_numeric_string": self._clean_numeric_string,
            "handle_missing_values": self._handle_missing_values,
            "remove_duplicates": self._remove_duplicates,
            "drop_column": self._drop_column,
            "request_approval": self._request_approval,
            "validate_dataset": self._validate_dataset,
            "finish": self._finish,
            "experiment_cleaning_method": self._experiment_cleaning_method,
            "apply_experimental_method": self._apply_experimental_method,
        }
        handler = handlers.get(name)
        if handler is None:
            return self._json({"success": False, "error": f"Unknown tool: {name}"})
        if not isinstance(arguments, dict):
            return self._json({"success": False, "error": "Tool arguments must be an object"})
        try:
            return self._json(handler(arguments))
        except (KeyError, TypeError, ValueError) as exc:
            return self._json({"success": False, "error": str(exc)})

    def _clean(
        self,
        name: str,
        function: Any,
        arguments: Dict[str, Any],
        columns: List[str],
    ) -> Dict[str, Any]:
        step_id = str(arguments.get("step_id") or f"tool-{uuid4().hex[:8]}")
        step = TransformationStep(
            step_id=step_id,
            operation=name,
            columns=columns,
            parameters=arguments,
            rationale=str(arguments.get("rationale", "")),
        )
        if requires_approval(step) and not (
            self.state.approve_all or step_id in self.state.approved_step_ids
        ):
            message = f"Approval required: {name} {columns} (step_id={step_id})"
            if message not in self.state.pending_approvals:
                self.state.pending_approvals.append(message)
            return {
                "success": False,
                "approval_required": True,
                "step_id": step_id,
                "message": message,
            }

        function_arguments = {key: value for key, value in arguments.items()
                              if key not in ("step_id", "rationale", "evidence_ids")}
        before = self.state.manager.load(self.state.current_ref)
        selected = columns or list(before.columns)
        evidence_ids = list(arguments.get("evidence_ids") or [])
        if not evidence_ids:
            evidence_ids = [key for key, item in self.state.evidence.items()
                            if item.get("column") in selected
                            or item.get("arguments", {}).get("column") in selected
                            or item.get("tool") in ("inspect_schema", "inspect_duplicates")]
        unknown = [key for key in evidence_ids if key not in self.state.evidence]
        if unknown:
            return {"success": False, "error": f"Unknown evidence IDs: {unknown}"}
        if not evidence_ids:
            evidence_id = f"before-{step_id}"
            self.state.evidence[evidence_id] = {
                "source": "pre-transformation measurement", "columns": selected,
                "version": self.state.current_ref.version, "snapshot": snapshot(before),
            }
            evidence_ids = [evidence_id]
        rationale = step.rationale or f"Apply {name} to {', '.join(map(str, selected))}; verify its measured effect."
        result = function(before.copy(), **function_arguments)
        assessment = assess_candidate(before, result.df, name, columns, function_arguments) if result.success and result.df is not None else None
        if assessment and time.monotonic() >= self.state.deadline:
            assessment["rules"].append({"rule_name": "run_budget", "passed": False,
                                        "message": "Run time budget expired before committing the change"})
            assessment["accepted"] = False
        accepted = bool(assessment and assessment["accepted"])
        error = result.error
        if assessment and not accepted:
            error = "; ".join(r["rule_name"] + ": " + r["message"] for r in assessment["rules"] if not r["passed"])
        metadata = {"evidence_ids": evidence_ids, "effect": assessment, "accepted": accepted,
                    "rationale_origin": "agent" if step.rationale else "executor default"}
        if name == "apply_experimental_method":
            metadata["experiment"] = result.details
        action_key = f"{name}:{selected}"
        if accepted:
            self.state.failed_actions.pop(action_key, None)
            # CSV persistence discards extension dtype distinctions (bool versus
            # nullable boolean). Recasting identical persisted values is no work.
            same_values = (before.equals(result.df) or (
                before.index.equals(result.df.index)
                and before.columns.equals(result.df.columns)
                and before.astype("string").equals(result.df.astype("string"))))
            if same_values:
                if name in ("convert_data_types", "clean_numeric_string"):
                    for column in ([function_arguments["column"]] if "column" in function_arguments else selected):
                        self.state.required_targets.setdefault(column, function_arguments.get("target_type", "numeric"))
                return {**result.to_dict(), "success": True, "accepted": True,
                        "no_op": True, "effect": assessment, "evidence_ids": evidence_ids,
                        "rationale": rationale, "version": self.state.current_ref.version,
                        "message": "No persisted values changed; no new version created. Choose an unmet requirement.",
                        "progress": self.progress()}
            new_ref, record = self.state.manager.commit_transformation(
                self.state.current_ref, result.df, operation=name, columns=selected,
                parameters=function_arguments, rationale=rationale, step_id=step_id,
                affected_rows=result.affected_rows, approval_obtained=requires_approval(step),
                metadata=metadata,
            )
            self.state.current_ref = new_ref
            self.state.validation = None
            if name == "drop_column" or (name == "handle_missing_values" and function_arguments.get("strategy") == "drop_columns"):
                if self.state.expected_columns is not None:
                    self.state.expected_columns = list(result.df.columns)
                for column in before.columns.difference(result.df.columns):
                    self.state.required_targets.pop(column, None)
                    self.state.required_missing = [c for c in self.state.required_missing if c != column]
            if name in ("convert_data_types", "clean_numeric_string"):
                for column in ([function_arguments["column"]] if "column" in function_arguments else selected):
                    self.state.required_targets.setdefault(column, function_arguments.get("target_type", "numeric"))
        else:
            self.state.failed_actions[action_key] = f"Rejected {name} on {selected}: {error or result.message}"
            record = self.state.manager.record_rejected(
                self.state.current_ref, operation=name, columns=selected, parameters=function_arguments,
                rationale=rationale, step_id=step_id, error_message=error or result.message,
                metadata=metadata,
            )
        return {**result.to_dict(), "success": accepted, "error": error,
                "accepted": accepted, "effect": assessment, "evidence_ids": evidence_ids,
                "rationale": rationale, "change_id": record.change_id,
                "version": self.state.current_ref.version}

    def _experiment_cleaning_method(self, args):
        return experiment(self.state, args)

    def _apply_experimental_method(self, args):
        candidate_id = args["candidate_id"]
        candidate = self.state.experiments.get(candidate_id)
        if candidate is None:
            raise ValueError("Unknown candidate ID; run experiment_cleaning_method first")
        return self._clean(
            "apply_experimental_method",
            lambda df, candidate_id: promote(self.state, candidate_id, df),
            {"candidate_id": candidate_id, "rationale": candidate["rationale"],
             "evidence_ids": list(dict.fromkeys(candidate["evidence_ids"] + [candidate_id]))},
            candidate["columns"],
        )

    def _inspect_schema(self, _: Dict[str, Any]) -> Dict[str, Any]:
        return inspect_schema(self.state.current_ref, self.state.manager)

    def _inspect_column(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return inspect_column(
            self.state.current_ref,
            column=args["column"],
            sample_size=args.get("sample_size", 20),
            manager=self.state.manager,
        )

    def _inspect_duplicates(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return inspect_duplicates(
            self.state.current_ref,
            subset=args.get("subset"),
            manager=self.state.manager,
        )

    def _check_value_patterns(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return check_value_patterns(
            self.state.current_ref,
            column=args["column"],
            manager=self.state.manager,
        )

    def _run_custom_check(self, args: Dict[str, Any]) -> Dict[str, Any]:
        column = args["column"]
        description = str(args["description"]).strip()
        code = args["code"]
        if not description:
            raise ValueError("A custom check description is required.")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("Custom check code must be a non-empty string.")

        df = self.state.manager.load(self.state.current_ref)
        if column not in df.columns:
            raise ValueError(f"Column not found: {column}")

        sample = df[column].head(500)
        result = run_sandboxed_check(code, sample, timeout_sec=8)
        execution_succeeded = result.get("error") is None
        if not execution_succeeded:
            self.state.unresolved.append(
                f"Custom check for '{column}' was not completed: "
                f"{result.get('error') or result['details']}"
            )
        return {
            "success": execution_succeeded,
            "column": column,
            "description": description,
            "sample_size": len(sample),
            "check_passed": result["passed"] if execution_succeeded else None,
            "details": result["details"],
            "backend": result.get("backend"),
            "error": result.get("error"),
        }

    def _trim_whitespace(self, args: Dict[str, Any]) -> Dict[str, Any]:
        columns = args.get("columns", [])
        return self._clean("trim_whitespace", trim_whitespace, args, columns)

    def _normalize_values(self, args: Dict[str, Any]) -> Dict[str, Any]:
        schema = next(t["function"]["parameters"] for t in TOOL_SCHEMAS
                      if t["function"]["name"] == "normalize_values")
        # Metadata may be inferred from measurements by the executor; operation
        # arguments must still obey the published contract before execution.
        errors = list(Draft202012Validator({**schema, "required": ["column"]}).iter_errors(args))
        if errors:
            raise ValueError("Invalid normalize_values arguments: " + "; ".join(e.message for e in errors)
                             + ". This tool edits text, not types; use convert_data_types(column=..., target_type='boolean') for booleans.")
        return self._clean("normalize_values", normalize_values, args, [args["column"]])

    def _convert_data_types(self, args: Dict[str, Any]) -> Dict[str, Any]:
        effective = {**args, "target_type": canonical_type(args["target_type"])}
        if effective["target_type"] not in {"numeric", "integer", "float", "string", "boolean", "datetime"}:
            raise ValueError("Unsupported target_type. Use numeric, integer, float, string, boolean or datetime.")
        result = self._clean("convert_data_types", convert_data_types, effective, [args["column"]])
        if effective != args:
            result["normalized_arguments"] = effective
        return result

    def _clean_numeric_string(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self._clean("clean_numeric_string", clean_numeric_string, args, [args["column"]])

    def _handle_missing_values(self, args: Dict[str, Any]) -> Dict[str, Any]:
        columns = args.get("columns", [])
        if not isinstance(columns, list) or not columns or any(not isinstance(c, str) for c in columns):
            raise ValueError("Specify a nonempty columns list; choose columns and a strategy using profiling or inspection evidence.")
        frame = self.state.manager.load(self.state.current_ref)
        unknown = [c for c in columns if c not in frame]
        if unknown:
            raise ValueError(f"Unknown columns: {unknown}")
        if args.get("strategy") in {"fill_mean", "fill_median"}:
            invalid = [c for c in columns if not pd.api.types.is_numeric_dtype(frame[c]) or pd.api.types.is_bool_dtype(frame[c])]
            if invalid:
                raise ValueError(f"{args['strategy']} requires numeric columns; incompatible columns: {invalid}. Inspect and convert numeric strings first. Choose a justified separate strategy for text/date columns.")
        step = TransformationStep(
            operation="handle_missing_values",
            columns=columns,
            parameters=args,
        )
        step_id = str(args.get("step_id") or f"tool-{uuid4().hex[:8]}")
        if requires_approval(step) and not (
            self.state.approve_all or step_id in self.state.approved_step_ids
        ):
            message = f"Approval required: handle_missing_values {columns} (step_id={step_id})"
            if message not in self.state.pending_approvals:
                self.state.pending_approvals.append(message)
            return {
                "success": False,
                "approval_required": True,
                "step_id": step_id,
                "message": message,
            }
        return self._clean(
            "handle_missing_values",
            handle_missing_values,
            {**args, "step_id": step_id},
            columns,
        )

    def _remove_duplicates(self, args: Dict[str, Any]) -> Dict[str, Any]:
        columns = args.get("subset", [])
        return self._clean("remove_duplicates", remove_duplicates, args, columns)

    def _drop_column(self, args: Dict[str, Any]) -> Dict[str, Any]:
        columns = args["columns"]
        return self._clean("drop_column", drop_column, args, columns)

    def _request_approval(self, args: Dict[str, Any]) -> Dict[str, Any]:
        step_id = str(args.get("step_id") or f"tool-{uuid4().hex[:8]}")
        operation = str(args["operation"])
        columns = args.get("columns", [])
        step = TransformationStep(
            step_id=step_id,
            operation=operation,
            columns=columns,
            rationale=str(args.get("rationale", "")),
        )
        if not requires_approval(step):
            self.state.approved_step_ids.add(step_id)
            return {"success": True, "approved": True, "step_id": step_id}
        if self.state.approve_all or step_id in self.state.approved_step_ids:
            self.state.approved_step_ids.add(step_id)
            return {"success": True, "approved": True, "step_id": step_id}
        message = f"Awaiting approval: {operation} {columns} (step_id={step_id})"
        if message not in self.state.pending_approvals:
            self.state.pending_approvals.append(message)
        return {
            "success": True,
            "approved": False,
            "step_id": step_id,
            "message": message,
        }

    def _validate_dataset(self, args: Dict[str, Any]) -> Dict[str, Any]:
        df = self.state.manager.load(self.state.current_ref)
        rules = []
        def check(name, passed, message):
            rules.append(ValidationRuleResult(rule_name=name, passed=bool(passed), message=message))
        check("non_empty", not df.empty, f"rows={len(df)}")
        if self.state.expected_columns is not None:
            check("expected_columns", list(df.columns) == self.state.expected_columns,
                  "Required columns must be preserved unless removal was approved")
        for column in args.get("numeric_columns", []):
            self.state.required_targets.setdefault(column, "numeric")
        targets = self.state.required_targets
        for column, target in targets.items():
            check(f"target_type:{column}", column in df and target_matches(df[column], target),
                  f"All populated values in {column} must match {target}")
        for column in self.state.required_missing:
            check(f"missing_resolved:{column}", column in df and present(df[column]).all(),
                  f"Reported missing values in {column} must be resolved")
        if self.state.workflow_used:
            from .workflow import refresh
            refresh(self.state)
            for key, issue in self.state.issues.items():
                check(f"issue:{key}", issue["status"] == "resolved", f"{key}: {issue['status']}")
        for issue in dict.fromkeys(self.state.unresolved + self.state.pending_approvals + list(self.state.failed_actions.values())):
            check("unresolved", False, issue)
        failed = [r for r in rules if not r.passed]
        self.state.validation = ValidationReport(
            dataset_ref=self.state.current_ref,
            status=ValidationStatus.FAILED if failed else ValidationStatus.PASSED,
            rules=rules, schema_ok=all(r.passed for r in rules if r.rule_name == "expected_columns"),
            quality_ok=not failed, unresolved_issues=[r.message for r in failed],
        )
        return {"success": not failed, "version": self.state.current_ref.version,
                "status": self.state.validation.status.value,
                "rules": [r.model_dump() for r in rules]}

    def _finish(self, args: Dict[str, Any]) -> Dict[str, Any]:
        self.state.finish_summary = str(args["summary"])
        self.state.unresolved.extend(
            item for item in args.get("unresolved", []) if item not in self.state.unresolved
        )
        validation = self._validate_dataset({})
        self.state.finished = True
        return {
            "success": validation["success"],
            "validation": validation,
            "summary": self.state.finish_summary,
            "unresolved": self.state.unresolved,
        }

    @staticmethod
    def _json(value: Dict[str, Any]) -> str:
        return json.dumps(value, default=str)
