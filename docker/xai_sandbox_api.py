"""
docker/xai_sandbox_api.py — BIFlow XAI Auditor Sandbox API
============================================================
Serveur FastAPI léger exposé sur le port 8003 dans le conteneur Docker.
Reçoit les requêtes d'audit XAI depuis orchestration/graph.py,
exécute XAIAuditorAgent en isolation complète et retourne le rapport JSON.

Endpoints :
    GET  /health          — liveness check
    POST /audit           — lance un audit XAI complet
    GET  /engine-status   — statut du moteur LLM configuré (sans exposer les clés)

Sécurité :
    - Aucune clé API n'est loggée ni retournée dans les réponses.
    - L'engine est lu depuis la variable d'environnement ENGINE.
    - En mode "cloud", aucun appel vers Ollama n'est tenté.
"""

from __future__ import annotations

import io
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ── Path setup ────────────────────────────────────────────────────────────────
WORKSPACE = Path("/workspace")
sys.path.insert(0, str(WORKSPACE))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
logger = logging.getLogger("xai_sandbox")

# ── Engine depuis l'environnement (injecté par docker-compose, jamais hardcodé) ─
_ENGINE = os.environ.get("ENGINE", "auto").lower()

# ── Vérification sécurité : en mode cloud, ne pas lire OLLAMA_HOST ────────────
if _ENGINE == "cloud":
    # Supprimer toute référence Ollama de l'environnement du process
    os.environ.pop("OLLAMA_HOST", None)
    logger.info("[Sandbox] Engine=cloud — Ollama désactivé.")
else:
    logger.info("[Sandbox] Engine=%s — Ollama activé si disponible.", _ENGINE)

# Import paresseux — évite de crasher si shap n'est pas encore installé au démarrage
_agent_module_loaded = False

app = FastAPI(
    title="BIFlow XAI Auditor Sandbox",
    description="Agent 3 — SHAP attributions, SHA-256 integrity, LLM explanation",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)


# =============================================================================
# Modèles Pydantic
# =============================================================================

class AuditRequest(BaseModel):
    """Payload d'une requête d'audit XAI."""

    data_path: str = Field(
        ...,
        description="Chemin absolu ou relatif à /workspace vers le fichier CSV.",
        example="/workspace/data/raw/telco_churn.csv",
    )
    dataset_name: str = Field(
        default="dataset",
        description="Nom du dataset pour le rapport.",
    )
    target_column: Optional[str] = Field(
        default=None,
        description="Colonne cible. Si None, la dernière colonne est utilisée.",
    )
    top_n_features: int = Field(
        default=10,
        ge=1,
        le=30,
        description="Nombre de features SHAP à inclure dans le résumé.",
    )
    engine: Optional[str] = Field(
        default=None,
        description=(
            "Moteur LLM : 'local' | 'cloud' | 'auto'. "
            "Si None, utilise la variable d'environnement ENGINE."
        ),
    )


class HealthResponse(BaseModel):
    status: str
    engine: str
    groq_configured: bool
    gemini_configured: bool
    # Les clés ne sont jamais exposées — seulement leur présence booléenne
    timestamp: float


class EngineStatusResponse(BaseModel):
    engine: str
    groq_configured: bool
    gemini_configured: bool
    ollama_enabled: bool
    message: str


# =============================================================================
# Helpers internes
# =============================================================================

def _resolve_data_path(raw_path: str) -> str:
    """Résout le chemin vers un fichier CSV dans le contexte du conteneur."""
    p = Path(raw_path)
    if p.is_absolute() and p.exists():
        return str(p)
    # Essayer relatif à /workspace
    candidate = WORKSPACE / raw_path
    if candidate.exists():
        return str(candidate)
    raise FileNotFoundError(
        f"Dataset introuvable : '{raw_path}'. "
        f"Vérifiez que le volume /workspace/data/ est correctement monté."
    )


def _build_surrogate(data_path: str, target_column: Optional[str]):
    """
    Construit un surrogate RandomForest sur le dataset fourni.
    Retourne (model, X_encoded, feature_names, task_type).
    """
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.preprocessing import LabelEncoder

    df = pd.read_csv(data_path)
    target_col = target_column or df.columns[-1]

    if target_col not in df.columns:
        raise ValueError(
            f"Colonne cible '{target_col}' introuvable. "
            f"Colonnes disponibles : {list(df.columns)}"
        )

    X_raw = df.drop(columns=[target_col]).copy()
    y_raw = df[target_col].copy()

    # Encodage auto des colonnes object/category
    for col in X_raw.select_dtypes(include=["object", "category"]).columns:
        X_raw[col] = pd.to_numeric(X_raw[col], errors="coerce")
        if X_raw[col].dtype == object:
            X_raw[col] = LabelEncoder().fit_transform(X_raw[col].astype(str))

    X_raw = X_raw.apply(pd.to_numeric, errors="coerce").fillna(0).astype(float)

    # Déterminer classification vs régression
    try:
        y_num = pd.to_numeric(y_raw, errors="coerce")
        if y_num.isna().sum() / len(y_raw) > 0.5:
            raise ValueError("mostly non-numeric")
        if int(y_num.nunique()) <= 20:
            le_y = LabelEncoder()
            y = le_y.fit_transform(y_raw.astype(str))
            mdl = RandomForestClassifier(n_estimators=60, max_depth=7, random_state=42, n_jobs=-1)
            task = "classification"
        else:
            y = y_num.fillna(y_num.median()).values
            mdl = RandomForestRegressor(n_estimators=60, max_depth=7, random_state=42, n_jobs=-1)
            task = "regression"
    except Exception:
        le_y = LabelEncoder()
        y = le_y.fit_transform(y_raw.astype(str))
        mdl = RandomForestClassifier(n_estimators=60, max_depth=7, random_state=42, n_jobs=-1)
        task = "classification"

    mdl.fit(X_raw, y)
    return mdl, X_raw, list(X_raw.columns), task


