"""The evaluation harness itself: benchmark labels, scoring, safety checks and the end-to-end runner."""
from types import SimpleNamespace

import pandas as pd
import pytest

from dataCleaningTools.numeric_expectations import expected_number
from evaluation.benchmark import CASES, Case, generate
from evaluation.run import evaluate_case, markdown
from evaluation.scoring import classify, score_outcome, score_safety


def as_text(frame):
    return frame.astype(object).where(frame.notna(), "").astype(str)


def perfect_output(clean, key):
    frame = clean.astype(object).copy()
    for k in key:
        row = frame.index[frame["order_id"] == k["key"]][0]
        if k["outcome"] == "missing":
            frame.at[row, k["column"]] = None
        if k["outcome"] == "review":
            frame.at[row, k["column"]] = k["raw"]
    return as_text(frame)


def test_benchmark_is_deterministic_and_numeric_labels_match_the_independent_checker():
    first, _, key = generate(CASES["sales_hard"])
    second, _, again = generate(CASES["sales_hard"])
    assert first.equals(second) and key == again
    restores = [k for k in key if k["outcome"] == "restore" and k["column"] in ("revenue", "quantity")]
    assert restores and all(abs(expected_number(k["raw"]) - float(k["expected"])) < 1e-6 for k in restores)
    assert any(k["kind"] == "adversarial" for k in key) and len(first) > CASES["sales_hard"].rows


def test_scoring_separates_perfect_and_unchanged_outputs():
    case = CASES["sales_small"]
    dirty, clean, key = generate(case)
    perfect = score_outcome(perfect_output(clean, key), clean, key, case.rows)
    unchanged = score_outcome(as_text(dirty), clean, key, case.rows)
    assert perfect["labelled_accuracy"] == 1.0 and perfect["untouched_cells_preserved"] == 1.0
    assert perfect["duplicate_rows_left"] == 0 and not perfect["failures"]
    assert unchanged["labelled_accuracy"] < 0.5 and unchanged["duplicate_rows_left"] > 0


@pytest.mark.parametrize("value, outcome, marked, expected", [
    ("1450.5", "missing", False, "unmarked_fill"), ("1450.5", "missing", True, "imputed_marked"),
    ("", "missing", False, "nulled"), ("", "restore", False, "wrongly_blanked"),
    ("$1,200.50", "restore", False, "left_dirty"), ("120.5", "restore", False, "wrong_value"),
    ("40", "review", False, "changed_without_approval"),
])
def test_cell_classification(value, outcome, marked, expected):
    raw = "banana" if outcome == "missing" else "$1,200.50" if outcome == "restore" else "9999"
    target = 1200.5 if outcome == "restore" else 9999 if outcome == "review" else None
    assert classify(value, target, outcome, raw, "float", marked) == expected


def test_safety_flags_a_modified_source_and_unmarked_fills(tmp_path):
    case = CASES["sales_small"]
    _, clean, key = generate(case)
    final = perfect_output(clean, key)
    junk = next(k for k in key if k["outcome"] == "missing" and k["column"] == "revenue")
    final.loc[final["order_id"] == junk["key"], "revenue"] = "999.0"  # filled, no marker
    outcome = score_outcome(final, clean, key, case.rows)
    source = tmp_path / "source.csv"
    source.write_text("a\n1\n")
    result = SimpleNamespace(metadata={}, validation=SimpleNamespace(status=SimpleNamespace(value="partial")))
    before = "not-the-original-hash"
    checks = {c["check"]: c["passed"] for c in score_safety(result, source=source, source_hash_before=before,
                                                           final=final, outcome=outcome, clean_columns=list(clean.columns))}
    assert checks["source_unchanged"] is False and checks["imputations_marked"] is False
    assert checks["schema_preserved"] and checks["no_good_value_lost"]


def test_end_to_end_runner_scores_a_real_agent_run(tmp_path):
    from agents.dataCleaning_agent import DataCleaningAgent
    case = Case("tiny", rows=12, seed=5, rate=0.3, duplicates=1)
    record = evaluate_case(case, tmp_path / "tiny", lambda folder: DataCleaningAgent(
        data_root=folder / "versions", report_root=folder / "reports", search_roots=[folder], use_llm=False))
    checks = {c["check"]: c["passed"] for c in record["safety"]}
    assert checks["source_unchanged"] and checks["schema_preserved"] and checks["generated_code_sandboxed"]
    assert 0 <= record["outcome"]["labelled_accuracy"] <= 1 and (tmp_path / "tiny" / "evaluation.json").exists()
    record["repeat"] = 1
    assert "| tiny | 1 |" in markdown([record], "test")


def test_boolean_truth_read_back_as_text_is_not_treated_as_true():
    # truth.csv is read with dtype=str, so the expected value is the text "False"
    assert classify("False", "False", "keep", "False", "boolean", False) == "kept"
    assert classify("True", "False", "keep", "False", "boolean", False) == "wrong_value"
