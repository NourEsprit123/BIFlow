"""
BI Analyst Agent — Intelligent Business Intelligence agent for BIFlow.
Supports:
1. Local Fine-Tuned Qwen 2.5 3B LoRA Adapter (4-bit GPU acceleration on RTX 4050)
   using compact dataset summary prompts (no verbose prompt engineering needed).
2. Cloud API (Groq Llama-3 / Google Gemini) using full prompt engineering instructions.
3. Deterministic Statistical Fallback Engine so analysis NEVER fails.
"""

import os
import sys
import json
import re
import logging
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List
import pandas as pd
import numpy as np
from dotenv import load_dotenv

from analytics.kpi import calculate_kpis, recommend_charts

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)

# Module-level model cache to prevent reloading 2GB weights on every Streamlit interaction
_CACHED_LOCAL_MODEL = None
_CACHED_LOCAL_TOKENIZER = None


def get_local_lora_model():
    """
    Loads and caches Qwen 2.5 3B in 4-bit with LoRA adapter attached.
    100% loaded in GPU VRAM (~2.1 GB) on NVIDIA RTX 4050.
    """
    global _CACHED_LOCAL_MODEL, _CACHED_LOCAL_TOKENIZER
    if _CACHED_LOCAL_MODEL is not None and _CACHED_LOCAL_TOKENIZER is not None:
        return _CACHED_LOCAL_MODEL, _CACHED_LOCAL_TOKENIZER

    os.environ["USE_TF"] = "0"
    os.environ["USE_TORCH"] = "1"
    os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    adapter_path = PROJECT_ROOT / "adapter"
    base_model_name = "Qwen/Qwen2.5-3B-Instruct"

    logger.info("Initializing Local Fine-Tuned Qwen 2.5 3B LoRA model...")
    tokenizer = AutoTokenizer.from_pretrained(base_model_name)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    try:
        from transformers import BitsAndBytesConfig
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )
        base = AutoModelForCausalLM.from_pretrained(
            base_model_name,
            quantization_config=bnb_config,
            device_map="cuda:0" if device == "cuda" else None,
            low_cpu_mem_usage=True
        )
    except Exception as e:
        logger.warning(f"4-bit BitsAndBytes not available, falling back to FP16: {e}")
        base = AutoModelForCausalLM.from_pretrained(
            base_model_name,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            device_map="auto" if device == "cuda" else None,
            low_cpu_mem_usage=True
        )

    model = PeftModel.from_pretrained(base, str(adapter_path))
    model.eval()

    _CACHED_LOCAL_MODEL = model
    _CACHED_LOCAL_TOKENIZER = tokenizer
    return _CACHED_LOCAL_MODEL, _CACHED_LOCAL_TOKENIZER


