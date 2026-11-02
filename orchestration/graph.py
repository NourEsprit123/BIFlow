"""
orchestration/graph.py — BIFlow Multi-Agent Orchestrator
=========================================================
Implémente le graphe LangGraph qui orchestre le pipeline séquentiel
entre les 3 agents spécialisés de BIFlow :

    Agent 1 — DataEngineeringAgent  (Profiling, Qualité, ETL)
    Agent 2 — BIAnalystAgent        (KPI, Tendances, Insights)
    Agent 3 — XAIAuditorAgent       (SHAP, SHA-256, Audit forensique)

Trois modes d'exécution configurables via GraphState.execution_mode :
    "auto"           — enchaînement A1 → A2 → A3 sans interruption.
    "hitl"           — pause après chaque agent (Human-in-the-Loop).
    "direct_agent_2" — démarre directement à l'Agent 2 (données fournies).
    "direct_agent_3" — démarre directement à l'Agent 3 (rapport BI fourni).

Interfaces Docker :
    - Agent 1 : exécution standard (in-process).
    - Agent 2 : wrapper Docker (sandbox déjà mis en place par l'équipe).
    - Agent 3 : wrapper Docker BIFlow XAI (isolé via notre sandbox).

Usage minimal :
    from orchestration.graph import build_graph, GraphState
    app = build_graph()
    state = GraphState(data_path="data/raw/telco_churn.csv", execution_mode="auto")
    result = app.invoke(state, {"configurable": {"thread_id": "session_1"}})
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import pandas as pd
from typing_extensions import TypedDict

# ── LangGraph ────────────────────────────────────────────────────────────────
from langgraph.graph import END, StateGraph
from langgraph.checkpoint.memory import MemorySaver

# ── BIFlow agents (imports paresseux à l'intérieur des nœuds pour éviter
#    les imports circulaires et les temps de démarrage lourds) ────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes Docker
# ---------------------------------------------------------------------------

# Image Docker pour l'Agent 2 (BI Analyst) — sandbox équipe
DOCKER_IMAGE_BI    = os.environ.get("BIFLOW_DOCKER_BI",  "biflow/bi-analyst:latest")
# Image Docker pour l'Agent 3 (XAI Auditor) — notre sandbox
DOCKER_IMAGE_XAI   = os.environ.get("BIFLOW_DOCKER_XAI", "biflow/xai-auditor:latest")
# Timeout Docker en secondes
DOCKER_TIMEOUT     = int(os.environ.get("BIFLOW_DOCKER_TIMEOUT", "300"))
# Monter le dossier projet en lecture seule dans les conteneurs
DOCKER_MOUNT_ROOT  = str(PROJECT_ROOT)

# ---------------------------------------------------------------------------
# GraphState — TypedDict complet
# ---------------------------------------------------------------------------

class GraphState(TypedDict, total=False):
    """
    État global partagé entre tous les nœuds du pipeline LangGraph.

    Tous les champs sont optionnels (total=False) sauf data_path et
    execution_mode qui sont requis au démarrage.
    """

    # ── Entrée utilisateur ────────────────────────────────────────────────
    data_path: str
    """Chemin vers le dataset CSV d'entrée (absolu ou relatif à PROJECT_ROOT)."""

    execution_mode: Literal["auto", "hitl", "direct_agent_2", "direct_agent_3"]
    """Mode d'exécution du pipeline."""

    # ── Routing & contrôle ────────────────────────────────────────────────
    current_step: Literal[
        "start", "data_engineer", "bi_analysis", "xai_audit", "done", "error"
    ]
    """Étape en cours d'exécution."""

    user_approval: Literal["pending", "approved", "rejected"]
    """Statut de validation humaine (HITL uniquement)."""

    retry_count: Dict[str, int]
    """Nombre de tentatives par nœud — ex: {"bi_analysis": 1}."""

    # ── Données transitées entre agents ──────────────────────────────────
    cleaned_data_path: str
    """Chemin vers le dataset nettoyé produit par l'Agent 1."""

    profiling_report: Dict[str, Any]
    """ProfilingReport JSON complet produit par l'Agent 1."""

    bi_report_markdown: str
    """Rapport Markdown produit par l'Agent 2."""

    bi_chart_config: Dict[str, Any]
    """Configuration des graphiques extraite du rapport BI (KPIs, charts)."""

    xai_audit_report: Dict[str, Any]
    """Rapport d'audit XAI complet (SHAP, SHA-256, narrative) — Agent 3."""

    # ── Stockage des outputs ──────────────────────────────────────────────
    reports: Dict[str, Any]
    """
    Dictionnaire centralisé des outputs de chaque agent :
    {
        "data_engineer": {"profiling_report": ..., "cleaned_path": ...},
        "bi_analyst":    {"markdown": ..., "chart_config": ...},
        "xai_auditor":   {"audit_report": ..., "narrative": ...},
    }
    """

    # ── Historique & télémétrie ───────────────────────────────────────────
    history_logs: List[Dict[str, Any]]
    """
    Historique chronologique de chaque exécution d'agent :
    [
        {
            "agent": "data_engineer",
            "timestamp": "2026-10-15T10:30:00Z",
            "duration_s": 4.2,
            "status": "success" | "error" | "skipped",
            "details": {...},
        },
        ...
    ]
    """

    # ── Gestion des erreurs ───────────────────────────────────────────────
    error_message: str
    """Message d'erreur de la dernière exception non récupérée."""

    sandbox_mode: Literal["docker", "inprocess"]
    """
    Mode de sandboxing pour l'Agent 2 et l'Agent 3.
    "docker"     — exécution dans un conteneur Docker isolé.
    "inprocess"  — exécution directe dans le process Python courant (dev/tests).
    """

    resource_mode: Literal["local", "cloud", "auto"]
    """
    Mode de ressources LLM pour les agents 2 et 3.
    "local"  — Ollama uniquement (offline, privé).
    "cloud"  — APIs Cloud uniquement (Groq → Gemini → LLMClient).
    "auto"   — Ollama d'abord, puis Cloud si indisponible, puis fallback déterministe.
    Propagé à BIAnalystAgent(engine=...) et XAIAuditorAgent(engine=...).
    """


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_entry(
    agent: str,
    status: str,
    duration_s: float,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Construit une entrée d'historique standardisée.
    Les details sont passés par _to_native pour garantir
    la compatibilité msgpack avant stockage dans history_logs.
    """
    return {
        "agent":      agent,
        "timestamp":  _now_iso(),
        "duration_s": round(float(duration_s), 2),
        "status":     status,
        "details":    _to_native(details or {}),
    }


def _append_log(state: GraphState, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Retourne une nouvelle liste history_logs avec l'entrée ajoutée."""
    existing: List[Dict[str, Any]] = state.get("history_logs") or []
    return existing + [entry]


def _resolve_path(path: str) -> str:
    """Résout un chemin relatif par rapport à PROJECT_ROOT."""
    p = Path(path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return str(p)


# ---------------------------------------------------------------------------
# Sérialiseur d'état — compatibilité msgpack (LangGraph checkpointing)
# ---------------------------------------------------------------------------

def _to_native(obj: Any) -> Any:
    """
    Convertit récursivement tout type NumPy / Pandas en type Python natif
    afin que LangGraph puisse sérialiser l'état via msgpack sans lever
    "Type is not msgpack serializable: numpy.float64".

    Couvre :
        numpy scalars  (float64, int64, bool_, etc.)
        numpy.ndarray  → liste Python imbriquée
        pandas Series  → liste Python
        pandas DataFrame → liste de dicts
        dict / list    → récursion
    """
    import numpy as np
    import pandas as pd

    # ── numpy scalars ─────────────────────────────────────────────────────────
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()             # ndarray → liste Python native

    # ── pandas ────────────────────────────────────────────────────────────────
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient="records")
    if isinstance(obj, pd.Series):
        return obj.tolist()

    # ── conteneurs Python ─────────────────────────────────────────────────────
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(v) for v in obj]

    # ── types primitifs natifs : passe-through ────────────────────────────────
    return obj


