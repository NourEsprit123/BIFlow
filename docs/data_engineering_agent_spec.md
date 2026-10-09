# ⚙️ Data Engineering Agent Specification & Strategy Guide

> **Robust, Dynamic Data Ingestion, Profiling, Quality Auditing, and Cleaning for Arbitrary Datasets**

---

## 🎯 1. Overview & Core Philosophy

The **Data Engineering Agent** is BIFlow's data preparation powerhouse. Its mission is to take **any raw, unknown dataset** (CSV, Excel, Parquet, etc.) and automatically transform it into a clean, normalized, and validated dataset ready for BI analytics and ML models.

### The Hybrid Execution Principle
To guarantee **100% data integrity, fast performance, and zero hallucinations**, the agent combines:
1. **Python / Pandas Engine:** Computes exact statistics, performs regex stripping, handles matrix operations, and executes cleaning code in milliseconds.
2. **LLM Reasoning Layer:** Infers business domain semantics, evaluates context-specific imputation strategies, normalizes text synonyms, and generates human-readable UI recommendations.

---

## 📊 2. Phase 1: Data Profiling

### Objectives
Inspect and map the anatomy, structure, and statistical distributions of an unknown dataset.

| Data Problem / Edge Case | How Python Handles It | LLM Role in this Step |
| :--- | :--- | :--- |
| **Unknown / Arbitrary Schema & Formats** | Supports `.csv`, `.xlsx`, `.parquet`. Extracts row/column counts, memory footprint, and raw pandas dtypes. | Analyzes column names & sample values to classify column roles (Primary Key ID, Target Variable, Categorical Feature, Continuous Measure, Timestamp). |
| **Ambiguous Column Types** | Detects string columns containing numbers or dates. | Determines true semantic type (e.g. recognizing `tenure` as a duration or `zip_code` as categorical despite being numeric). |
| **High Cardinality Text** | Computes `nunique()` and uniqueness percentages (`nunique() / len(df)`). | Flags identifier columns (e.g. `customer_id`, `UUID`) to be excluded from feature modeling but preserved for tracking. |
| **Zero Variance / Constant Columns** | Identifies columns where all values are identical or 100% null. | Recommends dropping redundant constant columns that provide zero analytical value. |

---

## 🧹 3. Phase 2: Data Quality Diagnostic

### Objectives
Audit data health, calculate weighted quality scores, and flag defects across 4 primary dimensions: **Completeness, Validity, Uniqueness, and Consistency**.

| Data Defect Category | Problem Description & Examples | Python Detection Engine | LLM Role & Decision Making |
| :--- | :--- | :--- | :--- |
| **Missing Values (Explicit & Implicit)** | `NaN`, `None`, empty spaces `" "`, or placeholders like `"N/A"`, `"null"`, `"?"`, `"-999"`. | Runs regex stripping, scans for explicit `NaN`s + text sentinel values, and calculates missing cell percentages. | Evaluates severity based on column importance (e.g., missing Target variable vs missing secondary feature). |
| **Row & ID Duplicates** | Exact duplicate rows or conflicting records sharing the same primary key ID. | Executes `df.duplicated()` and checks ID column uniqueness. | Recommends whether to keep `first`, `last`, or drop duplicate rows. |
| **Type Mismatches (Coercion Errors)** | Numeric columns stored as `object` strings due to dirty entries (e.g. `TotalCharges` having float numbers + `" "`). | Runs **Coercion Test**: `pd.to_numeric(series, errors='coerce')` and measures valid numeric ratio vs failure ratio. | Flags column as a *"Numeric Column containing Dirty Strings"* when valid numeric ratio > 80%. |
| **Statistical Outliers** | Extreme values far outside expected range (e.g. `Age = 999` or `MonthlyCharges = -$500`). | Computes Interquartile Range (IQR = Q3 - Q1) and Z-Scores to flag statistical outliers. | Determines if an outlier is a realistic extreme business value or an invalid recording error. |

---

## 🛠️ 4. Phase 3: Automated Data Cleaning & Remediation

### Objectives
Execute safe, deterministic cleaning transformations based on the LLM's structured action plan.

### 🌊 Problem 1: Dirty Numeric Strings (The 4-Level Waterfall Pipeline)
When a numeric column contains mixed dirty entries (`"$1,000"`, `"1.5k"`, `"one thousand"`, `" "`, `"banana"`):

```text
  Level 1: Regex & Formatting (Python)
  └── Strips $, €, £, commas, and whitespace. Fast & deterministic.
  
  Level 2: Word-to-Number Conversion (Python)
  └── Converts written number words (e.g., "one thousand" ──► 1000).
  
  Level 3: Targeted LLM Parsing (LLM)
  └── Converts complex string text (e.g., "1.5k", "half a million").
  
  Level 4: Safety Guardrail (Python + LLM)
  └── Nonsense entries (e.g., "banana", "ERROR_404") become NaN. NO HALLUCINATIONS.
```

