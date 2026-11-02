"""Run the Data Cleaning Agent on the synthetic benchmark and score outcome, safety and trajectory.

    python -m evaluation.run                       # all cases, once each
    python -m evaluation.run --cases sales_small --repeats 3

Uses the configured local model (Ollama) exactly as the dashboard does. Results go to data/evaluation/<timestamp>/.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .benchmark import CASES, SCHEMA, write_case
from .scoring import file_hash, score_outcome, score_safety
from .trajectory import run_metrics

ROOT = Path(__file__).resolve().parents[1]
OBJECTIVE = ("Improve data quality for BI analysis while preserving the uploaded original. "
             "Prefer builtin operations; write generated code only when no builtin can express the justified rule.")


def default_agent(folder: Path):
    from agents.dataCleaning_agent import DataCleaningAgent
    return DataCleaningAgent(data_root=folder / "versions", report_root=folder / "reports",
                             search_roots=[folder], use_llm=True)


def score_run(case, folder: Path, result, source_hash_before: str, wall_seconds: float) -> dict:
    final = pd.read_csv(result.final_dataset.path, dtype=str, keep_default_na=False)
    truth = pd.read_csv(folder / "truth.csv", dtype=str, keep_default_na=False)
    answer_key = json.loads((folder / "answer_key.json").read_text(encoding="utf-8"))
    outcome = score_outcome(final, truth, answer_key, case.rows)
    safety = score_safety(result, source=folder / f"{case.name}.csv", source_hash_before=source_hash_before,
                          final=final, outcome=outcome, clean_columns=list(SCHEMA))
    record = {"case": case.name, "validation": result.validation.status.value, "final_version": result.final_dataset.version,
              "wall_seconds": wall_seconds, "source_hash_before": source_hash_before, "outcome": outcome,
              "safety": safety, "trajectory": run_metrics(result), "result_path": result.metadata.get("result_path")}
    (folder / "evaluation.json").write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return record


def evaluate_case(case, folder: Path, agent_factory=default_agent) -> dict:
    files = write_case(case, folder)
    before = file_hash(files["source"])
    started = time.monotonic()
    result = agent_factory(folder).run(files["report"], user_request=OBJECTIVE)
    return score_run(case, folder, result, before, round(time.monotonic() - started, 1))


def rescore(root: Path) -> list[dict]:
    """Score saved runs again (after a scoring change) without running the agent."""
    from dataCleaningTools.models import CleaningResult
    records = []
    for path in sorted(root.glob("*/evaluation.json")):
        old = json.loads(path.read_text(encoding="utf-8"))
        result = CleaningResult.model_validate_json(Path(old["result_path"]).read_text(encoding="utf-8"))
        record = score_run(CASES[old["case"]], path.parent, result, old.get("source_hash_before") or file_hash(
            path.parent / f"{old['case']}.csv"), old["wall_seconds"])
        record["repeat"] = old.get("repeat", int(path.parent.name.rsplit("run", 1)[-1] or 1))
        records.append(record)
    (root / "summary.json").write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")
    (root / "report.md").write_text(markdown(records, f"Data Cleaning Agent evaluation · {root.name} (rescored)"), encoding="utf-8")
    return records


def markdown(records: list[dict], title: str) -> str:
    lines = [f"# {title}", "", "## Runs", "",
             "| Case | Run | Status | Labelled cells handled | Restore accuracy | Untouched cells kept | Duplicates left "
             "| Safety | Turns | Seconds | Invalid requests | Builtin first | Groq calls | Drops |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in records:
        o, t = r["outcome"], r["trajectory"]
        safe = [c for c in r["safety"] if c["passed"] is not None]
        lines.append(f"| {r['case']} | {r['repeat']} | {r['validation']} | {o['labelled_accuracy']:.1%} | "
                     f"{(o['restore_accuracy'] or 0):.1%} | {o['untouched_cells_preserved']:.1%} | {o['duplicate_rows_left']} | "
                     f"{sum(c['passed'] for c in safe)}/{len(safe)} | {t['turns']} | {t['elapsed_seconds']} | "
                     f"{t['invalid_request_rate']} | {t['builtin_first_rate']} | {t['groq_requests']} | "
                     f"{', '.join(f'{k} {v}' for k, v in t['drops'].items()) or '-'} |")
    kinds = {}
    for r in records:
        for kind, counts in r["outcome"]["by_kind"].items():
            kinds.setdefault(kind, Counter()).update(counts)
    lines += ["", "## Outcome by problem type (all runs)", "", "| Column:problem | Cells | Handled | Results |", "|---|---|---|---|"]
    good = {"restored", "kept", "nulled", "imputed_marked", "kept_for_review"}
    for kind, counts in sorted(kinds.items()):
        total = sum(counts.values())
        handled = sum(n for k, n in counts.items() if k in good)
        lines.append(f"| {kind} | {total} | {handled / total:.0%} | {', '.join(f'{k} {v}' for k, v in counts.most_common())} |")
    lines += ["", "## Safety failures", ""]
    failures = [f"- {r['case']} run {r['repeat']}: **{c['check']}** · {c['detail']}" for r in records
                for c in r["safety"] if c["passed"] is False]
    lines += failures or ["None."]
    lines += ["", "Labelled cells handled counts restored values, correctly blanked junk, marked fills and outliers left "
              "for review. Untouched cells kept is the share of never-corrupted cells that still hold their value in the "
              "canonical form. The profiling report is an oracle built from the answer key, so these scores isolate the "
              "cleaning agent."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", nargs="+", default=list(CASES), choices=list(CASES))
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "evaluation")
    parser.add_argument("--rescore", type=Path, help="score a previous evaluation folder again without running the agent")
    options = parser.parse_args(argv)
    if options.rescore:
        records = rescore(options.rescore)
        print(f"Rescored {len(records)} run(s): {options.rescore / 'report.md'}")
        return records
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = options.out / stamp
    records = []
    for name in options.cases:
        for repeat in range(1, options.repeats + 1):
            print(f"Running {name} (run {repeat}/{options.repeats})...", flush=True)
            record = evaluate_case(CASES[name], root / f"{name}_run{repeat}")
            record["repeat"] = repeat
            records.append(record)
            print(f"  {record['validation']} · labelled handled {record['outcome']['labelled_accuracy']:.1%} · "
                  f"{record['trajectory']['turns']} turns · {record['wall_seconds']} s", flush=True)
    (root / "summary.json").write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")
    (root / "report.md").write_text(markdown(records, f"Data Cleaning Agent evaluation · {stamp}"), encoding="utf-8")
    print(f"Report: {root / 'report.md'}")
    return records


if __name__ == "__main__":
    main()
