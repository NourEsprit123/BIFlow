
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