# ---------------------------------------------------------------------------
# Interfaces Docker (sandbox)
# ---------------------------------------------------------------------------

class DockerSandboxError(RuntimeError):
    """Levée quand un appel Docker échoue et que le fallback in-process est désactivé."""


def _docker_available() -> bool:
    """Vérifie que Docker est installé et que le daemon répond."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _run_agent_in_docker(
    image: str,
    command: List[str],
    env: Optional[Dict[str, str]] = None,
    timeout: int = DOCKER_TIMEOUT,
) -> Dict[str, Any]:
    """
    Exécute un agent dans un conteneur Docker isolé.

    Le conteneur monte PROJECT_ROOT en lecture seule (/workspace) et
    écrit ses outputs dans /workspace/data/reports/ (partagé en lecture-écriture).

    Retourne un dict {"stdout": str, "stderr": str, "returncode": int}.
    """
    docker_cmd = [
        "docker", "run", "--rm",
        "--network", "none",                           # isolation réseau
        "-v", f"{DOCKER_MOUNT_ROOT}:/workspace:rw",   # montage projet
        "-w", "/workspace",
    ]

    if env:
        for k, v in env.items():
            docker_cmd += ["-e", f"{k}={v}"]

    docker_cmd.append(image)
    docker_cmd.extend(command)

    logger.info("[Docker] Running: %s", " ".join(docker_cmd[:8]) + " …")

    try:
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "stdout":     result.stdout,
            "stderr":     result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        raise DockerSandboxError(
            f"Docker container for image '{image}' timed out after {timeout}s."
        )
    except FileNotFoundError:
        raise DockerSandboxError(
            "Docker CLI not found. Install Docker or set sandbox_mode='inprocess'."
        )


# ---------------------------------------------------------------------------
# NODE 1 — Data Engineering Agent
# ---------------------------------------------------------------------------

def node_data_engineer(state: GraphState) -> GraphState:
    """
    Nœud 1 : DataEngineeringAgent — Profiling, Qualité, Nettoyage, ETL.

    Exécution toujours in-process (Agent 1 hors scope sandbox Docker).
    Produit :
        - state["profiling_report"]  : rapport de profiling complet
        - state["cleaned_data_path"] : chemin du fichier nettoyé
        - state["reports"]["data_engineer"] : sous-dict de tracking
    """
    start = time.time()
    logger.info("[A1] Starting DataEngineeringAgent — path=%s", state.get("data_path"))

    # Import paresseux — évite de charger les 2 Go de poids si le nœud est sauté
    from agents.data_engineering_agent import DataEngineeringAgent

    data_path = _resolve_path(state.get("data_path", ""))
    reports   = dict(state.get("reports") or {})
    retries   = dict(state.get("retry_count") or {})

    try:
        agent  = DataEngineeringAgent()
        result = agent.run_audit(data_path)

        # Nettoyage du dataset sur la base de la stratégie déduite
        cleaned_path = data_path  # fallback : même fichier si nettoyage impossible
        try:
            clean_res = agent.execute_cleaning(
                data_path,
                strategy=result.get("cleaning_strategy"),
            )
            if isinstance(clean_res, dict) and clean_res.get("cleaned_file_path"):
                cleaned_path = clean_res["cleaned_file_path"]
            elif isinstance(clean_res, (list, tuple)):
                cleaned_path = clean_res[0]
        except Exception as clean_err:
            logger.warning("[A1] Cleaning step failed (non-fatal): %s", clean_err)

        reports["data_engineer"] = {
            "profile":             result.get("profile", {}),
            "profiling_report":    result.get("profiling_report", {}),
            "health":              result.get("health", {}),
            "cleaning_strategy":   result.get("cleaning_strategy", {}),
            "report_path":         result.get("report_path", ""),
            "cleaned_path":        cleaned_path,
            "file_path":           data_path,
            "transformations_log": clean_res.get("transformations_log", []) if isinstance(clean_res, dict) else [],
        }

        log = _log_entry(
            "data_engineer", "success", time.time() - start,
            details={
                "input":        data_path,
                "cleaned_path": cleaned_path,
                "health_score": result.get("health", {}).get("overall_score"),
            },
        )
        logger.info("[A1] Done in %.1fs.", time.time() - start)

        return _to_native({
            **state,
            "current_step":      "bi_analysis",
            "profiling_report":  result.get("profiling_report", {}),
            "cleaned_data_path": cleaned_path,
            "reports":           reports,
            "history_logs":      _append_log(state, log),
            "user_approval":     "pending" if state.get("execution_mode") == "hitl" else "approved",
        })

    except Exception as exc:
        logger.error("[A1] Fatal error: %s", exc, exc_info=True)
        log = _log_entry("data_engineer", "error", time.time() - start,
                         details={"error": str(exc)})
        return {
            **state,
            "current_step":  "error",
            "error_message": f"[Agent 1 — DataEngineer] {exc}",
            "history_logs":  _append_log(state, log),
        }


# ---------------------------------------------------------------------------
# NODE 2 — BI Analyst Agent
# ---------------------------------------------------------------------------

def _bi_inprocess(
    data_path: str,
    dataset_name: str,
    resource_mode: str = "auto",
) -> Dict[str, Any]:
    """Exécution in-process de BIAnalystAgent."""
    from agents.bi_analyst_agent import BIAnalystAgent

    # Mapper resource_mode → engine BIAnalystAgent ("local_lora" | "api" | "auto")
    _engine_map = {"local": "local_lora", "cloud": "api", "auto": "auto"}
    engine = _engine_map.get(resource_mode, "auto")

    df    = pd.read_csv(data_path)
    agent = BIAnalystAgent(engine=engine)
    full_response = agent.analyze(df, dataset_name=dataset_name)
    report, cfg   = agent.parse_response(full_response)
    return {
        "markdown":     report,
        "chart_config": cfg,
        "telemetry":    agent.get_telemetry(),
    }


def _bi_docker(data_path: str, dataset_name: str, resource_mode: str = "auto") -> Dict[str, Any]:
    """
    Exécution de BIAnalystAgent dans le sandbox Docker de l'équipe.

    L'image DOCKER_IMAGE_BI doit exposer un entrypoint CLI :
        python -m agents.bi_analyst_agent --input <path> --output <json_path>
    """
    _engine_map = {"local": "local_lora", "cloud": "api", "auto": "auto"}
    engine = _engine_map.get(resource_mode, "auto")

    output_path = str(PROJECT_ROOT / "data" / "reports" / "bi_docker_output.json")
    result = _run_agent_in_docker(
        image=DOCKER_IMAGE_BI,
        command=[
            "python", "-m", "agents.bi_analyst_agent",
            "--input",  data_path,
            "--output", output_path,
            "--engine", engine,
        ],
        env={
            "GROQ_API_KEY":   os.environ.get("GROQ_API_KEY", ""),
            "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
        },
    )
    if result["returncode"] != 0:
        raise DockerSandboxError(
            f"BI Docker container exited {result['returncode']}:\n{result['stderr'][:500]}"
        )
    with open(output_path, encoding="utf-8") as f:
        return json.load(f)


def node_bi_analyst(state: GraphState) -> GraphState:
    """
    Nœud 2 : BIAnalystAgent — KPI, Tendances, Anomalies, Insights.

    Route vers Docker (sandbox équipe) ou in-process selon state["sandbox_mode"].
    Produit :
        - state["bi_report_markdown"] : rapport Markdown
        - state["bi_chart_config"]    : KPIs + recommended_charts
        - state["reports"]["bi_analyst"]
    """
    start       = time.time()
    sandbox     = state.get("sandbox_mode", "inprocess")
    resource    = state.get("resource_mode", "auto")
    data_path   = _resolve_path(state.get("cleaned_data_path") or state.get("data_path", ""))
    dataset_name = Path(data_path).name
    reports     = dict(state.get("reports") or {})
    retries     = dict(state.get("retry_count") or {})

    logger.info("[A2] Starting BIAnalystAgent — sandbox=%s, resource=%s, path=%s",
                sandbox, resource, data_path)

    try:
        if sandbox == "docker" and _docker_available():
            logger.info("[A2] Using Docker sandbox.")
            bi_result = _bi_docker(data_path, dataset_name, resource_mode=resource)
        else:
            if sandbox == "docker":
                logger.warning("[A2] Docker unavailable — falling back to in-process.")
            bi_result = _bi_inprocess(data_path, dataset_name, resource_mode=resource)

        reports["bi_analyst"] = {
            "markdown":    bi_result.get("markdown", ""),
            "chart_config": bi_result.get("chart_config", {}),
            "telemetry":   bi_result.get("telemetry", {}),
        }

        log = _log_entry(
            "bi_analyst", "success", time.time() - start,
            details={
                "sandbox":        sandbox,
                "kpi_count":      len(bi_result.get("chart_config", {}).get("kpis", [])),
                "charts_count":   len(bi_result.get("chart_config", {}).get("recommended_charts", [])),
            },
        )
        logger.info("[A2] Done in %.1fs.", time.time() - start)

        return _to_native({
            **state,
            "current_step":      "xai_audit",
            "bi_report_markdown": bi_result.get("markdown", ""),
            "bi_chart_config":   bi_result.get("chart_config", {}),
            "reports":           reports,
            "history_logs":      _append_log(state, log),
            "user_approval":     "pending" if state.get("execution_mode") == "hitl" else "approved",
        })

    except Exception as exc:
        logger.error("[A2] Fatal error: %s", exc, exc_info=True)
        log = _log_entry("bi_analyst", "error", time.time() - start,
                         details={"error": str(exc)})
        return {
            **state,
            "current_step":  "error",
            "error_message": f"[Agent 2 — BIAnalyst] {exc}",
            "history_logs":  _append_log(state, log),
        }


# ---------------------------------------------------------------------------
# NODE 3 — XAI Auditor Agent
# ---------------------------------------------------------------------------

def _xai_inprocess(
    data_path: str,
    dataset_name: str,
    bi_report: str,
    engine: str = "auto",
) -> Dict[str, Any]:
    """Exécution in-process de XAIAuditorAgent."""
    from agents.xai_auditor_agent import XAIAuditorAgent
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import LabelEncoder

    # Sécurité : en mode cloud, supprimer OLLAMA_HOST pour éviter tout ping Ollama
    if engine == "cloud":
        os.environ.pop("OLLAMA_HOST", None)
    from sklearn.preprocessing import LabelEncoder

    df = pd.read_csv(data_path)

    # Surrogate model rapide — dernière colonne comme cible (convention BIFlow)
    target_col = df.columns[-1]
    X_raw = df.drop(columns=[target_col]).copy()
    y_raw = df[target_col].copy()

    # Encodage auto des colonnes object
    for col in X_raw.select_dtypes(include=["object", "category"]).columns:
        X_raw[col] = pd.to_numeric(X_raw[col], errors="coerce")
        if X_raw[col].dtype == object:
            X_raw[col] = LabelEncoder().fit_transform(X_raw[col].astype(str))
    # Coercion finale — NaN remplacés par 0, dtype homogène float64
    X_raw = X_raw.apply(pd.to_numeric, errors="coerce").fillna(0).astype(float)
    # Vérification : aucune colonne ne doit être de type object après encodage
    assert X_raw.select_dtypes(include=["object"]).empty, \
        "Colonnes object résiduelles après encodage — surrogate model impossible."

    le_y = LabelEncoder()
    y    = le_y.fit_transform(y_raw.astype(str))

    surrogate = RandomForestClassifier(n_estimators=50, max_depth=6, random_state=42, n_jobs=-1)
    surrogate.fit(X_raw, y)

    # En mode cloud : timeout Ollama minimal pour ne pas bloquer sur localhost:11434
    _ollama_timeout = 3 if engine == "cloud" else 120

    agent = XAIAuditorAgent(engine=engine, ollama_timeout=_ollama_timeout)
    report = agent.audit(
        model=surrogate,
        X=X_raw,
        feature_names=list(X_raw.columns),
        dataset_name=dataset_name,
        top_n_features=10,
    )
    return report


def _xai_docker(
    data_path: str,
    dataset_name: str,
    engine: str = "auto",
) -> Dict[str, Any]:
    """
    Exécution de XAIAuditorAgent via le sandbox FastAPI sur http://localhost:8003.

    Priorité :
    1. Appel HTTP POST /audit vers le sandbox Docker (port 8003).
    2. Si le service n'est pas joignable, fallback vers _xai_inprocess.

    Sécurité :
    - Les clés API ne transitent PAS dans la requête HTTP — elles sont
      configurées via docker-compose.yml / variables d'environnement du conteneur.
    - En mode "cloud", OLLAMA_HOST n'est pas transmis.
    """
    import requests as _requests

    sandbox_url = os.environ.get("XAI_SANDBOX_URL", "http://localhost:8003")
    audit_endpoint = f"{sandbox_url.rstrip('/')}/audit"
    timeout_s = int(os.environ.get("BIFLOW_DOCKER_TIMEOUT", "300"))

    # Résoudre le chemin du dataset tel que le conteneur le voit
    # Le volume monté map  ../data  →  /workspace/data
    # donc  data/raw/foo.csv  →  /workspace/data/raw/foo.csv
    _p = Path(data_path)
    if _p.is_absolute():
        # Transformer le chemin absolu hôte en chemin conteneur
        try:
            rel = _p.relative_to(PROJECT_ROOT / "data")
            container_path = f"/workspace/data/{rel.as_posix()}"
        except ValueError:
            container_path = str(_p)   # fallback : chemin brut
    else:
        container_path = f"/workspace/{_p.as_posix()}"

    payload = {
        "data_path":      container_path,
        "dataset_name":   dataset_name,
        "top_n_features": 10,
        "engine":         engine,    # propagé pour surcharg er ENGINE du conteneur
    }

    logger.info(
        "[A3-Docker] POST %s — engine=%s, path=%s",
        audit_endpoint, engine, container_path,
    )

    try:
        resp = _requests.post(audit_endpoint, json=payload, timeout=timeout_s)
        resp.raise_for_status()
        return resp.json()
    except _requests.exceptions.ConnectionError:
        logger.warning(
            "[A3-Docker] Sandbox non joignable sur %s — fallback in-process.",
            sandbox_url,
        )
        # Fallback transparent vers l'exécution in-process
        return _xai_inprocess(data_path, dataset_name, bi_report="", engine=engine)
    except _requests.exceptions.Timeout:
        raise DockerSandboxError(
            f"XAI sandbox timed out after {timeout_s}s ({audit_endpoint})."
        )
    except Exception as exc:
        raise DockerSandboxError(f"XAI sandbox call failed: {exc}")


def node_xai_auditor(state: GraphState) -> GraphState:
    """
    Nœud 3 : XAIAuditorAgent — SHAP, SHA-256, Explication narrative.

    Route vers Docker (notre sandbox) ou in-process selon state["sandbox_mode"].
    Produit :
        - state["xai_audit_report"]        : rapport d'audit complet
        - state["reports"]["xai_auditor"]  : sous-dict de tracking
    """
    start       = time.time()
    sandbox     = state.get("sandbox_mode", "inprocess")
    resource    = state.get("resource_mode", "auto")
    data_path   = _resolve_path(state.get("cleaned_data_path") or state.get("data_path", ""))
    dataset_name = Path(data_path).name
    bi_report   = state.get("bi_report_markdown", "")
    reports     = dict(state.get("reports") or {})
    # resource_mode → engine XAIAuditorAgent (même valeurs : "local"|"cloud"|"auto")
    xai_engine  = resource  # propagation directe — XAIAuditorAgent accepte ces valeurs

    # ── Sécurité : en mode cloud, supprimer OLLAMA_HOST du process courant ────
    # Évite tout ping accidentel vers localhost:11434
    if xai_engine == "cloud":
        os.environ.pop("OLLAMA_HOST", None)

    logger.info("[A3] Starting XAIAuditorAgent — sandbox=%s, engine=%s, path=%s",
                sandbox, xai_engine, data_path)

    try:
        if sandbox == "docker":
            # Appel HTTP vers le sandbox FastAPI sur port 8003
            # (fallback in-process automatique si le service n'est pas démarré)
            logger.info("[A3] Using FastAPI Docker sandbox (port 8003).")
            xai_report = _xai_docker(data_path, dataset_name, engine=xai_engine)
        else:
            xai_report = _xai_inprocess(data_path, dataset_name, bi_report, engine=xai_engine)

        reports["xai_auditor"] = {
            "audit_report":  xai_report,
            "audit_hash":    xai_report.get("integrity", {}).get("audit_hash", ""),
            "narrative":     xai_report.get("narrative_explanation", ""),
            "telemetry":     xai_report.get("telemetry", {}),
        }

        log = _log_entry(
            "xai_auditor", "success", time.time() - start,
            details={
                "sandbox":        sandbox,
                "engine_used":    xai_report.get("engine_used", "unknown"),
                "explainer":      xai_report.get("shap", {}).get("explainer_type"),
                "shap_features":  len(
                    xai_report.get("shap", {}).get("summary", {}).get("top_features", [])
                ),
                "hash_ok":        bool(xai_report.get("integrity", {}).get("audit_hash")),
            },
        )
        logger.info("[A3] Done in %.1fs.", time.time() - start)

        return _to_native({
            **state,
            "current_step":    "done",
            "xai_audit_report": xai_report,
            "reports":         reports,
            "history_logs":    _append_log(state, log),
            "user_approval":   "approved",
        })

    except Exception as exc:
        logger.error("[A3] Fatal error: %s", exc, exc_info=True)
        log = _log_entry("xai_auditor", "error", time.time() - start,
                         details={"error": str(exc)})
        return {
            **state,
            "current_step":  "error",
            "error_message": f"[Agent 3 — XAIAuditor] {exc}",
            "history_logs":  _append_log(state, log),
        }


# ---------------------------------------------------------------------------
# NODE HITL — Pause et validation humaine
# ---------------------------------------------------------------------------

def node_hitl_gate(state: GraphState) -> GraphState:
    """
    Nœud de contrôle Human-in-the-Loop.

    En mode "hitl", ce nœud est inséré après chaque agent.
    LangGraph interrompt l'exécution ici grâce à interrupt_before=[...].
    Le résumé de l'étape terminée est affiché ; l'humain reprend via app.invoke(None).

    En mode "auto" ou "direct_*", ce nœud passe directement (no-op).
    """
    mode = state.get("execution_mode", "auto")
    step = state.get("current_step", "done")

    if mode != "hitl":
        # Mode auto ou direct — on ne pause pas
        return {**state, "user_approval": "approved"}

    # En HITL : passer à "pending" — LangGraph suspendera avant le prochain nœud
    logs   = state.get("history_logs") or []
    last   = logs[-1] if logs else {}
    logger.info(
        "[HITL] Pausing after step '%s' — agent=%s status=%s",
        step, last.get("agent"), last.get("status"),
    )
    return {**state, "user_approval": "pending"}


# ---------------------------------------------------------------------------
# Fonctions de routing conditionnel
# ---------------------------------------------------------------------------

def _route_after_a1(state: GraphState) -> str:
    """Décide du nœud suivant après l'Agent 1."""
    if state.get("current_step") == "error":
        return "error_end"
    if state.get("execution_mode") == "hitl":
        return "hitl_gate_a1"
    return "bi_analyst"


