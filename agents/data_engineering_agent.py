import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Protocol

import pandas as pd

from analytics.profiler import profile_dataset, load_dataset
from analytics.data_quality import (
    calculate_health_scores,
    run_sandboxed_check,
    detect_cross_column_issues,
)
from agents.llm_client import LLMClient

logger = logging.getLogger(__name__)

_AGENT_VERSION = "2.0.0"


class JSONLLMClient(Protocol):
    def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]: ...


class DataEngineeringAgent:
    """
    Autonomous Data Engineering Agent — Data Profiling, Quality Auditing,
    Reasoning, Sandbox Check Generation, and Cleaning Strategy.

    Agent 1 (this class) produces a ProfilingReport that contains:
      - Per-column reasoning trails (what the LLM thinks each issue means)
      - Sandbox-tested custom check results for uncertain columns
      - Cross-column integrity findings
      - ETL hints for downstream processing
    """

    def __init__(self, llm_client: Optional[JSONLLMClient] = None):
        self.llm_client = llm_client or LLMClient()

    # ────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ────────────────────────────────────────────────────────────────────────

    def run_audit(self, file_path: str) -> Dict[str, Any]:
        """
        Full autonomous audit pipeline:
          1. Python analysis  — fast, deterministic stats
          2. LLM reasoning    — per-column interpretation + ETL hints
          3. Sandbox checks   — LLM writes custom Python check, we execute it
          4. Cross-column     — deterministic integrity checks
          5. ProfilingReport  — structured output for Agent 2

        Returns a dict containing:
          - "profile"          : raw profiler output (backward compat)
          - "health"           : health scores dict  (backward compat)
          - "cleaning_strategy": flat strategy dict  (backward compat)
          - "profiling_report" : full structured ProfilingReport (NEW)
        """
        logger.info("Starting autonomous audit: %s", file_path)

        # ── Step 1: Python analysis ─────────────────────────────────────────
        profile = profile_dataset(file_path)
        df = load_dataset(file_path)
        health = calculate_health_scores(df)
        cross_issues = detect_cross_column_issues(df)

        # ── Step 2: Build per-column evidence (sample values + stats) ───────
        column_evidence = self._build_column_evidence(df, profile, health)

        # ── Step 3: LLM reasons over the full dataset ───────────────────────
        llm_report = self._llm_reason_over_dataset(file_path, profile, health, column_evidence)

        # ── Step 4: Sandbox custom checks for flagged columns ───────────────
        sandbox_results = self._run_custom_checks(df, llm_report, column_evidence)

        # ── Step 5: Assemble ProfilingReport ────────────────────────────────
        profiling_report = self._build_profiling_report(
            file_path, df, profile, health, column_evidence,
            llm_report, sandbox_results, cross_issues
        )

        # ── Step 6: Extract backward-compatible cleaning_strategy ────────────
        cleaning_strategy = self._extract_cleaning_strategy(health, llm_report, profile, df)

        # ── Step 7: Save ProfilingReport JSON for Agent 2 (Cleaning) ─────────
        os.makedirs("data/reports", exist_ok=True)
        base_name   = os.path.splitext(os.path.basename(file_path))[0]
        report_path = f"data/reports/{base_name}_profiling_report.json"
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(profiling_report, f, indent=2, default=str)
            logger.info("ProfilingReport saved → %s", report_path)
        except Exception as e:
            logger.warning("Could not save ProfilingReport JSON: %s", e)

        return {
            "profile":           profile,
            "health":            health,
            "cleaning_strategy": cleaning_strategy,
            "profiling_report":  profiling_report,
            "report_path":       report_path,
        }

    # ────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ────────────────────────────────────────────────────────────────────────

    def _build_column_evidence(
        self,
        df: pd.DataFrame,
        profile: Dict[str, Any],
        health: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        """
        Build RICH per-column evidence for the LLM.
        Every column gets full stats — not just flagged ones.
        The LLM must see everything to reason freely.
        """
        evidence = {}
        missing_cols = health["missing_info"]["columns"]
        type_issues  = health["type_issues"]
        outlier_info = health["outlier_info"]
        total_rows   = max(len(df), 1)

        for col in df.columns:
            series     = df[col]
            non_null   = series.dropna()
            sample_vals = non_null.astype(str).head(8).tolist()

            col_ev: Dict[str, Any] = {
                # ── Basic metadata ──────────────────────────────────────────
                "dtype":          str(series.dtype),
                "inferred_role":  profile["column_roles"].get(col, "unknown"),
                "total_rows":     total_rows,
                "missing_count":  missing_cols.get(col, 0),
                "missing_pct":    round(missing_cols.get(col, 0) / total_rows * 100, 2),
                "unique_count":   int(series.nunique(dropna=True)),
                "unique_pct":     round(series.nunique(dropna=True) / total_rows * 100, 2),
                "sample_values":  sample_vals,

                # ── Python-detected issues (evidence, not commands) ─────────
                "python_detected_type_issue": type_issues.get(col, None),
                "python_detected_outliers":   outlier_info.get(col, None),

                # ── Numeric stats (if applicable) ───────────────────────────
                "numeric_stats": {},

                # ── Categorical stats (if applicable) ───────────────────────
                "unique_values":  [],
                "value_counts":   {},

                # ── Zero variance / constant column ─────────────────────────
                "is_constant": bool(series.nunique(dropna=True) <= 1),

                # ── All-null column ─────────────────────────────────────────
                "is_all_null": bool(series.isna().all()),
            }

            # Numeric stats
            if pd.api.types.is_numeric_dtype(series) and len(non_null) > 0:
                col_ev["numeric_stats"] = {
                    "mean":   round(float(non_null.mean()), 4),
                    "median": round(float(non_null.median()), 4),
                    "std":    round(float(non_null.std()), 4),
                    "min":    round(float(non_null.min()), 4),
                    "max":    round(float(non_null.max()), 4),
                    "q1":     round(float(non_null.quantile(0.25)), 4),
                    "q3":     round(float(non_null.quantile(0.75)), 4),
                    "skewness": round(float(non_null.skew()), 4),
                    "zeros_count": int((non_null == 0).sum()),
                    "negative_count": int((non_null < 0).sum()),
                }

            # Categorical: top value counts + unique values (for synonym detection)
            if series.dtype == "object" or str(series.dtype) == "category":
                n_unique = series.nunique(dropna=True)
                if n_unique <= 50:
                    col_ev["unique_values"] = (
                        non_null.astype(str).unique().tolist()[:50]
                    )
                # Top 10 value counts
                vc = series.value_counts(dropna=True).head(10)
                col_ev["value_counts"] = {
                    str(k): int(v) for k, v in vc.items()
                }

            evidence[col] = col_ev

        return evidence

    def _llm_reason_over_dataset(
        self,
        file_path: str,
        profile: Dict[str, Any],
        health: Dict[str, Any],
        column_evidence: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        The LLM investigates the FULL dataset freely.
        
        For large datasets with many columns, we batch columns to avoid
        timeout issues while still getting LLM reasoning.
        """
        total_columns = len(column_evidence)
        
        # If dataset has many columns, process in batches to avoid timeout
        if total_columns > 50:
            logger.info(f"Large dataset ({total_columns} columns) - processing in batches")
            return self._llm_reason_batched(file_path, profile, health, column_evidence)
        
        # For smaller datasets, process all at once
        return self._llm_reason_single_batch(file_path, profile, health, column_evidence)
    
    def _llm_reason_single_batch(
        self,
        file_path: str,
        profile: Dict[str, Any],
        health: Dict[str, Any],
        column_evidence: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Process all columns in a single LLM call (for datasets with <50 columns)."""
        # Build COMPACT evidence - only critical info
        cols_for_llm = {}
        for col, ev in column_evidence.items():
            cols_for_llm[col] = {
                "dtype": ev["dtype"],
                "role": ev["inferred_role"],
                "missing": f"{ev['missing_count']} ({ev['missing_pct']}%)",
                "unique": ev["unique_count"],
                "samples": ev["sample_values"][:3],  # Only 3 samples instead of 8
                "issue": ev.get("python_detected_type_issue", {}).get("issue", "none") if ev.get("python_detected_type_issue") else "none"
            }
            # Add only key stats for numerics
            if ev["numeric_stats"]:
                cols_for_llm[col]["stats"] = {
                    "mean": ev["numeric_stats"].get("mean"),
                    "min": ev["numeric_stats"].get("min"),
                    "max": ev["numeric_stats"].get("max"),
                }

        system_prompt = (
            "You are a Data Engineer. Analyze columns and return JSON with:\n"
            "1. column_reasoning: {col: {severity: HIGH|MEDIUM|LOW|NONE, agent_reasoning: brief text, imputation_strategy: median|mean|mode|drop}}\n"
            "2. agent_summary: 2 sentences\n"
            "3. numeric_waterfall_columns: [cols needing numeric cleaning]\n"
            "4. outlier_columns: [cols with outliers]\n"
            "Be brief and decisive."
        )

        user_prompt = (
            f"Dataset: {os.path.basename(file_path)}\n"
            f"Shape: {profile['rows']} rows × {profile['columns']} cols\n"
            f"Health: {health['overall_health_score']}%\n"
            f"Columns:\n{json.dumps(cols_for_llm, indent=1)}\n\n"
            f"Return JSON with column_reasoning, agent_summary, numeric_waterfall_columns, outlier_columns"
        )

        result = self.llm_client.generate_json(user_prompt, system_prompt)
        if not result or "column_reasoning" not in result:
            logger.warning("LLM reasoning failed — using rule-based fallback")
            result = self._fallback_llm_report(health, profile, column_evidence)
        else:
            logger.info(
                "LLM reasoned over %d columns, flagged %d for custom checks, "
                "discovered %d new issues",
                len(result.get("column_reasoning", {})),
                sum(1 for r in result.get("column_reasoning", {}).values()
                    if r.get("needs_custom_check")),
                len(result.get("llm_discovered_issues", [])),
            )

        return result

    def _run_custom_checks(
        self,
        df: pd.DataFrame,
        llm_report: Dict[str, Any],
        column_evidence: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """
        For columns where LLM flagged needs_custom_check=True:
          1. Ask LLM to write a custom_check() function
          2. Sandbox-execute it on the actual column data
          3. Return results keyed by column name
        """
        sandbox_results: Dict[str, Dict[str, Any]] = {}
        col_reasoning = llm_report.get("column_reasoning", {})

        for col, reasoning in col_reasoning.items():
            if not reasoning.get("needs_custom_check", False):
                continue
            if col not in df.columns:
                continue

            description = reasoning.get("custom_check_description", "")
            if not description:
                continue

            logger.info("Generating sandbox check for column: %s", col)

            # Ask LLM to write the check function
            code_prompt = (
                f"Write a Python function to validate a pandas Series column named '{col}'.\n"
                f"What to check: {description}\n"
                f"Column dtype: {column_evidence[col]['dtype']}\n"
                f"Sample values: {column_evidence[col]['sample_values']}\n\n"
                f"Rules:\n"
                f"- Define ONLY: def custom_check(series: pd.Series) -> dict\n"
                f"- Return: {{\"passed\": bool, \"metric\": float|str, \"details\": str}}\n"
                f"- Use only: pd, np, re, built-in Python functions\n"
                f"- NO imports, NO file I/O, NO external calls\n"
                f"- Keep it under 20 lines\n\n"
                f"Return JSON: {{\"code\": \"<full python code here>\"}}"
            )
            code_result = self.llm_client.generate_json(code_prompt)
            if not code_result or "code" not in code_result:
                sandbox_results[col] = {
                    "skipped": True,
                    "reason": "LLM did not generate check code",
                    "check_description": description,
                }
                continue

            check_code = code_result["code"]
            series = df[col]

            # Run on sample (50 rows max) to keep it fast
            sample_series = series.head(500)
            sandbox_result = run_sandboxed_check(check_code, sample_series, timeout_sec=8)

            sandbox_results[col] = {
                "skipped": False,
                "check_description": description,
                "generated_code": check_code,
                "result": sandbox_result,
                "sample_size": len(sample_series),
            }
            logger.info("Sandbox check for '%s': passed=%s, metric=%s",
                        col, sandbox_result.get("passed"), sandbox_result.get("metric"))

        return sandbox_results

    def _build_profiling_report(
        self,
        file_path: str,
        df: pd.DataFrame,
        profile: Dict[str, Any],
        health: Dict[str, Any],
        column_evidence: Dict[str, Dict[str, Any]],
        llm_report: Dict[str, Any],
        sandbox_results: Dict[str, Dict[str, Any]],
        cross_issues: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Assembles the full structured ProfilingReport for Agent 2 (Cleaning)."""
        col_reasoning = llm_report.get("column_reasoning", {})

        # Per-column profiles
        column_profiles: Dict[str, Any] = {}
        for col, ev in column_evidence.items():
            reasoning = col_reasoning.get(col, {})
            sandbox   = sandbox_results.get(col)

            # Issues list — merge Python findings + LLM assessment
            issues = []

            # Python-detected type issue
            if ev["python_detected_type_issue"]:
                ti = ev["python_detected_type_issue"]
                issues.append({
                    "issue_id":   "type_mismatch",
                    "source":     "python",
                    "severity":   reasoning.get("severity", "MEDIUM"),
                    "description": ti.get("issue", "Type issue detected"),
                    "evidence": {
                        "detected":        ti.get("detected", ""),
                        "recommendation":  ti.get("recommendation", ""),
                        "valid_ratio":     ti.get("valid_numeric_ratio"),
                    },
                    "llm_agreement": reasoning.get("python_agreement", "agree"),
                })

            # Missing values
            if ev["missing_count"] > 0:
                issues.append({
                    "issue_id":   "missing_values",
                    "source":     "python",
                    "severity":   "HIGH" if ev["missing_pct"] > 10 else "MEDIUM",
                    "description": f"Missing values: {ev['missing_count']} ({ev['missing_pct']}%)",
                    "evidence":   {"count": ev["missing_count"], "pct": ev["missing_pct"]},
                })

            # Outliers
            if ev["python_detected_outliers"]:
                oi = ev["python_detected_outliers"]
                issues.append({
                    "issue_id":   "statistical_outliers",
                    "source":     "python",
                    "severity":   "MEDIUM",
                    "description": f"{oi.get('outlier_count', 0)} statistical outliers (IQR)",
                    "evidence": {
                        "outlier_count": oi.get("outlier_count"),
                        "outlier_pct":   oi.get("outlier_pct"),
                        "bounds":        {"low": oi.get("lower_bound"),
                                          "high": oi.get("upper_bound")},
                    },
                })

            # Constant / zero-variance column
            if ev.get("is_constant"):
                issues.append({
                    "issue_id":   "zero_variance",
                    "source":     "python",
                    "severity":   "LOW",
                    "description": "Column has zero variance (constant value) — no analytical value",
                    "evidence":   {},
                })

            # Sandbox result (LLM-generated check)
            sandbox_issues = []
            if sandbox and not sandbox.get("skipped") and sandbox.get("result"):
                r = sandbox["result"]
                if r.get("passed") is False:
                    sandbox_issues.append({
                        "issue_id":   "sandbox_check_failed",
                        "source":     "sandbox",
                        "severity":   "MEDIUM",
                        "description": f"Custom check failed: {r.get('details', '')}",
                        "evidence":   {
                            "check_name":  sandbox.get("check_description", ""),
                            "metric":      r.get("metric"),
                            "sample_size": sandbox.get("sample_size"),
                        },
                    })

            col_profile: Dict[str, Any] = {
                # ── Raw stats ──────────────────────────────────────────────
                "dtype":            ev["dtype"],
                "inferred_role":    ev["inferred_role"],
                "missing_count":    ev["missing_count"],
                "missing_pct":      ev["missing_pct"],
                "unique_count":     ev["unique_count"],
                "unique_pct":       ev["unique_pct"],
                "sample_values":    ev["sample_values"],
                "numeric_stats":    ev.get("numeric_stats", {}),
                "value_counts":     ev.get("value_counts", {}),
                "is_constant":      ev.get("is_constant", False),

                # ── Issues (Python + Sandbox) ──────────────────────────────
                "issues":           issues + sandbox_issues,

                # ── LLM reasoning ─────────────────────────────────────────
                "agent_reasoning":           reasoning.get("agent_reasoning", ""),
                "business_interpretation":   reasoning.get("business_interpretation", ""),
                "severity":                  reasoning.get("severity", "NONE"),
                "uncertainty":               reasoning.get("uncertainty", "LOW"),
                "python_agreement":          reasoning.get("python_agreement", "agree"),
                "drop_recommended":          reasoning.get("drop_recommended", False),

                # ── Cleaning hints for Agent 2 ─────────────────────────────
                "imputation_strategy":  reasoning.get("imputation_strategy", "none"),
                "etl_cast_to":          reasoning.get("etl_cast_to", "none"),

                # ── Sandbox ────────────────────────────────────────────────
                "sandbox_triggered":   bool(sandbox and not sandbox.get("skipped")),
                "sandbox_result":      sandbox.get("result") if sandbox else None,
                "custom_check_code":   sandbox.get("generated_code") if sandbox else None,
            }

            column_profiles[col] = col_profile

        # ETL hints
        type_casting = {
            col: r.get("etl_cast_to")
            for col, r in col_reasoning.items()
            if r.get("etl_cast_to") and r.get("etl_cast_to") != "none"
        }
        etl_hints = {
            "type_casting_targets":      type_casting,
            "join_key_candidates":       llm_report.get("join_key_candidates", []),
            "drop_candidates":           llm_report.get("drop_candidates", []),
            "recommended_output_format": llm_report.get("recommended_output_format", "parquet"),
            "synonym_mappings":          llm_report.get("synonym_mappings", {}),
        }

        # Recommended cleaning order
        sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "NONE": 3}
        cols_with_issues = [
            (col, prof["severity"], prof["missing_count"])
            for col, prof in column_profiles.items()
            if prof["issues"]
        ]
        cols_sorted = sorted(
            cols_with_issues,
            key=lambda x: (sev_order.get(x[1], 3), -x[2])
        )
        recommended_order = [c[0] for c in cols_sorted]

        sandbox_count = sum(
            1 for r in sandbox_results.values() if not r.get("skipped", True)
        )

        return {
            "schema_version": "2.1",
            "dataset_ref": {
                "file_path":   file_path,
                "file_name":   os.path.basename(file_path),
                "rows":        profile["rows"],
                "columns":     profile["columns"],
                "size_bytes":  os.path.getsize(file_path) if os.path.exists(file_path) else 0,
            },
            "health_scores": {
                "overall":      health["overall_health_score"],
                "completeness": health["completeness"],
                "validity":     health["validity"],
                "uniqueness":   health["uniqueness"],
                "consistency":  health["consistency"],
            },
            "column_profiles":              column_profiles,
            "cross_column_issues":          cross_issues,
            "llm_discovered_issues":        llm_report.get("llm_discovered_issues", []),
            "uncertainty_flags":            llm_report.get("uncertainty_flags", []),
            "recommended_cleaning_order":   recommended_order,
            "etl_hints":                    etl_hints,
            "imputation_plan":              llm_report.get("imputation_plan", {}),
            "outlier_columns":              llm_report.get("outlier_columns", []),
            "agent_summary":                llm_report.get("agent_summary", ""),
            "recommendation_summary":       llm_report.get("recommendation_summary", ""),
            "metadata": {
                "agent_version":       _AGENT_VERSION,
                "profiling_timestamp": datetime.now(timezone.utc).isoformat(),
                "llm_model_used":      "gemini-flash-latest",
                "sandbox_executions":  sandbox_count,
                "llm_driven":          True,
            },
        }

    def _extract_cleaning_strategy(
        self,
        health: Dict[str, Any],
        llm_report: Dict[str, Any],
        profile: Dict[str, Any],
        df: pd.DataFrame,
    ) -> Dict[str, Any]:
        """Extract backward-compatible cleaning_strategy dict from LLM report."""
        # Prefer LLM-generated fields; fall back to rule-based if missing
        strategy = {
            "recommendation_summary": llm_report.get(
                "recommendation_summary",
                f"BIFlow recommends safe cleaning for {len(health['type_issues'])} type issues "
                f"and {health['missing_info']['total_missing_cells']} missing values."
            ),
            "numeric_waterfall_columns": llm_report.get(
                "numeric_waterfall_columns",
                list(health["type_issues"].keys())
            ),
            "imputation_plan": llm_report.get(
                "imputation_plan",
                {col: {"strategy": "median"} for col in health["missing_info"]["columns"]}
            ),
            "synonym_mappings": llm_report.get("synonym_mappings", {}),
            "outlier_columns": llm_report.get(
                "outlier_columns",
                [col for col, info in health.get("outlier_info", {}).items()
                 if info.get("outlier_count", 0) > 0]
            ),
        }
        return strategy

    def _fallback_llm_report(
        self,
        health: Dict[str, Any],
        profile: Dict[str, Any],
        column_evidence: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Rule-based fallback when LLM call fails - generates intelligent reasoning."""
        col_reasoning = {}
        for col, ev in column_evidence.items():
            # Determine severity
            severity = "NONE"
            if ev.get("python_detected_type_issue") or (ev["missing_pct"] > 5):
                severity = "MEDIUM"
            if ev["missing_pct"] > 20:
                severity = "HIGH"
            if ev.get("is_constant"):
                severity = "LOW"
            
            # Generate intelligent reasoning text based on evidence
            reasoning_parts = []
            
            # Missing values
            if ev["missing_pct"] > 0:
                if ev["missing_pct"] > 50:
                    reasoning_parts.append(f"{ev['missing_pct']:.1f}% missing values indicates severe sparsity")
                elif ev["missing_pct"] > 20:
                    reasoning_parts.append(f"{ev['missing_pct']:.1f}% missing values requiring imputation")
                else:
                    reasoning_parts.append(f"{ev['missing_count']} missing values ({ev['missing_pct']:.1f}%)")
            else:
                reasoning_parts.append("Complete data with no missing values")
            
            # Type issues
            if ev.get("python_detected_type_issue"):
                ti = ev["python_detected_type_issue"]
                reasoning_parts.append(f"Type issue: {ti.get('issue', 'unknown')}")
            
            # Outliers
            if ev.get("python_detected_outliers"):
                oi = ev["python_detected_outliers"]
                reasoning_parts.append(f"{oi.get('outlier_count', 0)} outliers detected ({oi.get('outlier_pct', 0):.1f}%)")
            
            # Cardinality for categorical
            if ev["dtype"] == "object" or ev["inferred_role"] == "categorical":
                if ev["unique_count"] == 2:
                    reasoning_parts.append("Binary categorical feature")
                elif ev["unique_count"] <= 10:
                    reasoning_parts.append(f"Low cardinality categorical ({ev['unique_count']} categories)")
                elif ev["unique_count"] > 100:
                    reasoning_parts.append(f"High cardinality ({ev['unique_count']} unique values)")
            
            # Zero variance
            if ev.get("is_constant"):
                reasoning_parts.append("Zero variance - consider dropping")
            
            # Default if no issues
            if not reasoning_parts or severity == "NONE":
                if ev["inferred_role"] == "primary_key":
                    reasoning_parts = ["Unique identifier with no analytical value"]
                elif ev["inferred_role"] == "categorical":
                    reasoning_parts = [f"Clean categorical column with {ev['unique_count']} categories"]
                elif ev["inferred_role"] == "continuous_numeric":
                    reasoning_parts = ["Complete numeric data with standard distribution"]
                else:
                    reasoning_parts = ["Column analyzed with rule-based detection"]
            
            agent_reasoning = "; ".join(reasoning_parts) + "."
            
            col_reasoning[col] = {
                "business_interpretation": f"Column '{col}' ({ev['inferred_role']})",
                "severity":               severity,
                "agent_reasoning":        agent_reasoning,
                "python_agreement":       "agree",
                "needs_custom_check":     False,
                "custom_check_description": "",
                "uncertainty":            "MEDIUM",  # Changed from HIGH
                "imputation_strategy":    "median" if ev["dtype"] != "object" else "mode",
                "etl_cast_to":            "none",
                "drop_recommended":       ev.get("is_constant", False),
            }
        return {
            "column_reasoning":     col_reasoning,
            "llm_discovered_issues": [],
            "agent_summary": (
                f"Dataset has {health['overall_health_score']}% health score. "
                f"LLM reasoning was unavailable — results are rule-based only."
            ),
            "recommendation_summary": (
                f"Rule-based analysis found {len(health['type_issues'])} type issues "
                f"and {health['missing_info']['total_missing_cells']} missing values."
            ),
            "numeric_waterfall_columns": list(health["type_issues"].keys()),
            "imputation_plan": {
                col: {"strategy": "median"} for col in health["missing_info"]["columns"]
            },
            "synonym_mappings":          {},
            "outlier_columns": [
                col for col, info in health.get("outlier_info", {}).items()
                if info.get("outlier_count", 0) > 0
            ],
            "join_key_candidates":       [],
            "drop_candidates":           [],
            "recommended_output_format": "parquet",
            "uncertainty_flags":         [],
        }

    def _llm_reason_batched(
        self,
        file_path: str,
        profile: Dict[str, Any],
        health: Dict[str, Any],
        column_evidence: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Process columns in batches of 30 to avoid timeout.
        Merge results from all batches.
        """
        batch_size = 30
        all_cols = list(column_evidence.keys())
        batches = [all_cols[i:i + batch_size] for i in range(0, len(all_cols), batch_size)]
        
        merged_reasoning = {}
        all_discovered_issues = []
        
        for batch_idx, batch_cols in enumerate(batches):
            logger.info(f"Processing batch {batch_idx + 1}/{len(batches)} ({len(batch_cols)} columns)")
            
            batch_evidence = {col: column_evidence[col] for col in batch_cols}
            batch_result = self._llm_reason_single_batch(
                file_path, profile, health, batch_evidence
            )
            
            # Merge results
            merged_reasoning.update(batch_result.get("column_reasoning", {}))
            all_discovered_issues.extend(batch_result.get("llm_discovered_issues", []))
        
        # Generate final summary based on all batches
        return {
            "column_reasoning": merged_reasoning,
            "llm_discovered_issues": all_discovered_issues,
            "agent_summary": f"Analyzed {len(all_cols)} columns in {len(batches)} batches. Health score: {health['overall_health_score']}%",
            "recommendation_summary": f"Found {len(health['type_issues'])} type issues, {health['missing_info']['total_missing_cells']} missing values",
            "numeric_waterfall_columns": list(health["type_issues"].keys()),
            "imputation_plan": {
                col: {"strategy": "median"} for col in health["missing_info"]["columns"]
            },
            "synonym_mappings": {},
            "outlier_columns": [
                col for col, info in health.get("outlier_info", {}).items()
                if info.get("outlier_count", 0) > 0
            ],
            "join_key_candidates": [],
            "drop_candidates": [],
            "recommended_output_format": "parquet",
            "uncertainty_flags": [],
        }
