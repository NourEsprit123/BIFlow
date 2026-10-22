# BIFlow Documentation - Guide Complet

## 📚 Vue d'Ensemble

Cette documentation explique le **Data Engineering Agent** (Agent 1) de BIFlow, un agent autonome qui utilise l'intelligence artificielle (LLM) pour analyser, raisonner, et préparer les données pour le nettoyage automatique.

---

## 📖 Documents Disponibles

### 1. 🎯 **LLM_REASONING_CLARIFICATION.md** (MUST READ!)

**Pour qui:** Mohamed, Malek, Professor

**Sujet:** Clarification sur le raisonnement LLM - Le LLM raisonne sur TOUTES les colonnes

**Ce que vous apprendrez:**
- ❌ Malentendu: "Le LLM raisonne seulement sur colonnes incertaines"
- ✅ Réalité: Le LLM raisonne sur **TOUTES** les colonnes (100%)
- Le flow complet en 4 étapes avec exemples visuels
- Différences entre Python, LLM, Sandbox, et Affichage
- Preuves dans le code avec numéros de lignes
- Pourquoi c'est un "True Autonomous Agent"

**Quand le lire:** PREMIER document à lire pour comprendre le système

**Longueur:** ~15 pages

---

### 2. 🔬 **SANDBOX_DEEP_DIVE.md** (MUST READ!)

**Pour qui:** Mohamed, Malek, Professor (Questions techniques sur le sandbox)

**Sujet:** Comment le Sandbox fonctionne pour les colonnes à haut risque

**Ce que vous apprendrez:**
- Comment le LLM décide quelles colonnes ont besoin de vérifications custom (5-10%)
- Comment le LLM génère du code Python pour chaque cas spécifique
- Comment le sandbox exécute ce code de façon sécurisée
- Exemples concrets: TotalCharges, Age, Email, Prix
- Sécurité: Protection contre code malveillant
- Comment tester le sandbox manuellement

**Quand le lire:** Après LLM_REASONING_CLARIFICATION.md, si vous voulez comprendre le sandbox

**Longueur:** ~25 pages

**Script de démo:** `test_sandbox_demo.py` - 4 démos interactives

---

### 3. 📘 **data_engineering_agent_workflow.md** (GUIDE COMPLET)

**Pour qui:** Mohamed, Malek (Pour intégration et utilisation)

**Sujet:** Guide complet du workflow de l'agent

**Ce que vous apprendrez:**
- Architecture générale (diagramme)
- Phase 1: Profiling & Data Quality (Python)
- Phase 2: LLM Reasoning Process (Gemini)
- Phase 3: Sandbox Custom Checks (Sécurité)
- Phase 4: Cleaning Integration (pour Malek) ← IMPORTANT
- Structure JSON complète du ProfilingReport
- Configuration LLM (Gemini vs Ollama)
- FAQ complète

**Quand le lire:** Pour comprendre le workflow complet et intégrer avec Agent 2 (Malek)

**Longueur:** ~40 pages

---

### 4. 📝 **REASONING_EXPLANATION.md** (TROUBLESHOOTING)

**Pour qui:** Mohamed, Malek (Si vous voyez "Standard rule-based detection")

**Sujet:** Pourquoi certaines colonnes ont fallback vs LLM reasoning

**Ce que vous apprendrez:**
- Pourquoi certaines colonnes ont "Standard rule-based detection (LLM unavailable)"
- Explication du batching (>50 colonnes → batches de 30)
- Différences LLM reasoning vs Intelligent fallback
- Comment améliorer (réduire batch size, augmenter timeout)
- Ce qui compte comme "autonomous" même avec fallback

**Quand le lire:** Si vous voyez des colonnes avec fallback et vous vous demandez pourquoi

**Longueur:** ~18 pages

---

### 5. 📋 **data_engineering_agent_spec.md** (SPÉCIFICATION TECHNIQUE)

**Pour qui:** Mohamed (Développement)

**Sujet:** Spécification technique détaillée de l'agent

**Ce que vous apprendrez:**
- Architecture technique
- API endpoints
- Schémas de données
- Règles de validation
- Design decisions

