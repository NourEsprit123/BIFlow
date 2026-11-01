"""One budgeted Groq code-generation request after four failed local corrections."""
import hashlib
import json
import os
import time
from pathlib import Path

from jsonschema import Draft202012Validator

from .effects import present
from .experiments import validate_code
from .inspection import value_inventory
from .llm_client import positive_setting, _post_with_progress
from .expert_context import fit_request, MAX_REQUEST_BYTES

ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
PROMPT = Path(__file__).with_name("prompts") / "expert_generation.md"
SCHEMA = {"type": "object", "additionalProperties": False,
    "properties": {"decision": {"type": "string", "enum": ["generated", "needs_review"]},
                   "code": {"type": "string"}, "hypothesis": {"type": "string"},
                   "assumptions": {"type": "array", "items": {"type": "string"}}},
    "required": ["decision", "code", "hypothesis", "assumptions"]}


def generation_context(executor, arguments, result, attempts, runtime=None):
    state = executor.state
    frame = state.manager.load(state.current_ref)
    columns = arguments["columns"]
    from .cleaning_tasks import model_view
    focused = model_view(state, executor) if state.focused_cleaning else {}
    from .value_interpretation import plans
    category = ((focused.get("cleaning_focus") or {}).get("task") or {}).get("category")
    profile_fields = {"agent_reasoning", "business_interpretation", "uncertainty", "issues"}
    if category in {None, "types"}:
        profile_fields.add("etl_cast_to")
    if category in {None, "missing"}:
        profile_fields.add("imputation_strategy")
    observations = {}
    for column in columns:
        inventory = value_inventory(frame[column], limit=100)
        inventory["missing_including_blank_strings"] = int((~present(frame[column])).sum())
        observations[column] = {"dtype": str(frame[column].dtype), "inventory": inventory,
            "profiling": {k: v for k, v in state.working_report.get("column_profiles", {}).get(column, {}).items()
                          if k in profile_fields}}
    objective = state.source_ref.metadata.get("user_request", "")
    # Migrate only the exact obsolete dashboard-generated instruction; preserve custom user objectives.
    objective = objective.replace("If the isolated runtime is unavailable or the method fails, explain that result and test builtin catalog methods where appropriate.",
        "If Docker is unavailable, stop. Failed generated methods use bounded correction without builtin fallback.")
    return {"trigger": trigger(attempts), "dataset": {"rows": len(frame), "version": state.current_ref.version,
                "schema": {str(c): str(frame[c].dtype) for c in frame}},
            "user_objective": objective,
            "cleaning_focus": focused.get("cleaning_focus"),
            "value_interpretation": focused.get("value_interpretation") or plans(state, columns, arguments.get("checks", [])),
            "required_outcomes": focused.get("outstanding", executor.progress()),
            "method": {k: arguments.get(k) for k in ("code", "hypothesis", "columns", "checks", "value_assessment")},
            "observations": observations,
            "related_row_examples": json.loads(frame[columns].head(20).to_json(orient="records", date_format="iso")),
            "failure": {"error": result.get("error"), "diagnostic": result.get("diagnostic"),
                        "failure_summary": result.get("failure_summary"), "repair_error": result.get("repair_error"),
                        "sandbox_logs": ((result.get("recovery_prompt") or {}).get("context") or {}).get("sandbox_logs", [])},
            "local_corrections": attempts,
            "execution_contract": {"signature": "def transform(df): ...; return df", "available": ["pd", "np", "re", "math"],
                "libraries": "pandas and numpy in Python 3.12",
                "runtime": {"image_id": (runtime or {}).get("image_id"),
                            "versions": (runtime or {}).get("versions", {}),
                            "version_note": "Versions come from actual sandbox execution; an empty mapping means not yet observed, not host versions."},
                "numeric_missing_values": "For numpy float64 output, return np.nan for missing/invalid values, not pd.NA. An object Series containing pd.NA cannot be directly cast with astype('float64'). Normalize missing values first or deliberately use pandas nullable Float64 when compatible with the required checks. Preserve the missing mask; do not impute during parsing.",
                "network": False, "package_installation": False,
                "row_removal": False, "preserve": "row order/index, unrelated columns and valid values",
                "existing_missing": "Preserve unless the active task is missing-value handling",
                "invalid_values": "User permits nonsensical/unparseable entries to become NaN; log them and parse recognizable formats correctly",
                "tests": "Disjoint sample/holdout, deterministic repeatability, then exact-code full-data checks"}}


