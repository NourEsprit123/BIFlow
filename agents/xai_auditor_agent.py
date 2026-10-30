"""
XAI Auditor Agent — Explainability, Traceability & Audit for BIFlow.
Supports:
1. SHAP-based feature attribution (TreeExplainer → LinearExplainer → KernelExplainer).
2. SHA-256 integrity hashing of prediction artefacts for full traceability.
3. Multi-engine LLM explanation (mirrors BIAnalystAgent routing):
   - 'local'  : Ollama local (Qwen 2.5:7b) — private, offline.
   - 'api'    : Cloud APIs — Groq → Gemini → LLMClient cascade.
   - 'auto'   : tries Ollama first, falls back to Cloud API, then deterministic.
4. Deterministic text fallback so the audit NEVER produces an empty report.
5. Structured audit trail (timestamp, SHA-256 hashes, SHAP table, narrative).

Usage:
    agent = XAIAuditorAgent(engine="auto")
    report = agent.audit(model=clf, X=df_features, dataset_name="telco")
"""

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OLLAMA_URL     = "http://localhost:11434/api/generate"
OLLAMA_MODEL   = "qwen2.5:7b"
OLLAMA_TIMEOUT = 120  # seconds

XAI_SYSTEM_PROMPT = (
    "You are the XAI Auditor Agent of the BIFlow enterprise platform. "
    "Your role is to produce clear, accessible explanations of machine-learning "
    "model predictions and their SHAP feature attributions for both technical "
    "and non-technical business stakeholders. "
    "Be precise, structured, and always cite specific feature names and SHAP magnitudes."
)

# Substrings that identify non-chat models in provider model lists
_NON_CHAT_MARKERS = (
    "whisper", "tts", "guard", "playai", "orpheus", "embed", "image",
    "audio", "live", "robotics", "computer-use", "transcribe", "imagen", "veo",
)


# ---------------------------------------------------------------------------
# XAIAuditorAgent
# ---------------------------------------------------------------------------

