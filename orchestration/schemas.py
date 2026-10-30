"""
orchestration/schemas.py — BIFlow I/O Schemas
===============================================
Définit les contrats de données stricts (Pydantic v2) pour les inputs
et outputs des 3 agents du pipeline BIFlow.

Ces schémas servent à :
  - Valider les données produites par chaque agent avant de les passer au suivant.
  - Documenter clairement les interfaces inter-agents.
  - Alimenter le mock_generator pour les tests en sandbox isolée.
  - Garantir la compatibilité msgpack (types Python natifs uniquement).

Usage :
    from orchestration.schemas import (
        DataEngineerOutput, BIAnalystOutput, XAIAuditorOutput,
        validate_agent_output,
    )
    output = DataEngineerOutput(**result_dict)
    output.model_dump()  # → dict sérialisable
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# =============================================================================
# Sous-modèles partagés
# =============================================================================

class ColumnQuality(BaseModel):
    """Qualité d'une colonne individuelle — produit par l'Agent 1."""

    name: str
    dtype: str
    missing_count: int = Field(ge=0)
    missing_pct: float = Field(ge=0.0, le=100.0)
    unique_count: int = Field(ge=0)
    flagged: bool = False
    flag_reason: Optional[str] = None


class KPICard(BaseModel):
    """Un KPI métier — produit par l'Agent 2."""

    title: str
    value: str
    subtitle: str = ""


class ChartSpec(BaseModel):
    """Spécification d'un graphique recommandé — produit par l'Agent 2."""

    title: str
    type: Literal["bar", "pie", "histogram", "scatter", "box", "line"]
    column_x: str
    column_y: Optional[str] = None


class SHAPFeatureEntry(BaseModel):
    """Attribution SHAP pour une feature individuelle — produit par l'Agent 3."""

    rank: int = Field(ge=1)
    feature: str
    mean_abs_shap: float = Field(ge=0.0)
    direction_sample_0: Literal["positive", "negative"]


class IntegrityHashes(BaseModel):
    """Empreintes SHA-256 des artefacts d'audit — produit par l'Agent 3."""

    data_hash: str = Field(min_length=64, max_length=64)
    predictions_hash: str = Field(min_length=64, max_length=64)
    audit_hash: str = Field(min_length=64, max_length=64)


# =============================================================================
# Agent 1 — DataEngineerOutput
# =============================================================================

class DataEngineerOutput(BaseModel):
    """
    Output complet de l'Agent 1 (Data Engineering Agent).

    Produit par DataEngineeringAgent.run_audit() + execute_cleaning().
    Transmis directement dans GraphState["reports"]["data_engineer"].
    """

    # Chemin vers le dataset nettoyé
    cleaned_dataset_path: str = Field(
        ...,
        description="Chemin absolu vers le fichier CSV nettoyé prêt pour l'Agent 2.",
    )

    # Dimensions du dataset nettoyé
    row_count: int = Field(ge=0, description="Nombre de lignes après nettoyage.")
    col_count: int = Field(ge=1, description="Nombre de colonnes après nettoyage.")

    # Empreinte cryptographique du dataset source (avant nettoyage)
    data_hash: str = Field(
        min_length=64, max_length=64,
        description="SHA-256 du fichier source original pour traçabilité.",
    )

    # Score de santé global
    overall_health_score: float = Field(
        ge=0.0, le=100.0,
        description="Score de qualité des données (0-100%) calculé par l'Agent 1.",
    )

    # Détail par colonne (optionnel — peut être vide pour les datasets larges)
    column_quality: List[ColumnQuality] = Field(
        default_factory=list,
        description="Qualité détaillée par colonne.",
    )

    # Rapport de profiling brut (optionnel — inclus pour rétro-compatibilité)
    profiling_report: Dict[str, Any] = Field(
        default_factory=dict,
        description="ProfilingReport JSON complet de DataEngineeringAgent.",
    )

    # Méta-données
    agent_version: str = "1.0"
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )

    @field_validator("data_hash")
    @classmethod
    def validate_hex(cls, v: str) -> str:
        if not all(c in "0123456789abcdef" for c in v.lower()):
            raise ValueError(f"data_hash must be a hex string, got: {v[:16]}…")
        return v.lower()

    def to_graph_state_dict(self) -> Dict[str, Any]:
        """Retourne le sous-dict compatible GraphState["reports"]["data_engineer"]."""
        return {
            "profiling_report":   self.profiling_report,
            "health":             {"overall_health_score": self.overall_health_score},
            "report_path":        "",
            "cleaned_path":       self.cleaned_dataset_path,
            "data_hash":          self.data_hash,
            "row_count":          self.row_count,
            "col_count":          self.col_count,
        }


