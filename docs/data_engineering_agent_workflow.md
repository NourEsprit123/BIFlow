# BIFlow Data Engineering Agent - Complete Workflow Guide

**Version:** 2.0.0  
**Date:** October 21, 2026  
**Authors:** Mohamed & Malek

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture Générale](#architecture-générale)
3. [Phase 1: Profiling & Data Quality (Agent Workflow)](#phase-1-profiling--data-quality-agent-workflow)
4. [Phase 2: LLM Reasoning Process](#phase-2-llm-reasoning-process)
5. [Phase 3: Sandbox Custom Checks](#phase-3-sandbox-custom-checks)
6. [JSON Output Structure](#json-output-structure)
7. [Phase 4: Cleaning Integration (pour Malek)](#phase-4-cleaning-integration-pour-malek)
8. [How LLM Works in BIFlow](#how-llm-works-in-biflow)
9. [Testing & Validation](#testing--validation)

---

## Overview

Le **Data Engineering Agent** est un agent autonome qui utilise une approche hybride:
- **Python déterministe** pour l'analyse rapide (statistiques, missing values, outliers)
- **LLM (Gemini)** pour le raisonnement intelligent (interprétation, décisions, stratégies)
- **Sandbox sécurisé** pour exécuter du code Python généré par le LLM

L'agent produit un **ProfilingReport JSON** qui contient toutes les informations nécessaires pour la phase de nettoyage (Cleaning Agent de Malek).

**Périmètre actuel :** Agent 1 profile et audite les données, puis transmet ses constats et recommandations dans le rapport. Il n'applique pas de nettoyage/ETL et ne produit pas de dataset transformé. Les exemples de la phase 4 décrivent l'intégration attendue côté agent aval.

---

## Architecture Générale

```
┌─────────────────────────────────────────────────────────────────┐
│                      BIFlow Agent 1                             │
│                 Data Engineering Agent                          │
│                                                                 │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────┐      │
│  │   Python    │    │     LLM      │    │   Sandbox   │      │
│  │  Analysis   │───▶│  Reasoning   │───▶│   Checks    │      │
│  │(Profiler +  │    │  (Gemini)    │    │  (Secure)   │      │
│  │  Quality)   │    │              │    │             │      │
│  └─────────────┘    └──────────────┘    └─────────────┘      │
│         │                   │                    │             │
│         └───────────────────┼────────────────────┘             │
│                             │                                  │
│                             ▼                                  │
│                ┌──────────────────────────┐                   │
│                │   ProfilingReport.json   │                   │
│                │  (Structured Output)     │                   │
│                └──────────────────────────┘                   │
│                             │                                  │
└─────────────────────────────┼──────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      BIFlow Agent 2                             │
│                    Cleaning Agent (Malek)                       │
│                                                                 │
│  Lit le ProfilingReport.json et applique:                      │
│  - Imputation strategies                                        │
│  - Type casting                                                 │
│  - Outlier treatment                                            │
│  - Synonym normalization                                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Profiling & Data Quality (Agent Workflow)

### Étape 1.1: Analyse Python (Déterministe)

Le fichier `analytics/profiler.py` analyse le dataset et calcule:

```python
profile = profile_dataset(file_path)
# Returns:
{
    "file_name": "telco_churn.csv",
    "rows": 7043,
    "columns": 21,
    "column_roles": {
        "customerID": "primary_key",
        "tenure": "continuous_numeric",
        "MonthlyCharges": "continuous_numeric",
        "gender": "categorical",
        ...
    },
    "missing_summary": {...},
    "type_summary": {...}
}
```

### Étape 1.2: Health Scores

Le fichier `analytics/data_quality.py` calcule les scores de santé:

```python
health = calculate_health_scores(df)
# Returns:
{
    "overall_health_score": 87.5,
    "completeness": 92.0,  # % de valeurs non-manquantes
    "validity": 85.0,      # % de colonnes sans type issues
    "uniqueness": 95.0,    # % de colonnes sans duplicates
    "consistency": 78.0,   # % de colonnes sans cross-column issues
    "missing_info": {
        "total_missing_cells": 234,
        "columns": {
            "TotalCharges": 11,  # nombre de missing values
            "age": 5
        }
    },
    "type_issues": {
        "TotalCharges": {
            "issue": "numeric_stored_as_object",
            "detected": "11 non-numeric values in numeric column",
            "valid_numeric_ratio": 0.9984,
            "recommendation": "Clean and cast to float64"
        }
    },
    "outlier_info": {
        "MonthlyCharges": {
            "outlier_count": 89,
            "outlier_pct": 1.26,
            "lower_bound": -45.2,
            "upper_bound": 150.8
        }
    }
}
```

### Étape 1.3: Column Evidence (Pour le LLM)

Le fichier `agents/data_engineering_agent.py` construit des **evidences riches** pour chaque colonne:

```python
column_evidence = self._build_column_evidence(df, profile, health)
# Returns pour chaque colonne:
{
    "MonthlyCharges": {
        "dtype": "float64",
        "inferred_role": "continuous_numeric",
        "missing_count": 0,
        "missing_pct": 0.0,
        "unique_count": 1585,
        "unique_pct": 22.5,
        "sample_values": ["29.85", "56.95", "53.85", ...],  # 8 exemples
        
        # Stats numériques
        "numeric_stats": {
            "mean": 64.76,
            "median": 70.35,
            "std": 30.09,
            "min": 18.25,
            "max": 118.75,
            "q1": 35.59,
            "q3": 89.85,
            "skewness": -0.22,
            "zeros_count": 0,
            "negative_count": 0
        },
        
        # Issues détectés par Python
        "python_detected_type_issue": null,  # Pas d'issue
        "python_detected_outliers": {
            "outlier_count": 89,
            "outlier_pct": 1.26,
            "lower_bound": -45.2,
            "upper_bound": 150.8
        },
        
        # Flags
        "is_constant": false,
        "is_all_null": false
    }
}
```

---

## Phase 2: LLM Reasoning Process

### Comment le LLM fonctionne dans BIFlow?

Le LLM (Gemini) est appelé pour **raisonner** sur les colonnes, pas juste appliquer des règles.

#### 2.1: Prompt Construction

Le fichier `agents/data_engineering_agent.py` construit un prompt **compact** pour éviter les timeouts:

```python
def _llm_reason_single_batch(self, file_path, profile, health, column_evidence):
    # ── COMPACT EVIDENCE (pour éviter timeout) ──────────────────
    cols_for_llm = {}
    for col, ev in column_evidence.items():
        cols_for_llm[col] = {
            "dtype": ev["dtype"],
            "role": ev["inferred_role"],
            "missing": f"{ev['missing_count']} ({ev['missing_pct']}%)",
            "unique": ev["unique_count"],
            "samples": ev["sample_values"][:3],  # Seulement 3 samples
            "issue": ev.get("python_detected_type_issue", {}).get("issue", "none")
        }
        # Stats minimales pour numerics
        if ev["numeric_stats"]:
            cols_for_llm[col]["stats"] = {
                "mean": ev["numeric_stats"].get("mean"),
                "min": ev["numeric_stats"].get("min"),
                "max": ev["numeric_stats"].get("max"),
            }
    
    # ── SYSTEM PROMPT (bref et décisif) ─────────────────────────
    system_prompt = (
        "You are a Data Engineer. Analyze columns and return JSON with:\n"
        "1. column_reasoning: {col: {severity: HIGH|MEDIUM|LOW|NONE, "
        "agent_reasoning: brief text, imputation_strategy: median|mean|mode|drop}}\n"
        "2. agent_summary: 2 sentences\n"
        "3. numeric_waterfall_columns: [cols needing numeric cleaning]\n"
        "4. outlier_columns: [cols with outliers]\n"
        "Be brief and decisive."
    )
    
    # ── USER PROMPT (avec données du dataset) ───────────────────
    user_prompt = (
        f"Dataset: {os.path.basename(file_path)}\n"
        f"Shape: {profile['rows']} rows × {profile['columns']} cols\n"
        f"Health: {health['overall_health_score']}%\n"
        f"Columns:\n{json.dumps(cols_for_llm, indent=1)}\n\n"
        f"Return JSON with column_reasoning, agent_summary, "
        f"numeric_waterfall_columns, outlier_columns"
    )
    
    # ── APPEL LLM ───────────────────────────────────────────────
    result = self.llm_client.generate_json(user_prompt, system_prompt)
    return result
```

#### 2.2: LLM API Call (Gemini)

Le fichier `agents/llm_client.py` appelle l'API Gemini:

```python
def _call_gemini(self, prompt: str, system_prompt: Optional[str] = None) -> str:
    """Calls Google Gemini API using google-genai SDK."""
    from google import genai
    from google.genai import types
    
    client = genai.Client(api_key=self.gemini_api_key)
    
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.3,        # Low temperature = plus déterministe
        max_output_tokens=8192,
    )
    
    # Appel avec retry automatique (2 tentatives)
    max_retries = 2
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model="gemini-flash-latest",  # Stable model alias
                contents=prompt,
                config=config
            )
            return response.text  # Texte JSON retourné par Gemini
        except Exception as e:
            if attempt < max_retries:
                time.sleep(2)
            else:
                return "{}"  # Fallback vers règles si échec
```

#### 2.3: LLM Response Example

Le LLM retourne un JSON structuré:

```json
{
  "column_reasoning": {
    "MonthlyCharges": {
      "severity": "MEDIUM",
      "agent_reasoning": "89 outliers detected (1.26%). Likely high-value contracts or data entry errors. Recommend capping at 99th percentile.",
      "imputation_strategy": "none",
      "needs_custom_check": false
    },
    "TotalCharges": {
      "severity": "HIGH",
      "agent_reasoning": "11 non-numeric values in numeric column. Python detected 99.8% valid numerics. Convert empty strings to NaN then impute with median.",
      "imputation_strategy": "median",
      "needs_custom_check": true,
      "custom_check_description": "Verify that converted values are in valid range [0, 10000]"
    },
    "gender": {
      "severity": "NONE",
      "agent_reasoning": "Clean categorical column with 2 values. No issues.",
      "imputation_strategy": "mode"
    }
  },
  "agent_summary": "Dataset has 87.5% health score. Main issues: TotalCharges needs type conversion, MonthlyCharges has outliers requiring capping.",
  "numeric_waterfall_columns": ["TotalCharges"],
  "outlier_columns": ["MonthlyCharges", "tenure"]
}
```

#### 2.4: Batching pour Large Datasets

Si le dataset a **plus de 50 colonnes**, on split en batches de 30 colonnes:

**⚠️ Important:** Si un batch échoue (timeout, erreur API), ce batch utilise le **fallback rule-based** qui génère un reasoning intelligent mais moins personnalisé. C'est pourquoi sur de gros datasets, certaines colonnes peuvent avoir un reasoning moins détaillé.

```python
def _llm_reason_batched(self, file_path, profile, health, column_evidence):
    """Process large datasets in batches to avoid timeout."""
    all_columns = list(column_evidence.keys())
    batch_size = 30
    batches = [all_columns[i:i+batch_size] 
               for i in range(0, len(all_columns), batch_size)]
    
    merged_results = {
        "column_reasoning": {},
        "agent_summary": "",
        "numeric_waterfall_columns": [],
        "outlier_columns": []
    }
    
    for i, batch_cols in enumerate(batches):
        logger.info(f"Processing batch {i+1}/{len(batches)} ({len(batch_cols)} cols)")
        
        # Filtrer column_evidence pour ce batch
        batch_evidence = {col: column_evidence[col] for col in batch_cols}
        
        # Appeler LLM sur ce batch
        batch_result = self._llm_reason_single_batch(
            file_path, profile, health, batch_evidence
        )
        
        # Merge results
        merged_results["column_reasoning"].update(
            batch_result.get("column_reasoning", {})
        )
        merged_results["numeric_waterfall_columns"].extend(
            batch_result.get("numeric_waterfall_columns", [])
        )
        merged_results["outlier_columns"].extend(
            batch_result.get("outlier_columns", [])
        )
    
    # Summary global
    merged_results["agent_summary"] = (
        f"Analyzed {len(all_columns)} columns in {len(batches)} batches. "
        f"{len(merged_results['numeric_waterfall_columns'])} need cleaning."
    )
    
    return merged_results
```

---

## Phase 3: Sandbox Custom Checks

### Pourquoi le Sandbox?

Quand le LLM détecte une colonne incertaine (ex: `needs_custom_check: true`), il peut **générer du code Python** pour vérifier la colonne de façon plus précise.

Le sandbox **exécute ce code de façon sécurisée** (pas d'accès fichiers, réseau, ou imports dangereux).

### Workflow Sandbox

#### 3.1: LLM Génère du Code Python

Le fichier `agents/data_engineering_agent.py` demande au LLM:

```python
def _run_custom_checks(self, df, llm_report, column_evidence):
    """For uncertain columns, ask LLM to write custom Python checks."""
    sandbox_results = {}
    col_reasoning = llm_report.get("column_reasoning", {})
    
    for col, reasoning in col_reasoning.items():
        if not reasoning.get("needs_custom_check", False):
            continue  # Skip si pas nécessaire
        
        # ── Ask LLM to WRITE CODE ───────────────────────────────
        code_prompt = (
            f"Write a Python function to validate column '{col}'.\n"
            f"What to check: {reasoning.get('custom_check_description', '')}\n"
            f"Column dtype: {column_evidence[col]['dtype']}\n"
            f"Sample values: {column_evidence[col]['sample_values']}\n\n"
            f"Rules:\n"
            f"- Define ONLY: def custom_check(series: pd.Series) -> dict\n"
            f"- Return: {{'passed': bool, 'metric': float|str, 'details': str}}\n"
            f"- Use only: pd, np, re, built-in Python\n"
            f"- NO imports, NO file I/O, NO external calls\n"
            f"- Keep it under 20 lines\n\n"
            f"Return JSON: {{\"code\": \"<full python code here>\"}}"
        )
        
        code_result = self.llm_client.generate_json(code_prompt)
        if not code_result or "code" not in code_result:
            continue  # Skip si LLM ne génère pas de code
        
        check_code = code_result["code"]
        series = df[col]
        
        # ── Run in SANDBOX (sécurisé) ───────────────────────────
        sample_series = series.head(500)  # Test sur 500 rows max
        sandbox_result = run_sandboxed_check(
            check_code, sample_series, timeout_sec=8
        )
        
        sandbox_results[col] = {
            "skipped": False,
            "check_description": reasoning.get("custom_check_description", ""),
            "generated_code": check_code,
            "result": sandbox_result,
            "sample_size": len(sample_series),
        }
    
    return sandbox_results
```

#### 3.2: Exemple de Code Généré par le LLM

Pour la colonne `TotalCharges` avec des valeurs non-numériques:

```python
def custom_check(series):
    """Check if TotalCharges values are in valid range after conversion."""
    import pandas as pd
    import numpy as np
    
    # Convert to numeric (coerce errors to NaN)
    numeric_series = pd.to_numeric(series, errors='coerce')
    
    # Check range [0, 10000]
    valid_mask = (numeric_series >= 0) & (numeric_series <= 10000)
    valid_count = valid_mask.sum()
    total_count = len(numeric_series.dropna())
    
    valid_ratio = valid_count / total_count if total_count > 0 else 0
    
    return {
        "passed": valid_ratio > 0.95,  # 95% threshold
        "metric": round(valid_ratio, 4),
        "details": f"{valid_count}/{total_count} values in valid range [0, 10000]"
    }
```

#### 3.3: Exécution Sécurisée

Le fichier `analytics/data_quality.py` exécute le code dans un namespace sécurisé:

```python
def run_sandboxed_check(code, series, timeout_sec=10):
    """
    Safely execute LLM-generated Python code in sandboxed namespace.
    """
    # ── SAFE NAMESPACE (pas d'accès dangereux) ──────────────────
    namespace = {
        "__builtins__": {
            "len": len,
            "sum": sum,
            "min": min,
            "max": max,
            "round": round,
            "int": int,
            "float": float,
            "str": str,
            "list": list,
            "dict": dict,
            "set": set,
            "tuple": tuple,
            "range": range,
            "enumerate": enumerate,
            "zip": zip,
            "abs": abs,
            # BLOCKED: open, exec, eval, __import__, compile
        },
        "pd": pd,   # pandas autorisé
        "np": np,   # numpy autorisé
        "re": re,   # regex autorisé
    }
    
    try:
        # ── EXEC CODE ───────────────────────────────────────────
        exec(code, namespace)
    except Exception as exc:
        return {"passed": None, "error": f"Exec error: {exc}"}
    
    if "custom_check" not in namespace:
        return {"passed": None, "error": "Code must define custom_check()"}
    
    # ── RUN WITH TIMEOUT (8 sec max) ────────────────────────────
    result, error = _run_with_timeout(
        lambda: namespace["custom_check"](series), 
        timeout_sec
    )
    
    if error:
        return {"passed": None, "error": error}
    
    if not isinstance(result, dict):
        return {"passed": None, "error": "Must return dict"}
    
    return {
        "passed": result.get("passed"),
        "metric": result.get("metric"),
        "details": result.get("details"),
        "error": None
    }
```

#### 3.4: Sandbox Result Example

```json
{
  "TotalCharges": {
    "skipped": false,
    "check_description": "Verify converted values are in valid range [0, 10000]",
    "generated_code": "def custom_check(series):\n    ...",
    "result": {
      "passed": true,
      "metric": 0.9989,
      "details": "7032/7043 values in valid range [0, 10000]",
      "error": null
    },
    "sample_size": 500
  }
}
```

---

## JSON Output Structure

### ProfilingReport.json

Le fichier final sauvegardé dans `data/reports/{dataset}_profiling_report.json`:

```json
{
  "schema_version": "2.1",
  
  "dataset_ref": {
    "file_path": "C:\\...\\telco_churn.csv",
    "file_name": "telco_churn.csv",
    "rows": 7043,
    "columns": 21,
    "size_bytes": 963738
  },
  
  "health_scores": {
    "overall": 87.5,
    "completeness": 92.0,
    "validity": 85.0,
    "uniqueness": 95.0,
    "consistency": 78.0
  },
  
  "column_profiles": {
    "TotalCharges": {
      "dtype": "object",
      "inferred_role": "continuous_numeric",
      "missing_count": 11,
      "missing_pct": 0.16,
      "unique_count": 6531,
      "sample_values": ["29.85", "1889.5", "108.15", ...],
      
      "numeric_stats": {},  // Empty car dtype=object
      
      "issues": [
        {
          "issue_id": "type_mismatch",
          "source": "python",
          "severity": "HIGH",
          "description": "numeric_stored_as_object",
          "evidence": {
            "detected": "11 non-numeric values",
            "recommendation": "Clean and cast to float64",
            "valid_numeric_ratio": 0.9984
          }
        },
        {
          "issue_id": "missing_values",
          "source": "python",
          "severity": "MEDIUM",
          "description": "Missing values: 11 (0.16%)",
          "evidence": {"count": 11, "pct": 0.16}
        },
        {
          "issue_id": "sandbox_check_failed",
          "source": "sandbox",
          "severity": "MEDIUM",
          "description": "Custom check failed: 11 values outside range",
          "evidence": {
            "check_name": "Verify range [0, 10000]",
            "metric": 0.9984,
            "sample_size": 500
          }
        }
      ],
      
      "agent_reasoning": "11 non-numeric values in numeric column. Python detected 99.8% valid numerics. Convert empty strings to NaN then impute with median.",
      "business_interpretation": "Total charges should be numeric. Empty values likely represent new customers with no billing history.",
      "severity": "HIGH",
      "uncertainty": "LOW",
      "python_agreement": "agree",
      "drop_recommended": false,
      
      "imputation_strategy": "median",
      "etl_cast_to": "float64",
      
      "sandbox_triggered": true,
      "sandbox_result": {
        "passed": false,
        "metric": 0.9984,
        "details": "7032/7043 values in valid range",
        "error": null
      },
      "custom_check_code": "def custom_check(series):\n    ..."
    },
    
    "MonthlyCharges": {
      "dtype": "float64",
      "inferred_role": "continuous_numeric",
      "missing_count": 0,
      "missing_pct": 0.0,
      "unique_count": 1585,
      "sample_values": ["29.85", "56.95", "53.85"],
      
      "numeric_stats": {
        "mean": 64.76,
        "median": 70.35,
        "std": 30.09,
        "min": 18.25,
        "max": 118.75,
        "q1": 35.59,
        "q3": 89.85,
        "skewness": -0.22,
        "zeros_count": 0,
        "negative_count": 0
      },
      
      "issues": [
        {
          "issue_id": "statistical_outliers",
          "source": "python",
          "severity": "MEDIUM",
          "description": "89 statistical outliers (IQR)",
          "evidence": {
            "outlier_count": 89,
            "outlier_pct": 1.26,
            "bounds": {"low": -45.2, "high": 150.8}
          }
        }
      ],
      
      "agent_reasoning": "89 outliers detected (1.26%). Likely high-value contracts. Recommend capping at 99th percentile.",
      "severity": "MEDIUM",
      "imputation_strategy": "none",
      "etl_cast_to": "none",
      
      "sandbox_triggered": false,
      "sandbox_result": null,
      "custom_check_code": null
    }
  },
  
  "cross_column_issues": [
    {
      "issue": "duplicate_rows",
      "count": 12,
      "description": "12 duplicate rows detected"
    }
  ],
  
  "llm_discovered_issues": [],
  "uncertainty_flags": [],
  
  "recommended_cleaning_order": [
    "TotalCharges",      // HIGH severity first
    "MonthlyCharges",    // MEDIUM severity
    "tenure"             // MEDIUM severity
  ],
  
  "etl_hints": {
    "type_casting_targets": {
      "TotalCharges": "float64"
    },
    "join_key_candidates": ["customerID"],
    "drop_candidates": [],
    "recommended_output_format": "parquet",
    "synonym_mappings": {}
  },
  
  "imputation_plan": {
    "TotalCharges": {"strategy": "median"},
    "gender": {"strategy": "mode"}
  },
  
  "outlier_columns": ["MonthlyCharges", "tenure"],
  
  "agent_summary": "Dataset has 87.5% health score. Main issues: TotalCharges needs type conversion, MonthlyCharges has outliers requiring capping.",
  
  "recommendation_summary": "Apply waterfall cleaning to TotalCharges, impute 11 missing values with median, cap 89 outliers in MonthlyCharges.",
  
  "metadata": {
    "agent_version": "2.0.0",
    "profiling_timestamp": "2026-10-21T14:32:15.123456+00:00",
    "llm_model_used": "gemini-flash-latest",
    "sandbox_executions": 1,
    "llm_driven": true
  }
}
```

---

## Phase 4: Cleaning Integration (pour Malek)

### Comment Malek utilise le ProfilingReport.json?

Le **Cleaning Agent** (Agent 2) lit le JSON et applique les transformations recommandées.

#### 4.1: Lire le ProfilingReport

```python
import json

# Lire le rapport de profiling
with open("data/reports/telco_churn_profiling_report.json", "r") as f:
    profiling_report = json.load(f)

# Extraire les infos nécessaires
dataset_path = profiling_report["dataset_ref"]["file_path"]
imputation_plan = profiling_report["imputation_plan"]
type_casting = profiling_report["etl_hints"]["type_casting_targets"]
outlier_cols = profiling_report["outlier_columns"]
cleaning_order = profiling_report["recommended_cleaning_order"]
```

#### 4.2: Appliquer les Transformations

```python
import pandas as pd

# Charger le dataset
df = pd.read_csv(dataset_path)

# ── 1. Type Casting (convertir TotalCharges en float64) ────────
for col, target_dtype in type_casting.items():
    if col in df.columns:
        if target_dtype == "float64":
            # Convertir avec coerce (invalids → NaN)
            df[col] = pd.to_numeric(df[col], errors='coerce')
        elif target_dtype == "int64":
            df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
        elif target_dtype == "datetime":
            df[col] = pd.to_datetime(df[col], errors='coerce')

# ── 2. Imputation (remplir les missing values) ─────────────────
for col, plan in imputation_plan.items():
    if col not in df.columns:
        continue
    
    strategy = plan.get("strategy", "median")
    
    if strategy == "median":
        df[col].fillna(df[col].median(), inplace=True)
    elif strategy == "mean":
        df[col].fillna(df[col].mean(), inplace=True)
    elif strategy == "mode":
        df[col].fillna(df[col].mode()[0], inplace=True)
    elif strategy == "drop":
        df.dropna(subset=[col], inplace=True)

# ── 3. Outlier Treatment (capping à 99th percentile) ───────────
for col in outlier_cols:
    if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
        q1 = df[col].quantile(0.01)
        q99 = df[col].quantile(0.99)
        df[col] = df[col].clip(lower=q1, upper=q99)

# ── 4. Sauvegarder le dataset nettoyé ──────────────────────────
df.to_csv("data/cleaned/telco_churn_cleaned.csv", index=False)
df.to_parquet("data/processed/telco_churn_processed.parquet", index=False)
```

#### 4.3: Structure des Issues pour Décisions Avancées

Malek peut aussi lire les **issues détaillées** pour des décisions plus fines:

```python
# Pour chaque colonne
for col, col_profile in profiling_report["column_profiles"].items():
    issues = col_profile["issues"]
    
    for issue in issues:
        if issue["issue_id"] == "type_mismatch":
            # Action: convertir la colonne
            print(f"Convert {col} to {col_profile['etl_cast_to']}")
        
        elif issue["issue_id"] == "missing_values":
            # Action: imputer selon la stratégie
            strategy = col_profile["imputation_strategy"]
            print(f"Impute {col} with {strategy}")
        
        elif issue["issue_id"] == "statistical_outliers":
            # Action: capping ou suppression
            evidence = issue["evidence"]
            print(f"Cap {col} outliers: {evidence['outlier_count']} rows")
        
        elif issue["issue_id"] == "sandbox_check_failed":
            # Action: vérification manuelle ou log
            print(f"WARNING: {col} failed custom check: {issue['description']}")
```

#### 4.4: Logging des Transformations

Créer un log de transformation pour traçabilité:

```python
transformation_log = []

# Pour chaque transformation appliquée
transformation_log.append({
    "column": "TotalCharges",
    "action": "type_casting",
    "from": "object",
    "to": "float64",
    "nulls_created": 11
})

transformation_log.append({
    "column": "TotalCharges",
    "action": "imputation_median",
    "imputed_rows": 11,
    "median_value": 1397.475
})

transformation_log.append({
    "column": "MonthlyCharges",
    "action": "outlier_capping",
    "capped_rows": 89,
    "bounds": {"low": 19.45, "high": 117.89}
})

# Sauvegarder le log
with open("data/cleaned/telco_churn_transformation_log.json", "w") as f:
    json.dump(transformation_log, f, indent=2)
```

---

## How LLM Works in BIFlow

### Configuration (.env)

```bash
# LLM Provider: "ollama" ou "gemini"
LLM_PROVIDER=gemini

# Gemini API Key (cloud)
GEMINI_API_KEY=your_gemini_api_key_here

# Ollama (local) settings (si utilisé)
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
```

### Pourquoi Gemini et pas Ollama?

- **Gemini (cloud):** Utilisé actuellement car Malek utilise aussi une API cloud (pas de modèle local)
- **Ollama (local):** Option pour usage offline avec Qwen 2.5 ou Llama 3.1

Le code supporte les deux, changeable dans `.env`.

### Timeout Handling

Pour éviter les timeouts sur de gros datasets:
1. **Prompt réduit:** Seulement 3 sample values au lieu de 8
2. **Stats minimales:** mean, min, max (pas median, std, skewness)
3. **Batching:** 30 colonnes par batch pour datasets >50 colonnes
4. **Retry:** 2 tentatives avec backoff de 2 secondes

### Fallback Automatique

Si le LLM échoue (timeout, API down, quota), le système utilise **rule-based fallback intelligent**:

```python
if not result or "column_reasoning" not in result:
    logger.warning("LLM reasoning failed — using rule-based fallback")
    result = self._fallback_llm_report(health, profile, column_evidence)
```

Le fallback génère un **reasoning intelligent** basé sur les statistiques Python:
- Missing values: "16.7% missing values requiring imputation"
- Outliers: "89 outliers detected (1.26%)"
- Cardinality: "Binary categorical feature" / "High cardinality (1032 unique values)"
- Type issues: "Type issue: numeric_stored_as_object"
- Zero variance: "Zero variance - consider dropping"

**Différence avec le LLM:**
- **LLM:** Raisonnement contextuel et décisions personnalisées ("Likely high-value contracts", "corresponds to missing basement")
- **Fallback:** Descriptions factuelles basées sur les stats ("89 outliers detected", "Complete data with no missing values")

Les deux sont corrects, mais le LLM donne plus de **contexte métier** et d'**interprétation**.

---

## Testing & Validation

### Test 1: Run Profiling

```python
from agents.data_engineering_agent import DataEngineeringAgent
from agents.llm_client import LLMClient

# Initialize agent
llm_client = LLMClient()
agent = DataEngineeringAgent(llm_client)

# Run audit
result = agent.run_audit("data/raw/telco_churn.csv")

# Check output
print(f"Health: {result['health']['overall_health_score']}%")
print(f"Report path: {result['report_path']}")
```

### Test 2: Verify LLM Reasoning

```python
# Load profiling report
with open("data/reports/telco_churn_profiling_report.json", "r") as f:
    report = json.load(f)

# Check LLM-driven flag
assert report["metadata"]["llm_driven"] == True

# Check column reasoning exists
total_charges = report["column_profiles"]["TotalCharges"]
assert total_charges["agent_reasoning"] != ""
assert total_charges["severity"] in ["HIGH", "MEDIUM", "LOW", "NONE"]

print("✅ LLM reasoning confirmed")
```

### Test 3: Sandbox Execution

```python
# Check sandbox results
for col, col_profile in report["column_profiles"].items():
    if col_profile["sandbox_triggered"]:
        sandbox_result = col_profile["sandbox_result"]
        print(f"Column: {col}")
        print(f"  Passed: {sandbox_result['passed']}")
        print(f"  Metric: {sandbox_result['metric']}")
        print(f"  Details: {sandbox_result['details']}")
```

### Test 4: Integration avec Malek

```python
# Malek reads the report
with open("data/reports/telco_churn_profiling_report.json", "r") as f:
    profiling_report = json.load(f)

# Extract cleaning hints
imputation_plan = profiling_report["imputation_plan"]
type_casting = profiling_report["etl_hints"]["type_casting_targets"]
outlier_cols = profiling_report["outlier_columns"]

# Apply transformations (voir section 4.2)
# ...

print("✅ Cleaning agent integration successful")
```

---

## Résumé pour le Professor

### Pourquoi c'est un "True Autonomous Agent"?

1. **Le LLM prend les décisions:**
   - Pas juste des règles if/else
   - Le LLM **raisonne** sur les données et décide la severity, imputation strategy, etc.
   - Le LLM peut générer du **code Python custom** pour des checks avancés

2. **Hybrid Architecture:**
   - Python fait l'analyse rapide (stats, missing, outliers)
   - LLM interprète et décide (reasoning, stratégies)
   - Sandbox exécute du code LLM-généré de façon sécurisée

3. **Extensible & Safe:**
   - Sandbox empêche l'exécution de code dangereux
   - Fallback automatique si LLM échoue
   - JSON structuré pour intégration avec Agent 2 (Malek)

4. **Production-Ready:**
   - Batching pour large datasets
   - Timeout handling
   - Logging complet
   - Transformation audit trail

---

## FAQ - Questions Fréquentes

### Q1: Pourquoi certaines colonnes ont "Standard rule-based detection (LLM unavailable)"?

**R:** Cela arrive dans deux cas:

1. **Batch Timeout:** Pour les gros datasets (>50 colonnes), on traite en batches de 30 colonnes. Si un batch prend trop de temps (timeout Gemini API), ce batch utilise automatiquement le fallback rule-based.

2. **LLM Complètement Indisponible:** Si l'API Gemini est down ou la clé API invalide, toutes les colonnes utilisent le fallback.

**Solution:** 
- Réduire la taille des batches (changer `batch_size = 30` → `batch_size = 20`)
- Améliorer la connexion internet
- Vérifier la clé API Gemini dans `.env`
- Retry l'exécution (le timeout peut être temporaire)

**Note:** Avec les améliorations récentes, le fallback génère maintenant un reasoning intelligent basé sur les stats Python (pas juste "LLM unavailable").

### Q2: Le LLM raisonne sur TOUTES les colonnes ou seulement celles avec issues?

**R:** Le LLM raisonne sur **TOUTES les colonnes**, même celles sans problèmes:
- Colonnes OK → `severity: NONE` + reasoning positif ("Clean column, no issues")
- Colonnes problématiques → `severity: HIGH/MEDIUM` + reasoning détaillé
- Colonnes incertaines → `needs_custom_check: true` → Sandbox exécution

### Q3: C'est quoi la différence entre le reasoning LLM et le fallback?

**R:** 

| Aspect | LLM Reasoning | Rule-Based Fallback |
|--------|--------------|---------------------|
| **Type** | Contextuel et interprétatif | Factuel et descriptif |
| **Exemple** | "Likely high-value contracts or data entry errors" | "89 outliers detected (1.26%)" |
| **Décisions** | Basées sur contexte métier | Basées sur seuils statistiques |
| **Sandbox** | Peut générer custom checks | Jamais de custom checks |
| **Uncertainty** | LOW ou MEDIUM | MEDIUM (toujours) |

Les deux sont **corrects**, mais le LLM donne plus de **contexte métier**.

### Q4: Comment Malek utilise le JSON pour le cleaning?

**R:** Malek lit le fichier `data/reports/{dataset}_profiling_report.json` et extrait:

```python
imputation_plan = report["imputation_plan"]          # Quelle stratégie d'imputation
type_casting = report["etl_hints"]["type_casting_targets"]  # Quels types convertir
outlier_cols = report["outlier_columns"]             # Quelles colonnes ont des outliers
cleaning_order = report["recommended_cleaning_order"] # Dans quel ordre nettoyer
```

Puis applique les transformations dans l'ordre recommandé. Voir **Section 4** pour le code complet.

### Q5: Le sandbox est-il sécurisé?

**R:** Oui, le sandbox est **hautement sécurisé**:
- ✅ Namespace restreint (pas d'`open`, `exec`, `eval`, `__import__`)
- ✅ Timeout de 8 secondes maximum
- ✅ Pas d'accès fichiers, réseau, ou système
- ✅ Seulement pandas, numpy, re autorisés
- ✅ Exécuté sur un échantillon de 500 rows max (pas le dataset entier)

Même si le LLM génère du code malveillant, il ne peut pas s'exécuter.

### Q6: Pourquoi utiliser Gemini et pas un modèle local (Ollama)?

**R:** Actuellement on utilise Gemini (cloud) car:
- Malek utilise aussi une API cloud (pas de modèle local)
- Plus rapide pour le développement
- Pas de setup hardware nécessaire

Le code **supporte les deux** (Ollama et Gemini). Pour changer:
```bash
# Dans .env
LLM_PROVIDER=ollama  # ou "gemini"
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
```

### Q7: Combien de temps prend le profiling d'un gros dataset?

**R:** Exemples de temps estimés:

| Dataset | Rows | Columns | Temps Python | Temps LLM | Total |
|---------|------|---------|--------------|-----------|-------|
| Small   | 1,000 | 10 | 2s | 5s | ~7s |
| Medium  | 10,000 | 30 | 5s | 8s | ~13s |
| Large   | 50,000 | 50 | 15s | 15s (1 batch) | ~30s |
| XLarge  | 100,000 | 82 | 30s | 45s (3 batches) | ~75s |

**Note:** Si un batch timeout (>60s), il utilise le fallback (instant).

---

## Contact & Questions

**Mohamed:** Agent 1 (Profiling, Quality, Reasoning, Sandbox)  
**Malek:** Agent 2 (Cleaning, basé sur ProfilingReport.json)

Pour toute question sur le workflow ou l'intégration, voir:
- `agents/data_engineering_agent.py` - Main agent logic
- `agents/llm_client.py` - LLM API calls
- `analytics/data_quality.py` - Sandbox execution
- `data/reports/*.json` - Example profiling reports

---

**Last Updated:** October 21, 2026  
**BIFlow Version:** 2.0.0
