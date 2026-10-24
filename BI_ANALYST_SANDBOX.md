# 📊 BIFlow — Sandbox & Évaluation de l'Agent BI Analyst

Ce document présente l'architecture de test isolé (Sandboxing), la méthodologie d'évaluation et le guide d'exécution pour le 2ème agent du workflow BIFlow : le **BI Analyst** (intervenant directement après l'agent *Data Engineer*).

---

## 🎯 Objectifs & Périmètre Académique

Ce composant est conçu pour répondre aux exigences techniques du projet :

- **Choix du LLM :** Utilisation de `qwen2.5:7b` en local via **Ollama** (stratégie du *modèle restreint* avec gestion de contexte ciblée).
- **Sécurité & Sandboxing :** Execution isolée du code via un conteneur **Docker** local pour empêcher toute exécution malveillante ou destructive sur la machine hôte.
- **Tool Schema :** Définition d'outils de manipulation de fichiers (fonctions CRUD dans `agent_action.py`) pour permettre à l'agent de lire ses entrées et d'écrire ses rapports.
- **Évaluation :** Validation quantitative et qualitative du rapport d'analyse BI généré sur un jeu de données propre et maîtrisé.

---

## 🛠️ Architecture Technique

```
 ┌──────────────────────────┐
 │ Data Engineer Agent      │ (Simulé par generateur_donnees_propres.py)
 └─────────────┬────────────┘
               │ Données nettoyées (donnees_propres_bi.csv)
               ▼
 ┌──────────────────────────┐
 │ Sandbox (Conteneur Docker)│
 │  ┌────────────────────┐  │
 │  │ Ollama Client      │  │ <---> Modèle Local Ollama (qwen2.5:7b)
 │  │ (demo_bi_analyst)  │  │
 │  └──────────┬─────────┘  │
 └─────────────┼────────────┘
               │ Génération
               ▼
 ┌──────────────────────────┐
 │ Rapport Markdown (KPIs)  │ (sandbox/reports_output/rapport_bi_analyst.md)
 └──────────────────────────┘
```

---

## 📂 Structure du Workspace

```text
BIFlow/
├── docs/
│   └── BI_ANALYST_SANDBOX.md         # La présente documentation
├── sandbox/
│   ├── data_input/                   # Répertoire des CSV nettoyés reçus
│   └── reports_output/               # Répertoire des rapports BI générés
├── Dockerfile                        # Configuration de l'environnement isolé
├── generateur_donnees_propres.py     # Générateur du dataset de test (Mock Data Engineer)
├── demo_bi_analyst_sandbox.py        # Script d'exécution et d'interrogation du LLM
├── agent_action.py                   # Définition des outils de gestion de fichiers (CRUD)
└── requirements.txt                  # Dépendances Python minimales
```

---

## 🚀 Guide d'Exécution Pas à Pas (PowerShell)

### Étape 1 : Générer le jeu de données de test

Exécutez le script de simulation de la sortie de l'agent Data Engineer :

```powershell
python generateur_donnees_propres.py
```

*Résultat : Un fichier `donnees_propres_bi.csv` contenant 100 transactions de ventes est créé dans `sandbox/data_input/`.*

### Étape 2 : Lancer l'évaluation dans la Sandbox Docker

Construisez l'image Docker et exécutez le conteneur avec un montage de volume local :

```powershell
# 1. Construction de l'image
docker build -t biflow-bi-analyst-sandbox .

# 2. Exécution isolée avec accès aux dossiers sandbox locaux
docker run --rm -v "${PWD}\sandbox:/app/sandbox" biflow-bi-analyst-sandbox
```

---

## 📊 Format du Livrable Généré

Après l'exécution, l'agent produit un rapport d'analyse BI structuré contenant :

1. **Synthèse globale :** Évolution du chiffre d'affaires et volumes globaux.
2. **Indicateurs Clés de Performance (KPIs) :** Calculs par catégorie et top produits.
3. **Recommandations Stratégiques :** Insights d'aide à la décision basés sur la donnée.

Le fichier final est automatiquement sauvegardé sous :  
`sandbox/reports_output/rapport_bi_analyst.md`