# =============================================================================
# Agent 2 — BIAnalystOutput
# =============================================================================

class BIAnalystOutput(BaseModel):
    """
    Output complet de l'Agent 2 (BI Analyst Agent).

    Produit par BIAnalystAgent.analyze() + parse_response().
    Transmis dans GraphState["reports"]["bi_analyst"].
    """

    # Rapport narratif en Markdown
    summary_markdown: str = Field(
        ...,
        min_length=1,
        description="Rapport Markdown complet généré par le LLM.",
    )

    # KPIs métier structurés
    kpis: List[KPICard] = Field(
        default_factory=list,
        description="Liste des KPIs calculés ou extraits du rapport.",
    )

    # Graphiques recommandés
    charts_data: List[ChartSpec] = Field(
        default_factory=list,
        description="Spécifications des graphiques recommandés par l'agent.",
    )

    # Télémétrie (provider LLM, modèle utilisé — sans clés)
    provider: str = Field(default="unknown", description="Fournisseur LLM utilisé.")
    model_used: str = Field(default="-", description="Modèle LLM utilisé.")
    is_llm: bool = Field(default=False)
    duration_s: float = Field(default=0.0, ge=0.0)

    # Méta-données
    agent_version: str = "1.0"
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )

    @model_validator(mode="after")
    def ensure_kpis_not_empty(self) -> "BIAnalystOutput":
        """Avertit (sans bloquer) si aucun KPI n'est extrait."""
        if not self.kpis:
            # On tolère les KPIs vides — l'agent peut n'en produire aucun
            pass
        return self

    def to_graph_state_dict(self) -> Dict[str, Any]:
        """Retourne le sous-dict compatible GraphState["reports"]["bi_analyst"]."""
        return {
            "markdown":     self.summary_markdown,
            "chart_config": {
                "kpis":               [k.model_dump() for k in self.kpis],
                "recommended_charts": [c.model_dump() for c in self.charts_data],
            },
            "telemetry": {
                "provider":   self.provider,
                "model":      self.model_used,
                "is_llm":     self.is_llm,
                "duration_s": self.duration_s,
            },
        }


# =============================================================================
# Agent 3 — XAIAuditorOutput
# =============================================================================

class SHAPSummary(BaseModel):
    """Résumé des attributions SHAP — sous-modèle de XAIAuditorOutput."""

    explainer_type: str = Field(
        description="Nom de l'explainer SHAP utilisé (TreeExplainer, KernelExplainer…).",
    )
    n_samples: int = Field(ge=0)
    n_features: int = Field(ge=0)
    top_features: List[SHAPFeatureEntry] = Field(default_factory=list)
    global_mean_abs_shap: float = Field(ge=0.0)


