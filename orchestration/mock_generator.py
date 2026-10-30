"""
orchestration/mock_generator.py — BIFlow Mock Data Generator
=============================================================
Génère des données fictives (datasets et outputs d'agents) pour tester
le pipeline en sandbox isolée sans dépendre de vrais fichiers ou LLMs.

Aucune clé API, aucun identifiant réel, aucune donnée sensible n'est
jamais générée ou écrite par ce module.

Fonctions publiques :
    generate_mock_dataset(...)          → pd.DataFrame + chemin CSV sauvegardé
    generate_mock_agent1_output(...)    → DataEngineerOutput (pydantic)
    generate_mock_agent2_output(...)    → BIAnalystOutput (pydantic)
    generate_mock_agent3_output(...)    → XAIAuditorOutput (pydantic)
    generate_mock_state_for_agent(...)  → GraphState prêt à injecter dans LangGraph

Usage rapide :
    from orchestration.mock_generator import MockGenerator
    gen = MockGenerator(seed=42)
    path, df = gen.save_mock_dataset()
    state = gen.make_state_for_agent("bi_analyst")
    app.invoke(state, {"configurable": {"thread_id": "mock_001"}})
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import string
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import numpy as np
import pandas as pd

from orchestration.schemas import (
    BIAnalystOutput,
    ChartSpec,
    DataEngineerOutput,
    ColumnQuality,
    IntegrityHashes,
    KPICard,
    SHAPFeatureEntry,
    SHAPSummary,
    XAIAuditorOutput,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Répertoire de sortie des mocks — sous /tmp pour ne jamais polluer data/raw/
MOCK_OUTPUT_DIR = Path(tempfile.gettempdir()) / "biflow_mocks"

# ---------------------------------------------------------------------------
# Domaines de datasets disponibles
# ---------------------------------------------------------------------------

DOMAIN_CONFIGS: Dict[str, Dict[str, Any]] = {
    "retail": {
        "label": "Ventes Retail",
        "numeric_cols": {
            "Prix_Unitaire":    (5.0,  500.0),
            "Quantite":         (1.0,   50.0),
            "Total_Vente":      (5.0, 25000.0),
            "Remise_Pct":       (0.0,   30.0),
            "Score_Client":     (1.0,   10.0),
        },
        "cat_cols": {
            "Categorie":  ["Electronique", "Vêtements", "Alimentation", "Maison", "Sport"],
            "Region":     ["Nord", "Sud", "Est", "Ouest", "Centre"],
            "Statut":     ["Confirmé", "Annulé", "En attente", "Retourné"],
            "Canal":      ["En ligne", "Magasin", "Téléphone", "Application"],
        },
        "target": "Statut",
    },
    "telecom": {
        "label": "Churn Télécom",
        "numeric_cols": {
            "Anciennete_Mois":      (1.0,  72.0),
            "Charges_Mensuelles":   (20.0, 120.0),
            "Charges_Totales":      (20.0, 8000.0),
            "Nb_Services":          (1.0,   8.0),
            "Score_Satisfaction":   (1.0,  10.0),
        },
        "cat_cols": {
            "Type_Contrat":  ["Mensuel", "Annuel", "Biennal"],
            "Methode_Paiement": ["Chèque", "Virement", "Carte", "Prélèvement"],
            "Acces_Internet": ["DSL", "Fibre", "Non"],
            "Churn": ["Oui", "Non"],
        },
        "target": "Churn",
    },
    "finance": {
        "label": "Risque Financier",
        "numeric_cols": {
            "Montant_Credit":    (1000.0, 50000.0),
            "Revenu_Annuel":     (15000.0, 120000.0),
            "Ratio_Endettement": (0.05, 0.80),
            "Score_Credit":      (300.0, 850.0),
            "Age":               (18.0, 75.0),
        },
        "cat_cols": {
            "Type_Emploi":   ["CDI", "CDD", "Indépendant", "Retraité", "Étudiant"],
            "Type_Logement": ["Propriétaire", "Locataire", "Hébergé"],
            "Statut_Marital":["Célibataire", "Marié", "Divorcé", "Veuf"],
            "Risque":        ["Faible", "Moyen", "Élevé"],
        },
        "target": "Risque",
    },
}


# =============================================================================
# Classe principale
# =============================================================================

class MockGenerator:
    """
    Générateur de données fictives pour les tests BIFlow.

    Paramètres :
        seed   : graine pour la reproductibilité
        domain : domaine métier ("retail" | "telecom" | "finance")
        n_rows : nombre de lignes du DataFrame généré
    """

    def __init__(
        self,
        seed: int = 42,
        domain: str = "telecom",
        n_rows: int = 300,
    ):
        self.seed   = seed
        self.domain = domain if domain in DOMAIN_CONFIGS else "telecom"
        self.n_rows = n_rows
        self._rng   = np.random.default_rng(seed)
        random.seed(seed)
        np.random.seed(seed)
        self._config = DOMAIN_CONFIGS[self.domain]

    # -------------------------------------------------------------------------
    # 1. Génération du DataFrame fictif
    # -------------------------------------------------------------------------

    def generate_dataframe(self, add_noise: bool = False) -> pd.DataFrame:
        """
        Génère un DataFrame Pandas propre avec colonnes numériques et catégorielles.

        Paramètres :
            add_noise : si True, injecte ~5% de NaN et quelques valeurs aberrantes
                        pour simuler un dataset réel imparfait.

        Retourne un DataFrame prêt à l'emploi (aucune valeur sensible).
        """
        n = self.n_rows
        cfg = self._config

        data: Dict[str, Any] = {}

        # Colonnes numériques
        for col, (lo, hi) in cfg["numeric_cols"].items():
            vals = self._rng.uniform(lo, hi, size=n).round(2)
            if add_noise:
                # ~5% de NaN
                mask = self._rng.random(n) < 0.05
                vals = vals.astype(float)
                vals[mask] = np.nan
            data[col] = vals

        # Colonnes catégorielles
        for col, categories in cfg["cat_cols"].items():
            data[col] = self._rng.choice(categories, size=n)

        # Colonne de date fictive
        start_date = datetime(2022, 1, 1)
        data["Date"] = [
            (start_date + timedelta(days=int(d))).strftime("%Y-%m-%d")
            for d in self._rng.integers(0, 730, size=n)
        ]

        # ID fictif (non-sensible)
        data["ID"] = [f"MOCK-{i:05d}" for i in range(1, n + 1)]

        return pd.DataFrame(data)

    def save_mock_dataset(
        self,
        output_dir: Optional[str] = None,
        filename: Optional[str] = None,
        add_noise: bool = False,
    ) -> Tuple[str, pd.DataFrame]:
        """
        Génère et sauvegarde un DataFrame fictif en CSV.

        Retourne (chemin_absolu, dataframe).
        Le fichier est écrit dans /tmp/biflow_mocks/ par défaut.
        """
        df = self.generate_dataframe(add_noise=add_noise)

        out_dir = Path(output_dir) if output_dir else MOCK_OUTPUT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)

        fname = filename or f"mock_{self.domain}_{self.n_rows}rows_seed{self.seed}.csv"
        out_path = out_dir / fname
        df.to_csv(out_path, index=False)

        return str(out_path), df

    # -------------------------------------------------------------------------
    # 2. Mock output — Agent 1
    # -------------------------------------------------------------------------

    def generate_agent1_output(
        self,
        data_path: Optional[str] = None,
        df: Optional[pd.DataFrame] = None,
    ) -> DataEngineerOutput:
        """
        Génère un output fictif de l'Agent 1 (DataEngineerOutput).

        Si data_path est fourni, sauvegarde un CSV fictif à cet emplacement.
        Sinon, utilise un chemin temporaire.
        """
        if df is None:
            data_path, df = self.save_mock_dataset()
        elif data_path is None:
            data_path, df = self.save_mock_dataset()

        # Hash SHA-256 du contenu CSV
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        data_hash = hashlib.sha256(csv_bytes).hexdigest()

        # Qualité par colonne
        col_quality = []
        for col in df.columns:
            missing = int(df[col].isna().sum())
            col_quality.append(ColumnQuality(
                name=col,
                dtype=str(df[col].dtype),
                missing_count=missing,
                missing_pct=round(missing / len(df) * 100, 2),
                unique_count=int(df[col].nunique()),
                flagged=missing > len(df) * 0.1,
                flag_reason="Taux de valeurs manquantes > 10%" if missing > len(df) * 0.1 else None,
            ))

        health_score = round(
            100.0 * (1 - df.isna().sum().sum() / max(df.size, 1)), 1
        )

        return DataEngineerOutput(
            cleaned_dataset_path=str(data_path),
            row_count=len(df),
            col_count=len(df.columns),
            data_hash=data_hash,
            overall_health_score=health_score,
            column_quality=col_quality,
            profiling_report={
                "agent_summary": (
                    f"Dataset mock '{self.domain}' analysé. "
                    f"{len(df):,} lignes, {len(df.columns)} colonnes. "
                    f"Score de santé : {health_score}%."
                ),
                "etl_hints": {
                    "type_casting_targets": {},
                    "columns_to_drop": [],
                },
                "cross_column_issues": [],
            },
        )

    # -------------------------------------------------------------------------
    # 3. Mock output — Agent 2
    # -------------------------------------------------------------------------

    def generate_agent2_output(self, df: Optional[pd.DataFrame] = None) -> BIAnalystOutput:
        """
        Génère un output fictif de l'Agent 2 (BIAnalystOutput).

        Les KPIs sont calculés de manière déterministe à partir du DataFrame
        (ou d'un DataFrame fictif si df est None) — aucun LLM n'est appelé.
        """
        if df is None:
            _, df = self.save_mock_dataset()

        cfg  = self._config
        num_cols = list(cfg["numeric_cols"].keys())
        cat_cols = list(cfg["cat_cols"].keys())

        # KPIs calculés
        kpis = []
        if num_cols:
            primary = num_cols[0]
            kpis.append(KPICard(
                title=f"Total {primary}",
                value=f"{df[primary].sum():,.2f}" if primary in df.columns else "N/A",
                subtitle="Somme globale",
            ))
            kpis.append(KPICard(
                title=f"Moyenne {primary}",
                value=f"{df[primary].mean():,.2f}" if primary in df.columns else "N/A",
                subtitle="Valeur centrale",
            ))
        if len(num_cols) > 1:
            secondary = num_cols[1]
            kpis.append(KPICard(
                title=f"Médiane {secondary}",
                value=f"{df[secondary].median():,.2f}" if secondary in df.columns else "N/A",
                subtitle="Distribution centrale",
            ))
        if cat_cols and cat_cols[0] in df.columns:
            top_cat = df[cat_cols[0]].value_counts().index[0]
            kpis.append(KPICard(
                title=f"Dominant {cat_cols[0]}",
                value=str(top_cat),
                subtitle=f"{df[cat_cols[0]].value_counts().iloc[0]} occurrences",
            ))

        # Graphiques recommandés
        charts = []
        if cat_cols and cat_cols[0] in df.columns:
            charts.append(ChartSpec(
                title=f"Distribution de {cat_cols[0]}",
                type="pie",
                column_x=cat_cols[0],
            ))
        if num_cols and num_cols[0] in df.columns:
            charts.append(ChartSpec(
                title=f"Distribution de {num_cols[0]}",
                type="histogram",
                column_x=num_cols[0],
            ))
        if len(num_cols) >= 2 and num_cols[0] in df.columns and num_cols[1] in df.columns:
            charts.append(ChartSpec(
                title=f"{num_cols[0]} vs {num_cols[1]}",
                type="scatter",
                column_x=num_cols[0],
                column_y=num_cols[1],
            ))

        # Rapport narratif fictif (aucun LLM)
        domain_label = cfg["label"]
        summary = (
            f"## 📊 Analyse BI — {domain_label} (Mock)\n\n"
            f"**Jeu de données :** {self.n_rows:,} observations · "
            f"{len(df.columns)} variables\n\n"
            f"### Résumé exécutif\n"
            f"Ce rapport a été généré par le générateur de données mock BIFlow "
            f"pour le domaine **{domain_label}**. "
            f"Les métriques ci-dessous sont calculées de manière déterministe "
            f"à partir des données synthétiques — aucun LLM n'a été utilisé.\n\n"
            f"### KPIs principaux\n"
            + "\n".join(f"- **{k.title}** : {k.value} ({k.subtitle})" for k in kpis)
            + f"\n\n### Recommandations\n"
            f"1. Valider les distributions observées contre les benchmarks sectoriels.\n"
            f"2. Explorer les corrélations inter-colonnes pour identifier des leviers d'action.\n"
            f"3. Segmenter par `{cat_cols[0] if cat_cols else 'catégorie'}` pour une analyse plus fine.\n"
        )

        return BIAnalystOutput(
            summary_markdown=summary,
            kpis=kpis,
            charts_data=charts,
            provider="📊 Mock Generator (deterministic)",
            model_used="no-llm",
            is_llm=False,
            duration_s=0.0,
        )

    # -------------------------------------------------------------------------
    # 4. Mock output — Agent 3
    # -------------------------------------------------------------------------

    def generate_agent3_output(
        self,
        df: Optional[pd.DataFrame] = None,
        n_features: int = 10,
    ) -> XAIAuditorOutput:
        """
        Génère un output fictif de l'Agent 3 (XAIAuditorOutput).

        Les attributions SHAP sont simulées avec des valeurs aléatoires
        reproductibles. Aucun modèle ML ni LLM n'est entraîné ou appelé.
        """
        if df is None:
            _, df = self.save_mock_dataset()

        cfg = self._config
        num_cols = list(cfg["numeric_cols"].keys())
        all_feature_names = [c for c in df.columns if c != cfg["target"]]
        selected = all_feature_names[:n_features]

        # Attributions SHAP fictives
        shap_vals = sorted(
            self._rng.uniform(0.001, 0.15, size=len(selected)).tolist(),
            reverse=True,
        )
        top_features = [
            SHAPFeatureEntry(
                rank=i + 1,
                feature=f,
                mean_abs_shap=round(float(v), 6),
                direction_sample_0="positive" if i % 2 == 0 else "negative",
            )
            for i, (f, v) in enumerate(zip(selected, shap_vals))
        ]

        # Hashes SHA-256 fictifs (64 chars hexadécimaux valides)
        def _fake_hash(seed_str: str) -> str:
            return hashlib.sha256(seed_str.encode()).hexdigest()

        csv_bytes = df.to_csv(index=False).encode("utf-8")
        data_hash = hashlib.sha256(csv_bytes).hexdigest()
        pred_hash = _fake_hash(f"predictions_{self.seed}")
        audit_hash = _fake_hash(f"audit_{data_hash}_{pred_hash}")

        # Distribution des prédictions fictive
        pred_dist = {
            "0": {"count": int(self.n_rows * 0.73), "pct": 73.0},
            "1": {"count": int(self.n_rows * 0.27), "pct": 27.0},
        }

        narrative = (
            "**[Explication mock — aucun LLM utilisé]**\n\n"
            f"Les {len(selected)} features les plus influentes pour la variable cible "
            f"`{cfg['target']}` ont été identifiées par simulation SHAP.\n\n"
            f"**Feature dominante :** `{selected[0]}` "
            f"(mean |SHAP| = {shap_vals[0]:.4f})\n\n"
            "Cette explication est générée de manière déterministe par le "
            "Mock Generator BIFlow — elle sert uniquement aux tests en sandbox isolée."
        )

        return XAIAuditorOutput(
            shap_summary=SHAPSummary(
                explainer_type="MockExplainer",
                n_samples=self.n_rows,
                n_features=len(selected),
                top_features=top_features,
                global_mean_abs_shap=round(float(np.mean(shap_vals)), 6),
            ),
            integrity_hashes=IntegrityHashes(
                data_hash=data_hash,
                predictions_hash=pred_hash,
                audit_hash=audit_hash,
            ),
            narrative_explanation=narrative,
            compliance_status="PARTIAL",    # mock → toujours PARTIAL (pas de vrai LLM)
            predictions_distribution=pred_dist,
            provider="📊 Mock Generator (deterministic)",
            engine_used="mock",
            is_llm=False,
            duration_s=0.0,
            dataset_name=f"mock_{self.domain}",
            n_samples=self.n_rows,
            n_features=len(selected),
        )

    # -------------------------------------------------------------------------
    # 5. GraphState prêt à injecter dans LangGraph
    # -------------------------------------------------------------------------

    def make_state_for_agent(
        self,
        target_agent: Literal["bi_analyst", "xai_auditor"],
        execution_mode: str = "auto",
        resource_mode: str = "auto",
        sandbox_mode: str = "inprocess",
    ) -> Dict[str, Any]:
        """
        Génère un GraphState complet pré-rempli avec des mocks pour démarrer
        directement à l'Agent 2 ou l'Agent 3 sans exécuter les étapes précédentes.

        Paramètres :
            target_agent    : "bi_analyst" ou "xai_auditor"
            execution_mode  : "direct_agent_2" ou "direct_agent_3" (déduit si non fourni)
            resource_mode   : "local" | "cloud" | "auto"
            sandbox_mode    : "inprocess" | "docker"

        Retourne un dict compatible GraphState.
        """
        if target_agent == "bi_analyst":
            execution_mode = "direct_agent_2"
        elif target_agent == "xai_auditor":
            execution_mode = "direct_agent_3"

        data_path, df = self.save_mock_dataset()

        # Préparer les reports mock pour les agents en amont
        reports: Dict[str, Any] = {}

        if target_agent == "xai_auditor":
            # On a besoin du mock A1 et A2 dans les reports
            a1_out  = self.generate_agent1_output(data_path=data_path, df=df)
            a2_out  = self.generate_agent2_output(df=df)
            reports["data_engineer"] = a1_out.to_graph_state_dict()
            reports["bi_analyst"]    = a2_out.to_graph_state_dict()
            bi_markdown = a2_out.summary_markdown
        else:
            # Pour A2, seul A1 est nécessaire en amont
            a1_out = self.generate_agent1_output(data_path=data_path, df=df)
            reports["data_engineer"] = a1_out.to_graph_state_dict()
            bi_markdown = ""

        # Construire le GraphState
        from orchestration.graph import GraphState
        state = GraphState(
            data_path           = data_path,
            cleaned_data_path   = data_path,
            execution_mode      = execution_mode,       # type: ignore[arg-type]
            sandbox_mode        = sandbox_mode,         # type: ignore[arg-type]
            resource_mode       = resource_mode,        # type: ignore[arg-type]
            current_step        = "start",
            user_approval       = "approved",
            retry_count         = {},
            reports             = reports,
            history_logs        = [],
            error_message       = "",
            bi_report_markdown  = bi_markdown,
            bi_chart_config     = {},
        )
        return state


# =============================================================================
# Fonctions module-level (API fonctionnelle alternative à la classe)
# =============================================================================

def generate_mock_dataset(
    domain: str = "telecom",
    n_rows: int = 300,
    seed: int = 42,
    add_noise: bool = False,
    output_dir: Optional[str] = None,
) -> Tuple[str, pd.DataFrame]:
    """Raccourci : génère et sauvegarde un dataset fictif."""
    return MockGenerator(seed=seed, domain=domain, n_rows=n_rows).save_mock_dataset(
        output_dir=output_dir, add_noise=add_noise
    )


def generate_mock_agent1_output(
    domain: str = "telecom",
    n_rows: int = 300,
    seed: int = 42,
) -> DataEngineerOutput:
    """Raccourci : génère un output fictif pour l'Agent 1."""
    return MockGenerator(seed=seed, domain=domain, n_rows=n_rows).generate_agent1_output()


def generate_mock_agent2_output(
    domain: str = "telecom",
    n_rows: int = 300,
    seed: int = 42,
) -> BIAnalystOutput:
    """Raccourci : génère un output fictif pour l'Agent 2."""
    return MockGenerator(seed=seed, domain=domain, n_rows=n_rows).generate_agent2_output()


def generate_mock_agent3_output(
    domain: str = "telecom",
    n_rows: int = 300,
    seed: int = 42,
) -> XAIAuditorOutput:
    """Raccourci : génère un output fictif pour l'Agent 3."""
    return MockGenerator(seed=seed, domain=domain, n_rows=n_rows).generate_agent3_output()