**Quand le lire:** Pour développement ou modifications techniques

**Longueur:** Variable (spec technique)

---

## 🎯 Ordre de Lecture Recommandé

### Pour Comprendre le Système (Mohamed, Malek, Professor):

```
1. LLM_REASONING_CLARIFICATION.md   (15 min)
   └─ Comprendre que le LLM raisonne sur TOUTES les colonnes
   
2. SANDBOX_DEEP_DIVE.md            (20 min)
   └─ Comprendre comment le sandbox fonctionne
   
3. data_engineering_agent_workflow.md (30 min)
   └─ Guide complet du workflow
   └─ IMPORTANT: Section 4 pour Malek (Cleaning Integration)
```

### Pour Intégration (Malek):

```
1. LLM_REASONING_CLARIFICATION.md   (15 min)
   └─ Comprendre le système général
   
2. data_engineering_agent_workflow.md - Section 4 & 6 (15 min)
   └─ Comment lire le ProfilingReport.json
   └─ Structure JSON complète
   └─ Code Python pour appliquer transformations
```

### Pour Troubleshooting:

```
Si vous voyez "Standard rule-based detection":
→ REASONING_EXPLANATION.md

Si vous voulez tester le sandbox:
→ SANDBOX_DEEP_DIVE.md + test_sandbox_demo.py

Si vous voulez modifier le code:
→ data_engineering_agent_spec.md
```

---

## 🧪 Scripts de Test

### 1. **test_sandbox_demo.py**

Démontre le fonctionnement du sandbox avec 4 démos interactives:

```bash
python test_sandbox_demo.py
```

**Démos:**
- Demo 1: Exécution basique du sandbox
- Demo 2: Génération de code par le LLM (nécessite API)
- Demo 3: Sécurité du sandbox contre code malveillant
- Demo 4: Exemple réel avec TotalCharges

---

## 📊 Structure du Système

```
┌─────────────────────────────────────────────────────────────────┐
│                      BIFlow Agent 1                             │
│                 Data Engineering Agent                          │
│                                                                 │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────┐      │
│  │   Python    │    │     LLM      │    │   Sandbox   │      │
│  │  Analysis   │───▶│  Reasoning   │───▶│   Checks    │      │
│  │(Profiler +  │    │  (Gemini)    │    │  (Secure)   │      │
│  │  Quality)   │    │              │    │             │      │
│  └─────────────┘    └──────────────┘    └─────────────┘      │
│         │                   │                    │             │
│         │    Raisonne sur   │   Exécute pour    │             │
│         │    TOUTES les     │   5-10% des       │             │
│         │    colonnes       │   colonnes        │             │
│         │    (100%)         │   (haut risque)   │             │
│         │                   │                    │             │
│         └───────────────────┼────────────────────┘             │
│                             │                                  │
│                             ▼                                  │
│                ┌──────────────────────────┐                   │
│                │   ProfilingReport.json   │                   │
│                │  (Structured Output)     │                   │
│                └──────────────────────────┘                   │
│                             │                                  │
└─────────────────────────────┼──────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      BIFlow Agent 2                             │
│                    Cleaning Agent (Malek)                       │
│                                                                 │
│  Lit le ProfilingReport.json et applique:                      │
│  - Imputation strategies                                        │
│  - Type casting                                                 │
│  - Outlier treatment                                            │
│  - Synonym normalization                                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔑 Concepts Clés

### 1. Le LLM Raisonne sur TOUTES les Colonnes

**❌ Faux:**
- "Le LLM raisonne seulement sur colonnes incertaines"
- "Le reste est juste de l'affichage"

**✅ Vrai:**
- Le LLM reçoit **TOUTES** les colonnes
- Le LLM décide pour **CHAQUE** colonne:
  - severity (HIGH/MEDIUM/LOW/NONE)
  - agent_reasoning (texte personnalisé)
  - imputation_strategy (median/mean/mode/drop)
  - needs_custom_check (true/false)

### 2. Le Sandbox Est Utilisé pour Colonnes à Haut Risque

**Quand?**
- Seulement pour **5-10%** des colonnes
- Celles où le LLM pense avoir besoin de vérifications custom

**Pourquoi?**
- Type issues incertains (99% valide, mais besoin vérifier la plage)
- Patterns suspects (dates multiples formats)
- Business logic complexe (prix négatifs = remboursements?)

**Comment?**
- LLM génère du code Python custom
- Sandbox exécute de façon sécurisée
- Résultats ajoutés au ProfilingReport

### 3. Architecture Hybrid

```
Python (Fast)  →  Détecte les problèmes (stats, missing, outliers)
    ↓
