"""Tool schemas and execution for the data-cleaning agent."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

import pandas as pd

from .cleaning import (
    apply_and_commit,
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
from .models import DatasetReference, TransformationStep
from .policy import requires_approval
from .versioning import DatasetVersionManager


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
        "trim_whitespace",
        "Trim whitespace in string columns.",
        {"columns": _STRING_LIST},
    ),
    _tool(
        "normalize_values",
        "Normalize values in a column using explicit options and mappings.",
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
        "Convert a column to a supported dtype.",
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
        "Handle missing values using an explicit strategy.",
        {
            "columns": _STRING_LIST,
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
        ["strategy"],
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
        "Validate that the current dataset is non-empty and selected columns are parseable.",
        {
            "numeric_columns": _STRING_LIST,
            "min_parseable_ratio": {"type": "number", "minimum": 0, "maximum": 1},
        },
    ),
    _tool(
        "finish",
        "Finish the run with a concise summary and unresolved items.",
        {"summary": _STRING, "unresolved": _STRING_LIST},
        ["summary"],
    ),
]


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
    finished: bool = False
    finish_summary: str = ""


class ToolExecutor:
    """Validate, authorize, and execute one registered tool call."""

    def __init__(self, state: AgentSessionState):
        self.state = state

    def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        handlers = {
            "inspect_schema": self._inspect_schema,
            "inspect_column": self._inspect_column,
            "inspect_duplicates": self._inspect_duplicates,
            "check_value_patterns": self._check_value_patterns,
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

        function_arguments = {
            key: value
            for key, value in arguments.items()
            if key not in ("step_id", "rationale")
        }
        new_ref, record, result = apply_and_commit(
            self.state.manager,
            self.state.current_ref,
            function,
            operation_name=name,
            affected_columns=columns,
            rationale=step.rationale,
            step_id=step_id,
            approval_obtained=requires_approval(step),
            **function_arguments,
        )
        self.state.current_ref = new_ref
        return {
            **result.to_dict(),
            "change_id": record.change_id,
            "version": new_ref.version,
        }

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

    def _trim_whitespace(self, args: Dict[str, Any]) -> Dict[str, Any]:
        columns = args.get("columns", [])
        return self._clean("trim_whitespace", trim_whitespace, args, columns)

    def _normalize_values(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self._clean("normalize_values", normalize_values, args, [args["column"]])

    def _convert_data_types(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self._clean("convert_data_types", convert_data_types, args, [args["column"]])

    def _clean_numeric_string(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self._clean("clean_numeric_string", clean_numeric_string, args, [args["column"]])

    def _handle_missing_values(self, args: Dict[str, Any]) -> Dict[str, Any]:
        columns = args.get("columns", [])
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
        minimum = args.get("min_parseable_ratio", 0.5)
        rules = [
            {
                "rule": "non_empty",
                "passed": not df.empty,
                "message": f"rows={len(df)}",
            }
        ]
        for column in args.get("numeric_columns", []):
            if column not in df.columns:
                rules.append(
                    {
                        "rule": f"numeric_parseable:{column}",
                        "passed": False,
                        "message": "column not found",
                    }
                )
                continue
            ratio = float(pd.to_numeric(df[column], errors="coerce").notna().mean())
            rules.append(
                {
                    "rule": f"numeric_parseable:{column}",
                    "passed": ratio >= minimum,
                    "message": f"parseable_ratio={ratio:.2f}",
                }
            )
        return {
            "success": all(rule["passed"] for rule in rules),
            "version": self.state.current_ref.version,
            "rules": rules,
        }

    def _finish(self, args: Dict[str, Any]) -> Dict[str, Any]:
        self.state.finish_summary = str(args["summary"])
        self.state.unresolved.extend(
            item for item in args.get("unresolved", []) if item not in self.state.unresolved
        )
        self.state.finished = True
        return {
            "success": True,
            "summary": self.state.finish_summary,
            "unresolved": self.state.unresolved,
        }

    @staticmethod
    def _json(value: Dict[str, Any]) -> str:
        return json.dumps(value, default=str)
