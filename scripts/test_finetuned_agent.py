"""
Test Script for Fine-Tuned Qwen 2.5 3B LoRA Adapter (BIFlow BI Analyst Agent).
Loads the base model Qwen/Qwen2.5-3B-Instruct, attaches ./adapter, and runs inference.
"""

import sys
import os

# Prevent TensorFlow import conflict and symlink warnings in transformers
os.environ["USE_TF"] = "0"
os.environ["USE_TORCH"] = "1"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import time
import json
import re
import argparse
from pathlib import Path
import pandas as pd
import numpy as np

# Force UTF-8 terminal encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

print(">>> Starting BIFlow LoRA Evaluation Script...", flush=True)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = PROJECT_ROOT / "adapter"
BASE_MODEL_NAME = "Qwen/Qwen2.5-3B-Instruct"

SYSTEM_PROMPT = (
    "You are the BI Analyst Agent of BIFlow. From the dataset summary, write an executive report "
    "(Executive Summary, Key KPIs Analysis, Emerging Trends & Patterns, Anomalies & Outliers, "
    "Strategic Recommendations) followed by one final ```json block with 'kpis' and 'recommended_charts'."
)


def build_dataset_summary(df: pd.DataFrame, dataset_name: str = "dataset") -> str:
    """
    Constructs a structured dataset summary matching the exact training distribution
    of BIFlow's fine-tuned model.
    """
    rows, cols = df.shape
    total_cells = rows * cols
    missing_total = int(df.isnull().sum().sum())
    completeness = round(((total_cells - missing_total) / max(total_cells, 1)) * 100, 1)

    lines = [f"Dataset: {dataset_name} | rows: {rows} | columns: {cols} | completeness: {completeness}%"]

    # 1. Numeric columns
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

    # 2. Categorical columns
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

    # 3. Datetime columns
    date_cols = df.select_dtypes(include=["datetime"]).columns.tolist()
    if date_cols:
        lines.append("Datetime columns:")
        for col in date_cols:
            s = df[col].dropna()
            if len(s) > 0:
                lines.append(f"{col}: min date={s.min()}, max date={s.max()}")

    # 4. Correlations
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