def _route_after_hitl_a1(state: GraphState) -> str:
    """Décide si on avance ou si on retry l'Agent 1 après validation HITL."""
    approval = state.get("user_approval", "pending")
    if approval == "rejected":
        retries = dict(state.get("retry_count") or {})
        retries["data_engineer"] = retries.get("data_engineer", 0) + 1
        # Limite de 3 retries pour éviter une boucle infinie
        if retries["data_engineer"] <= 3:
            return "data_engineer"
    return "bi_analyst"


def _route_after_a2(state: GraphState) -> str:
    """Décide du nœud suivant après l'Agent 2."""
    if state.get("current_step") == "error":
        return "error_end"
    if state.get("execution_mode") == "hitl":
        return "hitl_gate_a2"
    return "xai_auditor"


def _route_after_hitl_a2(state: GraphState) -> str:
    """Retry ou avance après validation HITL de l'Agent 2."""
    approval = state.get("user_approval", "pending")
    if approval == "rejected":
        retries = dict(state.get("retry_count") or {})
        retries["bi_analysis"] = retries.get("bi_analysis", 0) + 1
        if retries["bi_analysis"] <= 3:
            return "bi_analyst"
    return "xai_auditor"


def _route_after_a3(state: GraphState) -> str:
    """Fin du pipeline ou erreur."""
    if state.get("current_step") == "error":
        return "error_end"
    return "pipeline_end"