def _sanitize_report_for_response(report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Nettoie le rapport avant de le renvoyer en HTTP :
    - Retire les tentatives LLM détaillées (logs internes)
    - Ne retourne jamais les clés API ou les routes internes
    """
    safe = dict(report)

    if "telemetry" in safe:
        t = dict(safe["telemetry"])
        # Retirer les détails des tentatives — ils peuvent contenir des messages d'erreur
        # avec des noms de modèles internes ou des fragments de config
        if "attempts" in t:
            t["attempts"] = [
                {k: v for k, v in a.items() if k != "detail"}
                for a in t["attempts"]
            ]
        safe["telemetry"] = t

    return safe


# =============================================================================
# Endpoints FastAPI
# =============================================================================

@app.get("/health", response_model=HealthResponse, tags=["monitoring"])
def health_check() -> HealthResponse:
    """Liveness check — retourne le statut du service et la config moteur."""
    return HealthResponse(
        status="ok",
        engine=_ENGINE,
        groq_configured=bool(os.environ.get("GROQ_API_KEY")),
        gemini_configured=bool(
            os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        ),
        timestamp=time.time(),
    )


@app.get("/engine-status", response_model=EngineStatusResponse, tags=["monitoring"])
def engine_status() -> EngineStatusResponse:
    """Statut détaillé du moteur LLM — sans exposer les clés."""
    groq_ok   = bool(os.environ.get("GROQ_API_KEY"))
    gemini_ok = bool(
        os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    )
    ollama_en = _ENGINE in ("local", "auto")

    if _ENGINE == "cloud" and not groq_ok and not gemini_ok:
        msg = "⚠️ Mode Cloud actif mais aucune clé API configurée — fallback déterministe."
    elif _ENGINE == "local":
        msg = "🦙 Mode Local — Ollama requis sur l'hôte."
    elif _ENGINE == "cloud":
        msg = f"☁️ Mode Cloud — {'Groq' if groq_ok else 'Gemini' if gemini_ok else '?'} actif."
    else:
        msg = "⚡ Mode Auto — Ollama d'abord, Cloud en fallback."

    return EngineStatusResponse(
        engine=_ENGINE,
        groq_configured=groq_ok,
        gemini_configured=gemini_ok,
        ollama_enabled=ollama_en,
        message=msg,
    )


@app.post("/audit", tags=["xai"])
def run_audit(request: AuditRequest) -> JSONResponse:
    """
    Lance un audit XAI complet :
    1. Charge et encode le dataset depuis data_path.
    2. Entraîne un surrogate RandomForest.
    3. Calcule les attributions SHAP (TreeExplainer → KernelExplainer).
    4. Génère un hash SHA-256 des artefacts.
    5. Produit une explication en langage naturel via le moteur LLM configuré.

    Retourne le rapport d'audit JSON complet.
    """
    start = time.time()

    # Résoudre le chemin du dataset dans le contexte du conteneur
    try:
        resolved_path = _resolve_data_path(request.data_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Déterminer l'engine effectif
    engine = (request.engine or _ENGINE).lower()

    # Sécurité : en mode cloud, s'assurer qu'Ollama n'est pas appelé
    if engine == "cloud":
        os.environ.pop("OLLAMA_HOST", None)

    logger.info(
        "[Audit] Starting — dataset=%s, engine=%s, target=%s",
        request.dataset_name, engine, request.target_column or "auto",
    )

    # Construire le surrogate model
    try:
        model, X, feature_names, task_type = _build_surrogate(
            resolved_path, request.target_column
        )
    except Exception as e:
        logger.error("[Audit] Surrogate build failed: %s", e)
        raise HTTPException(
            status_code=422,
            detail=f"Impossible de construire le surrogate model : {e}",
        )

    # Instancier l'agent XAI avec l'engine résolu
    try:
        from agents.xai_auditor_agent import XAIAuditorAgent

        agent = XAIAuditorAgent(
            engine=engine,
            # Ollama non configuré en mode cloud — timeout minimal si jamais appelé
            ollama_timeout=3 if engine == "cloud" else 120,
        )
        report = agent.audit(
            model=model,
            X=X,
            feature_names=feature_names,
            dataset_name=request.dataset_name,
            top_n_features=request.top_n_features,
        )
    except Exception as e:
        logger.error("[Audit] XAI agent failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur agent XAI : {e}")

    duration = round(time.time() - start, 2)
    logger.info("[Audit] Completed in %.1fs — engine=%s", duration, engine)

    # Sauvegarder le rapport sur le volume partagé
    output_dir = WORKSPACE / "data" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"xai_audit_{request.dataset_name}.json"

    import json
    safe_report = _sanitize_report_for_response(report)
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(safe_report, f, indent=2, default=str)
        logger.info("[Audit] Report saved → %s", output_file)
    except Exception as e:
        logger.warning("[Audit] Could not save report file: %s", e)

    return JSONResponse(content=safe_report)