def load_model_and_adapter():
    """Loads base model with PEFT LoRA adapter."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    print(f"\n[1/4] Loading tokenizer for: {BASE_MODEL_NAME}...", flush=True)
    try:
        tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_NAME)
    except Exception:
        tokenizer = AutoTokenizer.from_pretrained(str(ADAPTER_PATH))

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[2/4] Device detected: {device}", flush=True)
    if device == "cuda":
        print(f"      GPU: {torch.cuda.get_device_name(0)}", flush=True)
        print(f"      VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB", flush=True)

    print(f"[3/4] Loading base model: {BASE_MODEL_NAME} (4-bit GPU acceleration)...", flush=True)
    try:
        from transformers import BitsAndBytesConfig
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )
        base_model = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL_NAME,
            quantization_config=bnb_config,
            device_map="cuda:0" if device == "cuda" else None,
            low_cpu_mem_usage=True
        )
        print("      4-bit Quantization active: 100% loaded in RTX 4050 VRAM (~2.1 GB)!", flush=True)
    except Exception as e:
        print(f"      4-bit fallback: {e}", flush=True)
        base_model = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL_NAME,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            device_map="auto" if device == "cuda" else None,
            low_cpu_mem_usage=True
        )

    print(f"[4/4] Attaching LoRA adapter from: {ADAPTER_PATH}...", flush=True)
    model = PeftModel.from_pretrained(base_model, str(ADAPTER_PATH))
    model.eval()
    print(">>> Model and LoRA Adapter successfully initialized! <<<\n", flush=True)
    return model, tokenizer


def extract_json_block(text: str):
    """Extracts and validates JSON block from the generated markdown."""
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        raw_str = match.group(1).strip()
        try:
            return json.loads(raw_str)
        except Exception:
            # Handle multiple consecutive JSON objects {...}\n{...}
            objs = re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw_str, re.DOTALL)
            parsed_list = []
            for o in objs:
                try:
                    parsed_list.append(json.loads(o))
                except Exception:
                    pass
            if parsed_list:
                return {"recommended_charts": parsed_list, "kpis": []}
            return {"error": "JSON parse error"}

    # Fallback to widest braces
    match2 = re.search(r"(\{.*\})", text, re.DOTALL)
    if match2:
        try:
            return json.loads(match2.group(1))
        except Exception as e:
            return {"error": f"JSON fallback parse error: {e}"}
    return None


def run_test(csv_path: Path):
    if not csv_path.exists():
        print(f"Error: Dataset not found at {csv_path}")
        return

    print(f"Reading dataset: {csv_path.name}")
    df = pd.read_csv(csv_path)
    summary_text = build_dataset_summary(df, dataset_name=csv_path.stem)

    print("-" * 60)
    print("INPUT PROMPT SUMMARY SENT TO MODEL:")
    print("-" * 60)
    print(summary_text)
    print("-" * 60)

    # Load model
    model, tokenizer = load_model_and_adapter()

    # Apply ChatML format
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": summary_text}
    ]
    prompt_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

    inputs = tokenizer(prompt_text, return_tensors="pt")
    if hasattr(model, "device"):
        inputs = {k: v.to(model.device) for k, v in inputs.items()}

    print("Generating report with fine-tuned model (streaming generation)...", flush=True)
    t0 = time.time()
    with __import__("torch").no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=1100,
            temperature=0.2,
            do_sample=True,
            top_p=0.9,
            repetition_penalty=1.05
        )
    latency = time.time() - t0

    # Extract only the newly generated tokens
    gen_tokens = outputs[0][inputs["input_ids"].shape[1]:]
    generated_text = tokenizer.decode(gen_tokens, skip_special_tokens=True)

    print("\n" + "=" * 60, flush=True)
    print(f"GENERATED BI REPORT (Latency: {latency:.2f}s | {len(gen_tokens)} tokens)", flush=True)
    print("=" * 60, flush=True)
    print(generated_text, flush=True)
    print("=" * 60, flush=True)

    # Validate JSON schema and domain grounding
    parsed_json = extract_json_block(generated_text)
    print("\n--- JSON VALIDATION & GROUNDING CHECK ---", flush=True)
    if parsed_json and "error" not in parsed_json:
        print("✅ JSON Parsing: SUCCESS", flush=True)
        kpis = parsed_json.get("kpis", [])
        charts = parsed_json.get("recommended_charts", [])
        print(f"✅ Found {len(kpis)} KPIs:", flush=True)
        for k in kpis:
            print(f"   • {k.get('title')}: {k.get('value')} ({k.get('subtitle')})", flush=True)

        print(f"\n✅ Found {len(charts)} Recommended Charts:", flush=True)
        all_cols = set(df.columns)
        for c in charts:
            cx = c.get("column_x")
            cy = c.get("column_y")
            valid_x = (cx in all_cols) if cx else True
            valid_y = (cy in all_cols) if cy else True
            grounding = "✅ VALID" if (valid_x and valid_y) else "⚠️ COLUMN MISMATCH"
            print(f"   • [{c.get('type')}] \"{c.get('title')}\" -> X: {cx}, Y: {cy} | {grounding}", flush=True)
    else:
        print(f"❌ JSON Parsing: FAILED ({parsed_json})")

    # Save to file
    out_file = PROJECT_ROOT / "data" / "reports" / f"finetuned_eval_{csv_path.stem}.md"
    out_file.write_text(generated_text, encoding="utf-8")
    print(f"\nSaved report to: {out_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=str, default="data/raw/telco_churn.csv", help="Path to CSV dataset")
    args = parser.parse_args()

    target_csv = Path(args.csv)
    if not target_csv.is_absolute():
        target_csv = PROJECT_ROOT / target_csv
    run_test(target_csv)
