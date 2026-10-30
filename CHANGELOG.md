# CHANGELOG — BIFlow Multi-Agent BI Platform

Toutes les modifications notables sont documentées ici.  
Format : [Version] — Date — Description

---

## [1.0.0] — Octobre 2026 — Release Majeure : Orchestration Multi-Agents Complète

### 🚀 Nouvelles fonctionnalités

#### Orchestration LangGraph (`orchestration/graph.py`)
- Implémentation complète du graphe LangGraph orchestrant les 3 agents en pipeline séquentiel.
- **4 modes d'exécution** configurables via `GraphState.execution_mode` :
  - `auto` — enchaînement automatique A1 → A2 → A3 sans interruption.
  - `hitl` — Human-in-the-Loop avec pause après chaque agent et boutons Valider / Retry.
  - `direct_agent_2` — démarrage direct à l'Agent 2 (dataset nettoyé pré-fourni).
  - `direct_agent_3` — démarrage direct à l'Agent 3 (rapport BI pré-fourni).
- **Retry borné** à 3 tentatives par agent en mode HITL via `retry_count`.
- **Sérialiseur msgpack** `_to_native()` — conversion automatique de tous les types NumPy en types Python natifs pour la compatibilité du checkpointing LangGraph.

#### Sélecteur de ressources LLM (`resource_mode`)
- Champ `resource_mode: "local" | "cloud" | "auto"` dans `GraphState`.
- Propagation complète depuis `3_Workflows.py` → `make_initial_state()` → nœuds A2 et A3.
- **Mode Cloud strict** : suppression de `OLLAMA_HOST` du process courant, `ollama_timeout=3s` pour éviter toute attente sur un endpoint désactivé.

#### Agent 3 — XAI Auditor (`agents/xai_auditor_agent.py`)
- Multi-engine LLM : Ollama local → Groq → Gemini → LLMClient → fallback déterministe.
- **Cascade SHAP** : TreeExplainer → LinearExplainer → KernelExplainer avec normalisation 3D→2D (correction du bug `ValueError: truth value of an array`).
- **Hashes SHA-256** : data, prédictions, audit — empreinte cryptographique de toute la chaîne.
- **Compliance status** : `COMPLIANT / PARTIAL / NON_COMPLIANT` dérivé automatiquement.

#### Sandbox Docker XAI (`docker/`)
- `docker/Dockerfile.xai` — image `python:3.10-slim` avec dépendances SHAP/SciPy.
- `docker/xai_sandbox_api.py` — serveur FastAPI sur le port `8003` avec endpoints `/health`, `/engine-status`, `/audit`.
- `docker-compose.yml` — service `xai_agent_sandbox`, clés injectées via `.env` (jamais hardcodées), volume `../data:/workspace/data:rw`.
- `_xai_docker()` dans `graph.py` : appel HTTP `POST /audit` vers le sandbox, fallback in-process automatique si le service n'est pas démarré.

#### Schémas I/O (`orchestration/schemas.py`)
- Modèles Pydantic v2 stricts pour chaque agent :
  - `DataEngineerOutput` — `cleaned_dataset_path`, `row_count`, `col_count`, `data_hash`, `overall_health_score`.
  - `BIAnalystOutput` — `summary_markdown`, `kpis`, `charts_data`, télémétrie sans clé.
  - `XAIAuditorOutput` — `shap_summary`, `integrity_hashes`, `narrative_explanation`, `compliance_status`.
- `validate_agent_output()` — utilitaire de validation non-bloquant (mode strict optionnel).

#### Générateur Mock (`orchestration/mock_generator.py`)
- Classe `MockGenerator` avec 3 domaines : `telecom`, `retail`, `finance`.
- Génération déterministe de datasets fictifs, outputs A1/A2/A3 et `GraphState` complets.
- Aucun LLM, aucune clé API, aucune dépendance réseau — 100% sandbox.

#### Cockpit Workflows (`dashboard/pages/3_Workflows.py`)
- Interface complète de pilotage du pipeline LangGraph avec stepper visuel.
- **HITL interactif** : affichage des livrables de chaque agent avec boutons Valider / Retry.
- **Sélecteur de ressources** : Local (Ollama) / Cloud (Groq/Gemini) / Hybride.
- **Bouton 🧪 Données Mock** : lancement direct A2 ou A3 sans fichier réel, avec sélecteur de domaine/lignes/graine.
- Statut Docker, statut Ollama (TTL 30s), statut clés Cloud (booléen uniquement — jamais la valeur).

