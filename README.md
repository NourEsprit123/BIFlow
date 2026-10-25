# 📊 BIFlow — Intelligent Business Intelligence - Multi-Agent AI System

> **Transform Data into Decisions**

BIFlow est une plateforme de **Business Intelligence intelligente basée sur une architecture multi-agents**.
Son objectif est de transformer des données brutes en **informations fiables, analyses pertinentes et insights exploitables pour la prise de décision**.

Le système automatise différentes étapes du processus BI : **profilage des données, contrôle de qualité, nettoyage, transformation, analyse, détection des tendances et anomalies, génération d'insights et explicabilité des résultats**.

---

## 🎯 Objectifs du projet

BIFlow vise à :

* 📥 Importer des données business provenant de différentes sources.
* 🔎 Profiler automatiquement les données.
* 🧹 Détecter et traiter les problèmes de qualité.
* 🔄 Nettoyer et transformer les données.
* 📊 Calculer automatiquement les KPI.
* 📈 Identifier les tendances importantes.
* ⚠️ Détecter les anomalies.
* 🧠 Générer des insights business.
* 🔍 Expliquer les résultats produits par le système.
* 📝 Assurer la traçabilité des transformations et des analyses.
* 🤖 Coordonner plusieurs agents spécialisés dans un workflow BI.

---

# 🏗️ Architecture

BIFlow repose sur une architecture composée de **4 agents principaux** :

```text
                         ┌──────────────────────┐
                         │  Orchestrator Agent  │
                         │  Workflow & Routing  │
                         └──────────┬───────────┘
                                    │
                                    ▼
                    ┌─────────────────────────────┐
                    │   Data Engineering Agent   │
                    │ Profiling • Quality • ETL  │
                    └─────────────┬───────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────────┐
                    │      BI Analyst Agent       │
                    │ KPI • Trends • Anomalies   │
                    │       • Insights            │
                    └─────────────┬───────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────────┐
                    │      XAI / Auditor Agent    │
                    │ Explainability • Traceability│
                    │          • Audit             │
                    └─────────────────────────────┘
```

### 🤖 Agents

| Agent                         | Responsabilité                                              |
| ----------------------------- | ----------------------------------------------------------- |
| 🧠 **Orchestrator Agent**     | Coordonne le workflow et l'exécution des agents             |
| ⚙️ **Data Engineering Agent** | Profilage, qualité, nettoyage et transformation des données |
| 📊 **BI Analyst Agent**       | KPI, tendances, anomalies, segmentation et insights         |
| 🔍 **XAI / Auditor Agent**    | Explication, traçabilité et audit des résultats             |

---

# 📁 Structure du projet

```text
BIFlow/
│
├── data/
│   ├── raw/
│   │   └── telco_churn.csv
│   ├── cleaned/
│   └── processed/
│
├── agents/
│   ├── data_engineering_agent.py
│   ├── bi_analyst_agent.py
│   └── xai_auditor_agent.py
│
├── analytics/
│   ├── profiler.py
│   ├── data_quality.py
│   ├── cleaning.py
│   ├── transformation.py
│   ├── etl.py
│   ├── kpi.py
│   ├── trend_detection.py
│   ├── anomaly_detection.py
│   ├── segmentation.py
│   └── churn_model.py
│
├── auth/
│   ├── __init__.py
│   └── service.py
│
├── explainability/
│   ├── shap_explainer.py
│   ├── lineage.py
│   └── audit.py
│
├── orchestration/
│   └── graph.py
│
├── api/
│   └── main.py
│
├── dashboard/
│   └── app.py
│
├── models/
│
├── tests/
│   ├── test_profiling.py
│   ├── test_cleaning.py
│   └── test_kpi.py
│
├── requirements.txt
├── .gitignore
└── README.md
```

---

# 🛠️ Technologies utilisées

BIFlow est développé principalement avec :

* **Python 3.11+**
* **Pandas** — manipulation et analyse des données
* **NumPy** — calcul numérique
* **Scikit-learn** — Machine Learning et détection d'anomalies
* **Matplotlib** — visualisation
* **Seaborn** — visualisation statistique
* **Streamlit** — interface utilisateur
* **OpenPyXL** — traitement des fichiers Excel

D'autres technologies pourront être ajoutées progressivement selon l'évolution du projet.

---

# 🚀 Installation du projet

## 1. Prérequis

Avant de commencer, vérifier que les éléments suivants sont installés :

* Python
* Git
* VS Code — recommandé

Vérifier Python :

```powershell
python --version
```

Vérifier Git :

```powershell
git --version
```

---

# 📥 2. Cloner le projet

Ouvrir PowerShell ou le terminal VS Code.

Cloner le dépôt GitHub :

