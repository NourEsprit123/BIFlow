"""Compact provider evidence without modifying the complete local audit."""
import json

MAX_REQUEST_BYTES = 60000


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


def fit_request(context, payload):
    """Budget the entire serialized request, including prompt, schema and escaping.

    Never shorten executable code, requirements or mappings to force a request.
    If irreducible evidence exceeds the budget, refuse before HTTP dispatch.
    """
    for limit in (100, 20, 5, 1):
        sent = compact(context, group_limit=limit)
        sent["evidence_summary"] = {"group_limit": limit, "full_evidence": "local audit",
            "note": "Repeated row failures are grouped by raw/expected/actual meaning. Inspect counts and omitted_groups; examples are not exhaustive."}
        payload["messages"][1]["content"] = encode(sent)
        # Default JSON escaping is deliberately conservative relative to HTTPX's
        # compact UTF-8 body; count bytes as well as characters for Unicode data.
        size = len(json.dumps(payload, default=str).encode("utf-8"))
        if size <= MAX_REQUEST_BYTES:
            return sent, size
    raise ValueError(f"Expert request cannot fit within {MAX_REQUEST_BYTES} bytes after grouping; no request sent. Complete evidence remains in the local audit.")