def _route_entry(state: GraphState) -> str:
    """
    Nœud d'entrée — route vers le bon point de départ selon execution_mode.

    "auto" / "hitl"      → Agent 1
    "direct_agent_2"     → Agent 2 directement (cleaned_data_path requis)
    "direct_agent_3"     → Agent 3 directement (bi_report_markdown requis)
    """
    mode = state.get("execution_mode", "auto")
    if mode == "direct_agent_2":
        return "bi_analyst"
    if mode == "direct_agent_3":
        return "xai_auditor"
    return "data_engineer"


# ---------------------------------------------------------------------------
# Nœud terminal partagé
# ---------------------------------------------------------------------------

def node_pipeline_end(state: GraphState) -> GraphState:
    """Nœud final — log de clôture et statut SUCCESS."""
    total_duration = sum(
        e.get("duration_s", 0) for e in (state.get("history_logs") or [])
    )
    logger.info(
        "[Pipeline] ✅ Completed in %.1fs — steps: %s",
        total_duration,
        [e.get("agent") for e in (state.get("history_logs") or [])],
    )
    return {
        **state,
        "current_step": "done",
        "user_approval": "approved",
    }


def node_error_end(state: GraphState) -> GraphState:
    """Nœud d'erreur — log et statut FAILED."""
    logger.error("[Pipeline] ❌ Failed — %s", state.get("error_message", "unknown error"))
    return {**state, "current_step": "error"}


