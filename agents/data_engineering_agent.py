import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import pandas as pd

from analytics.profiler import profile_dataset, load_dataset
from analytics.data_quality import calculate_health_scores
from analytics.etl import validate_transformed_dataset
from analytics.cleaning import (
    clean_dirty_numeric_series,
    impute_missing_values,
    standardize_categorical_synonyms,
    treat_outliers
)
from agents.llm_client import LLMClient, LLMRateLimitError

logger = logging.getLogger(__name__)

PROFILE_COLUMNS_PER_REQUEST = 5
PROFILE_MAX_OUTPUT_TOKENS = 150
SINGLE_COLUMN_PROFILE_MAX_OUTPUT_TOKENS = 100
QUALITY_PLAN_MAX_OUTPUT_TOKENS = 200
QUALITY_STRATEGY_REPAIR_MAX_OUTPUT_TOKENS = 180
QUALITY_IMPUTATION_PLAN_MAX_OUTPUT_TOKENS = 160


class DataEngineeringAgent:
    """
    Autonomous Data Engineering Agent responsible for Data Profiling,
    Data Quality Auditing, LLM Strategy Generation, and Automated Cleaning.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()

    def run_workflow(
        self,
        file_path: str,
        workflow: str,
        destination_format: str = "both",
    ) -> Dict[str, Any]:
        try:
            return self._run_llm_workflow(file_path, workflow, destination_format)
        except LLMRateLimitError as error:
            logger.warning(
                "LLM quota reached; running deterministic workflow for %s: %s",
                file_path,
                error,
            )
            return self._run_deterministic_workflow(
                file_path,
                workflow,
                destination_format,
            )

    def _run_llm_workflow(
        self,
        file_path: str,
        workflow: str,
        destination_format: str,
    ) -> Dict[str, Any]:
        """Run a selected workflow using an LLM decision at every analysis stage."""
        if workflow not in {"profiling", "profiling_quality_cleaning"}:
            raise ValueError(f"Unsupported workflow: {workflow}")

        df = load_dataset(file_path)
        profile = profile_dataset(file_path)
        health = calculate_health_scores(df)
        llm_context = {
            "file_name": os.path.basename(file_path),
            "rows": profile["rows"],
            "columns": profile["columns"],
            "column_types": profile["column_types"],
            "column_roles": profile["column_roles"],
            "unique_values_per_column": profile["unique_values"],
            "missing_values_per_column": profile["missing_values"],
            "duplicate_rows": profile["duplicate_rows"],
            "numerical_statistics": profile["numerical_statistics"],
            "quality_report": {
                "overall_health_score": health["overall_health_score"],
                "completeness": health["completeness"],
                "validity": health["validity"],
                "uniqueness": health["uniqueness"],
                "consistency": health["consistency"],
                "missing_info": health["missing_info"],
                "duplicate_info": health["duplicate_info"],
                "type_issues": health["type_issues"],
                "outlier_info": health["outlier_info"],
            },
        }

        analysis = self._request_llm_profile_in_chunks(
            "You are a data profiling agent. Produce evidence-based profiling results "
            "from the supplied dataset metadata. Do not invent values. Follow the requested "
            "JSON structure exactly and always include a concise, non-empty profile_summary.",
            llm_context,
            profile["column_names"],
        )
        if workflow == "profiling":
            return {
                "status": "success",
                "workflow": workflow,
                "profile": profile,
                "llm_analysis": analysis,
            }

        prompt = (
            "Assess data quality and return a concise JSON object with quality_findings "
            "(an array of short strings) and cleaning_strategy with exactly these fields: "
            "numeric_waterfall_columns (array), imputation_plan (object mapping column to "
            "{strategy: median|mean|mode|constant, value: optional}), synonym_mappings (object), "
            "outlier_columns (array), date_columns (array), boolean_columns (array), "
            "remove_duplicates (boolean). Select actions based on the report; do not include "
            "columns that do not need the operation. Do not return profile fields in this response.\n"
            f"Dataset metadata and quality report: {json.dumps(llm_context, default=str)}"
        )
        quality_plan = self._request_required_llm_json(
            prompt,
            "You are an autonomous data-quality and cleaning planner. Use only the supplied "
            "schema and aggregate statistics. Do not invent row values or synonym mappings. "
            "Return only the requested concise JSON object.",
            max_output_tokens=QUALITY_PLAN_MAX_OUTPUT_TOKENS,
        )
        quality_findings = quality_plan.get("quality_findings")
        if not isinstance(quality_findings, list) or not all(
            isinstance(item, str) for item in quality_findings
        ):
            raise ValueError("The LLM returned invalid quality findings.")
        strategy = quality_plan.get("cleaning_strategy")
        required_strategy_fields = {
            "numeric_waterfall_columns",
            "imputation_plan",
            "synonym_mappings",
            "outlier_columns",
            "date_columns",
            "boolean_columns",
            "remove_duplicates",
        }
        if isinstance(strategy, dict):
            missing_strategy_fields = required_strategy_fields - set(strategy)
            if missing_strategy_fields:
                repair_prompt = (
                    "Complete the cleaning strategy. Return only a JSON object containing "
                    "exactly these missing fields, with the required types: "
                    "numeric_waterfall_columns (array of source column names), "
                    "imputation_plan (object), synonym_mappings (object), "
                    "outlier_columns (array of source column names), "
                    "date_columns (array of source column names), "
                    "boolean_columns (array of source column names), and "
                    "remove_duplicates (boolean). Choose empty arrays/objects where no "
                    "operation is recommended. Decide remove_duplicates from the supplied "
                    "quality report. Do not repeat other strategy fields or add explanation.\n"
                    f"Missing fields: {json.dumps(sorted(missing_strategy_fields))}\n"
                    f"Dataset metadata and quality report: {json.dumps(llm_context, default=str)}"
                )
                repaired_strategy = self.llm_client.generate_json(
                    repair_prompt,
                    (
                        "You complete missing fields in a data cleaning plan using only "
                        "the provided dataset quality report. Return valid concise JSON."
                    ),
                    max_output_tokens=QUALITY_STRATEGY_REPAIR_MAX_OUTPUT_TOKENS,
                )
                if isinstance(repaired_strategy, dict):
                    strategy.update({
                        field: repaired_strategy[field]
                        for field in missing_strategy_fields
                        if field in repaired_strategy
                    })
        self._validate_llm_cleaning_strategy(strategy, profile["column_names"])
        analysis.update(quality_plan)
        result = self.execute_cleaning(
            file_path,
            strategy=strategy,
            preview_mode=False,
            destination_format=destination_format,
            llm_controlled=True,
        )
        result.update({
            "workflow": workflow,
            "profile": profile,
            "llm_analysis": analysis,
        })
        return result

    def _run_deterministic_workflow(
        self,
        file_path: str,
        workflow: str,
        destination_format: str,
    ) -> Dict[str, Any]:
        if workflow not in {"profiling", "profiling_quality_cleaning"}:
            raise ValueError(f"Unsupported workflow: {workflow}")

        dataframe = load_dataset(file_path)
        profile = profile_dataset(file_path)
        health = calculate_health_scores(dataframe)
        analysis = {
            "profile_summary": (
                f"Python profile of {profile['rows']} rows and "
                f"{profile['columns']} columns; LLM quota unavailable."
            ),
            "columns": [
                {
                    "name": column,
                    "type": profile["column_types"][column],
                    "role": profile["column_roles"][column],
                    "insight": (
                        f"{profile['unique_values'][column]} distinct values; "
                        f"{profile['missing_values'][column]} missing."
                    ),
                }
                for column in profile["column_names"]
            ],
        }
        if workflow == "profiling":
            return {
                "status": "success",
                "workflow": workflow,
                "profile": profile,
                "llm_analysis": analysis,
                "fallback_used": True,
                "fallback_reason": "LLM rate limit reached; Python profiling was used.",
            }

        dirty_numeric_columns = [
            column for column, issue in health["type_issues"].items()
            if issue["issue"].startswith("Dirty numeric strings")
        ]
        date_columns = [
            column for column, issue in health["type_issues"].items()
            if issue["issue"].startswith("Date/time values stored as plain text")
        ]
        boolean_columns = [
            column for column, issue in health["type_issues"].items()
            if issue["issue"].startswith("Boolean flag stored as text")
        ]
        missing_tokens = {"", "n/a", "null", "none", "?", "missing"}
        imputation_plan = {}
        for column in dataframe.columns:
            has_missing = bool(dataframe[column].isna().any())
            if pd.api.types.is_string_dtype(dataframe[column]) or dataframe[column].dtype == "object":
                has_missing = has_missing or dataframe[column].astype("string").str.strip().str.lower().isin(
                    missing_tokens
                ).any()
            if column in dirty_numeric_columns or column in date_columns or column in boolean_columns:
                has_missing = True
            if has_missing:
                if (
                    column in dirty_numeric_columns
                    or pd.api.types.is_numeric_dtype(dataframe[column])
                    and not pd.api.types.is_bool_dtype(dataframe[column])
                ):
                    strategy = "median"
                else:
                    strategy = "mode"
                imputation_plan[column] = {"strategy": strategy}

        strategy = {
            "numeric_waterfall_columns": dirty_numeric_columns,
            "imputation_plan": imputation_plan,
            "synonym_mappings": {},
            "outlier_columns": list(health.get("outlier_info", {})),
            "date_columns": date_columns,
            "boolean_columns": boolean_columns,
            "remove_duplicates": True,
        }
        result = self.execute_cleaning(
            file_path,
            strategy=strategy,
            preview_mode=False,
            destination_format=destination_format,
            llm_controlled=True,
        )
        result.update({
            "workflow": workflow,
            "profile": profile,
            "llm_analysis": {
                **analysis,
                "quality_findings": [
                    f"{health['missing_info']['total_missing_cells']} missing values detected.",
                    f"{health['duplicate_info']['count']} duplicate rows detected.",
                ],
                "cleaning_strategy": strategy,
            },
            "fallback_used": True,
            "fallback_reason": "LLM rate limit reached; deterministic Python cleaning was used.",
        })
        return result

    def _request_required_llm_json(
        self,
        prompt: str,
        system_prompt: str,
        max_output_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        response = self.llm_client.generate_json(
            prompt,
            system_prompt,
            max_output_tokens=max_output_tokens,
        )
        if not isinstance(response, dict) or not response:
            raise RuntimeError(
                "The configured LLM did not return a valid response. "
                "The workflow was stopped; no Python fallback was used."
            )
        return response

    def _request_llm_profile_in_chunks(
        self,
        system_prompt: str,
        llm_context: Dict[str, Any],
        column_names: list,
    ) -> Dict[str, Any]:
        columns_by_name = {}
        profile_summary = None
        for start in range(0, len(column_names), PROFILE_COLUMNS_PER_REQUEST):
            column_batch = column_names[start:start + PROFILE_COLUMNS_PER_REQUEST]
            include_summary = start == 0
            response = self._request_profile_chunk(
                self._build_profile_chunk_prompt(
                    llm_context,
                    column_batch,
                    include_summary,
                ),
                system_prompt,
                column_batch,
                include_summary,
            )
            if include_summary:
                profile_summary = response["profile_summary"]
            for column in response["columns"]:
                columns_by_name[column["name"]] = column

        missing_columns = [
            name for name in column_names
            if name not in columns_by_name
        ]
        for column_name in missing_columns:
            columns_by_name[column_name] = self._request_single_column_profile(
                system_prompt,
                llm_context,
                column_name,
            )

        analysis = {
            "profile_summary": profile_summary,
            "columns": [
                columns_by_name[name]
                for name in column_names
            ],
        }
        self._validate_profile_analysis(analysis, column_names)
        return analysis

    @staticmethod
    def _build_profile_chunk_prompt(
        llm_context: Dict[str, Any],
        column_batch: list,
        include_summary: bool,
    ) -> str:
        batch_context = {
            "dataset": {
                "file_name": llm_context["file_name"],
                "rows": llm_context["rows"],
                "columns": llm_context["columns"],
                "duplicate_rows": llm_context["duplicate_rows"],
            },
            "column_metadata": {
                key: {
                    name: values.get(name)
                    for name in column_batch
                }
                for key, values in (
                    ("types", llm_context["column_types"]),
                    ("roles", llm_context["column_roles"]),
                    ("unique_values", llm_context["unique_values_per_column"]),
                    ("missing_values", llm_context["missing_values_per_column"]),
                    ("numerical_statistics", llm_context["numerical_statistics"]),
                )
            },
            "columns_to_profile": column_batch,
        }
        required_keys = "profile_summary and columns" if include_summary else "columns"
        prompt = (
            "Profile only the listed columns using the supplied schema and aggregate "
            "statistics. Do not assume access to row values. Return one JSON object with "
            f"{required_keys}. Each columns item must contain name, type, role, and insight "
            "as non-empty strings. Include each listed column exactly once and no other "
            "columns. Keep each insight to at most 5 words. "
        )
        if include_summary:
            prompt += "Keep profile_summary to at most 20 words. "
        return (
            prompt
            + "Use compact type and role labels; do not add extra fields.\n"
            + f"Dataset metadata: {json.dumps(batch_context, default=str)}"
        )

    def _request_profile_chunk(
        self,
        prompt: str,
        system_prompt: str,
        column_batch: list,
        include_summary: bool,
    ) -> Dict[str, Any]:
        response = self._request_required_llm_json(
            prompt,
            system_prompt,
            max_output_tokens=PROFILE_MAX_OUTPUT_TOKENS,
        )
        summary = response.get("profile_summary")
        if include_summary and (
            not isinstance(summary, str) or not summary.strip()
        ):
            correction_prompt = (
                f"{prompt}\n\n"
                "Your JSON response omitted the required profile_summary. Add a concise, "
                "non-empty profile_summary and return all requested columns exactly once.\n"
                f"Previous JSON response: {json.dumps(response, ensure_ascii=False, default=str)}"
            )
            corrected_response = self._request_required_llm_json(
                correction_prompt,
                system_prompt,
                max_output_tokens=PROFILE_MAX_OUTPUT_TOKENS,
            )
            summary = corrected_response.get("profile_summary")
            if not isinstance(summary, str) or not summary.strip():
                raise ValueError("The LLM response is missing a profile summary.")
            response = corrected_response

        if include_summary:
            response["profile_summary"] = summary
        response["columns"] = self._valid_profile_columns(
            response.get("columns"),
            column_batch,
        )
        return response

    def _request_single_column_profile(
        self,
        system_prompt: str,
        llm_context: Dict[str, Any],
        column_name: str,
    ) -> Dict[str, Any]:
        prompt = self._build_profile_chunk_prompt(
            llm_context,
            [column_name],
            include_summary=False,
        )
        prompt += (
            "\nThis is a completion request for one missing column. Return exactly one "
            "columns item, and set its name to the exact source column name."
        )

        for attempt in range(2):
            response = self._request_required_llm_json(
                prompt,
                system_prompt,
                max_output_tokens=SINGLE_COLUMN_PROFILE_MAX_OUTPUT_TOKENS,
            )
            columns = self._valid_profile_columns(
                response.get("columns"),
                [column_name],
                allow_missing_single_name=True,
            )
            if len(columns) == 1:
                return columns[0]

            prompt += (
                "\nThe previous response did not provide a valid profile for the requested "
                f"column {column_name!r}. Return one item with non-empty name, type, role, "
                "and insight fields. Keep insight under 5 words. Previous response: "
                f"{json.dumps(response, ensure_ascii=False, default=str)}"
            )

        raise ValueError(
            f"The LLM did not provide a valid profile for source column {column_name!r} "
            "after a correction request."
        )

    @staticmethod
    def _validate_profile_analysis(
        analysis: Dict[str, Any],
        column_names: list,
    ) -> None:
        if not isinstance(analysis.get("profile_summary"), str) or not analysis["profile_summary"].strip():
            raise ValueError("The LLM response is missing a profile summary.")
        DataEngineeringAgent._validate_profile_columns(
            analysis.get("columns"),
            column_names,
        )

    @staticmethod
    def _validate_profile_columns(
        columns: Any,
        column_names: list,
    ) -> None:
        if not isinstance(columns, list):
            raise ValueError("The LLM response is missing its per-column profile.")
        valid_columns = DataEngineeringAgent._valid_profile_columns(
            columns,
            column_names,
        )
        returned_names = [item["name"] for item in valid_columns]
        if len(returned_names) != len(column_names) or set(returned_names) != set(column_names):
            raise ValueError("The LLM profile must describe every source column exactly once.")
        if len(set(returned_names)) != len(returned_names):
            raise ValueError("The LLM profile contains duplicate columns.")

    @staticmethod
    def _valid_profile_columns(
        columns: Any,
        requested_names: list,
        allow_missing_single_name: bool = False,
    ) -> list:
        if not isinstance(columns, list):
            return []
        requested = set(requested_names)
        valid_columns = []
        for item in columns:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if (
                not name
                and allow_missing_single_name
                and len(requested_names) == 1
            ):
                item = {**item, "name": requested_names[0]}
                name = requested_names[0]
            if not isinstance(name, str) or name not in requested or not all(
                isinstance(item.get(key), str) and item[key].strip()
                for key in ("type", "role", "insight")
            ):
                continue
            valid_columns.append(item)
        return valid_columns

    @staticmethod
    def _validate_llm_cleaning_strategy(
        strategy: Any,
        column_names: list,
    ) -> None:
        if not isinstance(strategy, dict):
            raise ValueError("The LLM response is missing a cleaning strategy.")

        required_fields = {
            "numeric_waterfall_columns",
            "imputation_plan",
            "synonym_mappings",
            "outlier_columns",
            "date_columns",
            "boolean_columns",
            "remove_duplicates",
        }
        if not required_fields.issubset(strategy):
            missing = sorted(required_fields - set(strategy))
            raise ValueError(f"The LLM cleaning strategy is missing: {', '.join(missing)}.")
        unexpected_fields = set(strategy) - required_fields
        if unexpected_fields:
            raise ValueError(
                f"The LLM returned unsupported cleaning fields: "
                f"{', '.join(sorted(unexpected_fields))}."
            )

        for field in (
            "numeric_waterfall_columns",
            "outlier_columns",
            "date_columns",
            "boolean_columns",
        ):
            columns = strategy[field]
            if not isinstance(columns, list) or not all(
                isinstance(column, str) and column in column_names for column in columns
            ):
                raise ValueError(f"The LLM returned invalid columns for {field}.")
            if len(set(columns)) != len(columns):
                raise ValueError(f"The LLM returned duplicate columns for {field}.")

        imputation_plan = strategy["imputation_plan"]
        if not isinstance(imputation_plan, dict):
            raise ValueError("The LLM returned an invalid imputation plan.")
        for column, plan in imputation_plan.items():
            if column not in column_names or not isinstance(plan, dict):
                raise ValueError(f"The LLM returned an invalid imputation plan for {column}.")
            if plan.get("strategy") not in {"median", "mean", "mode", "constant"}:
                raise ValueError(f"The LLM returned an unsupported imputation for {column}.")
            if plan["strategy"] == "constant" and "value" not in plan:
                raise ValueError(f"The constant imputation for {column} needs a value.")

        synonym_mappings = strategy["synonym_mappings"]
        if not isinstance(synonym_mappings, dict) or any(
            column not in column_names or not isinstance(mapping, dict)
            for column, mapping in synonym_mappings.items()
        ):
            raise ValueError("The LLM returned invalid categorical synonym mappings.")
        if not isinstance(strategy["remove_duplicates"], bool):
            raise ValueError("The LLM must explicitly decide whether to remove duplicates.")

    @staticmethod
    def _validate_llm_imputation_plan(
        imputation_plan: Any,
        required_columns: list,
    ) -> None:
        if not isinstance(imputation_plan, dict):
            raise ValueError("The LLM returned an invalid imputation plan.")
        if set(imputation_plan) != set(required_columns):
            raise ValueError(
                "The LLM imputation plan must cover every requested missing-value column "
                "exactly once."
            )
        for column, plan in imputation_plan.items():
            if not isinstance(plan, dict) or plan.get("strategy") not in {
                "median", "mean", "mode", "constant"
            }:
                raise ValueError(f"The LLM returned an invalid imputation plan for {column}.")
            if plan["strategy"] == "constant" and "value" not in plan:
                raise ValueError(f"The constant imputation for {column} needs a value.")

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

        # Keep the synonym-detection context bounded for API and output limits.
        cat_unique_values = {}
        for c in profile.get("categorical_columns", [])[:8]:
            if c in df.columns:
                uniques = df[c].dropna().astype(str).unique().tolist()
                cat_unique_values[c] = uniques[:10]

        user_prompt = (
            "Analyze the supplied aggregate quality report. Return one compact JSON object "
            "only, with these keys: recommendation_summary (one sentence), "
            "numeric_waterfall_columns (array), imputation_plan (object mapping each missing "
            "column to {strategy: median|mean|mode|constant, value: optional}), "
            "synonym_mappings (object; only clear synonym pairs, otherwise {}), "
            "outlier_columns (array). Use exact source column names. For dirty numeric type "
            "issues, include the column in numeric_waterfall_columns. For missing numeric "
            "columns choose median; for categorical choose mode. Keep all text concise. "
            "Do not include markdown or extra keys.\n"
            f"Dataset: {os.path.basename(file_path)}, {profile['rows']} rows, "
            f"{profile['columns']} columns, health {health['overall_health_score']}%.\n"
            f"Column roles: {profile['column_roles']}\n"
            f"Missing columns: {health['missing_info']['columns']}\n"
            f"Type issues: {health['type_issues']}\n"
            f"Outliers: {outlier_cols_info}\n"
            f"Categorical samples for synonym detection: {cat_unique_values}\n"
        )

        llm_strategy = self.llm_client.generate_json(
            user_prompt,
            system_prompt,
            max_output_tokens=400,
        )

        # Fallback if LLM JSON is empty
        if not llm_strategy or "recommendation_summary" not in llm_strategy:
            recommendation = (
                f"BIFlow recommends safe cleaning for {len(health['type_issues'])} type mismatches "
                f"and {health['missing_info']['total_missing_cells']} missing values."
            )
            numeric_issue_columns = [
                col for col, issue in health["type_issues"].items()
                if issue["issue"].startswith("Dirty numeric strings")
            ]
            llm_strategy = {
                "recommendation_summary": recommendation,
                "numeric_waterfall_columns": numeric_issue_columns,
                "imputation_plan": {
                    col: {
                        "strategy": "median"
                        if pd.api.types.is_numeric_dtype(df[col]) or col in numeric_issue_columns
                        else "mode"
                    }
                    for col in health["missing_info"]["columns"]
                },
                "synonym_mappings": {},
                "outlier_columns": list(health.get("outlier_info", {}).keys())
            }

        return {
            "profile": profile,
            "health": health,
            "cleaning_strategy": llm_strategy
        }

    def execute_cleaning(
        self,
        file_path: str,
        strategy: Optional[Dict[str, Any]] = None,
        preview_mode: bool = False,
        destination_format: str = "both",
        llm_controlled: bool = False,
    ) -> Dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        run_id = started_at.strftime("%Y%m%dT%H%M%S%fZ")
        try:
            return self._execute_cleaning(
                file_path,
                strategy,
                preview_mode,
                destination_format,
                run_id,
                started_at.isoformat(),
                llm_controlled,
            )
        except Exception as error:
            logger.exception("ETL run %s failed for %s", run_id, file_path)
            if not preview_mode:
                self._write_etl_log(
                    file_path,
                    run_id,
                    {
                        "run_id": run_id,
                        "status": "failed",
                        "source_file": file_path,
                        "started_at": started_at.isoformat(),
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "error_type": type(error).__name__,
                        "error": str(error),
                    },
                )
            raise

    def _execute_cleaning(
        self,
        file_path: str,
        strategy: Optional[Dict[str, Any]],
        preview_mode: bool,
        destination_format: str,
        run_id: str,
        started_at: str,
        llm_controlled: bool,
    ) -> Dict[str, Any]:
        """
        Runs the file-based ETL pipeline: extract, transform, validate, and load.
        """
        if destination_format not in {"csv", "parquet", "both"}:
            raise ValueError("destination_format must be 'csv', 'parquet', or 'both'.")

        # Extract
        df_raw = load_dataset(file_path)
        df_clean = df_raw.copy()

        if strategy is None:
            audit_res = self.run_audit(file_path)
            strategy = audit_res["cleaning_strategy"]

        health_before = calculate_health_scores(df_raw)
        transformations_log = []

        missing_tokens = ["", "n/a", "null", "none", "?", "missing"]
        for col in df_clean.columns:
            if pd.api.types.is_string_dtype(df_clean[col]) or df_clean[col].dtype == "object":
                missing_mask = df_clean[col].astype("string").str.strip().str.lower().isin(
                    missing_tokens
                )
                df_clean.loc[missing_mask, col] = pd.NA

        # 1. Remove exact duplicate rows and record the change.
        duplicate_count = int(df_clean.duplicated().sum())
        remove_duplicates = strategy.get("remove_duplicates", True)
        if duplicate_count and remove_duplicates:
            df_clean = df_clean.drop_duplicates().reset_index(drop=True)
            transformations_log.append({
                "action": "remove_duplicate_rows",
                "removed_rows": duplicate_count
            })

        # 2. Convert columns with detected numeric strings, even if the LLM
        #    strategy omitted them.
        detected_numeric_cols = [
            col for col, issue in health_before["type_issues"].items()
            if issue["issue"].startswith("Dirty numeric strings")
        ]
        waterfall_cols = set(strategy.get("numeric_waterfall_columns", []))
        if not llm_controlled:
            waterfall_cols.update(detected_numeric_cols)
        for col in waterfall_cols:
            if col in df_clean.columns:
                before_nulls = int(df_clean[col].isna().sum())
                numeric_llm = None if llm_controlled else self.llm_client
                df_clean[col] = clean_dirty_numeric_series(
                    df_clean[col],
                    numeric_llm,
                )
                after_nulls = int(df_clean[col].isna().sum())
                transformations_log.append({
                    "column": col, "action": "numeric_waterfall_cleaning",
                    "nulls_before": before_nulls, "nulls_after": after_nulls
                })

        # 3. Parse detected dates and normalize detected text booleans.
        if llm_controlled:
            date_cols = strategy.get("date_columns", [])
            boolean_cols = strategy.get("boolean_columns", [])
        else:
            date_cols = [
                col for col, issue in health_before["type_issues"].items()
                if issue["issue"].startswith("Date/time values stored as plain text")
            ]
            boolean_cols = [
                col for col, issue in health_before["type_issues"].items()
                if issue["issue"].startswith("Boolean flag stored as text")
            ]

        for col in date_cols:
            if col in df_clean.columns:
                df_clean[col] = pd.to_datetime(
                    df_clean[col], errors="coerce", format="mixed"
                )
                transformations_log.append({
                    "column": col, "action": "parse_datetime"
                })

        for col in boolean_cols:
            if col in df_clean.columns:
                boolean_values = {
                    "yes": True, "y": True, "true": True, "1": True, "oui": True,
                    "no": False, "n": False, "false": False, "0": False, "non": False,
                }
                df_clean[col] = (
                    df_clean[col].astype("string").str.strip().str.lower()
                    .map(boolean_values).astype("boolean")
                )
                transformations_log.append({
                    "column": col, "action": "normalize_boolean"
                })

        # 4. Impute detected and newly-created missing values.
        impute_plan = dict(strategy.get("imputation_plan", {}))
        if not llm_controlled:
            for col in df_clean.columns:
                has_missing = bool(df_clean[col].isna().any())
                if has_missing and col not in impute_plan:
                    impute_plan[col] = {
                        "strategy": "median"
                        if pd.api.types.is_numeric_dtype(df_clean[col])
                        else "mode"
                    }
        else:
            missing_columns = [
                col for col in df_clean.columns
                if df_clean[col].isna().any() and col not in impute_plan
            ]
            if missing_columns:
                missing_summary = {
                    col: {
                        "missing_cells": int(df_clean[col].isna().sum()),
                        "dtype": str(df_clean[col].dtype),
                    }
                    for col in missing_columns
                }
                imputation_response = self.llm_client.generate_json(
                    (
                        "Choose a safe imputation strategy for every listed column with "
                        "missing values. Return only JSON with one key, imputation_plan, "
                        "mapping every listed column exactly once to {strategy: median|mean|"
                        "mode|constant, value: required only for constant}. Prefer median "
                        "for numeric columns, mode for categorical, boolean, and datetime "
                        "columns. Use a constant only when its value is justified by the "
                        "provided quality context. Include no unlisted columns.\n"
                        f"Missing-value columns: {json.dumps(missing_summary)}\n"
                        "Use the dataset quality report and selected strategy already "
                        "provided earlier in this workflow."
                    ),
                    (
                        "You are a data-quality planner. Select an imputation plan for every "
                        "requested column using its type and missing count. Return valid JSON."
                    ),
                    max_output_tokens=QUALITY_IMPUTATION_PLAN_MAX_OUTPUT_TOKENS,
                )
                proposed_plan = (
                    imputation_response.get("imputation_plan")
                    if isinstance(imputation_response, dict)
                    else None
                )
                self._validate_llm_imputation_plan(proposed_plan, missing_columns)
                impute_plan.update(proposed_plan)
        for col, plan in impute_plan.items():
            if col in df_clean.columns:
                before_nulls = int(df_clean[col].isna().sum())
                transformations_log.append({
                    "column": col, "action": f"imputation_{plan.get('strategy','median')}",
                    "imputed_rows": before_nulls
                })
        df_clean = impute_missing_values(df_clean, impute_plan)

        # 5. Categorical synonym normalization
        synonym_maps = strategy.get("synonym_mappings", {})
        for col, mapping in synonym_maps.items():
            if col in df_clean.columns and mapping:
                transformations_log.append({
                    "column": col, "action": "synonym_normalization",
                    "replacements": len(mapping), "mapping": mapping
                })
        df_clean = standardize_categorical_synonyms(df_clean, synonym_maps)

        # 6. Winsorize detected outliers, including columns made numeric above.
        outlier_cols = set(strategy.get("outlier_columns", []))
        if not llm_controlled:
            detected_outlier_cols = calculate_health_scores(df_clean)["outlier_info"].keys()
            outlier_cols.update(health_before["outlier_info"].keys())
            outlier_cols.update(detected_outlier_cols)
        if outlier_cols:
            for col in outlier_cols:
                if col in df_clean.columns and pd.api.types.is_numeric_dtype(df_clean[col]):
                    q_low  = float(df_clean[col].quantile(0.01))
                    q_high = float(df_clean[col].quantile(0.99))
                    transformations_log.append({
                        "column": col, "action": "outlier_winsorizing",
                        "capped_at": {"low": q_low, "high": q_high}
                    })
            df_clean = treat_outliers(df_clean, outlier_cols, method="cap")

        # Imputation and normalization can make formerly different rows identical.
        if remove_duplicates:
            newly_duplicate_count = int(df_clean.duplicated().sum())
            if newly_duplicate_count:
                df_clean = df_clean.drop_duplicates().reset_index(drop=True)
                transformations_log.append({
                    "action": "remove_duplicate_rows_after_transformations",
                    "removed_rows": newly_duplicate_count,
                })

        health_after = calculate_health_scores(df_clean)

        validation = validate_transformed_dataset(df_raw, df_clean)

        # Preview includes validation results but never loads files.
        if preview_mode:
            return {
                "status": "preview",
                "rows_processed": len(df_clean),
                "columns_processed": len(df_clean.columns),
                "health_before": health_before,
                "health_after": health_after,
                "validation": validation,
                "applied_transformations": transformations_log,
            }

        if not validation["valid"]:
            raise ValueError(
                "ETL validation failed: " + " ".join(validation["errors"])
            )

        # Load only validated data. Stage output files before making them visible.
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        output_files = {}
        if destination_format in {"csv", "both"}:
            output_files["csv"] = os.path.join("data", "cleaned", f"{base_name}_cleaned.csv")
        if destination_format in {"parquet", "both"}:
            output_files["parquet"] = os.path.join(
                "data", "processed", f"{base_name}_processed.parquet"
            )

        staged_files = []
        try:
            for file_format, output_path in output_files.items():
                output_dir = os.path.dirname(output_path)
                os.makedirs(output_dir, exist_ok=True)
                staged_path = os.path.join(
                    output_dir,
                    f".{os.path.basename(output_path)}.{run_id}.tmp",
                )
                staged_files.append((staged_path, output_path))
                if file_format == "csv":
                    df_clean.to_csv(staged_path, index=False)
                else:
                    df_clean.to_parquet(staged_path, index=False)

            for staged_path, output_path in staged_files:
                os.replace(staged_path, output_path)
        finally:
            for staged_path, _ in staged_files:
                if os.path.exists(staged_path):
                    os.remove(staged_path)

        cleaned_path = output_files.get("csv") or output_files["parquet"]
        log_path = self._etl_log_path(file_path, run_id)
        audit_log = {
            "run_id": run_id,
            "status": "success",
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "source_file": file_path,
            "destination_format": destination_format,
            "output_files": output_files,
            "rows_extracted": len(df_raw),
            "rows_loaded": len(df_clean),
            "columns_extracted": len(df_raw.columns),
            "columns_loaded": len(df_clean.columns),
            "quality_score_before": health_before["overall_health_score"],
            "quality_score_after": health_after["overall_health_score"],
            "validation": validation,
            "applied_transformations": transformations_log,
        }
        self._write_etl_log(file_path, run_id, audit_log)

        return {
            "status": "success",
            "cleaned_file_path": cleaned_path,
            "output_files": output_files,
            "audit_log_path": log_path,
            "health_after": health_after,
            "validation": validation,
            "rows_extracted": len(df_raw),
            "rows_loaded": len(df_clean),
            "applied_transformations": transformations_log,
        }

    @staticmethod
    def _etl_log_path(file_path: str, run_id: str) -> str:
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        return os.path.join("data", "logs", "etl_runs", f"{base_name}_{run_id}.json")

    def _write_etl_log(self, file_path: str, run_id: str, log_data: Dict[str, Any]) -> None:
        log_path = self._etl_log_path(file_path, run_id)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        temporary_path = f"{log_path}.tmp"
        with open(temporary_path, "w", encoding="utf-8") as log_file:
            json.dump(log_data, log_file, indent=2, ensure_ascii=False, default=str)
        os.replace(temporary_path, log_path)
