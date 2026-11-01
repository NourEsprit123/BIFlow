"""Replay parser and chained-assignment regressions in Docker; no LLM/API calls."""
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from dataCleaningTools.self_correction import correction_context
from dataCleaningTools.tool_registry import AgentSessionState, ToolExecutor
from dataCleaningTools.versioning import DatasetVersionManager

CASES = [
    ("wrong_multiplier", ["1.5k", "2.1k", "banana"],
     "def transform(df):\n    df['amount'] = pd.to_numeric(df['amount'].str.replace('k', '000'), errors='coerce')\n    return df", False, False),
    ("currency_erased", ["$450.00", "$320.75", "half a million"],
     "def transform(df):\n    df['amount'] = pd.to_numeric(df['amount'].str.replace('\\\\$', '', regex=False), errors='coerce')\n    return df", False, False),
    ("chained_inplace", [10.0, None, 30.0],
     "def transform(df):\n    df['amount'].fillna(df['amount'].median(), inplace=True)\n    return df", False, True),
    ("valid_parse_with_invalid_nan", ["$450.00", "1.5k", "five hundred", "banana", None],
     """def transform(df):
    def parse(value):
        if pd.isna(value):
            return np.nan
        text = str(value).lower().replace('$', '').replace(',', '')
        if text == 'five hundred':
            return 500.0
        try:
            return float(text[:-1]) * 1000 if text.endswith('k') else float(text)
        except ValueError:
            return np.nan
    df['amount'] = df['amount'].map(parse)
    return df
""", True, False),
]


def main():
    destination = ROOT / "data/diagnostics" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_semantics_" + uuid4().hex[:8])
    destination.mkdir(parents=True)
    findings = []
    for name, values, code, should_pass, require_no_missing in CASES:
        source = destination / f"{name}.csv"
        pd.DataFrame({"amount": values}).to_csv(source, index=False)
        manager = DatasetVersionManager(destination / "versions")
        original = manager.register_original(source, dataset_id=name)
        state = AgentSessionState(manager=manager, dataset_id=name, source_ref=original,
            current_ref=manager.create_working_copy(original), required_targets={"amount": "float"})
        executor = ToolExecutor(state)
        checks = [{"column": "amount", "kind": "numeric"}]
        if require_no_missing:
            checks.append({"column": "amount", "kind": "no_missing"})
        args = {"hypothesis": "Live regression: " + name, "columns": ["amount"], "code": code, "checks": checks}
        result = json.loads(executor.execute("test_generated", args))
        context = correction_context(state, executor, args, result, 1, 4,
                                     (result.get("recovery_prompt") or {}).get("case"))
        finding = {"case": name, "accepted": bool(result.get("success")), "expected_acceptance": should_pass,
            "failed_checks": (result.get("failure_summary") or {}).get("failed_checks", []),
            "sandbox_logs_forwarded": bool(context["failure"]["sandbox_logs"]),
            "runtime_guidance": context["failure"]["diagnostic"].get("runtime_guidance"),
            "version": state.current_ref.version}
        finding["passed"] = finding["accepted"] == should_pass and not result.get("fatal")
        if require_no_missing:
            finding["passed"] = finding["passed"] and finding["sandbox_logs_forwarded"] and bool(finding["runtime_guidance"])
        findings.append(finding)
        print(name, "PASS" if finding["passed"] else "FAIL", flush=True)
    (destination / "findings.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
    print(destination, flush=True)
    if not all(f["passed"] for f in findings):
        raise SystemExit("A live semantic-validation regression failed")


if __name__ == "__main__":
    main()