# ---------------------------------------------------------------------------
# Construction du graphe LangGraph
# ---------------------------------------------------------------------------

def build_graph(
    sandbox_mode: str = "inprocess",
    enable_hitl: bool = True,
) -> Any:
    """
    Construit et compile le graphe LangGraph BIFlow.

    Paramètres :
        sandbox_mode : "docker" | "inprocess"
            Mode de sandboxing par défaut pour les agents 2 et 3.
            Peut être surchargé par l'état GraphState["sandbox_mode"].
        enable_hitl : bool
            Si False, les nœuds HITL sont ajoutés mais toujours passants (no-op).
            Utile pour les tests automatisés.

    Retourne :
        app — graphe compilé avec MemorySaver (checkpointing en mémoire).

    Topologie complète :
        ┌─────────────────────────────────────────────────────────┐
        │  entry_router                                           │
        │    ├─[auto/hitl]──► data_engineer                      │
        │    ├─[direct_a2]──► bi_analyst                         │
        │    └─[direct_a3]──► xai_auditor                        │
        │                                                         │
        │  data_engineer ──► hitl_gate_a1 ──► [approved] ──►     │
        │                         └──────────► [rejected] ──►    │
        │                  ──► bi_analyst ──► hitl_gate_a2 ──►    │
        │                         └──────────► [rejected] ──►    │
        │                  ──► xai_auditor ──► pipeline_end      │
        │                                                         │
        │  error_end ──► END                                      │
        └─────────────────────────────────────────────────────────┘
    """
    graph = StateGraph(GraphState)

    # ── Nœuds ────────────────────────────────────────────────────────────────
    graph.add_node("data_engineer",  node_data_engineer)
    graph.add_node("bi_analyst",     node_bi_analyst)
    graph.add_node("xai_auditor",    node_xai_auditor)
    graph.add_node("hitl_gate_a1",   node_hitl_gate)
    graph.add_node("hitl_gate_a2",   node_hitl_gate)
    graph.add_node("pipeline_end",   node_pipeline_end)
    graph.add_node("error_end",      node_error_end)

    # ── Point d'entrée conditionnel ───────────────────────────────────────────
    graph.set_conditional_entry_point(
        _route_entry,
        {
            "data_engineer": "data_engineer",
            "bi_analyst":    "bi_analyst",
            "xai_auditor":   "xai_auditor",
        },
    )

    # ── Edges après Agent 1 ───────────────────────────────────────────────────
    graph.add_conditional_edges(
        "data_engineer",
        _route_after_a1,
        {
            "hitl_gate_a1": "hitl_gate_a1",
            "bi_analyst":   "bi_analyst",
            "error_end":    "error_end",
        },
    )

    # ── Edges après HITL gate A1 ──────────────────────────────────────────────
    graph.add_conditional_edges(
        "hitl_gate_a1",
        _route_after_hitl_a1,
        {
            "data_engineer": "data_engineer",
            "bi_analyst":    "bi_analyst",
        },
    )

    # ── Edges après Agent 2 ───────────────────────────────────────────────────
    graph.add_conditional_edges(
        "bi_analyst",
        _route_after_a2,
        {
            "hitl_gate_a2": "hitl_gate_a2",
            "xai_auditor":  "xai_auditor",
            "error_end":    "error_end",
        },
    )

    # ── Edges après HITL gate A2 ──────────────────────────────────────────────
    graph.add_conditional_edges(
        "hitl_gate_a2",
        _route_after_hitl_a2,
        {
            "bi_analyst":  "bi_analyst",
            "xai_auditor": "xai_auditor",
        },
    )

    # ── Edges après Agent 3 ───────────────────────────────────────────────────
    graph.add_conditional_edges(
        "xai_auditor",
        _route_after_a3,
        {
            "pipeline_end": "pipeline_end",
            "error_end":    "error_end",
        },
    )

    # ── Terminaisons ─────────────────────────────────────────────────────────
    graph.add_edge("pipeline_end", END)
    graph.add_edge("error_end",    END)

    # ── Compilation avec checkpointing ───────────────────────────────────────
    memory = MemorySaver()

    # interrupt_before : LangGraph suspend AVANT ces nœuds en mode HITL
    # (l'humain inspecte l'état puis relance avec app.invoke(None, config))
    app = graph.compile(
        checkpointer=memory,
        interrupt_before=["hitl_gate_a1", "hitl_gate_a2"] if enable_hitl else [],
    )

    logger.info(
        "[Graph] BIFlow graph compiled — sandbox=%s, hitl=%s",
        sandbox_mode, enable_hitl,
    )
    return app