LLM (Smart)    →  Interprète et décide (reasoning, stratégies)
    ↓
Sandbox (Safe) →  Exécute vérifications custom (code sécurisé)
    ↓
JSON Output    →  ProfilingReport pour Agent 2 (Malek)
```

---

## 💡 Points Clés pour le Professor

### Pourquoi C'est un "True Autonomous Agent"?

1. **✅ Le LLM Prend les Décisions**
   - Pas juste appliquer des règles if/else
   - Raisonne sur tout le dataset
   - Décide severity et stratégies

2. **✅ Architecture Hybrid Production-Ready**
   - Python: Détection rapide (déterministe)
   - LLM: Raisonnement intelligent (contextuel)
   - Sandbox: Exécution sécurisée (custom checks)

3. **✅ Le LLM Génère du Code Dynamique**
   - Pas de code hardcodé pour chaque colonne
   - Génère du Python custom basé sur contexte
   - Sandbox exécute de façon sécurisée

4. **✅ Graceful Degradation**
   - Si LLM échoue → Fallback intelligent
   - Si API timeout → Batch suivant continue
   - Système résilient qui ne crash pas

5. **✅ Structured JSON Output**
   - ProfilingReport.json complet
   - Intégration facile avec Agent 2 (Malek)
   - Traçabilité complète

---

## 📧 Contact & Questions

**Mohamed:** Agent 1 (Profiling, Quality, Reasoning, Sandbox)  
**Malek:** Agent 2 (Cleaning, utilise ProfilingReport.json)

**Pour questions sur:**
- LLM Reasoning → LLM_REASONING_CLARIFICATION.md
- Sandbox → SANDBOX_DEEP_DIVE.md + test_sandbox_demo.py
- Workflow complet → data_engineering_agent_workflow.md
- Integration Malek → data_engineering_agent_workflow.md Section 4
- Fallback → REASONING_EXPLANATION.md

---

## 🚀 Quick Start pour Malek

```python
# 1. Lire le ProfilingReport.json
import json
with open("data/reports/telco_churn_profiling_report.json", "r") as f:
    report = json.load(f)

# 2. Extraire les infos nécessaires
imputation_plan = report["imputation_plan"]
type_casting = report["etl_hints"]["type_casting_targets"]
outlier_cols = report["outlier_columns"]
cleaning_order = report["recommended_cleaning_order"]

# 3. Appliquer les transformations
import pandas as pd
df = pd.read_csv(report["dataset_ref"]["file_path"])

# Type casting
for col, target_dtype in type_casting.items():
    if target_dtype == "float64":
        df[col] = pd.to_numeric(df[col], errors='coerce')

# Imputation
for col, plan in imputation_plan.items():
    strategy = plan.get("strategy", "median")
    if strategy == "median":
        df[col].fillna(df[col].median(), inplace=True)
    elif strategy == "mean":
        df[col].fillna(df[col].mean(), inplace=True)
    elif strategy == "mode":
        df[col].fillna(df[col].mode()[0], inplace=True)

# Outliers
for col in outlier_cols:
    if pd.api.types.is_numeric_dtype(df[col]):
        q1, q99 = df[col].quantile([0.01, 0.99])
        df[col] = df[col].clip(lower=q1, upper=q99)

# 4. Sauvegarder
df.to_csv("data/cleaned/telco_churn_cleaned.csv", index=False)
```

Voir **data_engineering_agent_workflow.md Section 4** pour le code complet!

---

**Dernière Mise à Jour:** October 22, 2026  
**BIFlow Version:** 2.0.0  
**Documentation Version:** 1.0.0
