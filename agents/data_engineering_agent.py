import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import pandas as pd

from analytics.profiler import profile_dataset, load_dataset
from analytics.data_quality import calculate_health_scores
from analytics.cleaning import (
    clean_dirty_numeric_series,
    impute_missing_values,
    standardize_categorical_synonyms,
    treat_outliers
)
from agents.llm_client import LLMClient

logger = logging.getLogger(__name__)


class DataEngineeringAgent:
    """
    Autonomous Data Engineering Agent responsible for Data Profiling,
    Data Quality Auditing, LLM Strategy Generation, and Automated Cleaning.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()

    def run_audit(self, file_path: str) -> Dict[str, Any]:
        """
        Runs complete profiling and quality health assessment on a dataset.
        Generates AI cleaning strategy and UI recommendation text.
        """
        profile = profile_dataset(file_path)
        df = load_dataset(file_path)
        health = calculate_health_scores(df)

        system_prompt = (
            "You are a Senior Data Engineer. Analyze the dataset metadata, column types, missing values, "
            "and type issues. Formulate a structured JSON cleaning strategy and a concise natural language "
            "UI recommendation summary."
        )

        # Pass outlier info to LLM
        outlier_cols_info = {
            col: info for col, info in health.get("outlier_info", {}).items()
            if info.get("outlier_count", 0) > 0
        }

        # Build actual unique text values per categorical column for synonym detection
        cat_unique_values = {}
        for c in profile.get("categorical_columns", [])[:15]:
            if c in df.columns:
                uniques = df[c].dropna().astype(str).unique().tolist()
                cat_unique_values[c] = uniques[:30]

        user_prompt = (
            f"Dataset File: {os.path.basename(file_path)}\n"
            f"Rows: {profile['rows']}, Columns: {profile['columns']}\n"
            f"Column Roles: {profile['column_roles']}\n"
            f"Missing Values Info: {health['missing_info']}\n"
            f"Type Mismatches: {health['type_issues']}\n"
            f"Outlier Columns: {outlier_cols_info}\n"
            f"Categorical Columns with actual unique values (for synonym detection):\n"
            f"{cat_unique_values}\n"
            f"Health Score: {health['overall_health_score']}%\n\n"
            f"Instructions:\n"
            f"1. 'numeric_waterfall_columns': list string/object columns with dirty numbers "
            f"(e.g. '$1,200', '1.5k', currency symbols, mixed text+number). Empty [] if none.\n"
            f"2. 'synonym_mappings': inspect the unique values of each categorical column above. "
            f"If you find inconsistent text variants of the same concept "
            f"(e.g. 'M-to-M' and 'Month-to-month'), generate a mapping dirty_variant -> canonical. "
            f"Empty {{}} if all values are already consistent.\n"
            f"3. 'imputation_plan': median for skewed numeric, mean for gaussian, mode for categorical, "
            f"constant 0 for boolean flags.\n"
            f"4. 'outlier_columns': numeric columns with extreme statistical outliers to winsorize.\n\n"
            f"Return ONLY a valid JSON object with this exact schema:\n"
            f"{{\n"
            f'  "recommendation_summary": "1-2 sentence recommendation for the UI banner",\n'
            f'  "numeric_waterfall_columns": ["col_name"],\n'
            f'  "imputation_plan": {{\n'
            f'     "col_name": {{"strategy": "median/mode/mean/constant", "value": null}}\n'
            f'  }},\n'
            f'  "synonym_mappings": {{\n'
            f'     "col_name": {{"dirty_variant": "canonical_value"}}\n'
            f'  }},\n'
            f'  "outlier_columns": ["col_name"]\n'
            f"}}\n"
        )

        llm_strategy = self.llm_client.generate_json(user_prompt, system_prompt)

        # Fallback if LLM JSON is empty
        if not llm_strategy or "recommendation_summary" not in llm_strategy:
            recommendation = (
                f"BIFlow recommends safe cleaning for {len(health['type_issues'])} type mismatches "
                f"and {health['missing_info']['total_missing_cells']} missing values."
            )
            llm_strategy = {
                "recommendation_summary": recommendation,
                "numeric_waterfall_columns": list(health["type_issues"].keys()),
                "imputation_plan": {col: {"strategy": "median"} for col in health["missing_info"]["columns"]},
                "synonym_mappings": {},
                "outlier_columns": list(health.get("outlier_info", {}).keys())
            }

        return {
            "profile": profile,
            "health": health,
            "cleaning_strategy": llm_strategy
        }

    def execute_cleaning(self, file_path: str, strategy: Optional[Dict[str, Any]] = None, preview_mode: bool = False) -> Dict[str, Any]:
        """
        Executes dataset cleaning using:
          1. 4-Level Waterfall Pipeline (dirty numeric strings)
          2. Missing value imputation
          3. Categorical synonym normalization
          4. Outlier winsorizing
        If preview_mode=True, returns diff metadata without saving to disk.
        """
        df_raw = load_dataset(file_path)
        df_clean = df_raw.copy()

        if not strategy:
            audit_res = self.run_audit(file_path)
            strategy = audit_res["cleaning_strategy"]

        transformations_log = []

        # 1. Waterfall cleaning on dirty numeric columns
        waterfall_cols = strategy.get("numeric_waterfall_columns", [])
        for col in waterfall_cols:
            if col in df_clean.columns:
                before_nulls = int(df_clean[col].isna().sum())
                df_clean[col] = clean_dirty_numeric_series(df_clean[col], self.llm_client)
                after_nulls = int(df_clean[col].isna().sum())
                transformations_log.append({
                    "column": col, "action": "numeric_waterfall_cleaning",
                    "nulls_before": before_nulls, "nulls_after": after_nulls
                })

        # 2. Imputation
        impute_plan = strategy.get("imputation_plan", {})
        for col, plan in impute_plan.items():
            if col in df_clean.columns:
                before_nulls = int(df_clean[col].isna().sum())
                transformations_log.append({
                    "column": col, "action": f"imputation_{plan.get('strategy','median')}",
                    "imputed_rows": before_nulls
                })
        df_clean = impute_missing_values(df_clean, impute_plan)

        # 3. Categorical synonym normalization
        synonym_maps = strategy.get("synonym_mappings", {})
        for col, mapping in synonym_maps.items():
            if col in df_clean.columns and mapping:
                transformations_log.append({
                    "column": col, "action": "synonym_normalization",
                    "replacements": len(mapping), "mapping": mapping
                })
        df_clean = standardize_categorical_synonyms(df_clean, synonym_maps)

        # 4. Outlier treatment (Winsorizing at 1st/99th percentile)
        outlier_cols = strategy.get("outlier_columns", [])
        if outlier_cols:
            for col in outlier_cols:
                if col in df_clean.columns:
                    q_low  = float(df_clean[col].quantile(0.01))
                    q_high = float(df_clean[col].quantile(0.99))
                    transformations_log.append({
                        "column": col, "action": "outlier_winsorizing",
                        "capped_at": {"low": q_low, "high": q_high}
                    })
            df_clean = treat_outliers(df_clean, outlier_cols, method="cap")

        health_after = calculate_health_scores(df_clean)

        # Preview mode
        if preview_mode:
            return {
                "status": "preview",
                "rows_processed": len(df_clean),
                "columns_processed": len(df_clean.columns),
                "health_after": health_after
            }

        # Save outputs
        os.makedirs("data/cleaned", exist_ok=True)
        os.makedirs("data/processed", exist_ok=True)

        base_name = os.path.splitext(os.path.basename(file_path))[0]
        cleaned_path = f"data/cleaned/{base_name}_cleaned.csv"
        df_clean.to_csv(cleaned_path, index=False)

        # Save processed Parquet (ML-ready)
        processed_path = f"data/processed/{base_name}_processed.parquet"
        df_clean.to_parquet(processed_path, index=False)

        # Generate audit log JSON (spec §5.3)
        health_before = calculate_health_scores(df_raw)
        audit_log = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw_file": file_path,
            "cleaned_file": cleaned_path,
            "processed_file": processed_path,
            "quality_score_before": health_before["overall_health_score"],
            "quality_score_after": health_after["overall_health_score"],
            "applied_transformations": transformations_log
        }

        audit_log_path = f"data/cleaned/{base_name}_transformation_log.json"
        with open(audit_log_path, "w", encoding="utf-8") as f:
            json.dump(audit_log, f, indent=2)

        return {
            "status": "success",
            "cleaned_file_path": cleaned_path,
            "audit_log_path": audit_log_path,
            "health_after": health_after
        }