#### Cockpit XAI (`dashboard/pages/6_Audit_XAI.py`)
- Refonte complète avec identité visuelle "Conformité & Gouvernance".
- Badge de conformité dynamique (`CERTIFIÉ COMPLIANT / AUDIT PARTIEL`).
- Graphique SHAP double couche : `st.bar_chart` natif + Plotly coloré par direction.
- Hashes SHA-256 tronqués (`8chars…4chars`) dans expander, jamais en affichage principal.
- Vérificateur SHA-256 manuel intégré.

---

### 🔒 Sécurité

- **Zéro clé API** dans les widgets Streamlit (`value=""`, badge statut uniquement).
- **Zéro hash brut** en UI principale (troncature systématique + expanders).
- **Sanitisation des erreurs** : chemins système masqués dans tous les messages d'erreur UI.
- **Sanitisation de l'export JSON** : champ `detail` des tentatives LLM retiré avant téléchargement.
- **Docker isolation** : réseau `none` en production, clés injectées via `docker-compose.yml` / `.env`.

---

### 🐛 Corrections de bugs

| Bug | Composant | Correction |
|---|---|---|
| `TypeError: numpy.float64 not msgpack serializable` | `orchestration/graph.py` | `_to_native()` — conversion récursive NumPy → Python natif |
| `ValueError: truth value of an array is ambiguous` | `agents/xai_auditor_agent.py` | SHAP 3D→2D normalisation + `bool(np.all(...))` explicite |
| `TypeError: XAIAuditorAgent.__init__() got unexpected keyword 'engine'` | `dashboard/pages/6_Audit_XAI.py` | Remplacement `@st.cache_resource` par session_state indexé |
| Ollama pingé en mode Cloud | `orchestration/graph.py` | `os.environ.pop("OLLAMA_HOST")` + `ollama_timeout=3` |
| `KeyError` sur datasets sans colonnes Telco | `test_pipeline_agents.py` | Refonte agnostique avec `select_dtypes` |

---

### 🏗️ Architecture

```
BIFlow/
├── agents/
│   ├── data_engineering_agent.py   # Agent 1 — Profiling, ETL, Qualité
│   ├── bi_analyst_agent.py         # Agent 2 — KPI, Tendances, Insights (LoRA + Cloud)
│   ├── xai_auditor_agent.py        # Agent 3 — SHAP, SHA-256, Audit (multi-engine)
│   └── llm_client.py               # Client LLM unifié (Ollama + Gemini)
├── orchestration/
│   ├── graph.py                    # Graphe LangGraph (4 modes, HITL, Docker)
│   ├── schemas.py                  # Schémas Pydantic I/O des 3 agents
│   └── mock_generator.py           # Générateur de données fictives pour tests
├── docker/
│   ├── Dockerfile.xai              # Image sandbox Agent 3
│   └── xai_sandbox_api.py          # API FastAPI port 8003
├── docker-compose.yml              # Orchestration Docker
├── dashboard/
│   └── pages/
│       ├── 3_Workflows.py          # Cockpit LangGraph (HITL, Mock, Engine selector)
│       ├── 5_BI_Analysis.py        # Interface Agent 2
│       └── 6_Audit_XAI.py         # Cockpit XAI (SHAP, SHA-256, Gouvernance)
└── test_pipeline_agents.py         # POC Pipeline agnostique (Streamlit standalone)
```

---

### ⚙️ Configuration requise

```bash
# Installation
pip install -r requirements.txt

# Variables d'environnement (.env)
GROQ_API_KEY=...          # Optionnel — mode Cloud
GEMINI_API_KEY=...        # Optionnel — mode Cloud fallback
XAI_ENGINE=auto           # local | cloud | auto

# Lancement dashboard
streamlit run dashboard/app.py

# Lancement sandbox XAI (Docker)
docker-compose up -d xai_agent_sandbox

# POC standalone (port 8520)
streamlit run test_pipeline_agents.py --server.port 8520
```

---

## [0.9.0] — Septembre 2026 — Fondations

- Pipeline BI initial avec Data Engineering Agent et BI Analyst Agent.
- Dashboard Streamlit multi-pages (Overview, Datasets, Data Quality, BI Analysis).
- Intégration Ollama locale (qwen2.5:7b).
- Tests unitaires : `test_cleaning.py`, `test_kpi.py`, `test_profiler.py`.
- Datasets : `telco_churn.csv`, `dirty_sales_test.csv`.

---

*BIFlow — Transform Data into Decisions.*
