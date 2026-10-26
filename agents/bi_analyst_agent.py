"""
BI Analyst Agent — Intelligent Business Intelligence agent for BIFlow.
Supports:
1. Local Fine-Tuned Qwen 2.5 3B LoRA Adapter (4-bit GPU acceleration on RTX 4050)
   using compact dataset summary prompts (no verbose prompt engineering needed).
2. Cloud API (Groq / Google Gemini / LLMClient) using full prompt engineering instructions.
3. Deterministic Statistical Fallback Engine so analysis NEVER fails.

Traceability: after each call, get_telemetry() reports the REAL provider and model
that produced the result (provider, model, is_llm) plus the list of every attempt
(success / failure + error) in the order they were tried.
"""

import os
import sys
import json
import re
import time
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

LOCAL_BASE_MODEL = "Qwen/Qwen2.5-3B-Instruct"
API_SYSTEM_PROMPT = "You are an expert AI agent in Business Intelligence and data analytics."

# Substrings that mark non-chat models in provider model lists
_NON_CHAT_MARKERS = (
    "whisper", "tts", "guard", "playai", "orpheus", "embed", "image",
    "audio", "live", "robotics", "computer-use", "transcribe", "imagen", "veo",
)


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
    base_model_name = LOCAL_BASE_MODEL

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
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.adapter_path = PROJECT_ROOT / "adapter"
        self.groq_client = None

        self._reset_telemetry()

        if self.groq_api_key:
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=self.groq_api_key)
            except Exception as e:
                logger.warning(f"Could not initialize Groq client: {e}")
                self._log_attempt("Groq", "-", "failed", f"client init: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # Telemetry helpers
    # ──────────────────────────────────────────────────────────────────────────
    def _reset_telemetry(self):
        self.last_engine_used = None
        self.last_execution_mode = "Unknown"
        self.last_prompt_type = "Standard"
        self.last_prompt_used = ""
        self.last_system_prompt = ""
        self.last_provider = "Unknown"
        self.last_model = "-"
        self.last_is_llm = False
        self.last_duration_s = 0.0
        self.last_prepared_columns: List[str] = []
        if not hasattr(self, "attempts"):
            self.attempts: List[Dict[str, str]] = []

    def _log_attempt(self, provider: str, model: str, status: str, detail: str = ""):
        self.attempts.append({
            "provider": provider,
            "model": model,
            "status": status,        # "success" | "failed" | "skipped"
            "detail": str(detail)[:300],
        })

    def _set_result(self, provider: str, model: str, is_llm: bool = True):
        """Records the provider/model that REALLY produced the final answer."""
        self.last_provider = provider
        self.last_model = model
        self.last_is_llm = is_llm
        self.last_execution_mode = f"{provider} · {model}" if model and model != "-" else provider

    # ──────────────────────────────────────────────────────────────────────────
    # Data preparation
    # ──────────────────────────────────────────────────────────────────────────
    def _prepare_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Converts text columns that are really numeric (e.g. Telco 'TotalCharges',
        which contains blank strings) to float so statistics are computed correctly.
        """
        df = df.copy()
        converted = []
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_bool_dtype(df[col]):
                continue
            if not (df[col].dtype == object or pd.api.types.is_string_dtype(df[col])):
                continue
            try:
                raw = df[col].astype("string").str.strip().replace("", pd.NA)
                conv = pd.to_numeric(raw, errors="coerce")
                present = int(raw.notna().sum())
                if present and conv.notna().sum() / present >= 0.9:
                    df[col] = conv.astype(float)
                    converted.append(col)
            except Exception:
                continue
        self.last_prepared_columns = converted
        return df

    # ──────────────────────────────────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────────────────────────────────
    def analyze(self, df: pd.DataFrame, dataset_name: str = "dataset") -> str:
        """
        Analyses the dataset and returns a full Markdown report with
        an embedded ```json ... ``` block describing KPIs and recommended charts.
        """
        self.attempts = []
        self._reset_telemetry()
        start = time.time()

        df = self._prepare_df(df)

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
        if use_local:
            if not has_local_adapter:
                self._log_attempt("Local LoRA", LOCAL_BASE_MODEL, "skipped",
                                  "adapter/adapter_model.safetensors not found")
            else:
                try:
                    logger.info("Executing BI Analyst using Local Fine-Tuned Qwen 2.5 3B LoRA...")
                    result = self._analyze_local_lora(df, dataset_name)
                    self.last_engine_used = "local_lora"
                    self.last_prompt_type = "Compact Dataset Summary (LoRA format - No long prompt)"
                    self._set_result("⚡ Local LoRA", f"{LOCAL_BASE_MODEL} + adapter")
                    self._log_attempt("Local LoRA", LOCAL_BASE_MODEL, "success")
                    self.last_duration_s = round(time.time() - start, 1)
                    return result
                except Exception as e:
                    logger.warning(f"Local LoRA inference error, falling back to Cloud API: {e}")
                    self._log_attempt("Local LoRA", LOCAL_BASE_MODEL, "failed", e)

        # ROUTE 2: Cloud API (Verbose Prompt Engineering)
        self.last_engine_used = "api"
        self.last_prompt_type = "Long Prompt Engineering (Multi-section instructions & schema)"
        result = self._analyze_via_api(df)
        self.last_duration_s = round(time.time() - start, 1)
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # Local LoRA
    # ──────────────────────────────────────────────────────────────────────────
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

        cat_cols = df.select_dtypes(include=["object", "category", "bool", "string"]).columns.tolist()
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

    # ──────────────────────────────────────────────────────────────────────────
    # Cloud API route
    # ──────────────────────────────────────────────────────────────────────────
    def _groq_candidate_models(self) -> List[str]:
        """
        Asks Groq which models this key can actually use, so we never rely on
        hard-coded names that may have been retired. The preferred model comes first.
        """
        preferred = [
            self.model_name,
            "llama-3.3-70b-versatile",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "llama-3.1-8b-instant",
        ]
        available: List[str] = []
        try:
            listing = self.groq_client.models.list()
            available = [m.id for m in listing.data
                         if not any(x in m.id.lower() for x in _NON_CHAT_MARKERS)]
        except Exception as e:
            self._log_attempt("Groq", "models.list()", "failed", e)

        ordered: List[str] = []
        if available:
            ordered = [m for m in preferred if m in available]
            ordered += [m for m in available if m not in ordered]
        else:
            ordered = list(preferred)

        seen, unique = set(), []
        for m in ordered:
            if m and m not in seen:
                seen.add(m)
                unique.append(m)
        return unique[:5]  # cap attempts to keep latency reasonable

    def _try_groq(self, prompt: str) -> Optional[str]:
        if not self.groq_client:
            self._log_attempt("Groq", "-", "skipped",
                              "no API key" if not self.groq_api_key else "client not initialised (is `groq` installed?)")
            return None

        for m in self._groq_candidate_models():
            try:
                response = self.groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": API_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    model=m,
                    temperature=0.2,
                    max_tokens=4000
                )
                text = response.choices[0].message.content
                if text and len(text.strip()) > 50:
                    self._log_attempt("Groq", m, "success")
                    self._set_result("☁️ Groq", m)
                    return text
                self._log_attempt("Groq", m, "failed", "empty / too short response")
            except Exception as model_err:
                logger.warning(f"Groq model {m} failed: {model_err}")
                self._log_attempt("Groq", m, "failed", model_err)
        return None

    def _gemini_candidate_models(self, client) -> List[str]:
        """Lists Gemini models that support generateContent for this key."""
        names: List[str] = []
        try:
            for m in client.models.list():
                name = getattr(m, "name", "") or ""
                actions = getattr(m, "supported_actions", None) or []
                if actions and "generateContent" not in actions:
                    continue
                short = name.replace("models/", "")
                low = short.lower()
                if "gemini" not in low or any(x in low for x in _NON_CHAT_MARKERS):
                    continue
                names.append(short)
        except Exception as e:
            self._log_attempt("Gemini", "models.list()", "failed", e)
            return []

        # Prefer fast "flash" models, newest names first, stable before preview/exp
        def sort_key(n: str):
            low = n.lower()
            return (
                0 if "flash" in low and "lite" not in low else 1,
                1 if ("preview" in low or "exp" in low) else 0,
                [-ord(c) for c in n],
            )
        names.sort(key=sort_key)
        return names[:3]

    def _try_gemini(self, prompt: str) -> Optional[str]:
        if not self.gemini_api_key:
            self._log_attempt("Gemini", "-", "skipped", "no GEMINI_API_KEY / GOOGLE_API_KEY")
            return None
        try:
            from google import genai
        except Exception as e:
            self._log_attempt("Gemini", "-", "skipped", f"`google-genai` not installed: {e}")
            return None

        try:
            client = genai.Client(api_key=self.gemini_api_key)
        except Exception as e:
            self._log_attempt("Gemini", "-", "failed", f"client init: {e}")
            return None

        for m in self._gemini_candidate_models(client):
            try:
                resp = client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config={
                        "system_instruction": API_SYSTEM_PROMPT,
                        "temperature": 0.2,
                        "max_output_tokens": 4000,
                    },
                )
                text = getattr(resp, "text", None)
                if text and len(text.strip()) > 50:
                    self._log_attempt("Gemini", m, "success")
                    self._set_result("☁️ Google Gemini", m)
                    return text
                self._log_attempt("Gemini", m, "failed", "empty / too short response")
            except Exception as e:
                logger.warning(f"Gemini model {m} failed: {e}")
                self._log_attempt("Gemini", m, "failed", e)
        return None

    def _try_llm_client(self, prompt: str) -> Optional[str]:
        """Last LLM route: the project's own LLMClient (Gemini / Ollama ...)."""
        try:
            from agents.llm_client import LLMClient
            llm = LLMClient()
            resp = llm.generate_text(
                prompt,
                system_prompt="You are an expert AI agent in Business Intelligence."
            )
            if resp and resp.strip() and resp.strip() != "{}":
                # LLMClient may not expose its provider; read what it offers, else say so honestly.
                provider = (getattr(llm, "provider", None) or getattr(llm, "backend", None)
                            or getattr(llm, "active_provider", None) or "provider not reported")
                model = (getattr(llm, "model", None) or getattr(llm, "model_name", None)
                         or getattr(llm, "active_model", None) or "-")
                self._log_attempt("LLMClient", f"{provider} / {model}", "success")
                self._set_result(f"☁️ LLMClient ({provider})", str(model))
                return resp
            self._log_attempt("LLMClient", "-", "failed", "empty response")
        except Exception as e:
            logger.warning(f"LLMClient call failed: {e}")
            self._log_attempt("LLMClient", "-", "failed", e)
        return None

    def _analyze_via_api(self, df: pd.DataFrame) -> str:
        """
        Cloud API inference route using comprehensive prompt engineering.
        Order: Groq → Gemini (direct) → LLMClient → deterministic heuristic.
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
        self.last_system_prompt = API_SYSTEM_PROMPT

        for route in (self._try_groq, self._try_gemini, self._try_llm_client):
            text = route(prompt)
            if text:
                return text

        # Deterministic Statistical Fallback Engine
        return self._generate_heuristic_report(df)

    # ──────────────────────────────────────────────────────────────────────────
    # Heuristic fallback (no LLM)
    # ──────────────────────────────────────────────────────────────────────────
    def _generate_heuristic_report(self, df: pd.DataFrame) -> str:
        """
        Generates a rich, dynamic BI report and chart configuration
        directly from DataFrame statistics when external LLMs are unavailable.
        """
        self.last_engine_used = "heuristic"
        self.last_prompt_type = "Pure Python statistical aggregation (No LLM prompt needed)"
        self.last_prompt_used = "N/A - Direct statistical calculations from DataFrame"
        self.last_system_prompt = "N/A"
        self._set_result("📊 Heuristic (no LLM)", "-", is_llm=False)
        self._log_attempt("Heuristic", "-", "success", "all LLM routes failed or were unavailable")

        kpis = calculate_kpis(df)
        charts = recommend_charts(df)
        n_rows, n_cols = df.shape
        num_cols = list(df.select_dtypes(include=["number"]).columns)
        cat_cols = list(df.select_dtypes(include=["object", "category", "bool", "string"]).columns)

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
            top_val = df[c].mode()[0] if not df[c].dropna().empty else "N/A"
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

    # ──────────────────────────────────────────────────────────────────────────
    # Parsing + telemetry
    # ──────────────────────────────────────────────────────────────────────────
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
        `provider` / `model` are the ones that really produced the result.
        """
        return {
            "engine": self.last_engine_used or self.engine,
            "provider": self.last_provider,
            "model": self.last_model,
            "is_llm": self.last_is_llm,
            "execution_mode": self.last_execution_mode,
            "duration_s": self.last_duration_s,
            "converted_columns": list(self.last_prepared_columns),
            "attempts": list(self.attempts),
            "prompt_type": self.last_prompt_type,
            "system_prompt": self.last_system_prompt,
            "prompt_used": self.last_prompt_used,
        }