```powershell
git clone https://github.com/NourEsprit123/BIFlow.git

Entrer dans le projet :

```powershell
cd BIFlow
```

---

# 🐍 3. Créer l'environnement virtuel

Créer un environnement virtuel Python :

```powershell
python -m venv .venv
```

L'environnement `.venv` permet d'isoler les dépendances du projet des autres projets Python présents sur la machine.

---

# ▶️ 4. Activer l'environnement virtuel

Sous **Windows PowerShell** :

```powershell
.venv\Scripts\Activate.ps1
```

Si l'activation fonctionne, le terminal devrait afficher quelque chose comme :

```text
(.venv) PS D:\BIFlow>
```

### En cas de problème PowerShell

Si PowerShell bloque l'exécution des scripts, utiliser :

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Puis réactiver :

```powershell
.venv\Scripts\Activate.ps1
```

---

# 📦 5. Installer les dépendances

Une fois l'environnement virtuel activé :

```powershell
pip install -r requirements.txt
```

Cette commande installe automatiquement toutes les bibliothèques nécessaires au projet.

---

# ✅ 6. Vérifier l'installation

Vous pouvez également vérifier les packages installés avec :

```powershell
pip list
```

---

# 📊 7. Vérifier les données

Le dataset utilisé par BIFlow doit être placé dans :

```text
data/raw/
```

Par exemple :

```text
data/
└── raw/
    └── telco_churn.csv
```

Le dossier `data/raw/` contient les **données originales**.

Les données nettoyées seront ensuite placées dans :

```text
data/cleaned/
```

et les données transformées dans :

```text
data/processed/
```

---

# 🖥️ 8. Lancer l'application BIFlow

L'interface utilisateur est développée avec **Streamlit**.

Depuis la racine du projet :

```powershell
streamlit run dashboard/app.py
```

Streamlit démarre alors l'application BIFlow.

L'interface est accessible depuis le navigateur à l'adresse indiquée par Streamlit, généralement :

```text
http://localhost:8501
```

## Comptes BIFlow

Les boutons **Sign up** et **Sign in** utilisent une base SQLite locale.
Les nouveaux comptes sont enregistrés dans `data/biflow_auth.sqlite3` ; les
mot de passe sont stockés sous forme de hachages et non en clair. Le mot de
passe doit contenir au moins 8 caractères, une lettre majuscule et un caractère
spécial. Cette règle s'applique à l'inscription et à la réinitialisation.

Par défaut, la base reste sur cette machine et n'est pas suivie par Git. Pour
choisir un autre emplacement, définissez la variable d'environnement
`BIFLOW_AUTH_DB` avant de démarrer Streamlit. **Forgot password?** envoie un
code à usage unique par e-mail ; ce code expire après 30 minutes. Configurez
SMTP dans `.env` à partir du modèle `.env.example` :

* `BIFLOW_SMTP_HOST` et `BIFLOW_SMTP_FROM` sont obligatoires ;
* `BIFLOW_SMTP_PORT` vaut `587` par défaut (STARTTLS) ;
* `BIFLOW_SMTP_USE_SSL=true` active TLS direct, habituellement avec le port `465` ;
* `BIFLOW_SMTP_USER` et `BIFLOW_SMTP_PASSWORD` sont facultatifs ensemble, selon
  le fournisseur.

Copiez `.env.example` vers `.env`, puis remplacez les valeurs par celles de votre
fournisseur SMTP. Ne partagez pas et ne commitez jamais le fichier `.env`.
Les pages internes nécessitent une session connectée et le bouton **Sign out**
ferme la session.

---

# 🧭 9. Interface BIFlow

L'application contient plusieurs espaces :

### 🏠 Overview

Vue générale du système BIFlow.

Elle permet notamment de :

* charger un dataset ;
* visualiser le pipeline BIFlow ;
* consulter les différents agents ;
* suivre l'état général du système.

### 📁 Data

Gestion et exploration des datasets.

### 🧹 Data Quality

Analyse de la qualité des données :

* valeurs manquantes ;
* doublons ;
* valeurs incohérentes ;
* colonnes problématiques ;
* score de qualité.

### 📊 Analytics

Espace dédié à l'analyse business :

* KPI ;
* tendances ;
* anomalies ;
* segmentation ;
* insights.

### 🤖 AI Agents

Visualisation et suivi des différents agents BIFlow.

Depuis la barre horizontale en haut de l'application, ouvrez **Agent 1**
et cochez les tâches souhaitées. La sélection est affichée dans le menu ;
aucune tâche n'est exécutée à ce stade.

* **Agent 1 · Data Engineering** : Data Profiling, Data Quality et Data Cleaning ;
* **Agent 2 · BI Analyst** : KPIs et Dashboards ;
* **Agent 3 · XAI Auditor** : XAI.

### 🔍 Audit

Espace dédié à :

* l'explicabilité ;
* la traçabilité ;
* la justification des résultats ;
* l'audit des transformations.

---

# 🔄 Workflow BIFlow

Le fonctionnement global de BIFlow peut être résumé comme suit :

```text
       DATASET
          │
          ▼
   ┌──────────────┐
   │   PROFILING  │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ DATA QUALITY │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │    CLEAN     │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │     ETL      │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │   ANALYSIS   │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ KPI / TRENDS │
   │ / ANOMALIES  │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │    XAI       │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │   INSIGHTS   │
   └──────────────┘