class XAIAuditorOutput(BaseModel):
    """
    Output complet de l'Agent 3 (XAI Auditor Agent).

    Produit par XAIAuditorAgent.audit().
    Transmis dans GraphState["reports"]["xai_auditor"].
    """

    # Résumé des attributions SHAP
    shap_summary: SHAPSummary

    # Empreintes cryptographiques
    integrity_hashes: IntegrityHashes

    # Explication en langage naturel
    narrative_explanation: str = Field(
        ...,
        min_length=1,
        description="Explication narrative générée par le LLM ou le fallback déterministe.",
    )

    # Statut de conformité
    compliance_status: Literal["COMPLIANT", "PARTIAL", "NON_COMPLIANT"] = Field(
        description=(
            "COMPLIANT    = SHAP + hashes + LLM tous opérationnels. "
            "PARTIAL      = SHAP ou LLM indisponible mais audit partiel produit. "
            "NON_COMPLIANT= Audit impossible (erreur critique)."
        ),
    )

    # Distribution des prédictions
    predictions_distribution: Dict[str, Any] = Field(default_factory=dict)

    # Télémétrie
    provider: str = Field(default="unknown")
    engine_used: str = Field(default="auto")
    is_llm: bool = Field(default=False)
    duration_s: float = Field(default=0.0, ge=0.0)

    # Méta-données
    dataset_name: str = ""
    n_samples: int = Field(ge=0, default=0)
    n_features: int = Field(ge=0, default=0)
    agent_version: str = "1.0"
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )

    @model_validator(mode="after")
    def derive_compliance_status(self) -> "XAIAuditorOutput":
        """
        Recalcule compliance_status si les données SHAP ou les hashes sont absents.
        N'écrase pas une valeur déjà explicitement fournie.
        """
        shap_ok  = len(self.shap_summary.top_features) > 0
        hash_ok  = bool(self.integrity_hashes.audit_hash)
        llm_ok   = self.is_llm
        if shap_ok and hash_ok:
            if self.compliance_status == "NON_COMPLIANT":
                # Les données sont là — mettre à jour vers PARTIAL ou COMPLIANT
                self.compliance_status = "COMPLIANT" if llm_ok else "PARTIAL"
        return self

    def to_graph_state_dict(self) -> Dict[str, Any]:
        """Retourne le sous-dict compatible GraphState["reports"]["xai_auditor"]."""
        return {
            "audit_report": {
                "timestamp":               self.timestamp,
                "dataset_name":            self.dataset_name,
                "n_samples":               self.n_samples,
                "n_features":              self.n_features,
                "engine_used":             self.engine_used,
                "integrity": {
                    "data_hash":        self.integrity_hashes.data_hash,
                    "predictions_hash": self.integrity_hashes.predictions_hash,
                    "audit_hash":       self.integrity_hashes.audit_hash,
                },
                "shap": {
                    "explainer_type": self.shap_summary.explainer_type,
                    "summary": {
                        "n_samples":            self.shap_summary.n_samples,
                        "n_features":           self.shap_summary.n_features,
                        "top_features":         [f.model_dump() for f in self.shap_summary.top_features],
                        "global_mean_abs_shap": self.shap_summary.global_mean_abs_shap,
                    },
                },
                "predictions_distribution": self.predictions_distribution,
                "narrative_explanation":    self.narrative_explanation,
                "telemetry": {
                    "provider":   self.provider,
                    "model":      "-",
                    "is_llm":     self.is_llm,
                    "duration_s": self.duration_s,
                },
            },
            "audit_hash":  self.integrity_hashes.audit_hash,
            "narrative":   self.narrative_explanation,
            "telemetry": {
                "provider":   self.provider,
                "is_llm":     self.is_llm,
                "duration_s": self.duration_s,
            },
            "compliance_status": self.compliance_status,
        }


# =============================================================================
# Utilitaire de validation
# =============================================================================

_SCHEMA_MAP = {
    "data_engineer": DataEngineerOutput,
    "bi_analyst":    BIAnalystOutput,
    "xai_auditor":   XAIAuditorOutput,
}


def validate_agent_output(
    agent_key: str,
    raw_dict: Dict[str, Any],
    strict: bool = False,
) -> Optional[BaseModel]:
    """
    Valide et parse un dict brut d'agent contre son schéma Pydantic.

    Paramètres :
        agent_key : "data_engineer" | "bi_analyst" | "xai_auditor"
        raw_dict  : dict brut retourné par l'agent
        strict    : si True, lève ValidationError en cas d'erreur ;
                    si False (défaut), retourne None et logue l'erreur.

    Retourne l'instance Pydantic validée, ou None en mode non-strict.
    """
    import logging
    logger = logging.getLogger(__name__)

    schema_cls = _SCHEMA_MAP.get(agent_key)
    if schema_cls is None:
        raise ValueError(
            f"Agent inconnu : '{agent_key}'. "
            f"Valeurs valides : {list(_SCHEMA_MAP.keys())}"
        )

    try:
        return schema_cls.model_validate(raw_dict)
    except Exception as exc:
        if strict:
            raise
        logger.warning(
            "[schemas] Validation failed for '%s': %s", agent_key, str(exc)[:200]
        )
        return None
