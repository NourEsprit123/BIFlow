# 📊 BIFlow — Intelligent Business Intelligence, Multi-Agent AI System

> **Transform Data into Decisions**

BIFlow transforme un fichier de données brut en analyses BI expliquées, grâce à **quatre agents spécialisés** enchaînés dans un pipeline LangGraph et pilotés depuis une interface Streamlit.

```text
  Dataset brut (data/raw)
        │
        ▼
 ┌────────────────────┐   rapport de profilage    ┌────────────────────┐
 │ 1. Data Profiling  │ ────────────────────────▶ │ 2. Data Cleaning   │
 │ profil, qualité,   │                           │ nettoyage versionné│
 │ plan d'imputation  │                           │ validé et tracé    │
 └────────────────────┘                           └─────────┬──────────┘
                                                            │ data/cleaned/<dataset>_cleaned.csv
                                                            ▼
                         ┌────────────────────┐   ┌────────────────────┐
                         │ 4. XAI Auditor     │ ◀─│ 3. BI Analyst      │
                         │ SHAP, audit,       │   │ KPIs, graphiques,  │
                         │ explications       │   │ recommandations    │
                         └────────────────────┘   └────────────────────┘
```

| Agent | Rôle | Moteur LLM | Code principal |
| --- | --- | --- | --- |
| 1 · Data Profiling | Statistiques déterministes, contrôles qualité, interprétation LLM, rapport de profilage (types cibles, valeurs manquantes, anomalies, plan d'imputation) | Ollama local ou Gemini (`LLM_PROVIDER`) | `agents/data_engineering_agent.py` |
| 2 · Data Cleaning | Nettoyage piloté par le rapport : une tâche à la fois, outils contrôlés, code généré exécuté seulement dans Docker, chaque changement testé puis versionné | Ollama local (expert Groq optionnel) | `agents/dataCleaning_agent.py`, `dataCleaningTools/` |
| 3 · BI Analyst | KPIs, graphiques et recommandations sur le dataset **nettoyé** | Qwen 2.5 3B fine-tuné (LoRA, GPU) ou API cloud Groq/Gemini | `agents/bi_analyst_agent.py` |
| 4 · XAI Auditor | Explicabilité SHAP, empreintes SHA-256, rapport d'audit | Ollama local ou Groq/Gemini | `agents/xai_auditor_agent.py` |

L'orchestration est dans `orchestration/graph.py` ; l'interface dans `dashboard/`.

---

## ✅ Prérequis

| Outil | Obligatoire ? | Utilisé par |
| --- | --- | --- |
| **Python 3.11+** (testé avec 3.12) | Oui | Tout le projet |
| **Git** | Oui | Récupérer le projet |
| **[Ollama](https://ollama.com/download)** | Oui | Agent 2 (nettoyage) ; agent 1 et 4 en mode local |
| **Docker Desktop** (conteneurs Linux) | Fortement recommandé | Bac à sable du code généré par l'agent 2 |
| Clé **Gemini** | Optionnel | Agent 1 avec `LLM_PROVIDER=gemini` |
| Clé **Groq** | Recommandé | Agents 3 et 4 en mode cloud ; expert de l'agent 2 |
| GPU NVIDIA + poids LoRA | Optionnel | Agent 3 en mode local |

Sans Docker, le nettoyage fonctionne avec les opérations intégrées, mais le code généré par le modèle n'est jamais exécuté (pas de repli sur la machine hôte).

---

## 🚀 Installation et lancement (pas à pas)

Toutes les commandes se lancent **depuis la racine du projet** (le dossier qui contient `README.md`). Exemples pour Windows PowerShell.

### 1. Cloner le projet

```powershell
git clone https://github.com/NourEsprit123/BIFlow.git
cd BIFlow
```

### 2. Créer l'environnement Python et installer les dépendances

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Si PowerShell bloque l'activation : `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`, puis réactiver.

### 3. Configurer `.env`

```powershell
Copy-Item .env.example .env
```

Ouvrez `.env` et renseignez au minimum :

* `OLLAMA_MODEL` et `BIFLOW_CLEANING_OLLAMA_MODEL` : les modèles Ollama installés à l'étape 4 ;
* `GROQ_API_KEY` : pour le BI Analyst et le XAI Auditor en mode cloud ;
* `GEMINI_API_KEY` et `LLM_PROVIDER=gemini` si vous voulez le profilage via Gemini.

Ne commitez jamais `.env` (il est ignoré par Git). Si vous avez déjà un `.env`, ne l'écrasez pas : ajoutez seulement les nouvelles variables de `.env.example`.

### 4. Installer les modèles Ollama

Démarrez Ollama, puis téléchargez les modèles indiqués dans `.env` :

```powershell
ollama pull qwen2.5:7b
```

L'agent de nettoyage a été évalué avec `qwen3:8b` (`ollama pull qwen3:8b`, puis `BIFLOW_CLEANING_OLLAMA_MODEL=qwen3:8b`). Vérifiez avec `ollama list`.

### 5. Construire le bac à sable Docker du nettoyage

Démarrez Docker Desktop, puis :

```powershell
docker build -t biflow-cleaning-sandbox:latest -f sandbox/Dockerfile sandbox
```

À faire une seule fois par machine. L'image doit correspondre à `BIFLOW_EXPERIMENT_IMAGE` dans `.env`.

### 6. Lancer l'application

```powershell
streamlit run dashboard/app.py
```

Ouvrez <http://localhost:8501>. Lancez toujours Streamlit depuis la racine du projet : sinon le thème et la configuration de `.streamlit/` ne sont pas chargés.

### 7. Premier passage complet

1. **Créez un compte** (Sign up), puis connectez-vous. Les comptes sont stockés localement dans `data/biflow_auth.sqlite3`.
2. **Choisissez un dataset** : 15 jeux d'exemple sont fournis dans `data/raw/`, ou importez un CSV, Excel ou Parquet depuis la page **Datasets**.
3. Ouvrez **Workflows**, choisissez **qui prend les décisions de nettoyage** (voir plus bas), puis lancez le pipeline.
4. Suivez les quatre étapes dans la barre du haut : Data Profiling → Data Cleaning → BI Analyst → XAI Auditor.
5. Si le nettoyage attend votre avis, validez les changements et décisions dans le panneau du nettoyage ; le dataset nettoyé est republié et le BI Analyst l'utilise automatiquement.

Chaque agent peut aussi être lancé seul depuis sa page.

---

## 🧭 L'interface

| Page | Contenu |
| --- | --- |
| Overview | Vue d'ensemble du dataset actif et activité des agents |
| Datasets | Import, aperçu et choix du dataset actif ; liste des datasets bruts et nettoyés |
| Workflows | Lancement du pipeline complet, choix du mode de décision |
| Profiling / Quality | Agent 1 : profil, problèmes de qualité, rapport (régénérable) |
| Cleaning | Agent 2 : progression en direct, résultat validé, approbations, décisions, rapports |
| BI Analysis | Agent 3 : KPIs et graphiques sur le dataset nettoyé, choix local LoRA / cloud |
| Audit XAI | Agent 4 : explications SHAP et audit |

### Modes de décision du nettoyage

Près du bouton de lancement (Workflows et Cleaning) :

* **Rester dans la boucle** (par défaut) : les changements sensibles (valeurs aberrantes, suppression de doublons par clé métier) attendent votre approbation ; les points que l'agent ne peut pas trancher arrivent dans « Needs your decision », avec des suggestions de remplissage issues du profilage.
* **Laisser le modèle décider** : ces changements sont appliqués dès que leurs tests passent, puis le modèle règle les points restants (doublons exacts supprimés, valeurs manquantes remplies et marquées, le reste conservé avec la raison). Le résultat vise un dataset entièrement validé sans intervention.

Dans les deux modes, chaque valeur estimée est signalée dans une colonne `<colonne>_imputed`, et le fichier source n'est jamais modifié.

---

## 📂 Où sont les données

| Dossier | Contenu | Dans Git ? |
| --- | --- | --- |
| `data/raw/` | Datasets sources (exemples fournis + imports) | Oui (exemples) |
| `data/cleaned/` | `<dataset>_cleaned.csv`, dernière version validée, lue par les agents 3 et 4 | Non |
| `data/reports/` | Rapports de profilage et de nettoyage (JSON) | Non |
| `data/versions/` | Historique complet de chaque nettoyage : versions V0, V1…, journal, trace, code généré | Non |
| `data/evaluation/` | Résultats du benchmark de nettoyage | Non |
| `data/biflow_auth.sqlite3` | Comptes utilisateurs (mots de passe hachés) | Non |

Les dossiers générés sont créés automatiquement au premier usage.

---

## ⚙️ Configuration (`.env`)

| Variable | Défaut (`.env.example`) | Rôle |
| --- | --- | --- |
| `LLM_PROVIDER` | `ollama` | Agent 1 : `ollama` ou `gemini` |
| `OLLAMA_HOST`, `OLLAMA_MODEL` | `http://127.0.0.1:11434`, `qwen2.5:7b` | Ollama pour les agents 1 et 4 |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | vide, `gemini-3.6-flash` | Profilage via Gemini |
| `GROQ_API_KEY`, `GROQ_MODEL` | vide, `llama-3.3-70b-versatile` | Agents 3 et 4 en mode cloud |
| `BIFLOW_CLEANING_OLLAMA_MODEL` | `qwen2.5:7b` | Modèle de l'agent de nettoyage |
| `BIFLOW_EXPERIMENT_IMAGE` | `biflow-cleaning-sandbox:latest` | Image Docker du code généré |
| `BIFLOW_DOCKER_TIMEOUT` | `30` | Attente maximale des réponses Docker (s) |
| `BIFLOW_CLEANING_MAX_TURNS` / `_TURNS_PER_TASK` | `24` / `3` | Tours minimum du nettoyage ; la limite grandit avec le nombre de tâches |
| `BIFLOW_CLEANING_MAX_SECONDS` / `_SECONDS_PER_TASK` | `300` / `30` | Durée minimum (s) ; grandit avec le nombre de tâches |
| `BIFLOW_CLEANING_EXPERT_ENABLED` | `false` | Expert Groq après 4 corrections locales échouées (envoie des échantillons à Groq) |
| `BIFLOW_SMTP_*` | vide | E-mail de réinitialisation du mot de passe (facultatif) |
| `BIFLOW_AUTH_DB` | `data/biflow_auth.sqlite3` | Emplacement de la base des comptes |

La liste complète, commentée, est dans `.env.example`.

---

## 🧩 Options avancées

### BI Analyst en local (modèle fine-tuné)

Par défaut, le BI Analyst utilise l'API cloud (Groq/Gemini). Pour le modèle local Qwen 2.5 3B + LoRA, il faut un GPU NVIDIA, les paquets `torch`, `transformers`, `peft`, `bitsandbytes`, `accelerate`, et le fichier de poids `adapter/adapter_model.safetensors` (≈120 Mo, non versionné). Voir [le guide d'exécution du BI Analyst](docs/RUN_BI_ANALYST_FINETUNED_AGENT.md).

### XAI Auditor dans un conteneur

L'agent 4 tente d'abord un service sur `http://localhost:8003` (`XAI_SANDBOX_URL`) et, s'il n'est pas joignable, s'exécute directement dans l'application. Le conteneur est donc facultatif. Dans l'état actuel, `docker-compose.yml` (à la racine, avec `context: ..`) et `docker/Dockerfile.xai` doivent être corrigés avant de pouvoir construire ce service. Voir [le guide du XAI Auditor](docs/XAI_AUDITOR_AGENT_GUIDE.md).

---

## 🧪 Tests et évaluation

```powershell
python -m pytest tests -q
```

La plupart des tests simulent les réponses des modèles et ne nécessitent ni Ollama ni clé API ; certains utilisent Docker s'il est disponible. Le benchmark du nettoyage lance le vrai agent sur des données synthétiques et mesure la qualité et la sécurité du résultat :

```powershell
python -m evaluation.run --cases sales_small
```

Détails dans [docs/evaluation.md](docs/evaluation.md).

---

## 🗂️ Structure du projet

```text
BIFlow/
├── agents/              Agents 1 à 4 et client LLM partagé
├── dataCleaningTools/   Outils, contrôles, versions, prompts de l'agent de nettoyage
├── orchestration/       Pipeline LangGraph (graph.py)
├── dashboard/           Application Streamlit (app.py, pages/)
├── auth/                Comptes et sessions (SQLite)
├── analytics/           Fonctions d'analyse partagées
├── evaluation/          Benchmark de l'agent de nettoyage
├── sandbox/             Image Docker du code généré (nettoyage)
├── docker/              Service XAI (FastAPI) et son Dockerfile
├── adapter/             Configuration LoRA du BI Analyst (poids non versionnés)
├── scripts/             Scripts de test manuels (Ollama, Docker, modèle fine-tuné)
├── tests/               Tests automatisés
├── docs/                Documentation technique
├── data/raw/            Datasets d'exemple
├── .env.example         Modèle de configuration
└── requirements.txt
```

---

## 📚 Documentation

| Document | Sujet |
| --- | --- |
| [Architecture de l'agent de nettoyage](docs/cleaning-agent-architecture.md) | Boucle, outils, contrôles, modes de décision, publication vers le BI |
| [Évaluation de l'agent de nettoyage](docs/evaluation.md) | Benchmark, métriques, résultats |
| [Génération experte (Groq)](docs/expert-generation.md) | Repli Groq de l'agent de nettoyage |
| [Évaluation du profilage](docs/DATA_ENGINEERING_AGENT_MASTER_EVALUATION_GUIDE.md) | Benchmarks et LLM-as-a-Judge de l'agent 1 |
| [Exécution du BI Analyst](docs/RUN_BI_ANALYST_FINETUNED_AGENT.md) | Modèle LoRA local ou API cloud |
| [Fine-tuning du BI Analyst](docs/BI_ANALYST_AGENT_AND_FINETUNING_GUIDE.md) | Stratégie QLoRA |
| [Notebook Colab](docs/COLAB_FINETUNING_NOTEBOOK_QWEN_LORA.md) | Reproduire l'entraînement LoRA |
| [XAI Auditor](docs/XAI_AUDITOR_AGENT_GUIDE.md) | SHAP, audit, service FastAPI |
| [Architecture globale](docs/biflow_architecture_and_plan.md) | Vue d'ensemble du projet |

---

## 🛠️ Dépannage

| Symptôme | Cause probable | Solution |
| --- | --- | --- |
| Le nettoyage s'arrête avec une erreur Ollama | Ollama arrêté ou modèle absent | Lancer Ollama, `ollama pull <modèle>`, vérifier `BIFLOW_CLEANING_OLLAMA_MODEL` |
| « Docker was not available to test generated code » | Docker Desktop arrêté ou image absente | Démarrer Docker, refaire l'étape 5 |
| Le profilage indique un rapport de repli (« fallback ») | Gemini surchargé (503) ou clé absente | Réessayer plus tard, ou `LLM_PROVIDER=ollama` |
| BI Analyst : `adapter_model.safetensors` introuvable | Poids LoRA non installés | Utiliser le mode Cloud API ou ajouter les poids (voir le guide) |
| Thème sombre ou pages manquantes | Streamlit lancé hors de la racine | Relancer `streamlit run dashboard/app.py` depuis la racine |
| Mot de passe refusé à l'inscription | Règle de sécurité | 8 caractères minimum, une majuscule et un caractère spécial |

---

## 👥 Travail en équipe

Chaque membre travaille sur sa branche (`feature/...`) puis ouvre une Pull Request vers `main`. Ne commitez ni `.env`, ni `.venv/`, ni les dossiers générés de `data/`.

**Projet académique — BIFlow** · *Transform Data into Decisions.*
