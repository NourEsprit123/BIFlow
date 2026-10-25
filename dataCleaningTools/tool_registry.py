"""Five public tools and a single independently checked commit boundary."""
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from jsonschema import Draft202012Validator
from .contracts import canonical_type
from .effects import assess_candidate, snapshot, present, target_matches
from .experiments import digest, promote
from .inspection import inspect_schema, inspect_column, inspect_duplicates, check_value_patterns
from .method_catalog import SCHEMAS as METHOD_SCHEMAS
from .models import DatasetReference, TransformationStep, ValidationReport, ValidationRuleResult, ValidationStatus
from .policy import requires_approval
from .versioning import DatasetVersionManager

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
    method_candidates: Dict[str, Any] = field(default_factory=dict)
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

    def persist_trace(self):
        path = self.manager.root / self.dataset_id / "execution_trace.json"
        payload = {"current_dataset": self.current_ref.model_dump(mode="json"),
            "stop_reason": self.stop_reason, "finish_summary": self.finish_summary,
            "elapsed_seconds": time.monotonic()-self.run_started, "current_turn": self.current_turn,
            "llm_provider": self.llm_provider, "llm_model": self.llm_model,
            "events": self.events, "evidence": self.evidence, "experiments": self.experiments,
            "method_candidates": self.method_candidates, "decisions": self.decisions,
            "flagged": self.flagged, "failures": self.failures, "finish_attempts": self.finish_attempts,
            "step_log": self.step_log, "provider_errors": self.provider_errors,
            "unresolved": self.unresolved, "pending_approvals": self.pending_approvals}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        for attempt in range(4):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 3: raise
                time.sleep(0.05)

class ToolExecutor:
    def __init__(self, state):
        self.state = state

    def progress(self):
        frame = self.state.manager.load(self.state.current_ref)
        return {"version": self.state.current_ref.version,
            "pending_types": {c: canonical_type(t) for c,t in self.state.required_targets.items()
                if c not in self.state.flagged and (c not in frame or not target_matches(frame[c],t))},
            "pending_missing": {c: int((~present(frame[c])).sum()) if c in frame else "column absent"
                for c in self.state.required_missing if c not in self.state.flagged
                and (c not in frame or not present(frame[c]).all())},
            "flagged": dict(self.state.flagged)}

    def execute(self, name, arguments):
        source = self.state.current_ref.version
        if self.state.on_event: self.state.on_event({"phase": f"running {name} on {source}"})
        started = time.monotonic()
        result = json.loads(self._dispatch(name, arguments))
        from .recovery import build_prompt
        guidance = build_prompt(self, name, arguments, result)
        if guidance:
            result["recovery_prompt"] = guidance
        return self._record(name, arguments, result, source, started)

    def _record(self, name, arguments, result, source, started):
        event_id = f"event-{len(self.state.events)+1}"
        if name.startswith("inspect_") or name == "check_value_patterns":
            self.state.evidence[event_id] = {"source": "inspection", "tool": name,
                "arguments": arguments, "version": source, "result": result}
        event = {"duration_seconds": time.monotonic()-started, "event_id": event_id,
            "tool": name, "arguments": arguments, "source_version": source,
            "version": self.state.current_ref.version, "result": result,
            "evidence": {k:self.state.evidence[k] for k in result.get("evidence_ids",[])}}
        self.state.events.append(event)
        self.state.persist_trace()
        if self.state.on_event: self.state.on_event(event)
        return self._json({**result,"event_id":event_id})

    def _dispatch(self, name, arguments):
        from .workflow import SCHEMA, dispatch
        if name not in SCHEMA:
            return self._json({"success":False,"error":f"Unknown tool: {name}"})
        try:
            return self._json(dispatch(self,name,arguments))
        except KeyError as exc:
            return self._json({"success":False,"error":f"Missing argument: {exc}"})
        except (TypeError,ValueError) as exc:
            return self._json({"success":False,"error":str(exc)})

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
        step_id = "step-" + digest(json.dumps({"op": name, "cols": sorted(columns),
            "args": {k: v for k, v in arguments.items() if k not in {"rationale", "evidence_ids", "step_id"}}},
            sort_keys=True, default=str).encode())[:12]
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

        approval_message = f"Approval required: {name} {columns} (step_id={step_id})"
        if approval_message in self.state.pending_approvals:
            self.state.pending_approvals.remove(approval_message)
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
        return inspect_column(self.state.current_ref,args["column"],args.get("sample_size",20),self.state.manager)
    def _inspect_duplicates(self, args):
        return inspect_duplicates(self.state.current_ref,args.get("subset"),self.state.manager)
    def _check_value_patterns(self, args):
        return check_value_patterns(self.state.current_ref,args["column"],self.state.manager)

    def _validate_dataset(self, args):
        frame = self.state.manager.load(self.state.current_ref)
        rules = []
        def check(name,passed,message): rules.append(ValidationRuleResult(rule_name=name,passed=bool(passed),message=message))
        check("non_empty",not frame.empty,f"rows={len(frame)}")
        if self.state.expected_columns is not None:
            check("expected_columns",list(frame.columns)==self.state.expected_columns,"Required columns must be preserved unless removal was approved")
        for c in args.get("numeric_columns",[]): self.state.required_targets.setdefault(c,"numeric")
        for c,target in self.state.required_targets.items():
            if c not in self.state.flagged:
                check(f"target_type:{c}",c in frame and target_matches(frame[c],target),f"{c} must match {target}")
        for c in self.state.required_missing:
            if c not in self.state.flagged:
                check(f"missing_resolved:{c}",c in frame and present(frame[c]).all(),f"Reported missing values in {c} must be resolved")
        exceptions = list(dict.fromkeys([f"{c}: {reason}" for c,reason in self.state.flagged.items()]
            + self.state.unresolved + self.state.pending_approvals))
        failed = [r for r in rules if not r.passed]
        status = ValidationStatus.FAILED if failed else ValidationStatus.PARTIAL if exceptions else ValidationStatus.PASSED
        self.state.validation = ValidationReport(dataset_ref=self.state.current_ref,status=status,rules=rules,
            schema_ok=all(r.passed for r in rules if r.rule_name=="expected_columns"), quality_ok=not failed,
            unresolved_issues=[r.message for r in failed],exceptions=exceptions)
        return {"success":not failed,"version":self.state.current_ref.version,"status":status.value,
            "rules":[r.model_dump() for r in rules],"exceptions":exceptions}

    def _finish(self, args):
        self.state.finish_summary = args["summary"]
        self.state.unresolved.extend(item for item in args.get("unresolved",[]) if item not in self.state.unresolved)
        validation = self._validate_dataset({})
        self.state.finish_attempts += 1
        self.state.finished = validation["success"] or self.state.finish_attempts >= 2
        return {"success":validation["success"],"validation":validation,"summary":args["summary"],"exceptions":validation["exceptions"]}

    @staticmethod
    def _json(value): return json.dumps(value,default=str)
