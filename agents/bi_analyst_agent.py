import os
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
from groq import Groq

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

class BIAnalystAgent:
    def __init__(self, model_name: str = "openai/gpt-oss-120b"):
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("La clé GROQ_API_KEY n'a pas été trouvée dans l'environnement !")
        self.client = Groq(api_key=api_key)
        self.model_name = model_name

    def analyze(self, df: pd.DataFrame) -> str:
        shape = df.shape
        dtypes = df.dtypes.astype(str).to_dict()
        missing_values = df.isnull().sum().to_dict()
        stats_summary = df.describe(include='all').to_dict()
        sample_data = df.head(5).to_dict(orient='records')

        prompt = f"""
        Tu es l'Agent BI Analyst principal de la plateforme BIFlow. 
        Ton rôle est d'analyser dynamiquement un jeu de données de {shape[0]} lignes et {shape[1]} colonnes.

        Caractéristiques techniques :
        - Types de colonnes : {dtypes}
        - Valeurs manquantes : {missing_values}
        - Résumé statistique : {stats_summary}
        - Échantillon (5 lignes) : {sample_data}

        ### MISSION :
        1. Rédige un rapport complet en Markdown comprenant : Résumé Exécutif, KPIs Clés, Tendances, Anomalies et Recommandations Stratégiques.
        2. **Détermine exactement 4 KPIs métiers clés** adaptés spécifiquement au domaine de ce dataset (ex: taux moyen, somme, maximum, indicateur spécifique au métier). Donne pour chaque KPI un titre, une valeur calculée à partir des statistiques fournies, et un sous-titre explicatif.
        3. **Décide de 4 à 6 graphiques pertinents** à afficher (types: "pie", "bar", "histogram", "box").
        
        À la toute fin de ta réponse, tu DOIS inclure un bloc JSON valide entouré de balises markdown ```json ... ``` respectant strictement cette structure :
        ```json
        {{
          "kpis": [
            {{"title": "Titre du KPI 1", "value": "Valeur", "subtitle": "Contexte"}},
            {{"title": "Titre du KPI 2", "value": "Valeur", "subtitle": "Contexte"}},
            {{"title": "Titre du KPI 3", "value": "Valeur", "subtitle": "Contexte"}},
            {{"title": "Titre du KPI 4", "value": "Valeur", "subtitle": "Contexte"}}
          ],
          "recommended_charts": [
            {{
              "title": "Titre explicite du graphique",
              "type": "bar",
              "column_x": "nom_exact_de_la_colonne",
              "column_y": "nom_de_la_colonne_numerique_si_besoin_sinon_null"
            }}
          ]
        }}
        ```
        Sois précis, professionnel et réponds en français.
        """

        response = self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Tu es un agent d'intelligence artificielle expert en Business Intelligence."},
                {"role": "user", "content": prompt}
            ],
            model=self.model_name,
            temperature=0.2
        )
        
        return response.choices[0].message.content