class XAIAuditorAgent:
    """
    Agent XAI / Auditeur de BIFlow.

    Paramètre engine :
        'local' — Ollama uniquement (offline, privé).
        'api'   — Cloud APIs Groq → Gemini → LLMClient.
        'auto'  — Ollama d'abord, puis Cloud si échec, puis fallback déterministe.
    """

    def __init__(
        self,
        engine: str = "auto",
        # ── Ollama (moteur local)
        ollama_url: str = OLLAMA_URL,
        ollama_model: str = OLLAMA_MODEL,
        ollama_timeout: int = OLLAMA_TIMEOUT,
        # ── Cloud APIs
        groq_api_key: Optional[str] = None,
        groq_model: Optional[str] = None,
    ):
        self.engine        = engine.lower()
        self.ollama_url    = ollama_url
        self.ollama_model  = ollama_model
        self.ollama_timeout = ollama_timeout

        self.groq_api_key  = groq_api_key or os.environ.get("GROQ_API_KEY")
        self.groq_model    = groq_model   or os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.gemini_api_key = (
            os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        )

        # Initialiser le client Groq si la clé est disponible
        self.groq_client = None
        if self.groq_api_key:
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=self.groq_api_key)
            except Exception as e:
                logger.warning(f"[XAI] Groq client init failed: {e}")

        self._reset_telemetry()

    # -------------------------------------------------------------------------
    # Telemetry — même convention que BIAnalystAgent
    # -------------------------------------------------------------------------

    def _reset_telemetry(self) -> None:
        self.last_provider   = "Unknown"
        self.last_model      = "-"
        self.last_is_llm     = False
        self.last_duration_s = 0.0
        self.last_engine_used: Optional[str] = None
        self.attempts: List[Dict[str, str]] = []

    def _log_attempt(self, provider: str, model: str, status: str, detail: str = "") -> None:
        self.attempts.append({
            "provider": provider,
            "model":    model,
            "status":   status,
            "detail":   str(detail)[:300],
        })

    def _set_result(self, provider: str, model: str, is_llm: bool = True) -> None:
        self.last_provider = provider
        self.last_model    = model
        self.last_is_llm   = is_llm

    def get_telemetry(self) -> Dict[str, Any]:
        return {
            "provider":     self.last_provider,
            "model":        self.last_model,
            "is_llm":       self.last_is_llm,
            "engine_used":  self.last_engine_used,
            "duration_s":   self.last_duration_s,
            "attempts":     self.attempts,
        }

    # -------------------------------------------------------------------------
    # 1. SHA-256 integrity hashing
    # -------------------------------------------------------------------------

    def compute_sha256(self, data: Any) -> str:
        """
        Hache n'importe quel artefact (str, bytes, ndarray, DataFrame, dict…)
        et retourne l'empreinte hexadécimale SHA-256 (64 caractères).
        """
        if isinstance(data, bytes):
            raw = data
        elif isinstance(data, str):
            raw = data.encode("utf-8")
        elif isinstance(data, np.ndarray):
            raw = data.tobytes()
        elif isinstance(data, pd.DataFrame):
            raw = data.to_csv(index=False).encode("utf-8")
        elif isinstance(data, pd.Series):
            raw = data.to_csv(index=True).encode("utf-8")
        else:
            raw = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    # -------------------------------------------------------------------------
    # 2. SHAP feature attributions
    # -------------------------------------------------------------------------

    def compute_shap_values(
        self,
        model: Any,
        X: pd.DataFrame,
        max_background_samples: int = 50,
    ) -> Tuple[Optional[np.ndarray], str]:
        """
        Cascade TreeExplainer → LinearExplainer → KernelExplainer.
        Retourne (shap_values, explainer_type_str).
        """
        try:
            import shap
        except ImportError:
            logger.error("'shap' not installed. Run: pip install shap")
            return None, "shap_not_installed"

        X_array = X.values if isinstance(X, pd.DataFrame) else np.array(X)

        # TreeExplainer — arbres (RF, XGBoost, LightGBM…)
        try:
            explainer = shap.TreeExplainer(model)
            sv = explainer.shap_values(X_array)
            # Normaliser toutes les formes possibles vers (n_samples, n_features) 2D :
            # - list de 2 arrays [class0, class1]  → prendre class 1
            # - ndarray 3D (n_samples, n_features, n_classes) → slice [:, :, 1]
            # - ndarray 2D (n_samples, n_features)            → garder tel quel
            if isinstance(sv, list):
                sv = sv[1] if len(sv) == 2 else sv[0]
            sv = np.array(sv)
            if sv.ndim == 3:
                sv = sv[:, :, 1]   # (n_samples, n_features, n_classes) → classe 1
            if sv.ndim != 2:
                raise ValueError(f"Unexpected SHAP shape after normalisation: {sv.shape}")
            logger.info("[XAI-SHAP] TreeExplainer OK — shape %s.", sv.shape)
            return sv, "TreeExplainer"
        except Exception as e:
            logger.debug(f"[XAI-SHAP] TreeExplainer failed: {e}")

        # LinearExplainer — modèles linéaires
        try:
            explainer = shap.LinearExplainer(model, X_array)
            sv = explainer.shap_values(X_array)
            sv = np.array(sv)
            if sv.ndim == 3:
                sv = sv[:, :, 1]
            logger.info("[XAI-SHAP] LinearExplainer OK.")
            return sv, "LinearExplainer"
        except Exception as e:
            logger.debug(f"[XAI-SHAP] LinearExplainer failed: {e}")

        # KernelExplainer — fallback universel
        try:
            n_bg = min(max_background_samples, len(X_array))
            background = shap.sample(X_array, n_bg)
            predict_fn = (
                model.predict_proba if hasattr(model, "predict_proba") else model.predict
            )
            explainer = shap.KernelExplainer(predict_fn, background)
            sv = explainer.shap_values(X_array, nsamples=100)
            if isinstance(sv, list):
                sv = sv[1] if len(sv) == 2 else sv[0]
            sv = np.array(sv)
            if sv.ndim == 3:
                sv = sv[:, :, 1]
            logger.info("[XAI-SHAP] KernelExplainer OK.")
            return sv, "KernelExplainer"
        except Exception as e:
            logger.error(f"[XAI-SHAP] All explainers failed: {e}")
            return None, f"failed ({e})"

    def _build_shap_summary(
        self,
        shap_values: np.ndarray,
        feature_names: List[str],
        top_n: int = 10,
    ) -> Dict[str, Any]:
        # Garantir que shap_values est strictement 2D (n_samples, n_features)
        # au cas où un explainer retournerait un array de forme inattendue
        sv = np.array(shap_values)
        if sv.ndim == 3:
            sv = sv[:, :, 1]   # (n, f, classes) → classe positive
        if sv.ndim != 2:
            sv = sv.reshape(len(sv), -1)

        mean_abs = np.abs(sv).mean(axis=0)      # shape (n_features,) garanti
        ranking  = np.argsort(mean_abs)[::-1]   # shape (n_features,)

        top_features = []
        for rank, idx in enumerate(ranking[:top_n]):
            # Forcer idx en int Python pur — élimine toute ambiguïté numpy
            i = int(idx)
            fname = feature_names[i] if i < len(feature_names) else f"feature_{i}"
            top_features.append({
                "rank":               rank + 1,
                "feature":            fname,
                "mean_abs_shap":      float(round(mean_abs[i], 6)),
                "direction_sample_0": "positive" if float(sv[0, i]) >= 0 else "negative",
            })

        return {
            "n_samples":            int(sv.shape[0]),
            "n_features":           int(sv.shape[1]),
            "top_features":         top_features,
            "global_mean_abs_shap": float(round(float(mean_abs.mean()), 6)),
        }

    # -------------------------------------------------------------------------
    # 3. LLM explanation — multi-engine routing
    # -------------------------------------------------------------------------

    def _build_explanation_prompt(
        self,
        shap_summary: Dict[str, Any],
        predictions: np.ndarray,
        integrity_hash: str,
        dataset_name: str,
    ) -> str:
        """Construit le prompt commun utilisé par tous les moteurs LLM."""
        top_f = shap_summary.get("top_features", [])
        top_lines = "\n".join(
            f"  {f['rank']}. {f['feature']:30s}  mean |SHAP| = {f['mean_abs_shap']:.6f}"
            f"  direction = {f['direction_sample_0']}"
            for f in top_f
        )

        # BUG-03 fix — séparer binaire vs continu
        pred_flat = np.array(predictions, dtype=float).flatten()
        _is_binary_int = bool(np.all((pred_flat == 0) | (pred_flat == 1)))
        if _is_binary_int:
            unique_p, counts_p = np.unique(pred_flat, return_counts=True)
            pred_dist_str = ", ".join(
                f"class {int(k)}: {int(v)} ({int(v)/len(pred_flat)*100:.1f}%)"
                for k, v in zip(unique_p, counts_p)
            )
        else:
            pred_dist_str = (
                f"min={pred_flat.min():.4f}, max={pred_flat.max():.4f}, "
                f"mean={pred_flat.mean():.4f}, median={float(np.median(pred_flat)):.4f}"
            )

        return (
            f"Dataset analysé         : {dataset_name}\n"
            f"Observations            : {len(predictions)}\n"
            f"Distribution prédictions: {pred_dist_str}\n"
            f"Explainer SHAP          : {shap_summary.get('explainer_type', 'N/A')}\n"
            f"Hash SHA-256 (audit)    : {integrity_hash[:16]}…\n\n"
            f"--- Top {len(top_f)} features SHAP ---\n"
            f"{top_lines}\n\n"
            "Produis une explication structurée en Markdown :\n"
            "1. **Résumé exécutif** — ce que le modèle prédit et avec quelle confiance.\n"
            "2. **Analyse des features dominantes** — ampleur, direction, sens métier.\n"
            "3. **Risques & biais potentiels** — features à surveiller.\n"
            "4. **Recommandations audit** — actions pour améliorer équité et transparence.\n"
            "Sois précis, professionnel, cite les noms de features exacts."
        )

    # ── Moteur local : Ollama ─────────────────────────────────────────────────

    def _try_ollama(self, user_message: str) -> Optional[str]:
        """Appelle l'instance Ollama locale en streaming NDJSON."""
        # Fast health check (1.5s) pour éviter un freeze de 120s quand Ollama est hors ligne
        ping_url = self.ollama_url.rsplit("/", 1)[0] + "/tags"
        try:
            r_ping = requests.get(ping_url, timeout=1.5)
            if r_ping.status_code != 200:
                self._log_attempt("Ollama", self.ollama_model, "skipped", "Ollama server not ready")
                return None
        except Exception:
            self._log_attempt("Ollama", self.ollama_model, "skipped", "Ollama server offline")
            return None

        payload = {
            "model":  self.ollama_model,
            "system": XAI_SYSTEM_PROMPT,
            "prompt": user_message,
            "stream": True,
        }
        try:
            resp = requests.post(
                self.ollama_url, json=payload,
                timeout=self.ollama_timeout, stream=True
            )
            resp.raise_for_status()

            collected: List[str] = []
            for raw_line in resp.iter_lines():
                if raw_line:
                    try:
                        chunk = json.loads(raw_line.decode("utf-8"))
                        collected.append(chunk.get("response", ""))
                        if chunk.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue

            text = "".join(collected).strip()
            if text and len(text) > 50:
                self._log_attempt("Ollama", self.ollama_model, "success")
                self._set_result("🦙 Ollama (local)", self.ollama_model, is_llm=True)
                self.last_engine_used = "local"
                return text

            self._log_attempt("Ollama", self.ollama_model, "failed", "empty / too short response")
            return None

        except requests.exceptions.ConnectionError:
            self._log_attempt("Ollama", self.ollama_model, "failed", "ConnectionError")
            logger.warning(f"[XAI] Ollama not reachable at {self.ollama_url}")
            return None
        except requests.exceptions.Timeout:
            self._log_attempt("Ollama", self.ollama_model, "failed",
                              f"Timeout after {self.ollama_timeout}s")
            logger.warning("[XAI] Ollama timeout.")
            return None
        except requests.exceptions.RequestException as exc:
            self._log_attempt("Ollama", self.ollama_model, "failed", str(exc))
            return None

    # ── Moteur cloud : Groq ───────────────────────────────────────────────────

    def _groq_candidate_models(self) -> List[str]:
        preferred = [
            self.groq_model,
            "llama-3.3-70b-versatile",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "llama-3.1-8b-instant",
        ]
        available: List[str] = []
        try:
            listing = self.groq_client.models.list()
            available = [
                m.id for m in listing.data
                if not any(x in m.id.lower() for x in _NON_CHAT_MARKERS)
            ]
        except Exception as e:
            self._log_attempt("Groq", "models.list()", "failed", str(e))

        ordered = [m for m in preferred if m in available] if available else list(preferred)
        ordered += [m for m in available if m not in ordered]
        seen, unique = set(), []
        for m in ordered:
            if m and m not in seen:
                seen.add(m); unique.append(m)
        return unique[:5]

    def _try_groq(self, prompt: str) -> Optional[str]:
        if not self.groq_client:
            self._log_attempt(
                "Groq", "-", "skipped",
                "no API key" if not self.groq_api_key else "groq package not installed",
            )
            return None

        for m in self._groq_candidate_models():
            try:
                response = self.groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": XAI_SYSTEM_PROMPT},
                        {"role": "user",   "content": prompt},
                    ],
                    model=m,
                    temperature=0.2,
                    max_tokens=4000,
                )
                text = response.choices[0].message.content
                if text and len(text.strip()) > 50:
                    self._log_attempt("Groq", m, "success")
                    self._set_result("☁️ Groq", m)
                    self.last_engine_used = "api"
                    return text
                self._log_attempt("Groq", m, "failed", "empty / too short")
            except Exception as e:
                logger.warning(f"[XAI] Groq model {m} failed: {e}")
                self._log_attempt("Groq", m, "failed", str(e))
        return None

    # ── Moteur cloud : Gemini ─────────────────────────────────────────────────

    def _gemini_candidate_models(self, client: Any) -> List[str]:
        names: List[str] = []
        try:
            for m in client.models.list():
                name    = getattr(m, "name", "") or ""
                actions = getattr(m, "supported_actions", None) or []
                if actions and "generateContent" not in actions:
                    continue
                short = name.replace("models/", "")
                low   = short.lower()
                if "gemini" not in low or any(x in low for x in _NON_CHAT_MARKERS):
                    continue
                names.append(short)
        except Exception as e:
            self._log_attempt("Gemini", "models.list()", "failed", str(e))
            return []

        def sort_key(n: str):
            low = n.lower()
            return (
                0 if "flash" in low and "lite" not in low else 1,
                1 if ("preview" in low or "exp" in low) else 0,
                [-ord(c) for c in n],
            )
        names.sort(key=sort_key)
        return names[:3]

    def _try_gemini(self, prompt: str) -> Optional[str]:
        if not self.gemini_api_key:
            self._log_attempt("Gemini", "-", "skipped", "no GEMINI_API_KEY")
            return None
        try:
            from google import genai
        except Exception as e:
            self._log_attempt("Gemini", "-", "skipped", f"google-genai not installed: {e}")
            return None
        try:
            client = genai.Client(api_key=self.gemini_api_key)
        except Exception as e:
            self._log_attempt("Gemini", "-", "failed", f"client init: {e}")
            return None

        for m in self._gemini_candidate_models(client):
            try:
                resp = client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config={
                        "system_instruction": XAI_SYSTEM_PROMPT,
                        "temperature":        0.2,
                        "max_output_tokens":  4096,
                    },
                )
                text = getattr(resp, "text", None)
                if text and len(text.strip()) > 50:
                    self._log_attempt("Gemini", m, "success")
                    self._set_result("☁️ Google Gemini", m)
                    self.last_engine_used = "api"
                    return text
                self._log_attempt("Gemini", m, "failed", "empty / too short")
            except Exception as e:
                logger.warning(f"[XAI] Gemini model {m} failed: {e}")
                self._log_attempt("Gemini", m, "failed", str(e))
        return None

    # ── Moteur cloud : LLMClient (dernier recours) ────────────────────────────

    def _try_llm_client(self, prompt: str) -> Optional[str]:
        try:
            from agents.llm_client import LLMClient
            llm  = LLMClient()
            resp = llm.generate_text(prompt, system_prompt=XAI_SYSTEM_PROMPT)
            if resp and resp.strip() and resp.strip() != "{}":
                provider = (getattr(llm, "provider", None) or "provider not reported")
                model    = (getattr(llm, "model", None) or "-")
                self._log_attempt("LLMClient", f"{provider}/{model}", "success")
                self._set_result(f"☁️ LLMClient ({provider})", str(model))
                self.last_engine_used = "api"
                return resp
            self._log_attempt("LLMClient", "-", "failed", "empty response")
        except Exception as e:
            logger.warning(f"[XAI] LLMClient failed: {e}")
            self._log_attempt("LLMClient", "-", "failed", str(e))
        return None

    # ── Fallback déterministe ─────────────────────────────────────────────────

    def _deterministic_fallback(self) -> str:
        """Explication texte sans LLM — garantit que le rapport n'est jamais vide."""
        self._set_result("📊 Deterministic Fallback", "pandas/numpy", is_llm=False)
        self.last_engine_used = "fallback"
        return (
            "**[Mode déterministe — aucun LLM disponible]**\n\n"
            "L'explication en langage naturel n'a pas pu être générée. "
            "Les attributions SHAP et les hashes SHA-256 restent pleinement valides "
            "et ont été calculés de manière déterministe à partir des données.\n\n"
            "Pour activer les explications narratives :\n"
            "- **Local** : démarrez Ollama avec `ollama serve` et assurez-vous que "
            f"`{self.ollama_model}` est disponible.\n"
            "- **Cloud** : configurez `GROQ_API_KEY` ou `GEMINI_API_KEY` dans votre `.env`."
        )

    # ── Point d'entrée de l'explication ──────────────────────────────────────

    def explain_with_llm(
        self,
        shap_summary: Dict[str, Any],
        predictions: np.ndarray,
        integrity_hash: str,
        dataset_name: str = "dataset",
    ) -> str:
        """
        Route l'explication vers le bon moteur selon self.engine.
        Ordre auto : Ollama → Groq → Gemini → LLMClient → fallback déterministe.
        """
        prompt = self._build_explanation_prompt(
            shap_summary, predictions, integrity_hash, dataset_name
        )

        engine = self.engine

        # ── Mode 'local' — Ollama seulement ──────────────────────────────────
        if engine == "local":
            result = self._try_ollama(prompt)
            return result if result else self._deterministic_fallback()

        # ── Mode 'api' — Cloud seulement ─────────────────────────────────────
        if engine == "api":
            for route in (self._try_groq, self._try_gemini, self._try_llm_client):
                result = route(prompt)
                if result:
                    return result
            return self._deterministic_fallback()

        # ── Mode 'auto' — Ollama en premier, puis Cloud ───────────────────────
        result = self._try_ollama(prompt)
        if result:
            return result
        for route in (self._try_groq, self._try_gemini, self._try_llm_client):
            result = route(prompt)
            if result:
                return result
        return self._deterministic_fallback()

    # -------------------------------------------------------------------------
    # 4. Main audit entry point
    # -------------------------------------------------------------------------

    def audit(
        self,
        model: Any,
        X: pd.DataFrame,
        predictions: Optional[np.ndarray] = None,
        feature_names: Optional[List[str]] = None,
        dataset_name: str = "dataset",
        top_n_features: int = 10,
    ) -> Dict[str, Any]:
        """
        Orchestre l'audit complet en 4 étapes :
        1. Prédictions (calculées si non fournies).
        2. Hashes SHA-256 (data, prédictions, audit).
        3. Attributions SHAP (TreeExplainer → LinearExplainer → KernelExplainer).
        4. Explication en langage naturel (moteur sélectionné par self.engine).

        Retourne un dict structuré avec les clés :
        timestamp, dataset_name, n_samples, n_features, engine_used,
        integrity, shap, predictions_distribution, narrative_explanation, telemetry.
        """
        self._reset_telemetry()
        start = time.time()

        if feature_names is None:
            feature_names = (
                list(X.columns) if isinstance(X, pd.DataFrame)
                else [f"feature_{i}" for i in range(X.shape[1])]
            )

        # ── Étape 1 : prédictions ─────────────────────────────────────────────
        if predictions is None:
            try:
                raw_preds = (
                    model.predict_proba(X)
                    if hasattr(model, "predict_proba")
                    else model.predict(X)
                )
                # predict_proba retourne (n, k) — on prend la colonne classe 1
                # pour binaire, ou on aplatit pour régression/predict
                if hasattr(raw_preds, "ndim") and raw_preds.ndim == 2:
                    predictions = raw_preds[:, 1]
                else:
                    predictions = raw_preds
            except Exception as e:
                logger.error(f"[XAI] Prediction failed: {e}")
                predictions = np.zeros(len(X))
        predictions = np.array(predictions, dtype=float).flatten()

        # ── Étape 2 : SHA-256 ────────────────────────────────────────────────
        data_hash   = self.compute_sha256(X)
        pred_hash   = self.compute_sha256(predictions)
        audit_hash  = self.compute_sha256({
            "data_hash": data_hash,
            "predictions_hash": pred_hash,
            "dataset_name": dataset_name,
        })
        integrity = {
            "data_hash":         data_hash,
            "predictions_hash":  pred_hash,
            "audit_hash":        audit_hash,
        }

        # ── Étape 3 : SHAP ───────────────────────────────────────────────────
        shap_values, explainer_type = self.compute_shap_values(model, X)
        shap_block: Dict[str, Any] = {"explainer_type": explainer_type, "summary": {}}
        if shap_values is not None:
            shap_block["summary"] = self._build_shap_summary(
                shap_values, feature_names, top_n=top_n_features
            )
        else:
            logger.warning("[XAI] SHAP values unavailable — partial report.")

        # ── Étape 4 : explication LLM ────────────────────────────────────────
        narrative = self.explain_with_llm(
            shap_summary={**shap_block["summary"], "explainer_type": explainer_type},
            predictions=predictions,
            integrity_hash=audit_hash,
            dataset_name=dataset_name,
        )

        self.last_duration_s = round(time.time() - start, 2)

        # Distribution des prédictions
        # Garantir un array 1D de float avant toute comparaison booléenne
        pred_flat = np.array(predictions, dtype=float).flatten()
        # Classifier comme "binaire entier" seulement si TOUTES les valeurs
        # sont exactement 0 ou 1 — bool() sur un scalaire numpy, pas sur l'array
        _is_binary_int = bool(np.all((pred_flat == 0) | (pred_flat == 1)))
        if _is_binary_int:
            unique_p, counts_p = np.unique(pred_flat, return_counts=True)
            pred_dist = {
                str(int(k)): {
                    "count": int(v),
                    "pct":   round(int(v) / len(pred_flat) * 100, 2),
                }
                for k, v in zip(unique_p, counts_p)
            }
        else:
            pred_dist = {
                "min":    float(round(pred_flat.min(), 4)),
                "max":    float(round(pred_flat.max(), 4)),
                "mean":   float(round(pred_flat.mean(), 4)),
                "median": float(round(float(np.median(pred_flat)), 4)),
            }

        audit_report = {
            "timestamp":               datetime.now(timezone.utc).isoformat(),
            "dataset_name":            dataset_name,
            "n_samples":               int(len(X)),
            "n_features":              int(len(feature_names)),
            "engine_used":             self.last_engine_used,
            "integrity":               integrity,
            "shap":                    shap_block,
            "predictions_distribution": pred_dist,
            "narrative_explanation":   narrative,
            "telemetry":               self.get_telemetry(),
        }

        logger.info(
            f"[XAI] Audit done in {self.last_duration_s}s — "
            f"explainer={explainer_type}, engine={self.last_engine_used}, "
            f"provider={self.last_provider}"
        )
        return audit_report

    # -------------------------------------------------------------------------
    # 5. Markdown report formatter
    # -------------------------------------------------------------------------

    def format_audit_report(self, audit_report: Dict[str, Any]) -> str:
        ts         = audit_report.get("timestamp", "N/A")
        ds         = audit_report.get("dataset_name", "N/A")
        n_s        = audit_report.get("n_samples", 0)
        n_f        = audit_report.get("n_features", 0)
        engine     = audit_report.get("engine_used", "N/A")
        integrity  = audit_report.get("integrity", {})
        shap_block = audit_report.get("shap", {})
        summary    = shap_block.get("summary", {})
        top_f      = summary.get("top_features", [])
        pred_dist  = audit_report.get("predictions_distribution", {})
        narrative  = audit_report.get("narrative_explanation", "")
        telemetry  = audit_report.get("telemetry", {})

        lines = [
            "# 🔍 Rapport d'Audit XAI — BIFlow",
            "",
            f"**Dataset**         : `{ds}`",
            f"**Timestamp (UTC)** : `{ts}`",
            f"**Observations**    : {n_s:,}",
            f"**Features**        : {n_f}",
            f"**Moteur LLM**      : {engine}",
            "",
            "---",
            "## 🔐 Intégrité SHA-256",
            "",
            f"- **Data hash**        : `{integrity.get('data_hash', 'N/A')}`",
            f"- **Predictions hash** : `{integrity.get('predictions_hash', 'N/A')}`",
            f"- **Audit hash**       : `{integrity.get('audit_hash', 'N/A')}`",
            "",
            "---",
            "## 📊 Attributions SHAP",
            "",
            f"**Explainer** : `{shap_block.get('explainer_type', 'N/A')}`",
            f"**Mean |SHAP| global** : `{summary.get('global_mean_abs_shap', 'N/A')}`",
            "",
        ]

        if top_f:
            lines += [
                f"### Top {len(top_f)} features",
                "",
                "| Rang | Feature | Mean \\|SHAP\\| | Direction |",
                "|------|---------|-------------|-----------|",
            ]
            for f in top_f:
                lines.append(
                    f"| {f['rank']} | `{f['feature']}` | "
                    f"{f['mean_abs_shap']:.6f} | {f['direction_sample_0']} |"
                )
            lines.append("")

        lines += ["---", "## 📈 Distribution des prédictions", ""]
        for k, v in pred_dist.items():
            if isinstance(v, dict):
                lines.append(
                    f"- **Classe {k}** : {v.get('count', 0):,} obs. ({v.get('pct', 0)}%)"
                )
            else:
                lines.append(f"- **{k}** : {v}")

        lines += [
            "",
            "---",
            "## 💬 Explication narrative",
            "",
            narrative,
            "",
            "---",
            "## ⚙️ Télémétrie",
            "",
            f"- **Fournisseur** : {telemetry.get('provider', 'N/A')}",
            f"- **Modèle**      : `{telemetry.get('model', 'N/A')}`",
            f"- **LLM actif**   : {'✅' if telemetry.get('is_llm') else '❌ fallback déterministe'}",
            f"- **Durée**       : {telemetry.get('duration_s', 0)}s",
            "",
        ]
        return "\n".join(lines)

    def __str__(self)  -> str: return f"XAIAuditorAgent(engine={self.engine}, model={self.ollama_model})"
    def __repr__(self) -> str: return self.__str__()