def trigger(attempts):
    return "four_failed_local_corrections" if len(attempts) == 4 else "unproductive_local_corrections"


def generate_candidate(executor, arguments, result, *, attempts):
    state = executor.state
    from .experiments import runtime_status
    runtime = runtime_status()
    context = generation_context(executor, arguments, result, attempts, runtime)
    encoded = json.dumps(context, default=str)
    key = hashlib.sha256((str(state.current_ref.version) + encoded).encode()).hexdigest()
    if key in state.expert_generations:
        return state.expert_generations[key]
    record = {"provider": "groq", "model": os.environ.get("BIFLOW_CLEANING_EXPERT_MODEL", "openai/gpt-oss-120b"),
              "version": state.current_ref.version, "trigger": trigger(attempts),
              "decision": "unavailable", "request_sent": False}
    try:
        if not 1 <= len(attempts) <= 4:
            raise ValueError("Groq generation requires one to four unsuccessful local corrections")
        if os.environ.get("BIFLOW_CLEANING_EXPERT_ENABLED", "false").lower() != "true":
            raise ValueError("Groq expert code generation is disabled")
        if not runtime.get("available"):
            executor.stop("sandbox_timeout" if runtime.get("transient") else "sandbox_unavailable",
                          "Docker sandbox unavailable before Groq code generation: " + runtime.get("error", "Unknown runtime error"))
            raise ValueError("Docker sandbox unavailable; no Groq request was sent")
        maximum = positive_setting("BIFLOW_CLEANING_EXPERT_MAX_CALLS", 2, integer=True)
        if sum(r.get("request_sent", False) for r in state.expert_generations.values()) >= maximum:
            raise ValueError("Groq code-generation call budget exhausted")
        token = os.environ.get("GROQ_API_KEY", "").strip()
        if not token:
            raise ValueError("Set GROQ_API_KEY in .env")
        timeout = min(positive_setting("BIFLOW_CLEANING_EXPERT_TIMEOUT", 60), state.deadline-time.monotonic())
        if timeout <= 0:
            raise ValueError("Run time budget expired before Groq code generation")
        payload = {"model": record["model"], "messages": [
            {"role": "system", "content": PROMPT.read_text(encoding="utf-8")}, {"role": "user", "content": encoded}],
            "max_completion_tokens": 4096,
            "response_format": {"type": "json_schema", "json_schema": {"name": "cleaning_method", "strict": True, "schema": SCHEMA}}}
        if record["model"].startswith("openai/gpt-oss-"):
            payload["reasoning_effort"] = "low"
        record["audit_context"] = context
        sent_context, request_size = fit_request(context, payload)
        record.update(context=sent_context, request_bytes=request_size, request_limit_bytes=MAX_REQUEST_BYTES)
        if state.on_event:
            state.on_event({"phase": "Groq · generating a replacement method after four failed corrections", "stage": "model"})
        record.update(request_sent=True)
        response = _post_with_progress(ENDPOINT, payload, timeout, state.on_event,
            headers={"Authorization": f"Bearer {token}"}, label="Groq code generator")
        if response.status_code >= 400:
            raise ValueError(f"Groq generation returned HTTP {response.status_code}; check account access and quota")
        body = response.json()
        choice = body["choices"][0]
        record["usage"] = body.get("usage", {})
        if choice.get("finish_reason") != "stop":
            raise ValueError("Groq generation was incomplete; its code was not accepted")
        proposal = json.loads(choice["message"]["content"])
        if list(Draft202012Validator(SCHEMA).iter_errors(proposal)) or not proposal.get("hypothesis", "").strip():
            raise ValueError("Groq response does not match the code-generation contract")
        if proposal["decision"] == "generated":
            if not proposal["code"].strip() or len(proposal["code"]) > 8000:
                raise ValueError("Groq must provide a complete method of at most 8000 characters")
            validate_code(proposal["code"])
        record.update(proposal)
    except (TimeoutError, ValueError) as exc:
        record["error"] = str(exc)
    except Exception as exc:
        # Provider exceptions can contain auth headers: never log their messages.
        record["error"] = f"Groq code generation failed ({type(exc).__name__})"
    state.expert_generations[key] = record
    state.persist_trace()
    return record
