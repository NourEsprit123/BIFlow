import json
import os
from typing import Any, Dict, Optional

import pandas as pd

from analytics.kpi import calculate_kpis
from analytics.profiler import load_dataset
from agents.data_engineering_agent import DataEngineeringAgent
from agents.llm_client import LLMClient, LLMRateLimitError

INSIGHT_MAX_OUTPUT_TOKENS = 700
INSIGHTS_PER_DATASET = 3


class BIAnalystAgent:
    """Calculates dataset KPIs and asks the configured LLM for evidence-based insights."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()

    def run_pipeline(self, raw_file_path: str) -> Dict[str, Any]:
        """Profile and clean the raw dataset, then analyze only the validated output."""
        data_engineering_agent = DataEngineeringAgent(llm_client=self.llm_client)
        pipeline_result = data_engineering_agent.run_workflow(
            raw_file_path,
            "profiling_quality_cleaning",
            destination_format="csv",
        )
        cleaned_file_path = pipeline_result["output_files"].get("csv")
        if not cleaned_file_path or not os.path.isfile(cleaned_file_path):
            raise RuntimeError("The validated cleaning pipeline did not produce a CSV dataset.")

        analysis = self.analyze(cleaned_file_path)
        insights_fallback_used = analysis.get("fallback_used", False)
        cleaning_fallback_used = pipeline_result.get("fallback_used", False)
        fallback_used = cleaning_fallback_used or insights_fallback_used
        analysis["cleaning_fallback_used"] = cleaning_fallback_used
        analysis["insights_fallback_used"] = insights_fallback_used
        analysis["fallback_used"] = fallback_used
        fallback_reasons = list(dict.fromkeys(
            reason for reason in (
                pipeline_result.get("fallback_reason"),
                analysis.get("fallback_reason"),
            )
            if reason
        ))
        analysis["fallback_reason"] = " ".join(fallback_reasons) or None
        return {
            "status": "success",
            "source_dataset": os.path.basename(raw_file_path),
            "cleaned_dataset_path": cleaned_file_path,
            "profile": pipeline_result["profile"],
            "cleaning": {
                "validation": pipeline_result["validation"],
                "health_after": pipeline_result["health_after"],
                "rows_loaded": pipeline_result["rows_loaded"],
                "output_files": pipeline_result["output_files"],
                "fallback_used": cleaning_fallback_used,
            },
            "fallback_used": fallback_used,
            "fallback_reason": analysis["fallback_reason"],
            "analysis": analysis,
        }

    def analyze(self, file_path: str) -> Dict[str, Any]:
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Dataset not found: {file_path}")

        dataframe = load_dataset(file_path)
        if dataframe.empty or len(dataframe.columns) == 0:
            raise ValueError("Cannot analyze an empty dataset.")

        kpis = calculate_kpis(dataframe)
        llm_input = {
            "dataset_name": os.path.basename(file_path),
            "dataset_kpis": kpis,
        }
        system_prompt = (
            "You are a careful business intelligence analyst. You receive aggregate "
            "statistics only, never individual records. Ground every insight in the "
            "provided numbers and return only valid JSON."
        )
        prompt = (
                "Analyze this dataset using only the supplied aggregate statistics. "
                f"Return exactly {INSIGHTS_PER_DATASET} very concise insights as JSON with "
                "an 'insights' array. Each item must contain: title, finding, evidence, "
                "recommendation, confidence (integer 0-100), and source_columns "
                "(array of supplied column names). State associations, not causation. "
                "Use one short sentence for finding, evidence, and recommendation. "
                "Do not invent statistics or imply predictions. Include exactly three "
                "items, even when evidence is limited; state the limitation rather than "
                "omitting an item. Use [] when no column can be attributed. "
                'JSON shape: {"insights":[{"title":"...","finding":"...","evidence":"...",'
                '"recommendation":"...","confidence":50,"source_columns":[]}]}.\n'
                f"Aggregated dataset data: {json.dumps(llm_input, ensure_ascii=False, allow_nan=False)}"
        )
        try:
            response = self.llm_client.generate_json(
                prompt=prompt,
                system_prompt=system_prompt,
                max_output_tokens=INSIGHT_MAX_OUTPUT_TOKENS,
            )
        except LLMRateLimitError as error:
            return self._build_deterministic_analysis(
                file_path,
                dataframe,
                kpis,
                str(error),
            )
        insights = response.get("insights") if isinstance(response, dict) else None
        if not isinstance(insights, list) or len(insights) != INSIGHTS_PER_DATASET:
            retry_prompt = (
                f"Your previous answer returned "
                f"{len(insights) if isinstance(insights, list) else 'no valid'} insights. "
                f"Regenerate the answer as exactly {INSIGHTS_PER_DATASET} concise insights "
                "in the required JSON structure. Do not omit items; when evidence is "
                "limited, state that limitation. Use only these dataset aggregates:\n"
                f"{json.dumps(llm_input, ensure_ascii=False, allow_nan=False)}"
            )
            try:
                response = self.llm_client.generate_json(
                    prompt=retry_prompt,
                    system_prompt=system_prompt,
                    max_output_tokens=INSIGHT_MAX_OUTPUT_TOKENS,
                )
            except LLMRateLimitError as error:
                return self._build_deterministic_analysis(
                    file_path,
                    dataframe,
                    kpis,
                    str(error),
                )
            insights = response.get("insights") if isinstance(response, dict) else None
            if not isinstance(insights, list) or len(insights) != INSIGHTS_PER_DATASET:
                returned_count = len(insights) if isinstance(insights, list) else 0
                raise ValueError(
                    f"The LLM returned {returned_count} BI insights after one retry; "
                    f"exactly {INSIGHTS_PER_DATASET} are required."
                )

        available_columns = set(dataframe.columns.astype(str))
        validated_insights = []
        required_text = ("title", "finding", "evidence", "recommendation")
        for insight in insights:
            if not isinstance(insight, dict) or any(
                not isinstance(insight.get(field), str) or not insight[field].strip()
                for field in required_text
            ):
                raise ValueError("The LLM returned an incomplete BI insight.")
            confidence = insight.get("confidence")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                raise ValueError("The LLM returned an invalid insight confidence.")
            if not 0 <= confidence <= 100:
                raise ValueError("Insight confidence must be between 0 and 100.")
            source_columns = insight.get("source_columns")
            if (
                not isinstance(source_columns, list)
                or not all(isinstance(column, str) for column in source_columns)
                or not set(source_columns).issubset(available_columns)
            ):
                raise ValueError("The LLM returned invalid BI insight source columns.")
            validated_insights.append({
                **insight,
                "confidence": int(confidence),
                "source_columns": source_columns,
            })

        return {
            "status": "success",
            "dataset": os.path.basename(file_path),
            "kpis": kpis,
            "insights": validated_insights,
            "fallback_used": False,
        }

    @staticmethod
    def _build_deterministic_analysis(
        file_path: str,
        dataframe: pd.DataFrame,
        kpis: Dict[str, Any],
        reason: str,
    ) -> Dict[str, Any]:
        insights = [{
            "title": "Dataset overview",
            "finding": f"The cleaned dataset contains {kpis['record_count']:,} records across {kpis['field_count']} fields.",
            "evidence": (
                f"Quality aggregates report {kpis['missing_cells']:,} missing cells "
                f"and {kpis['duplicate_rows']:,} exact duplicate rows."
            ),
            "recommendation": "Use the interactive charts to explore distributions and relationships.",
            "confidence": 100,
            "source_columns": [],
        }]

        numeric_metrics = kpis["numeric_metrics"]
        if numeric_metrics:
            name, metrics = next(iter(numeric_metrics.items()))
            insights.append({
                "title": f"{name} summary",
                "finding": f"The average {name} is {metrics['mean']:,.2f}.",
                "evidence": (
                    f"Across {metrics['count']:,} valid values, the median is "
                    f"{metrics['median']:,.2f} and the range is "
                    f"{metrics['min']:,.2f}–{metrics['max']:,.2f}."
                ),
                "recommendation": f"Compare {name} across categories using the dashboard charts.",
                "confidence": 100,
                "source_columns": [name],
            })
        else:
            insights.append({
                "title": "Numeric analysis",
                "finding": "No continuous numeric fields were available for numeric KPI analysis.",
                "evidence": "The cleaned dataset profile did not identify any eligible numeric metrics.",
                "recommendation": "Review field types if numeric measures are expected.",
                "confidence": 100,
                "source_columns": [],
            })

        categorical = kpis["categorical_distributions"]
        if categorical:
            name, groups = next(iter(categorical.items()))
            top = groups[0]
            insights.append({
                "title": f"{name} distribution",
                "finding": f"{top['category']} is the largest represented {name} group.",
                "evidence": (
                    f"It accounts for {top['count']:,} records "
                    f"({top['percentage']:.2f}% of the dataset)."
                ),
                "recommendation": f"Inspect the interactive {name} chart for the remaining groups.",
                "confidence": 100,
                "source_columns": [name],
            })
        else:
            insights.append({
                "title": "Category analysis",
                "finding": "No categorical field with a useful number of groups was identified.",
                "evidence": "The cleaned dataset profile contains no eligible categorical distributions.",
                "recommendation": "Review available fields and use numeric charts to explore the data.",
                "confidence": 100,
                "source_columns": [],
            })

        return {
            "status": "success",
            "dataset": os.path.basename(file_path),
            "kpis": kpis,
            "insights": insights,
            "fallback_used": True,
            "fallback_reason": f"Groq rate limit reached; deterministic insights were used. {reason}",
        }