```

---

# 👥 Organisation du travail avec Git

Chaque membre de l'équipe travaille sur sa propre branche.

Exemple :

```text
main
│
├── feature/orchestrator
├── feature/data-engineering
├── feature/bi-analyst
├── feature/xai-auditor
└── feature/streamlit-dashboard
```

## Créer une branche

Exemple :

```powershell
git checkout -b feature/data-engineering
```

Après avoir travaillé :

```powershell
git add .
```

Puis :

```powershell
git commit -m "Implement data profiling"
```

Envoyer la branche vers GitHub :

```powershell
git push origin feature/data-engineering
```

Ensuite, une **Pull Request** peut être créée sur GitHub afin de fusionner le travail dans `main`.

---

# 🔐 Variables d'environnement

Les clés API et informations sensibles ne doivent **jamais être directement écrites dans le code source**.

Utiliser un fichier `.env` local :

```text
GEMINI_API_KEY=your_api_key
```

Le fichier `.env` est ignoré par Git grâce au `.gitignore`.

Pour partager la structure des variables nécessaires avec l'équipe, utiliser plutôt :

```text
.env.example
```

Exemple :

```text
GEMINI_API_KEY=
```

---

# 🧪 Tests

Les tests automatisés sont regroupés dans :

```text
tests/
```

Exemples :

```text
tests/
├── test_profiling.py
├── test_cleaning.py
└── test_kpi.py
```

Les tests peuvent être exécutés avec :

```powershell
pytest
```

---

# 📌 Principes de développement

BIFlow suit quelques principes importants :

### 1. Séparer le calcul de l'interprétation

Les calculs déterministes sont réalisés avec Python :

```text
Pandas
NumPy
Scikit-learn
```

Le modèle de langage est utilisé principalement pour :

```text
Interprétation
Génération d'insights
Explications
Recommandations
```

### 2. Modularité

Chaque fonctionnalité est développée dans un module indépendant afin de faciliter :

* le travail en équipe ;
* les tests ;
* la maintenance ;
* l'évolution du système.

### 3. Traçabilité

Les transformations et résultats produits par BIFlow doivent pouvoir être expliqués et retracés.

---

# 📚 Guides Techniques & Documentation des Agents

| Document | Description |
| :--- | :--- |
| 🚀 [**Guide d'Exécution BI Analyst (LoRA & API)**](docs/RUN_BI_ANALYST_FINETUNED_AGENT.md) | **Guide pas-à-pas** pour exécuter le BI Analyst Agent, configurer le modèle fine-tuné local Qwen 2.5 3B (LoRA en 4-bit) ou basculer en mode Cloud API (Groq/Gemini). |
| 📊 [**Guide & Stratégie Fine-Tuning BI Agent**](docs/BI_ANALYST_AGENT_AND_FINETUNING_GUIDE.md) | Justification théorique et technique du fine-tuning QLoRA pour l'Agent 2 et arguments pour la soutenance. |
| 📓 [**Notebook Colab Fine-Tuning Qwen LoRA**](docs/COLAB_FINETUNING_NOTEBOOK_QWEN_LORA.md) | Procédure complète pour reproduire l'entraînement LoRA sur GPU T4 gratuit (Google Colab). |
| 🛠️ [**Master Guide Évaluation Data Engineering**](docs/DATA_ENGINEERING_AGENT_MASTER_EVALUATION_GUIDE.md) | Guide d'évaluation empirique, benchmarks de profilage et LLM-as-a-Judge de l'Agent 1. |
| 🔬 [**Sandbox Deep Dive**](docs/SANDBOX_DEEP_DIVE.md) | Analyse détaillée de la génération de code Python dynamique et exécution sandboxée sécurisée. |

---

# 🔮 Évolutions prévues

Les fonctionnalités suivantes pourront être intégrées progressivement :

* 🤖 intégration complète des agents IA ;
* 🧠 intégration d'un LLM ;
* 🔍 système d'explicabilité avancé ;
* 📚 RAG pour enrichir les analyses ;
* 📝 versionnement des prompts ;
* 📊 évaluation des performances ;
* 🔄 orchestration complète du workflow ;
* 📈 dashboards BI avancés ;
* 🧪 tests automatisés plus complets.

---

# 👨‍💻 Équipe

**Projet académique — BIFlow**

> Intelligent Business Intelligence
> *Transform Data into Decisions.*
