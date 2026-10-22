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

BIFlow sépare le profilage et le nettoyage dans **4 agents spécialisés**,
coordonnés par l'orchestrateur :

```text
                         ┌──────────────────────┐
                         │  Orchestrator Agent  │
                         │  Workflow & Routing  │
                         └──────────┬───────────┘
                                    │
                                    ▼
                    ┌─────────────────────────────┐
                    │   Data Profiling Agent    │
                    │ Profiling • Quality Audit │
                    └─────────────┬───────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────────┐
                    │    Data Cleaning Agent     │
                    │ Cleaning • Validation • ETL│
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

| Agent                         | Responsabilité                                      |
| ----------------------------- | --------------------------------------------------- |
| 🧠 **Orchestrator Agent**     | Coordonne le workflow et l'exécution des agents     |
| 🔎 **Data Profiling Agent**   | Profilage, contrôles de qualité et rapport de profil|
| 🧹 **Data Cleaning Agent**    | Nettoyage, validation, conversions et ETL            |
| 📊 **BI Analyst Agent**       | KPI, tendances, anomalies, segmentation et insights  |
| 🔍 **XAI / Auditor Agent**    | Explication, traçabilité et audit des résultats     |

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

## Tests

Depuis le dossier `BIFlow`, lancez les tests hors ligne avec :

```powershell
python -m pytest -q
```

Le script manuel `python test_smoke.py` vérifie également la connexion à Ollama ;
il nécessite un serveur Ollama actif et le modèle configuré dans `.env`.

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

Vue générale du dataset actif : dimensions, score de qualité et activité des
agents. **Run Data Profiling Agent** lance le profilage et les contrôles de
qualité ; **Create analysis** ouvre l'analyse correspondante.

### 📁 Data

La page **Datasets** importe les fichiers CSV, Excel ou Parquet vers
`data/raw/`, affiche leurs dimensions et permet de filtrer la liste. Le dataset
actif se choisit dans la barre latérale et est utilisé par les autres pages.
Les connecteurs de bases de données et de services cloud ne sont pas configurés
dans cette version.

### ⛓ Workflows

Sélectionnez les tâches à lancer : profilage, audit qualité, nettoyage
versionné, analyse KPI et vérification du rapport. **Run BIFlow Pipeline**
exécute les tâches choisies sur le dataset actif. **Save as template** conserve
la configuration dans la session Streamlit en cours.

Le nettoyage écrit une copie versionnée sous `data/versions/dashboard/` et ne
modifie pas le fichier source. La page permet de télécharger le rapport de
profilage et, après nettoyage, le CSV résultant.

### 🧹 Data Quality

Les métriques et problèmes sont calculés sur le fichier actif. **Run quality
audit** génère le rapport du Data Profiling Agent ; **Run safe cleaning**
exécute les transformations permises par la politique de nettoyage et garde
l'original intact.

### 📊 Analytics

L'analyse affiche les statistiques descriptives et distributions calculées à
partir des données actives. Un taux de churn est calculé uniquement si le
dataset contient une colonne `Churn` ou `Is_Churn`. Les résultats peuvent être
téléchargés en JSON.

### 🤖 AI Agents

Les boutons d'agent dans la barre supérieure lancent réellement les fonctions
disponibles sur le dataset actif :

* **Agent 1 · Data Profiling** : profilage, contrôles de qualité et rapport remis à l'agent de nettoyage ;
* **Agent 2 · Data Cleaning** : transformations déterministes, validation et copie versionnée ;
* **Agent 3 · BI Analyst** : statistiques descriptives et KPIs disponibles dans les données ;
* **Agent 4 · XAI Auditor** : vérification de la provenance, des dimensions et du contenu du rapport sauvegardé.

Le profilage utilise son mode déterministe local et ne requiert pas de service
LLM. **Agent Ops** montre l'activité de la session courante ; aucun pool
d'agents persistant ni connecteur de télémétrie n'est configuré.

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
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.3-70b-versatile
```

Le fichier `.env` est ignoré par Git grâce au `.gitignore`.
L'agent de nettoyage utilise `GROQ_API_KEY`; `GROQ_MODEL` est facultatif.

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
