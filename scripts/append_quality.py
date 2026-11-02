
SANDBOX_CODE = r'''

# ── Sandbox Executor ──────────────────────────────────────────────────────────

_SAFE_BUILTINS = {
    "len": len, "range": range, "enumerate": enumerate, "zip": zip,
    "map": map, "filter": filter, "sorted": sorted, "min": min, "max": max,
    "sum": sum, "abs": abs, "round": round, "int": int, "float": float,
    "str": str, "bool": bool, "list": list, "dict": dict, "set": set,
    "tuple": tuple, "type": type, "isinstance": isinstance, "print": print,
    "repr": repr, "any": any, "all": all, "next": next, "iter": iter,
    "hasattr": hasattr, "getattr": getattr,
    "None": None, "True": True, "False": False,
}


def _run_with_timeout(fn, timeout_sec=10):
    result_box = [None]
    error_box = [None]
    def _target():
        try:
            result_box[0] = fn()
        except Exception:
            error_box[0] = traceback.format_exc()
    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)
    if t.is_alive():
        return None, f"TimeoutError: custom_check exceeded {timeout_sec}s"
    return result_box[0], error_box[0]


def run_sandboxed_check(code, series, timeout_sec=10):
    """
    Safely execute LLM-generated Python check code in a sandboxed namespace.
    Code must define: def custom_check(series) -> dict
    Returns: {"passed": bool|None, "metric": ..., "details": str|None, "error": str|None}
    """
    namespace = {
        "__builtins__": _SAFE_BUILTINS,
        "pd": pd, "np": np, "re": re,
    }
    try:
        exec(textwrap.dedent(code), namespace)
    except SyntaxError as exc:
        return {"passed": None, "metric": None, "details": None, "error": f"SyntaxError: {exc}"}
    except Exception as exc:
        return {"passed": None, "metric": None, "details": None, "error": f"Exec error: {exc}"}

    if "custom_check" not in namespace:
        return {"passed": None, "metric": None, "details": None, "error": "Code must define custom_check(series)"}

    result, error = _run_with_timeout(lambda: namespace["custom_check"](series), timeout_sec)
    if error:
        return {"passed": None, "metric": None, "details": None, "error": error}
    if not isinstance(result, dict):
        return {"passed": None, "metric": None, "details": repr(result), "error": "custom_check() must return a dict"}
    return {"passed": result.get("passed"), "metric": result.get("metric"),
            "details": result.get("details"), "error": None}


# ── Cross-column integrity checks ─────────────────────────────────────────────

def detect_cross_column_issues(df):
    """
    Detects cross-column logical inconsistencies.
    Returns list of {columns, issue, affected_rows, severity, recommendation}.
    """
    issues = []
    cols_lower = {c.lower(): c for c in df.columns}

    # tenure=0 but TotalCharges>0
    tenure_col = cols_lower.get("tenure")
    tc_col = cols_lower.get("totalcharges")
    if tenure_col and tc_col:
        tc_num = pd.to_numeric(df[tc_col], errors="coerce")
        mask = (df[tenure_col] == 0) & (tc_num > 0)
        n = int(mask.sum())
        if n > 0:
            issues.append({"columns": [tenure_col, tc_col],
                "issue": "Tenure=0 but TotalCharges>0 — logical impossibility",
                "affected_rows": n, "severity": "HIGH",
                "recommendation": "Set TotalCharges=0 where tenure=0, or verify source"})

    # MonthlyCharges * tenure mismatch with TotalCharges
    mc_col = cols_lower.get("monthlycharges")
    if tenure_col and mc_col and tc_col:
        tc_num = pd.to_numeric(df[tc_col], errors="coerce")
        mc_num = pd.to_numeric(df[mc_col], errors="coerce")
        ten_num = pd.to_numeric(df[tenure_col], errors="coerce")
        expected = mc_num * ten_num
        pct_diff = ((tc_num - expected).abs() / (expected.abs() + 1e-9)) * 100
        n = int((pct_diff > 50).sum())
        if n > 0:
            issues.append({"columns": [tenure_col, mc_col, tc_col],
                "issue": f"TotalCharges deviates >50% from MonthlyCharges x Tenure in {n} rows",
                "affected_rows": n, "severity": "MEDIUM",
                "recommendation": "Investigate prorated charges, discounts, or data entry errors"})

    # Negative values in inherently-positive columns
    for col in df.select_dtypes(include="number").columns:
        if any(kw in col.lower() for kw in ["price", "charge", "amount", "cost", "revenue", "salary", "age"]):
            n_neg = int((df[col] < 0).sum())
            if n_neg > 0:
                issues.append({"columns": [col],
                    "issue": f"Negative values in '{col}' (should always be positive)",
                    "affected_rows": n_neg, "severity": "HIGH",
                    "recommendation": "Check for sign error or encoding artifact in source data"})

    # Date logic: end before start
    date_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    start_cols = [c for c in date_cols if any(kw in c.lower() for kw in ["start","begin","created","open"])]
    end_cols   = [c for c in date_cols if any(kw in c.lower() for kw in ["end","expir","closed","finish"])]
    for sc in start_cols:
        for ec in end_cols:
            n = int((df[ec] < df[sc]).sum())
            if n > 0:
                issues.append({"columns": [sc, ec],
                    "issue": f"'{ec}' is before '{sc}' in {n} rows",
                    "affected_rows": n, "severity": "HIGH",
                    "recommendation": "Check for date entry errors or timezone mismatches"})
    return issues
'''

with open('analytics/data_quality.py', 'rb') as f:
    existing = f.read()

with open('analytics/data_quality.py', 'wb') as f:
    f.write(existing)
    f.write(SANDBOX_CODE.encode('utf-8'))

print("Done - appended sandbox + cross-column checks")
