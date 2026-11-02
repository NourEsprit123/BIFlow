"""Compact provider evidence without modifying the complete local audit."""
import json
from copy import deepcopy

from .llm_client import positive_setting

MAX_REQUEST_BYTES = 60000
# Characters of message text per token for JSON-heavy prompts, used to respect provider token limits.
CHARS_PER_TOKEN = 3.6


def completion_tokens():
    return positive_setting("BIFLOW_CLEANING_EXPERT_MAX_COMPLETION_TOKENS", 2000, integer=True)


def request_budget():
    """Characters of prompt text so that prompt plus reserved completion stays within the provider's token limit.

    Groq counts max_completion_tokens against its per-minute token limit (8,000 for gpt-oss-120b on the free
    tier), so a large reserve or request is refused with HTTP 413 before any generation.
    """
    tokens = positive_setting("BIFLOW_CLEANING_EXPERT_TOKEN_LIMIT", 8000, integer=True)
    return int((tokens - completion_tokens()) * CHARS_PER_TOKEN)


def prompt_chars(payload):
    """Text the provider tokenizes: message contents and the response schema, without HTTP JSON escaping."""
    schema = (payload.get("response_format") or {}).get("json_schema") or payload.get("response_format") or {}
    return sum(len(m["content"]) for m in payload["messages"]) + len(encode(schema))


def deduplicate(context):
    """Remove evidence the request already carries elsewhere, and cap illustrative examples.

    Code, requirements and value mappings are never shortened.
    """
    sent = deepcopy(context)
    failure = sent.get("failure") or {}
    if failure.get("failure_summary") and isinstance(failure.get("diagnostic"), dict) and "evidence" in failure["diagnostic"]:
        failure["diagnostic"]["evidence"] = "same failed checks as failure.failure_summary"
    if isinstance(failure.get("sandbox_logs"), list):
        failure["sandbox_logs"] = [str(log)[-2000:] for log in failure["sandbox_logs"][-2:]]
    plans = (sent.get("value_interpretation") or {}).get("columns") or {}
    for column, observation in (sent.get("observations") or {}).items():
        inventory = observation.get("inventory") or {}
        if "format_groups" in inventory and "format_groups" in (plans.get(column) or {}):
            inventory["format_groups"] = "see value_interpretation"
        if isinstance(inventory.get("values"), list) and len(inventory["values"]) > 10:
            inventory["omitted_values"] = len(inventory["values"]) - 10
            inventory["values"] = inventory["values"][:10]
    if isinstance(sent.get("related_row_examples"), list):
        sent["related_row_examples"] = sent["related_row_examples"][:5]
    method_code, seen = (sent.get("method") or {}).get("code"), {}
    for number, attempt in enumerate(sent.get("local_corrections") or [], 1):
        code = attempt.get("code")
        if code and code == method_code:
            attempt["code"] = "same as method.code"
        elif code in seen:
            attempt["code"] = f"same as local correction {seen[code]}"
        elif code:
            seen[code] = number
    return sent


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def compact(value, *, group_limit=100, key=""):
    if key == "raw_response" and value:
        # Local reasoning transcripts are not executable repairs. Preserve output
        # previews and finish metadata; the complete reply stays in step_log.
        if isinstance(value, dict):
            value = (value.get("message") or {}).get("content", "")
        text = str(value)
        return {"output_preview": text[:1000], "omitted_characters": max(0, len(text)-1000),
                "full_reply": "local audit step_log"}
    if isinstance(value, dict):
        return {k: compact(v, group_limit=group_limit, key=k) for k, v in value.items()}
    if isinstance(value, list):
        if key in {"mismatches", "lost_values"}:
            groups = {}
            for entry in value:
                meaning = {k: v for k, v in entry.items() if k not in {"row_position", "row_index", "partition"}}
                signature = encode(meaning)
                group = groups.setdefault(signature, {**meaning, "count": 0, "row_examples": []})
                group["count"] += 1
                if len(group["row_examples"]) < 2:
                    group["row_examples"].append({k: entry[k] for k in ("row_position", "row_index", "partition") if k in entry})
            ranked = sorted(groups.values(), key=lambda g: -g["count"])
            return {"total_cells": len(value), "distinct_groups": len(ranked),
                    "groups": ranked[:group_limit], "omitted_groups": max(0, len(ranked)-group_limit),
                    "full_details": "local execution trace; counts refer to this evidence list, not summed across repeated checks"}
        result = [compact(v, group_limit=group_limit) for v in value]
        if key == "failed_checks":
            result = list({encode(v): v for v in result}.values())
        return result
    return value


def fit_request(context, payload, limit=None):
    """Budget the entire serialized request, including prompt, schema and escaping.

    Duplicated evidence is removed first, then repeated row failures are grouped more coarsely.
    Never shorten executable code, requirements or mappings to force a request.
    If irreducible evidence exceeds the budget, refuse before HTTP dispatch.
    """
    limit = request_budget() if limit is None else limit
    for deduplicated, base in ((False, context), (True, deduplicate(context))):
        for groups in (100, 20, 5, 1):
            sent = compact(base, group_limit=groups)
            sent["evidence_summary"] = {"group_limit": groups, "deduplicated": deduplicated, "full_evidence": "local audit",
                "note": "Repeated row failures are grouped by raw/expected/actual meaning. Inspect counts and omitted_groups; examples are not exhaustive."}
            payload["messages"][1]["content"] = encode(sent)
            # The token budget applies to the text the provider tokenizes; the HTTP body (with
            # conservative JSON escaping, counted in bytes for Unicode) keeps its own ceiling.
            size = len(json.dumps(payload, default=str).encode("utf-8"))
            if prompt_chars(payload) <= limit and size <= MAX_REQUEST_BYTES:
                return sent, size
    raise ValueError(f"Expert request cannot fit within {limit} prompt characters after grouping; no request sent. Complete evidence remains in the local audit.")
