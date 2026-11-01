"""Focused public tools and a single independently checked commit boundary."""
from __future__ import annotations
import json
import time
import pandas as pd
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from jsonschema import Draft202012Validator
from .contracts import canonical_type, model_arguments
from .effects import assess_candidate, change_impact, snapshot, present, target_matches, failure_summary
from .experiments import digest, promote
from .inspection import inspect_schema, inspect_column, inspect_duplicates, check_value_patterns
from .method_catalog import SCHEMAS as METHOD_SCHEMAS
from .models import DatasetReference, TransformationStep, ValidationReport, ValidationRuleResult, ValidationStatus
from .policy import requires_approval
from .versioning import DatasetVersionManager

# Failures confined to one task: with a task queue they drop that task instead of ending the run.
TASK_LEVEL_FAILURES = {"correction_exhausted", "expert_generation_failed", "request_correction_failed",
                       "local_correction_error", "tool_execution_error", "sandbox_unavailable",
                       "sandbox_timeout", "no_tool_calls", "context_budget"}

@dataclass
class AgentSessionState:
    manager: DatasetVersionManager
    dataset_id: str
    current_ref: DatasetReference
    source_ref: DatasetReference
    approve_all: bool = False
    approved_step_ids: Set[str] = field(default_factory=set)
    pending_approvals: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    model_unresolved: List[str] = field(default_factory=list)
    step_log: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    experiments: Dict[str, Any] = field(default_factory=dict)
    method_candidates: Dict[str, Any] = field(default_factory=dict)
    repair_history: List[Dict[str, Any]] = field(default_factory=list)
    expert_generations: Dict[str, Any] = field(default_factory=dict)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    flagged: Dict[str, str] = field(default_factory=dict)
    failures: Dict[str, int] = field(default_factory=dict)
    finish_attempts: int = 0
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
    working_report: Dict[str, Any] = field(default_factory=dict)
    working_context: Dict[str, Any] = field(default_factory=dict)
    cleaning_tasks: List[Dict[str, Any]] = field(default_factory=list)
    focused_cleaning: bool = False
    sandbox_checked: bool = False
    sandbox_error: Optional[str] = None
    inspection_progress: Dict[str, Any] = field(default_factory=dict)
    max_task_turns: int = 6
    max_task_failures: int = 4
    task_drops: List[Dict[str, Any]] = field(default_factory=list)

    def stop(self, reason, error=None):
        """Set the terminal state; persistence is handled at the caller's boundary."""
        self.finished, self.stop_reason = True, reason
        if error:
            self.finish_summary = f"Stopped: {error}"
            if error not in self.unresolved:
                self.unresolved.append(error)

    def audit(self):
        return {name: getattr(self, name) for name in (
            "events", "evidence", "experiments", "method_candidates", "decisions", "repair_history",
            "expert_generations", "flagged", "failures", "finish_attempts", "step_log", "provider_errors",
            "unresolved", "model_unresolved", "pending_approvals", "working_context", "cleaning_tasks", "inspection_progress",
            "task_drops")}

    def persist_trace(self):
        """Save state without loading data or changing task completion."""
        path = self.manager.root / self.dataset_id / "execution_trace.json"
        payload = {"current_dataset": self.current_ref.model_dump(mode="json"),
            "stop_reason": self.stop_reason, "finish_summary": self.finish_summary,
            "elapsed_seconds": time.monotonic()-self.run_started, "current_turn": self.current_turn,
            "llm_provider": self.llm_provider, "llm_model": self.llm_model,
            **self.audit()}
        self._write_snapshot(path, payload)
        if self.working_report:
            self._write_snapshot(path.with_name("cleaning_context.json"), {
                "profiling_report_copy": self.working_report,
                "progress": self.working_context, "cleaning_tasks": self.cleaning_tasks})

    @staticmethod
    def _write_snapshot(path, payload):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        for attempt in range(4):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 3: raise
                time.sleep(0.05)