# ---------------------------------------------------------------------------
# Helpers publics pour l'interface Streamlit / CLI
# ---------------------------------------------------------------------------

def make_initial_state(
    data_path: str,
    execution_mode: str = "auto",
    sandbox_mode: str = "inprocess",
    resource_mode: str = "auto",
) -> GraphState:
    """
    Crée un état initial propre pour un nouveau run du pipeline.

    Usage :
        state = make_initial_state(
            "data/raw/telco_churn.csv",
            execution_mode="hitl",
            resource_mode="local",
        )
        app   = build_graph()
        result = app.invoke(state, {"configurable": {"thread_id": "run_001"}})
    """
    return GraphState(
        data_path       = data_path,
        execution_mode  = execution_mode,   # type: ignore[arg-type]
        sandbox_mode    = sandbox_mode,     # type: ignore[arg-type]
        resource_mode   = resource_mode,    # type: ignore[arg-type]
        current_step    = "start",
        user_approval   = "approved",
        retry_count     = {},
        reports         = {},
        history_logs    = [],
        error_message   = "",
    )


def resume_hitl(
    app: Any,
    thread_config: Dict[str, Any],
    decision: Literal["approved", "rejected"] = "approved",
) -> GraphState:
    """
    Reprend un pipeline suspendu en mode HITL.

    Paramètres :
        app            : graphe compilé retourné par build_graph().
        thread_config  : {"configurable": {"thread_id": "..."}}.
        decision       : "approved" → avancer, "rejected" → retry l'agent courant.

    Retourne le nouvel état après reprise.
    """
    # On met à jour l'état avec la décision de l'utilisateur
    current = app.get_state(thread_config)
    app.update_state(
        thread_config,
        {"user_approval": decision},
    )
    # Relance depuis le checkpoint (None = reprendre là où on s'est arrêté)
    return app.invoke(None, thread_config)