---

### 🩹 Problem 2: Missing Value Imputation
Different columns require different imputation logic based on domain semantics:

| Column Semantic Type | Imputation Strategy | Executed By |
| :--- | :--- | :--- |
| **Continuous Skewed Numericals** (e.g. `TotalCharges`, `Income`) | **Column Median** (protects against outlier distortion). | LLM selects strategy $\rightarrow$ Pandas executes `.fillna(median)`. |
| **Continuous Gaussian Numericals** (e.g. `Temperature`, `Score`) | **Column Mean**. | LLM selects strategy $\rightarrow$ Pandas executes `.fillna(mean)`. |
| **Categorical Strings** (e.g. `PaymentMethod`, `City`) | **Mode** (most frequent) or `"Unknown"` label. | LLM selects strategy $\rightarrow$ Pandas executes `.fillna(mode)`. |
| **Binary Flags** (e.g. `SeniorCitizen`, `IsActive`) | **Conservative Constant** (e.g. `0`). | LLM selects strategy $\rightarrow$ Pandas executes `.fillna(0)`. |

---

### 🔤 Problem 3: Categorical Synonym Merging & Normalization
* **Problem:** Inconsistent text entries in categorical columns (e.g., `Contract` contains `["Month-to-month", "m-to-m", "month2month", "One year", "1 yr"]`).
* **LLM Role:** Inspects unique text values and generates a canonical mapping dictionary:
  ```json
  {
    "m-to-m": "Month-to-month",
    "month2month": "Month-to-month",
    "1 yr": "One year"
  }
  ```
* **Python Engine:** Executes `df[col].replace(mapping)` instantly in Pandas.

---

### 🛡️ Problem 4: Outlier Treatment
* **Problem:** Outlier values that skew analytics or break ML algorithms.
* **Treatment Options:**
  1. **Capping / Winsorizing:** Cap values at 1st and 99th percentiles.
  2. **Coercion to NaN:** Treat invalid extreme values (e.g. `Age = 999`) as missing and impute.

---

## 💾 5. Phase 4: Output Storage, Lineage Audit & UI Integration

To complete the end-to-end operational pipeline, the agent handles these 4 final requirements:

### 1. 🔍 Preview Mode (`Preview changes`)
* When the user clicks **`Preview changes`** on the UI, the agent generates a **Diff Comparison** without overwriting disk files:
  * **Before vs After Metrics:** Shows Quality Score improvement (e.g. `94%` $\rightarrow$ `99.8%`).
  * **Rows Affected Summary:** Table showing exact rows/columns modified.

### 2. 🗄️ Cleaned Dataset Persistence
* Saves the cleaned BI dataset to: `data/cleaned/<filename>_cleaned.csv`.
* Saves the numeric encoded ML dataset to: `data/processed/<filename>_processed.parquet`.

### 3. 📜 Transformation Audit Logging (For XAI / Auditor Agent)
* Generates a structured JSON lineage file: `data/cleaned/<filename>_transformation_log.json`:
  ```json
  {
    "timestamp": "2026-10-08T15:26:00Z",
    "raw_file": "data/raw/telco_churn.csv",
    "quality_score_before": 94.0,
    "quality_score_after": 99.8,
    "applied_transformations": [
      {"column": "TotalCharges", "action": "coercion_and_median_imputation", "imputed_rows": 11},
      {"column": "Contract", "action": "synonym_normalization", "replacements": 4}
    ]
  }
  ```

### 4. ⚡ File Format Flexibility
* Input loader (`load_dataset()`) handles `.csv`, `.xlsx` (Excel), and `.parquet` seamlessly.

---

## 📋 6. Summary of Division of Labor

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA ENGINEERING AGENT                            │
├──────────────────────────────────────┬──────────────────────────────────────┤
│          PYTHON ENGINE               │              LLM LAYER               │
│      (Fast & Deterministic)          │         (Reasoning & Planning)       │
├──────────────────────────────────────┼──────────────────────────────────────┤
│ • Multi-format File Ingestion        │ • Semantic Column Role Inference     │
│ • Regex Character & Symbol Stripping │ • Contextual Imputation Strategy     │
│ • Coercion Tests & Null Auditing     │ • Synonym Recognition & Mapping      │
│ • IQR / Z-Score Outlier Math         │ • Nonsense vs Value Disambiguation   │
│ • Fast Matrix & File Operations      │ • UI Recommendation Text Synthesis   │
│ • Generating Preview Diffs           │ • Audit Log JSON Plan Generation     │
└──────────────────────────────────────┴──────────────────────────────────────┘
```

---
*Updated with Output Storage, Lineage Audit Logging & Preview Mode*