class ToolExecutor:
    def __init__(self, state):
        self.state = state

    def progress(self, frame=None):
        if frame is None:
            frame = self.state.manager.load(self.state.current_ref)
        return {"version": self.state.current_ref.version,
            "pending_types": {c: canonical_type(t) for c,t in self.state.required_targets.items()
                if c not in self.state.flagged and (c not in frame or not target_matches(frame[c],t))},
            "pending_missing": {c: int((~present(frame[c])).sum()) if c in frame else "column absent"
                for c in self.state.required_missing if c not in self.state.flagged
                and (c not in frame or not present(frame[c]).all())},
            "flagged": dict(self.state.flagged)}

    def execute(self, name, arguments, *, origin="model"):
        from .cleaning_tasks import active
        task = active(self.state)
        task_id = task["id"] if task else None
        source = self.state.current_ref.version
        if self.state.on_event: self.state.on_event({"phase": f"running {name} on {source}"})
        started = time.monotonic()
        from .repair_history import repeated_failure, remember
        canonical = model_arguments(name, arguments)
        from .workflow import TEST_TOOLS, validate_request
        # Selecting generated execution commits this task to that path. A wrong
        # code layout must be repaired, never interpreted as permission to fall back.
        if task and (name == "test_generated" or (isinstance(canonical, dict)
                and (canonical.get("code") or isinstance(canonical.get("parameters"), dict)
                     and canonical["parameters"].get("code")))):
            task["generated_required"] = True
        result = validate_request(name, canonical)
        previous = repeated_failure(self.state, canonical) if result is None and name in TEST_TOOLS else None
        if previous:
            result = {"success": False, "error_kind": "duplicate_method", "candidate_status": "failed",
                      "candidate_id": previous.get("candidate_id"), "tested": False,
                      "failure_summary": previous.get("failure_summary") or {},
                      "previous_attempt": previous["attempt_id"],
                      "error": "Already tested on this version. This candidate failed. Do not apply or repeat it. Change the actual transformation, inspect missing evidence, or flag genuine ambiguity and continue other pending columns."}
        elif result is None:
            result = self._dispatch(name, canonical)
        if task and result.get("success") is False and (result.get("error_kind") == "invalid_tool_arguments"
                or name in {"inspect_data", "complete_task"} and result.get("error_kind") not in {"inspection_no_progress", "tool_execution"}):
            from .investigation import stalled
            original_error = result.get("error", "Invalid request")
            result = stalled(self, original_error + f" Active task: {task['id']}; exact columns: {task['columns']}. "
                "Use these column names, not row values, 'value', or placeholders.", task=task)
            result["original_error"] = original_error
            if name != "inspect_data" and not result.get("task_deferred"):
                result["error_kind"] = "invalid_tool_arguments"
        elif task and name in TEST_TOOLS and (result.get("trials") or result.get("tested")):
            progress = self.state.inspection_progress.get(f"{source}:{task['id']}")
            if progress:
                progress["consecutive_stalls"] = 0
        if result.get("error_kind") == "tool_execution":
            self.stop("tool_execution_error", result["error"])
            result["fatal"] = True
        details = result.get("details") if isinstance(result.get("details"), dict) else {}
        if result.get("success") is False and not result.get("failure_summary") and (result.get("effect") or details.get("full_data_effect")):
            result["failure_summary"] = failure_summary(result)
            result["error"] = result["failure_summary"]["reason"]
        from .recovery import build_prompt
        guidance = None if result.get("fatal") else build_prompt(self, name, arguments, result)
        if guidance:
            result["recovery_prompt"] = guidance
            if "diagnostic" in guidance["context"]:
                result["diagnostic"] = guidance["context"]["diagnostic"]
        if guidance and guidance["case"] == "sandbox_unavailable":
            # A timed-out Docker reply drops this task only; later tasks check Docker again.
            transient = result.get("transient") or any(t.get("transient") for t in result.get("trials", []))
            self.stop("sandbox_timeout" if transient else "sandbox_unavailable",
                      result.get("error") or "Docker execution is unavailable")
            result.update(fatal=True, error_kind="sandbox_unavailable")
        if name in TEST_TOOLS and isinstance(canonical, dict) and not previous:
            remember(self.state, canonical, result)
        elif name == "apply_candidate" and result.get("success") is False and isinstance(canonical, dict):
            candidate_id = canonical.get("candidate_id")
            candidate = self.state.method_candidates.get(candidate_id) if isinstance(candidate_id, str) else None
            if candidate:
                remember(self.state, candidate, result)
        if task and result.get("approval_required") and not task.get("measured") and task["status"] == "pending":
            # The decision now belongs to the host; the run moves on without freezing the columns.
            task.update(status="awaiting_approval", step_id=result["step_id"], reason=result["message"],
                        assessed_version=self.state.current_ref.version)
            self.state.validation = None
            result["task_closed"] = "awaiting_approval"
        return self._record(name, arguments, result, source, started, origin=origin, task_id=task_id)

    def stop(self, reason, error):
        """Stop the run, or only drop the active task when the failure is confined to it."""
        from .cleaning_tasks import active, drop
        task = active(self.state) if self.state.focused_cleaning else None
        if reason == "sandbox_unavailable":
            # Later tasks lose generated code but keep builtins.
            self.state.sandbox_error = error
        if task and reason in TASK_LEVEL_FAILURES:
            drop(self.state, task, reason, error)
        else:
            self.state.stop(reason, error)
        self.state.persist_trace()

    def _record(self, name, arguments, result, source, started, *, origin="host", task_id=None):
        from .contracts import model_arguments
        canonical_arguments = model_arguments(name, arguments)
        event_id = f"event-{len(self.state.events)+1}"
        if name.startswith("inspect_") or name == "check_value_patterns":
            self.state.evidence[event_id] = {"source": "inspection", "tool": name,
                "arguments": arguments, "version": source, "result": result}
        event = {"duration_seconds": time.monotonic()-started, "event_id": event_id,
            "task_id": task_id,
            "tool": name, "arguments": canonical_arguments, "source_version": source, "origin": origin,
            "version": self.state.current_ref.version, "result": result,
            "evidence": {k:self.state.evidence[k] for k in result.get("evidence_ids",[])}}
        if canonical_arguments != arguments:
            event["raw_arguments"] = arguments
        explanation_field = {"inspect_data": "reason", "test_builtin": "hypothesis", "test_generated": "hypothesis",
            "apply_candidate": "assessment", "flag_for_review": "reason", "complete_task": "reason", "finish": "summary"}.get(name)
        if isinstance(canonical_arguments, dict) and explanation_field:
            event["explanation"] = canonical_arguments.get(explanation_field)
        self.state.events.append(event)
        from .working_context import refresh
        if not result.get("fatal") and (name != "inspect_data" or result.get("task_deferred")):
            refresh(self.state)
        self.state.persist_trace()
        if self.state.on_event: self.state.on_event(event)
        return self._json({**result,"event_id":event_id})

    def _dispatch(self, name, arguments):
        from .workflow import dispatch
        try:
            return dispatch(self,name,arguments)
        except ValueError as exc:
            return {"success":False,"error":str(exc)}
        except Exception as exc:
            return {"success":False,"error_kind":"tool_execution",
                    "error":f"Tool execution failed ({type(exc).__name__}): {exc}"}

    def execute_trusted(self, name, arguments):
        """Host-only deterministic baseline/core checks, never model dispatch."""
        source, started = self.state.current_ref.version, time.monotonic()
        args = {k:v for k,v in arguments.items() if k not in {"step_id","evidence_ids"}}
        try:
            inspect = {"inspect_schema":self._inspect_schema,"inspect_column":self._inspect_column,
                "inspect_duplicates":self._inspect_duplicates,"check_value_patterns":self._check_value_patterns}
            if name in inspect: result = inspect[name](args)
            elif name == "validate_dataset": result = self._validate_dataset(args)
            elif name == "finish": result = self._finish(args)
            elif name in METHOD_SCHEMAS:
                from .workflow import run_builtin
                columns = args.get("columns") or ([args["column"]] if "column" in args else list(self.state.current_ref.columns))
                parameters = {k:v for k,v in args.items() if k != "rationale"}
                if name == "convert_data_types": parameters["target_type"] = canonical_type(parameters["target_type"])
                errors = list(Draft202012Validator(METHOD_SCHEMAS[name]).iter_errors(parameters))
                if errors: raise ValueError("; ".join(e.message for e in errors))
                result = self._clean(name, lambda df,**p: run_builtin(df,name,p),
                    {**parameters,"rationale":args.get("rationale","")}, columns)
            else: result = {"success":False,"error":f"Unknown trusted operation: {name}"}
        except (KeyError,TypeError,ValueError) as exc:
            result = {"success":False,"error":str(exc)}
        return self._record(name,arguments,result,source,started)

    def _clean(
        self,
        name: str,
        function: Any,
        arguments: Dict[str, Any],
        columns: List[str],
    ) -> Dict[str, Any]:
        if self.state.finished:
            return {"success": False, "error": "Run is finished; start a new run before applying transformations"}
        step_id = "step-" + digest(json.dumps({"op": name, "cols": sorted(columns),
            "args": {k: v for k, v in arguments.items() if k not in {"rationale", "evidence_ids", "step_id"}}},
            sort_keys=True, default=str).encode())[:12]
        from .cleaning_tasks import active
        task = active(self.state) if self.state.focused_cleaning else None
        step = TransformationStep(
            step_id=step_id,
            operation=name,
            columns=columns,
            parameters=arguments,
            rationale=str(arguments.get("rationale", "")),
            # Capping or blanking unusual values changes business figures; a passing trial is not enough.
            requires_approval=bool(task and task["category"] == "outliers"),
        )
        # Evaluated on a copy first: approval is requested only for an accepted change to actual values.
        needs_approval = requires_approval(step) and not (
            self.state.approve_all or step_id in self.state.approved_step_ids)
        if not needs_approval:
            self.state.pending_approvals = [p for p in self.state.pending_approvals if f"(step_id={step_id})" not in p]
        function_arguments = {key: value for key, value in arguments.items()
                              if key not in ("step_id", "rationale", "evidence_ids")}
        before = self.state.manager.load(self.state.current_ref)
        selected = columns or list(before.columns)
        if set(selected) & set(self.state.flagged):
            return {"success": False, "error": "Columns flagged for human review cannot be changed"}
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
        if assessment and name in {"convert_data_types", "clean_numeric_string", "handle_missing_values"}:
            from .cleaning_tasks import active
            from .numeric_expectations import numeric_rules
            from .value_interpretation import boolean_rules
            task = active(self.state) if self.state.focused_cleaning else None
            if not task or task["category"] in {"types", "missing"}:
                numeric_columns = [c for c in selected if c in result.df and pd.api.types.is_numeric_dtype(result.df[c])
                                   and not pd.api.types.is_bool_dtype(result.df[c])]
                assessment["rules"].extend(numeric_rules(before, result.df, numeric_columns))
                boolean_columns = [c for c in selected if c in result.df and (
                    pd.api.types.is_bool_dtype(result.df[c]) or
                    canonical_type(self.state.required_targets.get(c, "")) == "boolean")]
                assessment["rules"].extend(boolean_rules(before, result.df, boolean_columns))
                assessment["accepted"] = all(rule["passed"] for rule in assessment["rules"])
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
        if accepted:
            # CSV persistence discards extension dtype distinctions (bool versus
            # nullable boolean). Recasting identical persisted values is no work.
            same_values = (before.equals(result.df) or (
                before.index.equals(result.df.index)
                and before.columns.equals(result.df.columns)
                and before.astype("string").equals(result.df.astype("string"))))
            if same_values:
                if name in ("convert_data_types", "clean_numeric_string", "parse_datetime"):
                    for column in ([function_arguments["column"]] if "column" in function_arguments else selected):
                        self.state.required_targets.setdefault(column, "datetime" if name == "parse_datetime"
                                                               else function_arguments.get("target_type", "numeric"))
                prog = self.progress()
                msg = ("No persisted values changed; all required type and missing obligations are satisfied. Call finish."
                       if not prog.get("pending_types") and not prog.get("pending_missing")
                       and not any(t["status"] == "pending" for t in self.state.cleaning_tasks)
                       else "No persisted values changed; no new version created. Choose an unmet requirement.")
                return {**result.to_dict(), "success": True, "accepted": True,
                        "no_op": True, "effect": assessment, "evidence_ids": evidence_ids,
                        "rationale": rationale, "version": self.state.current_ref.version,
                        "message": msg,
                        "progress": prog}
            if needs_approval:
                impact = change_impact(before, result.df, selected)
                if (impact["rows_after"] == impact["rows"] and not impact["columns_removed"]
                        and not any(impact["values_changed"].values())):
                    return {**result.to_dict(), "success": True, "accepted": True, "no_op": True,
                            "effect": assessment, "impact": impact, "version": self.state.current_ref.version,
                            "message": "No values would change (only the dtype); nothing committed and no approval needed."}
                change = (f"would change {impact['rows_changed']} of {impact['rows']} rows" if "rows_changed" in impact
                          else f"would keep {impact['rows_after']} of {impact['rows']} rows")
                message = f"Approval required: {name} {columns} {change} (step_id={step_id})"
                self.state.pending_approvals = [p for p in self.state.pending_approvals if f"(step_id={step_id})" not in p]
                self.state.pending_approvals.append(message)
                return {"success": False, "approval_required": True, "step_id": step_id,
                        "message": message, "impact": impact}
            new_ref, record = self.state.manager.commit_transformation(
                self.state.current_ref, result.df, operation=name, columns=selected,
                parameters=function_arguments, rationale=rationale, step_id=step_id,
                affected_rows=result.affected_rows, approval_obtained=requires_approval(step),
                metadata=metadata,
            )
            self.state.current_ref = new_ref
            self.state.validation = None
            # Newly coerced invalid values become ordinary missing-value work.
            # Register only committed data, never a sample/trial copy.
            for column in selected:
                if (column in result.df and column not in self.state.required_missing
                        and (~present(result.df[column])).sum() > (~present(before[column])).sum()):
                    self.state.required_missing.append(column)
            if name == "drop_column" or (name == "handle_missing_values" and function_arguments.get("strategy") == "drop_columns"):
                if self.state.expected_columns is not None:
                    self.state.expected_columns = list(result.df.columns)
                for column in before.columns.difference(result.df.columns):
                    self.state.required_targets.pop(column, None)
                    self.state.required_missing = [c for c in self.state.required_missing if c != column]
            if name in ("convert_data_types", "clean_numeric_string", "parse_datetime"):
                for column in ([function_arguments["column"]] if "column" in function_arguments else selected):
                    self.state.required_targets.setdefault(column, "datetime" if name == "parse_datetime"
                                                           else function_arguments.get("target_type", "numeric"))
        else:
            record = self.state.manager.record_rejected(
                self.state.current_ref, operation=name, columns=selected, parameters=function_arguments,
                rationale=rationale, step_id=step_id, error_message=error or result.message,
                metadata=metadata,
            )
        return {**result.to_dict(), "success": accepted, "error": error,
                "accepted": accepted, "effect": assessment, "evidence_ids": evidence_ids,
                "rationale": rationale, "change_id": record.change_id,
                "version": self.state.current_ref.version}

    def _apply_experimental_method(self, args):
        candidate = self.state.experiments.get(args["candidate_id"])
        if candidate is None: raise ValueError("Unknown generated candidate")
        return self._clean("apply_experimental_method",
            lambda df,candidate_id: promote(self.state,candidate_id,df),
            {"candidate_id":args["candidate_id"],"rationale":candidate["rationale"]},candidate["columns"])

    def _inspect_schema(self, args):
        return inspect_schema(self.state.current_ref,self.state.manager)
    def _inspect_column(self, args):
        return inspect_column(self.state.current_ref,args["column"],args.get("limit",args.get("sample_size",20)),self.state.manager)
    def _inspect_duplicates(self, args):
        return inspect_duplicates(self.state.current_ref,args.get("subset"),self.state.manager,args.get("limit",10))
    def _check_value_patterns(self, args):
        return check_value_patterns(self.state.current_ref,args["column"],self.state.manager)

    def _validate_dataset(self, args):
        for c in args.get("numeric_columns",[]): self.state.required_targets.setdefault(c,"numeric")
        frame = self.state.manager.load(self.state.current_ref)
        from .working_context import refresh
        refresh(self.state, frame=frame)
        rules = []
        def check(name,passed,message): rules.append(ValidationRuleResult(rule_name=name,passed=bool(passed),message=message))
        check("non_empty",not frame.empty,f"rows={len(frame)}")
        if self.state.expected_columns is not None:
            check("expected_columns",list(frame.columns)==self.state.expected_columns,"Required columns must be preserved unless removal was approved")
        for c,target in self.state.required_targets.items():
            if c not in self.state.flagged:
                check(f"target_type:{c}",c in frame and target_matches(frame[c],target),f"{c} must match {target}")
        for c in self.state.required_missing:
            if c not in self.state.flagged:
                check(f"missing_resolved:{c}",c in frame and present(frame[c]).all(),f"Reported missing values in {c} must be resolved")
        exceptions = list(dict.fromkeys([f"{c}: {reason}" for c,reason in self.state.flagged.items()]
            + self.state.unresolved + self.state.model_unresolved + self.state.pending_approvals))
        if self.state.focused_cleaning:
            pending = [t for t in self.state.cleaning_tasks if t["status"] == "pending"]
            check("cleaning_tasks_assessed", not pending, "All reported cleaning tasks must be addressed or explicitly flagged")
            exceptions += [f"{t['category']} ({', '.join(t['columns']) or 'dataset'}): {t.get('reason', 'Needs review')}"
                           for t in self.state.cleaning_tasks
                           if t["status"] in {"needs_review", "dropped", "blocked", "awaiting_approval"} and not t.get("measured")]
        failed = [r for r in rules if not r.passed]
        status = ValidationStatus.FAILED if failed else ValidationStatus.PARTIAL if exceptions else ValidationStatus.PASSED
        self.state.validation = ValidationReport(dataset_ref=self.state.current_ref,status=status,rules=rules,
            schema_ok=all(r.passed for r in rules if r.rule_name=="expected_columns"), quality_ok=not failed,
            unresolved_issues=[r.message for r in failed],exceptions=exceptions)
        return {"success":not failed,"version":self.state.current_ref.version,"status":status.value,
            "rules":[r.model_dump() for r in rules],"exceptions":exceptions}

    def _finish(self, args):
        self.state.finish_summary = args["summary"]
        previous_unresolved = list(self.state.model_unresolved)
        # A finish call is the model's current assessment. Host failures,
        # review flags and pending approvals have independent lifetimes.
        self.state.model_unresolved = list(dict.fromkeys(args.get("unresolved", [])))
        validation = self._validate_dataset({})
        self.state.finish_attempts += 1
        self.state.finished = validation["success"] or self.state.finish_attempts >= 2
        return {"success":validation["success"],"validation":validation,"summary":args["summary"],
                "unresolved": list(self.state.model_unresolved), "previous_unresolved": previous_unresolved,
                "exceptions":validation["exceptions"]}

    @staticmethod
    def _json(value): return json.dumps(value,default=str)
