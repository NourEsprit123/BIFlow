"""
BI Analyst Agent — Intelligent Business Intelligence agent for BIFlow.
Supports Groq API (friend's preferred LLM), Google Gemini, and Ollama,
with an intelligent analytical engine fallback so analysis NEVER fails.
"""

import os
import json
import re
import logging
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
import pandas as pd
from dotenv import load_dotenv

from analytics.kpi import calculate_kpis, recommend_charts

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)


class BIAnalystAgent:
    """
    AI-powered Business Intelligence Analyst Agent.
    Generates dynamic KPIs, interactive chart recommendations, and
    an executive BI report for any dataset.
    """

    def __init__(self, model_name: Optional[str] = None, api_key: Optional[str] = None):
        self.groq_api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.model_name = model_name or os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.groq_client = None

        if self.groq_api_key:
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=self.groq_api_key)
            except Exception as e:
                logger.warning(f"Could not initialize Groq client: {e}")

    def analyze(self, df: pd.DataFrame) -> str:
        """
        Analyses the dataset and returns a full Markdown report with
        an embedded ```json ... ``` block describing KPIs and recommended charts.
        """
        shape = df.shape
        dtypes = df.dtypes.astype(str).to_dict()
        missing_values = df.isnull().sum().to_dict()
        stats_summary = df.describe(include="all").to_dict()
        sample_data = df.head(5).to_dict(orient="records")

        prompt = f"""
You are the primary BI Analyst Agent of the BIFlow enterprise platform.
Your task is to dynamically analyse a dataset with {shape[0]} rows and {shape[1]} columns.

Technical summary:
- Column types: {dtypes}
- Missing values: {missing_values}
- Statistical summary: {stats_summary}
- Sample (5 rows): {sample_data}

### MISSION:
1. Write a comprehensive executive report in Markdown including:
   - Executive Summary
   - Key KPIs Analysis
   - Emerging Trends & Patterns
   - Anomalies & Outliers
   - Strategic Business Recommendations

2. **Determine exactly 4 key domain KPIs** specifically tailored to this dataset
   (e.g., Conversion Rate, Avg Value, Churn Rate, Max Peak, Volume).
   For each KPI, provide: title, calculated value, and context subtitle.

3. **Decide on 4 to 6 relevant charts** to display
   (types: "pie", "bar", "histogram", "box").

At the end of your response, you MUST include a valid JSON block enclosed in markdown triple backticks ```json ... ```:
```json
{{
  "kpis": [
    {{"title": "KPI Title 1", "value": "123", "subtitle": "Context description"}},
    {{"title": "KPI Title 2", "value": "45.6%", "subtitle": "Context description"}},
    {{"title": "KPI Title 3", "value": "789", "subtitle": "Context description"}},
    {{"title": "KPI Title 4", "value": "99.1%", "subtitle": "Context description"}}
  ],
  "recommended_charts": [
    {{
      "title": "Descriptive Chart Title",
      "type": "bar",
      "column_x": "exact_column_name",
      "column_y": "numeric_column_if_needed_else_null"
    }}
  ]
}}
```
Be precise, professional, and clear.
"""

        # 1. Attempt Groq if client is ready
        if self.groq_client:
            try:
                candidate_models = [
                    self.model_name,
                    "llama-3.3-70b-versatile",
                    "llama-3.1-8b-instant",
                    "mixtral-8x7b-32768",
                ]
                for m in candidate_models:
                    try:
                        response = self.groq_client.chat.completions.create(
                            messages=[
                                {"role": "system", "content": "You are an expert AI agent in Business Intelligence and data analytics."},
                                {"role": "user", "content": prompt}
                            ],
                            model=m,
                            temperature=0.2
                        )
                        text = response.choices[0].message.content
                        if text and len(text.strip()) > 50:
                            return text
                    except Exception as model_err:
                        logger.warning(f"Groq model {m} failed: {model_err}")
                        continue
            except Exception as e:
                logger.warning(f"Groq API call failed: {e}")

        # 2. Attempt LLMClient (Gemini / Ollama)
        try:
            from agents.llm_client import LLMClient
            llm = LLMClient()
            resp = llm.generate_text(
                prompt,
                system_prompt="You are an expert AI agent in Business Intelligence."
            )
            if resp and resp.strip() and resp.strip() != "{}":
                return resp
        except Exception as e:
            logger.warning(f"LLMClient call failed: {e}")

        # 3. Deterministic Statistical Fallback Engine
        return self._generate_heuristic_report(df)

    def _generate_heuristic_report(self, df: pd.DataFrame) -> str:
        """
        Generates a rich, dynamic BI report and chart configuration
        directly from DataFrame statistics when external LLMs are unavailable.
        """
        kpis = calculate_kpis(df)
        charts = recommend_charts(df)
        n_rows, n_cols = df.shape
        num_cols = list(df.select_dtypes(include=["number"]).columns)
        cat_cols = list(df.select_dtypes(include=["object", "category", "bool"]).columns)

        missing_count = int(df.isnull().sum().sum())
        completeness = ((df.size - missing_count) / max(df.size, 1)) * 100

        top_stats = []
        for c in num_cols[:3]:
            top_stats.append(f"- **{c}**: Mean = `{df[c].mean():.2f}`, Median = `{df[c].median():.2f}`, Max = `{df[c].max():.2f}`")
        stats_md = "\n".join(top_stats) if top_stats else "- No continuous numerical metrics detected."

        top_cats = []
        for c in cat_cols[:3]:
            top_cats.append(f"- **{c}**: {df[c].nunique()} distinct values (Most frequent: `{df[c].mode().iloc[0] if not df[c].mode().empty else 'N/A'}`)")
        cats_md = "\n".join(top_cats) if top_cats else "- No categorical dimensions detected."

        json_block = json.dumps({
            "kpis": kpis,
            "recommended_charts": charts
        }, indent=2)

        return f"""# 📊 Executive Business Intelligence Report

## 1. Executive Summary
The dataset comprises **{n_rows:,} rows** and **{n_cols} columns** across numerical metrics and categorical dimensions. Overall data completeness is evaluated at **{completeness:.1f}%** with {missing_count:,} missing observations.

## 2. Key Performance Indicators
{chr(10).join([f"- **{k['title']}**: `{k['value']}` ({k['subtitle']})" for k in kpis])}

## 3. Metric Distributions & Insights
### Numerical Profiles
{stats_md}

### Categorical Segmentations
{cats_md}

## 4. Anomalies & Data Observations
- **Data Integrity**: {'Identified missing values requiring imputation or filtering before advanced modelling.' if missing_count > 0 else 'All recorded fields exhibit complete data density with zero missing cells.'}
- **Outlier Assessment**: Extreme values observed in top numerical percentiles warrant monitoring for operational spikes.

## 5. Strategic Recommendations
1. **Focus on High-Impact Segments**: Align operational resources to address customer groups displaying elevated churn or variance.
2. **Standardize Collection Pipeline**: Maintain automated data quality validations to safeguard consistency across analytical workflows.
3. **Automate Continuous Tracking**: Schedule recurring KPI monitoring to detect shifts in distribution before performance deviations compound.

```json
{json_block}
```
"""

    def parse_response(self, raw: str) -> Tuple[str, Dict[str, Any]]:
        """
        Separates the Markdown report text from the JSON configuration block.
        """
        chart_config: Dict[str, Any] = {"kpis": [], "recommended_charts": []}
        json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
        if json_match:
            try:
                chart_config = json.loads(json_match.group(1))
            except Exception as e:
                logger.warning(f"Error parsing JSON from agent output: {e}")

        report = re.sub(r"```(?:json)?.*?```", "", raw, flags=re.DOTALL).strip()
        return report, chart_config