def get_pipeline_summary(state: GraphState) -> Dict[str, Any]:
    """
    Construit un résumé lisible du pipeline pour affichage Streamlit.

    Retourne :
    {
        "status":         "success" | "error" | "in_progress",
        "current_step":   str,
        "steps_done":     [{"agent": str, "status": str, "duration_s": float}],
        "total_duration": float,
        "reports_available": [str],
    }
    """
    logs   = state.get("history_logs") or []
    step   = state.get("current_step", "start")
    status = (
        "error"       if step == "error"
        else "success" if step == "done"
        else "in_progress"
    )
    return {
        "status":        status,
        "current_step":  step,
        "steps_done": [
            {
                "agent":      e.get("agent"),
                "status":     e.get("status"),
                "duration_s": e.get("duration_s"),
            }
            for e in logs
        ],
        "total_duration":     round(sum(e.get("duration_s", 0) for e in logs), 2),
        "reports_available":  list((state.get("reports") or {}).keys()),
        "error_message":      state.get("error_message", ""),
    }


# ---------------------------------------------------------------------------
# CLI — exécution directe pour tests rapides
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    parser = argparse.ArgumentParser(description="BIFlow Multi-Agent Orchestrator")
    parser.add_argument("--data",    required=True, help="Chemin vers le dataset CSV")
    parser.add_argument("--mode",    default="auto",
                        choices=["auto", "hitl", "direct_agent_2", "direct_agent_3"],
                        help="Mode d'exécution du pipeline")
    parser.add_argument("--sandbox", default="inprocess",
                        choices=["docker", "inprocess"],
                        help="Mode de sandboxing pour les agents 2 et 3")
    args = parser.parse_args()

    print(f"\n🚀 BIFlow Orchestrator — mode={args.mode}, sandbox={args.sandbox}")
    print(f"   Dataset : {args.data}\n")

    app           = build_graph(sandbox_mode=args.sandbox)
    initial_state = make_initial_state(args.data, args.mode, args.sandbox)
    thread_cfg    = {"configurable": {"thread_id": f"biflow_{int(time.time())}"}}

    if args.mode == "hitl":
        # ── Mode HITL interactif ──────────────────────────────────────────────
        current = app.invoke(initial_state, thread_cfg)

        while True:
            snapshot   = app.get_state(thread_cfg)
            next_nodes = snapshot.next

            if not next_nodes:
                print("\n✅ Pipeline terminé.")
                break

            print(f"\n⏸  [HITL] Pause avant : {next_nodes}")
            summary = get_pipeline_summary(snapshot.values)
            for s in summary["steps_done"]:
                print(f"   ✓ {s['agent']:20s} {s['status']:10s} {s['duration_s']:.1f}s")

            choice = input("\n  Valider (v) / Refaire (r) / Arrêter (q) ? ").strip().lower()
            if choice == "q":
                print("❌ Arrêté par l'utilisateur.")
                break
            decision = "rejected" if choice == "r" else "approved"
            current  = resume_hitl(app, thread_cfg, decision)

    else:
        # ── Mode auto ou direct ───────────────────────────────────────────────
        final = app.invoke(initial_state, thread_cfg)
        summary = get_pipeline_summary(final)
        print(f"\nStatut  : {summary['status'].upper()}")
        print(f"Durée   : {summary['total_duration']}s")
        for s in summary["steps_done"]:
            icon = "✅" if s["status"] == "success" else "❌"
            print(f"  {icon}  {s['agent']:20s} {s['duration_s']:.1f}s")
        if summary["error_message"]:
            print(f"\nErreur  : {summary['error_message']}")
