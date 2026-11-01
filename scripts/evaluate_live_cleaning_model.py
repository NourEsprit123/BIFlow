"""Small live capability evaluation; synthetic inputs, fixed assertions, no application."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from dataCleaningTools import llm_client, workflow
from dataCleaningTools.experiments import run_isolated_transform, assess_method
from dataCleaningTools.self_correction import PROMPT, REPAIR_TOOL
from dataCleaningTools.inspection import value_inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--model", default=None)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--num-predict", type=int, default=1024)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--thinking", choices=["default", "enabled", "disabled"], default="default")
    options = parser.parse_args()
    destination = ROOT / "data/diagnostics" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_evaluation_" + uuid4().hex[:8])
    destination.mkdir(parents=True)
    def save(name, data):
        (destination / name).write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    cases = [
        {"name": "syntax_repair", "values": [" alpha ", "beta  ", None], "expected": ["alpha", "beta", None],
         "code": r"def transform(df):\n    df['value'] = df['value'].str.strip()\n    return df",
         "error": "SyntaxError at line 1: unexpected character after line continuation character. The code contains literal backslash-n text instead of actual line breaks.",
         "goal": "Strip surrounding whitespace in value, preserving actual nulls and all other data."},
        {"name": "numeric_repair", "values": ["1.5k", "2k", "five hundred", "one thousand", "850", "$1,200.50", None],
         "expected": [1500.0, 2000.0, 500.0, 1000.0, 850.0, 1200.5, None],
         "holdout": ["2.5k", "three hundred", "two thousand"], "holdout_expected": [2500.0, 300.0, 2000.0],
         "code": "def transform(df):\n    df['value'] = df['value'].str.replace('$', '', regex=False).str.replace(',', '', regex=False).str.replace('k', '000', regex=False).astype(float)\n    return df",
         "error": "ValueError: could not convert string to float: 'five hundred'. Replacing k with 000 also misinterprets decimal multipliers.",
         "goal": "Parse these monetary/number representations into their numeric meanings. Preserve genuine missing values; do not impute. Change only value."},
        {"name": "ambiguity_decision", "values": ["$100", "five hundred", "banana", "ERROR_404", None],
         "goal": "The final value column must be numeric while preserving populated information. Decide the justified next action using the observed values. Do not invent meanings or discard information."},
    ]
    production_main = (ROOT / "dataCleaningTools/prompts/cleaning.md").read_text(encoding="utf-8")
    guide = (ROOT / "dataCleaningTools/prompts/request_guide.md").read_text(encoding="utf-8")
    post = llm_client._post_with_progress
    results = []
    try:
        for condition in ("production", "focused"):
            for case in cases:
                for repeat in range(1, options.repeats+1):
                    identity = f"{condition}_{case['name']}_{repeat}"
                    print("RUNNING " + identity, flush=True)
                    request_number = 0
                    def capture(url, payload, timeout, callback):
                        nonlocal request_number
                        request_number += 1
                        suffix = "" if request_number == 1 else f"_followup{request_number}"
                        payload["options"]["num_predict"] = options.num_predict
                        if options.thinking != "default":
                            payload["think"] = options.thinking == "enabled"
                        save(identity + suffix + "_request.json", payload)
                        response = post(url, payload, timeout, callback)
                        save(identity + suffix + "_raw_response.json", response.json())
                        return response
                    llm_client._post_with_progress = capture
                    decision = case["name"] == "ambiguity_decision"
                    if condition == "production":
                        system = production_main if decision else PROMPT.read_text(encoding="utf-8")
                    else:
                        system = ("Choose an evidence-based cleaning action using the available tools. Unknown tokens must not be erased or assigned invented numeric meanings. Flag genuine ambiguity."
                                  if decision else "Repair the complete transform(df) using the reported error and observed values. Return only JSON matching the schema with code and a concise hypothesis. Preserve rows, other columns and missing values. Do not claim results you have not executed.")
                    context = {"goal": case["goal"], "column": "value", "observed_values": case["values"],
                               "coverage": "Every value in the test input is shown.", "version": "V1"}
                    if decision:
                        tools = workflow.SCHEMAS_LIST
                        if condition == "production":
                            context["request_guide"] = guide
                    else:
                        context.update(failed_method={"code": case["code"], "columns": ["value"]}, diagnostic=case["error"])
                        tools = [REPAIR_TOOL]
                    messages = [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(context)}]
                    record = {"condition": condition, "case": case["name"], "repeat": repeat}
                    started = time.monotonic()
                    try:
                        response = llm_client.chat_with_tools(messages, tools, model=options.model or llm_client.default_model(), temperature=options.temperature, structured=not decision, timeout=options.timeout)
                        save(identity + "_parsed_response.json", response)
                        if decision and len(response["tool_calls"]) == 1 and response["tool_calls"][0]["name"] == "inspect_data":
                            call = response["tool_calls"][0]
                            record["initial_action"] = call["name"]
                            inventory = value_inventory(pd.Series(case["values"]))
                            observed = {"column": "value", "version": "V1", "dtype": "str", "null_count": inventory["null_count"], "value_overview": inventory}
                            messages += [{"role": "assistant", "content": None, "tool_calls": [{"id": call["id"], "type": "function",
                                "function": {"name": call["name"], "arguments": json.dumps(call["arguments"])}}]},
                                {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(observed)},
                                {"role": "user", "content": "This is the full current value inventory; there are no additional pages. Decide the justified next action."}]
                            response = llm_client.chat_with_tools(messages, tools, model=options.model or llm_client.default_model(), temperature=options.temperature, timeout=options.timeout)
                            save(identity + "_followup_parsed.json", response)
                        calls = response["tool_calls"]
                        record.update(model=response["model"], response_issue=response["response_issue"], finish_reason=response["finish_reason"],
                                      usage=response["usage"], format_valid=len(calls) == 1)
                        if decision:
                            call = calls[0] if len(calls) == 1 else {}
                            args = call.get("arguments", {})
                            reason = args.get("reason", "").lower()
                            record.update(action=call.get("name"), reason=reason,
                                passed=call.get("name") == "flag_for_review" and args.get("columns") == ["value"]
                                and "banana" in reason and ("error_404" in reason or "error" in reason))
                        elif len(calls) == 1:
                            code = calls[0]["arguments"]["code"]
                            record["code"] = code
                            frame = pd.DataFrame({"value": case["values"], "untouched": list(range(len(case["values"])))})
                            trial = run_isolated_transform(frame, code)
                            save(identity + "_trial.json", {k:v for k,v in trial.items() if k != "df"} | ({"output": trial["df"].to_dict(orient="list")} if trial.get("success") else {}))
                            record.update(executable=bool(trial.get("success")), error=trial.get("error"), passed=False)
                            if trial.get("success"):
                                output = trial["df"]
                                expected = pd.Series(case["expected"], name="value")
                                actual = output["value"]
                                matches = all((pd.isna(a) and pd.isna(b)) or (not pd.isna(a) and not pd.isna(b) and a == b) for a,b in zip(actual,expected)) and len(actual) == len(expected)
                                preservation = assess_method(frame, output, ["value"], [])
                                record.update(measured_output=actual.tolist(), preservation_passed=preservation["accepted"], passed=bool(matches and preservation["accepted"]))
                                if case.get("holdout"):
                                    holdout = run_isolated_transform(pd.DataFrame({"value": case["holdout"]}), code)
                                    record["holdout_passed"] = bool(holdout.get("success") and holdout["df"]["value"].tolist() == case["holdout_expected"])
                        else:
                            record["passed"] = False
                    except Exception as exc:
                        record.update(passed=False, error=f"{type(exc).__name__}: {exc}")
                    record["seconds"] = round(time.monotonic()-started, 3)
                    record["inference_calls"] = request_number
                    results.append(record)
                    save("evaluation_results.json", {"model": options.model or llm_client.default_model(), "settings": vars(options), "results": results,
                         "applied": False, "production_settings_changed": False})
                    print(("PASS " if record["passed"] else "FAIL ") + identity, flush=True)
    finally:
        llm_client._post_with_progress = post
    print(destination, flush=True)
    for condition in ("production", "focused"):
        subset = [r for r in results if r["condition"] == condition]
        print(condition, sum(r["passed"] for r in subset), "/", len(subset), flush=True)


if __name__ == "__main__":
    main()
