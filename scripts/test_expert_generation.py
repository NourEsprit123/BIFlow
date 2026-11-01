"""Live synthetic test: four local failures, then Groq code and Docker validation."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from dataCleaningTools import llm_client
from dataCleaningTools.experiments import run_isolated_transform, promote

from dataCleaningTools.self_correction import execute_and_fix_loop
from dataCleaningTools.tool_registry import AgentSessionState, ToolExecutor
from dataCleaningTools.versioning import DatasetVersionManager


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inject-local-failures", action="store_true",
                        help="Inject four explicit failing corrections to test the real Groq/Docker boundary without local inference")
    parser.add_argument("--include-invalid-values", action="store_true",
                        help="Verify the invalid-token-to-NaN policy while retaining valid numeric formats")
    options = parser.parse_args()
    token_name = "GROQ_API_KEY"
    if not os.environ.get(token_name, "").strip():
        raise SystemExit(f"Add {token_name} to .env before running this diagnostic")
    # Changes affect this process only; never rewrite production configuration.
    os.environ["BIFLOW_CLEANING_EXPERT_ENABLED"] = "true"
    os.environ["BIFLOW_CLEANING_EXPERT_MAX_CALLS"] = "1"
    os.environ["BIFLOW_OLLAMA_TIMEOUT"] = "180"
    os.environ["BIFLOW_OLLAMA_NUM_PREDICT"] = "4096"
    destination = ROOT / "data/diagnostics" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_expert_" + uuid4().hex[:8])
    destination.mkdir(parents=True)
    frame = pd.DataFrame({"amount": ["1.5k", "2k", "five hundred", "one thousand", "850", "$1,200.50", None]})
    if options.include_invalid_values:
        frame = pd.concat([frame, pd.DataFrame({"amount": ["banana", "ERROR_404"]})], ignore_index=True)
    source = destination / "synthetic.csv"
    frame.to_csv(source, index=False)
    manager = DatasetVersionManager(destination / "versions")
    original = manager.register_original(source, dataset_id="expert_test")
    state = AgentSessionState(manager=manager, dataset_id="expert_test", source_ref=original,
        current_ref=manager.create_working_copy(original), expected_columns=["amount"],
        required_targets={"amount": "float"}, deadline=time.monotonic()+420)
    executor = ToolExecutor(state)
    code = """def transform(df):
    values = df['amount']
    values = values.str.replace('$', '', regex=False).str.replace(',', '', regex=False).str.replace('k', '000', regex=False)
    df['amount'] = pd.to_numeric(values, errors='raise')
    return df
"""
    arguments = {"code": code, "columns": ["amount"], "hypothesis": "Parse amount representations without information loss",
                 "checks": [{"column": "amount", "kind": "numeric"}]}
    trial = json.loads(executor.execute("test_generated", arguments))
    print("Initial trial:", trial.get("success"), flush=True)
    local_attempts = []
    def generate(messages, tools, **settings):
        local_attempts.append(1)
        if options.inject_local_failures:
            print(f"Injected local correction {len(local_attempts)}", flush=True)
            return {"tool_calls": [{"name": "repair_method", "arguments": {
                "code": f"def transform(df):\n    raise ValueError('injected local failure {len(local_attempts)}')",
                "hypothesis": "Deliberate diagnostic failure; not an actual local model result"}}]}
        print("Local model writing revision", flush=True)
        return llm_client.chat_with_tools(messages, tools, model="qwen3:8b", temperature=0.6,
                                         structured=True, **settings)
    revised, corrected = execute_and_fix_loop(arguments, trial, executor=executor, generate=generate, max_retries=4)
    result = {"expert_generations": list(state.expert_generations.values()), "applied": False,
              "local_attempts": len(local_attempts), "local_failures_injected": options.inject_local_failures,
              "corrected_trial_passed": bool(corrected.get("tested") and corrected.get("success")),
              "repair_error": corrected.get("repair_error")}
    if result["corrected_trial_passed"]:
        spec_id = state.method_candidates[corrected["candidate_id"]]["experiment_id"]
        execution = promote(state, spec_id, frame)
        result["full_data_checks_passed"] = execution.success
        output = execution.df["amount"].tolist() if execution.success else None
        expected = [1500, 2000, 500, 1000, 850, 1200.5, None]
        if options.include_invalid_values:
            expected += [None, None]
        result["output"] = output
        result["expected_values_passed"] = output is not None and len(output) == len(expected) and all(
            (pd.isna(a) and pd.isna(b)) or (not pd.isna(a) and not pd.isna(b) and a == b) for a,b in zip(output, expected))
        if result["expected_values_passed"]:
            holdout = run_isolated_transform(pd.DataFrame({"amount": ["2.5k", "three hundred", "two thousand"]}), revised["code"])
            result["holdout_passed"] = bool(holdout.get("success") and holdout["df"]["amount"].tolist() == [2500, 300, 2000])
    result["working_version"] = state.current_ref.version
    (destination / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(destination, flush=True)
    print(json.dumps({k: v for k, v in result.items() if k != "expert_generations"}, default=str), flush=True)
    print("Groq requests:", sum(r.get("request_sent", False) for r in state.expert_generations.values()), flush=True)


if __name__ == "__main__":
    main()
