<<<<<<< Updated upstream

import json
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google import genai

load_dotenv()

MODEL_NAME = "gemini-3.8-flash"


class DataEngineeringAgent:
    """
    Gemini interprète librement le dataset.
    Python fournit les faits calculés sur le fichier complet.
    """

    def __init__(self, model=None):
        self.model = model or os.getenv(
            "BIFLOW_MODEL", MODEL_NAME
        )

        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY est absent du fichier .env."
            )

        self.client = genai.Client(api_key=api_key)

    def load_dataset(self, path: Path) -> pd.DataFrame:
        """Charge le fichier localement avec pandas."""

        extension = path.suffix.lower()

        if extension == ".csv":
            return pd.read_csv(path, low_memory=False)

        if extension in {".xlsx", ".xls"}:
            return pd.read_excel(path)

        if extension == ".json":
            return pd.read_json(path)

        if extension == ".parquet":
            return pd.read_parquet(path)

        raise ValueError(
            f"Format non pris en charge : {extension}"
        )

    def build_factual_summary(
        self, df: pd.DataFrame
    ) -> dict:
        """
        Calcule des faits génériques.
        Ne décide pas du rôle métier des colonnes.
        """

        columns_summary = {}

        for column in df.columns:
            series = df[column]

            info = {
                "type_python": str(series.dtype),
                "valeurs_manquantes": int(
                    series.isna().sum()
                ),
                "valeurs_uniques": int(
                    series.nunique(dropna=True)
                ),
                "exemples": [
                    str(value)
                    for value in series.dropna().head(3)
                ],
            }

            # Signale les chaînes vides sans les confondre
            # avec les valeurs manquantes pandas.
            if (
                pd.api.types.is_object_dtype(series)
                or pd.api.types.is_string_dtype(series)
            ):
                info["chaines_vides_ou_espaces"] = int(
                    series.astype("string")
                    .str.strip()
                    .eq("")
                    .fillna(False)
                    .sum()
                )

                info["valeurs_frequentes"] = {
                    str(value): int(count)
                    for value, count
                    in series.value_counts().head(8).items()
                }

            if pd.api.types.is_numeric_dtype(series):
                values = series.dropna()

                if not values.empty:
                    info["statistiques_numeriques"] = {
                        "count": int(values.count()),
                        "min": float(values.min()),
                        "max": float(values.max()),
                        "mean": float(values.mean()),
                        "median": float(values.median()),
                        "q25": float(values.quantile(0.25)),
                        "q75": float(values.quantile(0.75)),
                    }

            columns_summary[str(column)] = info

        return {
            "nombre_exact_lignes": int(len(df)),
            "nombre_exact_colonnes": int(len(df.columns)),
            "noms_colonnes": [
                str(column) for column in df.columns
            ],
            "nombre_lignes_dupliquees": int(
                df.duplicated().sum()
            ),
            "colonnes": columns_summary,
        }

    def analyze(
        self,
        file_path: str,
        objective: str = "",
    ) -> dict:

        dataset = Path(file_path).resolve()

        if not dataset.is_file():
            raise FileNotFoundError(
                f"Dataset introuvable : {dataset}"
            )

        # 1. Python lit le fichier complet.
        df = self.load_dataset(dataset)

        if df.empty:
            raise ValueError("Le dataset est vide.")

        # 2. Python calcule les faits vérifiables.
        summary = self.build_factual_summary(df)

        print(
            f"[BIFlow] Lignes : {summary['nombre_exact_lignes']}"
        )
        print(
            f"[BIFlow] Colonnes : "
            f"{summary['nombre_exact_colonnes']}"
        )
        print("[BIFlow] Envoi du résumé factuel à Gemini...")

        # 3. Gemini interprète les faits sans rôles prédéfinis.
        prompt = f"""
Tu es le Data Engineering Agent de BIFlow.

OBJECTIF :
{objective or "Interpréter le dataset de manière exploratoire."}

Voici un résumé calculé localement par Python à partir
du dataset complet :

{json.dumps(summary, ensure_ascii=False, default=str)}

RÈGLES OBLIGATOIRES :

1. Les nombres de lignes et de colonnes fournis par Python
   sont les références exactes pour ce fichier.
2. Ne recalcule pas ces nombres à partir des exemples.
3. N'affirme pas qu'une statistique a été calculée si elle
   n'apparaît pas dans les résultats fournis.
4. N'invente aucun pourcentage, corrélation ou taux métier.
5. Tu dois interpréter toi-même les noms, types, valeurs
   fréquentes et statistiques disponibles.
6. Déduis les rôles possibles des colonnes à partir du contexte.
   Ne suppose pas que chaque dataset est un dataset de churn.
7. Distingue les faits calculés, les interprétations probables
   et les hypothèses à vérifier.
8. Une valeur unique n'est pas nécessairement un identifiant.
9. Une valeur extrême n'est pas nécessairement une erreur.
10. Propose des analyses complémentaires adaptées au domaine
    découvert, sans prétendre qu'elles ont déjà été réalisées.
11. Les statistiques numériques concernent le type réellement
    lu par pandas. Signale les limites de typage éventuelles.
12. N'invente pas le nombre de lignes analysées.

RÉDIGE EN FRANÇAIS UN RAPPORT STRUCTURÉ :

1. Vue d'ensemble et volumétrie.
2. Domaine probable du dataset et justification.
3. Interprétation des colonnes importantes.
4. Observations étayées par les informations fournies.
5. Problèmes potentiels de qualité et incertitudes.
6. Analyses complémentaires recommandées.
7. Conclusion.

N'affirme pas avoir inspecté individuellement chaque ligne
avec le LLM : tu disposes ici d'un résumé calculé sur le fichier.
"""

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
        )

        report = response.text

        if not report:
            raise RuntimeError(
                "Gemini n'a retourné aucun rapport."
            )

        result = {
            "status": "success",
            "model": self.model,
            "dataset": dataset.name,
            "objective": objective,
            "metadata": {
                "rows": summary["nombre_exact_lignes"],
                "columns": summary["nombre_exact_colonnes"],
            },
            "factual_summary": summary,
            "report": report,
        }

        output_dir = Path("reports")
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = (
            output_dir / "data_engineering_report.json"
        )

        output_path.write_text(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        print(f"[BIFlow] Rapport enregistré : {output_path}")

        return result


if __name__ == "__main__":
    agent = DataEngineeringAgent()

    result = agent.analyze(
        "data/raw/telco_churn.csv",
        objective=(
            "Comprendre le dataset, interpréter ses variables "
            "et proposer des pistes d'analyse pertinentes."
        ),
    )

    print("\n===== RAPPORT BIFlow =====\n")
    print(result["report"])
=======
import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import pandas as pd

from analytics.profiler import profile_dataset, load_dataset
from analytics.data_quality import calculate_health_scores
from analytics.etl import dataset_table_name, load_dataframe_to_postgres
from analytics.cleaning import (
    clean_dirty_numeric_series,
    impute_missing_values,
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

        # Keep the executable strategy aligned with the actions surfaced in Data Quality.
        recommended_numeric = {
            col for col, issue in health["type_issues"].items()
            if "waterfall cleaning" in issue.get("recommendation", "").lower()
        }
        recommended_dates = {
            col for col, issue in health["type_issues"].items()
            if "pd.to_datetime" in issue.get("recommendation", "")
        }
        recommended_booleans = {
            col for col, issue in health["type_issues"].items()
            if "map to bool dtype" in issue.get("recommendation", "").lower()
        }
        llm_strategy["numeric_waterfall_columns"] = sorted(recommended_numeric)
        llm_strategy["datetime_columns"] = sorted(recommended_dates)
        llm_strategy["boolean_columns"] = sorted(recommended_booleans)

        missing_columns = health["missing_info"]["columns"]
        requested_imputation = llm_strategy.get("imputation_plan", {})
        if not isinstance(requested_imputation, dict):
            requested_imputation = {}
        imputation_plan = {}
        for col in missing_columns:
            plan = requested_imputation.get(col, {})
            if not isinstance(plan, dict) or plan.get("strategy") not in {
                "median", "mean", "mode", "constant"
            }:
                default_strategy = "median" if pd.api.types.is_numeric_dtype(df[col]) else "mode"
                plan = {"strategy": default_strategy}
            elif col in recommended_dates and plan["strategy"] in {"median", "mean"}:
                plan = {"strategy": "mode"}
            elif plan["strategy"] == "constant":
                plan = {**plan, "value": plan.get("value", 0)}
            imputation_plan[col] = plan
        llm_strategy["imputation_plan"] = imputation_plan
        llm_strategy["synonym_mappings"] = {}
        llm_strategy["outlier_columns"] = list(health.get("outlier_info", {}).keys())

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
        health_before = calculate_health_scores(df_raw)

        if not strategy:
            audit_res = self.run_audit(file_path)
            strategy = audit_res["cleaning_strategy"]

        transformations_log = []

        # Apply only operations for columns with matching Data Quality findings.
        recommended_numeric = {
            col for col, issue in health_before["type_issues"].items()
            if "waterfall cleaning" in issue.get("recommendation", "").lower()
        }
        requested_numeric = strategy.get("numeric_waterfall_columns", [])
        waterfall_cols = (
            [col for col in requested_numeric if col in recommended_numeric]
            if isinstance(requested_numeric, list) else []
        )
        for col in waterfall_cols:
            before_nulls = int(df_clean[col].isna().sum())
            df_clean[col] = clean_dirty_numeric_series(df_clean[col], self.llm_client)
            after_nulls = int(df_clean[col].isna().sum())
            transformations_log.append({
                "column": col, "action": "numeric_waterfall_cleaning",
                "nulls_before": before_nulls, "nulls_after": after_nulls
            })

        recommended_dates = {
            col for col, issue in health_before["type_issues"].items()
            if "pd.to_datetime" in issue.get("recommendation", "")
        }
        requested_dates = strategy.get("datetime_columns", [])
        date_cols = (
            [col for col in requested_dates if col in recommended_dates]
            if isinstance(requested_dates, list) else []
        )
        for col in date_cols:
            df_clean[col] = pd.to_datetime(df_clean[col], errors="coerce")
            transformations_log.append({
                "column": col, "action": "datetime_conversion"
            })

        recommended_booleans = {
            col for col, issue in health_before["type_issues"].items()
            if "map to bool dtype" in issue.get("recommendation", "").lower()
        }
        requested_booleans = strategy.get("boolean_columns", [])
        boolean_cols = (
            [col for col in requested_booleans if col in recommended_booleans]
            if isinstance(requested_booleans, list) else []
        )
        bool_values = {
            "yes": True, "true": True, "y": True, "1": True, "oui": True,
            "no": False, "false": False, "n": False, "0": False, "non": False,
        }
        for col in boolean_cols:
            df_clean[col] = (
                df_clean[col].astype("string").str.strip().str.lower()
                .map(bool_values).astype("boolean")
            )
            transformations_log.append({
                "column": col, "action": "boolean_conversion"
            })

        # 2. Imputation
        recommended_missing = set(health_before["missing_info"]["columns"])
        requested_imputation = strategy.get("imputation_plan", {})
        impute_plan = {
            col: plan for col, plan in requested_imputation.items()
            if col in recommended_missing and isinstance(plan, dict)
        } if isinstance(requested_imputation, dict) else {}
        for col, plan in impute_plan.items():
            before_nulls = int(df_clean[col].isna().sum())
            transformations_log.append({
                "column": col, "action": f"imputation_{plan.get('strategy','median')}",
                "imputed_rows": before_nulls
            })
        df_clean = impute_missing_values(df_clean, impute_plan)

        # 3. Outlier treatment uses the IQR bounds shown in the Data Quality table.
        recommended_outliers = set(health_before.get("outlier_info", {}))
        requested_outliers = strategy.get("outlier_columns", [])
        outlier_cols = (
            [col for col in requested_outliers if col in recommended_outliers]
            if isinstance(requested_outliers, list) else []
        )
        if outlier_cols:
            for col in outlier_cols:
                info = health_before["outlier_info"][col]
                transformations_log.append({
                    "column": col, "action": "outlier_winsorizing",
                    "capped_at": {
                        "low": info["lower_bound"],
                        "high": info["upper_bound"]
                    }
                })
            df_clean = treat_outliers(
                df_clean,
                outlier_cols,
                method="cap",
                bounds=health_before["outlier_info"],
            )

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

        database_url = os.getenv("DATABASE_URL", "").strip()
        if database_url:
            database_load = load_dataframe_to_postgres(
                df_clean,
                database_url=database_url,
                table_name=dataset_table_name(file_path),
                schema=os.getenv("POSTGRES_SCHEMA", "analytics"),
            )
        else:
            database_load = {"status": "not_configured"}

        # Generate audit log JSON (spec §5.3)
        audit_log = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw_file": file_path,
            "cleaned_file": cleaned_path,
            "processed_file": processed_path,
            "database_load": database_load,
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
            "processed_file_path": processed_path,
            "database_load": database_load,
            "health_after": health_after
        }
>>>>>>> Stashed changes