class BIAnalystAgent:
    """
    AI-powered Business Intelligence Analyst Agent.
    Supports seamless switching between:
    - 'local_lora' : Local fine-tuned model (concise prompt, private, offline)
    - 'api'        : Cloud API (Groq / Gemini) with comprehensive prompt engineering
    - 'auto'       : Automatically selects local LoRA if available, else API
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        engine: str = "auto"
    ):
        self.engine = engine.lower()
        self.groq_api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.model_name = model_name or os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.adapter_path = PROJECT_ROOT / "adapter"
        self.groq_client = None
        self.last_engine_used = None
        self.last_execution_mode = None
        self.last_prompt_type = None
        self.last_prompt_used = ""
        self.last_system_prompt = ""

        if self.groq_api_key:
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=self.groq_api_key)
            except Exception as e:
                logger.warning(f"Could not initialize Groq client: {e}")

    def analyze(self, df: pd.DataFrame, dataset_name: str = "dataset") -> str:
        """
        Analyses the dataset and returns a full Markdown report with
        an embedded ```json ... ``` block describing KPIs and recommended charts.
        """
        # Determine execution path
        has_local_adapter = (self.adapter_path / "adapter_model.safetensors").exists()
        use_local = False

        if self.engine in ("local_lora", "local"):
            use_local = True
        elif self.engine == "auto" and has_local_adapter:
            try:
                import torch
                if torch.cuda.is_available():
                    use_local = True
            except Exception:
                pass

        # ROUTE 1: Local Fine-Tuned Model (Compact Prompt)
        if use_local and has_local_adapter:
            try:
                logger.info("Executing BI Analyst using Local Fine-Tuned Qwen 2.5 3B LoRA...")
                self.last_engine_used = "local_lora"
                self.last_execution_mode = "⚡ Local Fine-Tuned (Qwen 2.5 3B LoRA - RTX 4050)"
                self.last_prompt_type = "Compact Dataset Summary (LoRA format - No long prompt)"
                return self._analyze_local_lora(df, dataset_name)
            except Exception as e:
                logger.warning(f"Local LoRA inference error, falling back to Cloud API: {e}")

        # ROUTE 2: Cloud API (Verbose Prompt Engineering)
        self.last_engine_used = "api"
        self.last_execution_mode = "☁️ Cloud API (Groq Llama-3 / Gemini)"
        self.last_prompt_type = "Long Prompt Engineering (Multi-section instructions & schema)"
        return self._analyze_via_api(df)

    def _analyze_local_lora(self, df: pd.DataFrame, dataset_name: str = "dataset") -> str:
        """
        Executes inference using the fine-tuned LoRA model with the exact
        compact summary prompt format it was trained on.
        """
        summary_text = self._build_compact_summary(df, dataset_name)
        system_prompt = (
            "You are the BI Analyst Agent of BIFlow. From the dataset summary, write an executive report "
            "(Executive Summary, Key KPIs Analysis, Emerging Trends & Patterns, Anomalies & Outliers, "
            "Strategic Recommendations) followed by one final ```json block with 'kpis' and 'recommended_charts'."
        )
        self.last_system_prompt = system_prompt
        self.last_prompt_used = summary_text

        model, tokenizer = get_local_lora_model()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": summary_text}
        ]
        prompt_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(prompt_text, return_tensors="pt")
        if hasattr(model, "device"):
            inputs = {k: v.to(model.device) for k, v in inputs.items()}

        import torch
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=1100,
                temperature=0.2,
                do_sample=True,
                top_p=0.9,
                repetition_penalty=1.05
            )

        gen_tokens = outputs[0][inputs["input_ids"].shape[1]:]
        return tokenizer.decode(gen_tokens, skip_special_tokens=True)

    def _build_compact_summary(self, df: pd.DataFrame, dataset_name: str = "dataset") -> str:
        """
        Extracts concise dataset statistical metrics matching the fine-tuning training distribution.
        """
        rows, cols = df.shape
        total_cells = rows * cols
        missing_total = int(df.isnull().sum().sum())
        completeness = round(((total_cells - missing_total) / max(total_cells, 1)) * 100, 1)

        lines = [f"Dataset: {dataset_name} | rows: {rows} | columns: {cols} | completeness: {completeness}%"]

        num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if num_cols:
            lines.append("Numeric columns:")
            for col in num_cols[:12]:
                s = df[col].dropna()
                if len(s) == 0:
                    continue
                mean_v = round(float(s.mean()), 2)
                med_v = round(float(s.median()), 2)
                std_v = round(float(s.std()), 2) if len(s) > 1 else 0.0
                min_v = round(float(s.min()), 2)
                max_v = round(float(s.max()), 2)
                missing = int(df[col].isnull().sum())
                lines.append(f"{col}: mean={mean_v}, median={med_v}, std={std_v}, min={min_v}, max={max_v}, missing={missing}")

        cat_cols = df.select_dtypes(include=["object", "category", "bool"]).columns.tolist()
        if cat_cols:
            lines.append("Categorical columns:")
            for col in cat_cols[:10]:
                s = df[col].dropna().astype(str)
                nunique = s.nunique()
                vc = s.value_counts().head(4)
                top_parts = []
                for k, count in vc.items():
                    pct = round((count / max(len(s), 1)) * 100, 1)
                    top_parts.append(f"{k}: {count} ({pct}%)")
                lines.append(f"{col}: {nunique} unique; " + ", ".join(top_parts))

        if len(num_cols) >= 2:
            try:
                corr_matrix = df[num_cols].corr().abs()
                np.fill_diagonal(corr_matrix.values, np.nan)
                unstacked = corr_matrix.unstack().dropna().sort_values(ascending=False)
                seen_pairs = set()
                top_corrs = []
                for (c1, c2), val in unstacked.items():
                    pair = tuple(sorted([c1, c2]))
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        top_corrs.append(f"{c1} & {c2}: r = {round(val, 2)}")
                    if len(top_corrs) >= 4:
                        break
                if top_corrs:
                    lines.append("Top correlations:")
                    lines.extend(top_corrs)
            except Exception:
                pass

        return "\n".join(lines)

    def _analyze_via_api(self, df: pd.DataFrame) -> str:
        """
        Cloud API inference route (Groq Llama-3 / Gemini) using comprehensive prompt engineering.
        """
        shape = df.shape
        dtypes = df.dtypes.astype(str).to_dict()
        missing_values = df.isnull().sum().to_dict()
        stats_summary = df.describe(include="all").to_dict()
        sample_data = df.head(5).to_dict(orient="records")

        # Long, detailed prompt engineering for general-purpose LLMs
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
   (types: "pie", "bar", "histogram", "scatter", "box").

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
        self.last_prompt_used = prompt
        self.last_system_prompt = "You are an expert AI agent in Business Intelligence and data analytics."

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
        self.last_engine_used = "heuristic"
        self.last_execution_mode = "📊 Deterministic Statistical Fallback"
        self.last_prompt_type = "Pure Python statistical aggregation (No LLM prompt needed)"
        self.last_prompt_used = "N/A - Direct statistical calculations from DataFrame"
        self.last_system_prompt = "N/A"

        kpis = calculate_kpis(df)
        charts = recommend_charts(df)
        n_rows, n_cols = df.shape
        num_cols = list(df.select_dtypes(include=["number"]).columns)
        cat_cols = list(df.select_dtypes(include=["object", "category", "bool"]).columns)

        missing_count = int(df.isnull().sum().sum())
        completeness = ((df.size - missing_count) / max(df.size, 1)) * 100

        top_stats = []
        for c in num_cols[:3]:
            mean_v = df[c].mean()
            std_v = df[c].std()
            top_stats.append(f"- **{c}**: Mean `{mean_v:.2f}`, Std `{std_v:.2f}`")
        stats_md = "\n".join(top_stats) if top_stats else "- No numeric columns available"

        top_cats = []
        for c in cat_cols[:3]:
            top_val = df[c].mode()[0] if not df[c].empty else "N/A"
            uniques = df[c].nunique()
            top_cats.append(f"- **{c}**: Dominant `{top_val}`, Distinct `{uniques}`")
        cats_md = "\n".join(top_cats) if top_cats else "- No categorical columns available"

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
        Separates the Markdown report text from the JSON configuration block,
        supporting single JSON dicts as well as multiple JSON segments.
        """
        chart_config: Dict[str, Any] = {"kpis": [], "recommended_charts": []}
        json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
        if json_match:
            raw_json_str = json_match.group(1).strip()
            try:
                parsed = json.loads(raw_json_str)
                if isinstance(parsed, dict):
                    chart_config = parsed
            except Exception:
                # Handle multiple consecutive JSON objects {...}\n{...}
                objs = re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw_json_str, re.DOTALL)
                parsed_list = []
                for o in objs:
                    try:
                        p = json.loads(o)
                        if isinstance(p, dict):
                            parsed_list.append(p)
                    except Exception:
                        pass
                if parsed_list:
                    for p in parsed_list:
                        if "kpis" in p:
                            chart_config["kpis"] = p["kpis"]
                        if "recommended_charts" in p:
                            chart_config["recommended_charts"] = p["recommended_charts"]
                    if not chart_config.get("recommended_charts") and parsed_list:
                        chart_config["recommended_charts"] = parsed_list

        report = re.sub(r"```(?:json)?.*?```", "", raw, flags=re.DOTALL).strip()
        return report, chart_config

    def get_telemetry(self) -> Dict[str, Any]:
        """
        Returns execution details and prompt metadata for dashboard inspection.
        """
        return {
            "engine": getattr(self, "last_engine_used", self.engine),
            "execution_mode": getattr(self, "last_execution_mode", "Unknown"),
            "prompt_type": getattr(self, "last_prompt_type", "Standard"),
            "system_prompt": getattr(self, "last_system_prompt", ""),
            "prompt_used": getattr(self, "last_prompt_used", "")
        }
