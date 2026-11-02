# 📊 Guide Technique : BI Analyst Agent & Stratégie de Fine-Tuning QLoRA
> **Destinataire :** Binôme responsable du *BI Analyst Agent* (Agent 2)  
> **Projet :** BIFlow — Plateforme Multi-Agents Autonome  
> **Objectif :** Comprendre le fonctionnement de l'Agent 2, le contrat d'interface avec Plotly, et savoir justifier la stratégie de Fine-Tuning lors de la soutenance.

---

## 1. Rôle de l'Agent BI dans BIFlow

Dans l'architecture de BIFlow, chaque agent a une responsabilité unique :
- **Agent 1 (Data Engineering) :** Nettoie les données brutes, corrige les types et élimine les valeurs manquantes.
- **Agent 2 (BI Analyst — Ton Agent) :** Prend le jeu de données nettoyé et répond à la question :  
  *« Que disent ces données ? Quels sont les 4 KPIs clés ? Quels graphiques décisionnels faut-il afficher ? »*
- **Agent 3 (XAI Auditor) :** Explique les modèles prédictifs et audite la conformité juridique/algorithmique (SHAP, lignage).

---

## 2. Le Contrat d'Interface : Ce que le Dashboard attend de toi

Pour que la page Streamlit ([`dashboard/pages/5_BI_Analysis.py`](../dashboard/pages/5_BI_Analysis.py)) puisse afficher tes résultats sans planter, la sortie de ton agent doit **obligatoirement** contenir deux éléments :

### A. Un Rapport Exécutif en Markdown
Une synthèse décisionnelle structurée en 5 sections standards :
1. **Executive Summary** (Volume, dimensions, taux de complétude).
2. **Key KPIs Analysis** (Interprétation des indicateurs majeurs).
3. **Emerging Trends & Patterns** (Corrélations et tendances observées).
4. **Anomalies & Outliers** (Observations sur les distributions extrêmes).
5. **Strategic Recommendations** (3 actions concrètes pour le management).

### B. Un Bloc JSON Strict à la fin (pour les composants Streamlit & Plotly)
Ce bloc doit être impérativement entouré de triple backticks ```` ```json ... ``` ```` :

```json
{
  "kpis": [
    {
      "title": "Taux de Churn",
      "value": "26.5%",
      "subtitle": "1 869 clients résiliés"
    },
    {
      "title": "Revenu Moyen Mensuel",
      "value": "64.76 $",
      "subtitle": "Par abonné actif"
    },
    {
      "title": "Ancienneté Médiane",
      "value": "29 mois",
      "subtitle": "Durée de rétention moyenne"
    },
    {
      "title": "Part Contrats Mensuels",
      "value": "55.0%",
      "subtitle": "Segment le plus volatile"
    }
  ],
  "recommended_charts": [
    {
      "title": "Répartition du Churn par Type de Contrat",
      "type": "bar",
      "column_x": "Contract",
      "column_y": "TotalCharges"
    },
    {
      "title": "Distribution des Charges Mensuelles",
      "type": "histogram",
      "column_x": "MonthlyCharges",
      "column_y": null
    },
    {
      "title": "Proportion des Modes de Paiement",
      "type": "pie",
      "column_x": "PaymentMethod",
      "column_y": null
    }
  ]
}
```

### Pourquoi cette syntaxe est-elle critique ?
Dans le code de l'interface Streamlit, nous lisons directement ces clés pour tracer les graphiques avec **Plotly Express** :
```python
# Exemple de rendu dans 5_BI_Analysis.py :
if chart["type"] == "bar":
    fig = px.bar(df, x=chart["column_x"], y=chart["column_y"], title=chart["title"])
    st.plotly_chart(fig, use_container_width=True)
elif chart["type"] == "pie":
    fig = px.pie(df, names=chart["column_x"], title=chart["title"])
    st.plotly_chart(fig, use_container_width=True)
```
- Si le LLM écrit `"axe_x"` au lieu de `"column_x"`, Python renvoie une `KeyError`.
- Si le LLM invente un type comme `"radar_chart_3d"`, Plotly ne sait pas le dessiner.
- Si le LLM oublie de fermer une accolade, `json.loads()` plante l'affichage.

---

## 3. Le Problème Actuel : Le "Prompt Engineering Forcé"

Aujourd'hui, dans [`agents/bi_analyst_agent.py`](../agents/bi_analyst_agent.py), nous sommes obligés d'écrire un prompt système de plus de 50 lignes pour supplier le LLM :
> *« Tu es un agent BI. Tu dois OBLIGATOIREMENT renvoyer exactement 4 KPIs. Tu dois OBLIGATOIREMENT inclure un bloc ```json ... ``` avec les clés 'title', 'value', 'type', 'column_x' ! Ne mets aucun texte après le JSON ! »*

### Les inconvénients de cette approche :
1. **Consommation excessive de tokens :** ~500 tokens gaspillés à chaque requête juste pour lui rappeler le format.
2. **Latence accrue :** Le LLM met plus de temps à lire et traiter ces règles répétitives.
3. **Risque avec les modèles légers (7B) :** Un petit modèle local comme Qwen 2.5 7B ou Llama 3.1 8B peut parfois dévier, inventer une clé ou ajouter un mot de politesse qui casse le parser.

---

## 4. La Solution d'Ingénieur : Le Fine-Tuning QLoRA

### C'est quoi ?
Le **Fine-Tuning** consiste à spécialiser les neurones du modèle pour qu'il intègre **naturellement** la structure de nos rapports et le schéma JSON sans qu'on ait besoin de lui répéter les règles dans le prompt.

### Pourquoi l'Agent BI est le SEUL candidat éligible ?
- **Agent 1 (Data Engineering) :** ❌ NON. Il doit rester généraliste pour comprendre n'importe quelle colonne inconnue. Le fine-tuner provoquerait un surapprentissage (*overfitting de schéma*) et détruirait son raisonnement zéro-shot.
- **Agent 3 (XAI Auditor) :** ❌ NON. L'explicabilité repose sur des maths exactes (SHAP). Un LLM fine-tuné risquerait d'halluciner de fausses corrélations.
- **Agent 2 (BI Analyst) :** ✅ **OUI**. Il s'agit d'une tâche de style, de concision et de respect de format strict (JSON + Plotly). C'est le cas d'usage idéal du fine-tuning.

---

## 5. Comment le réaliser en pratique ? (Méthode QLoRA)

Si la professeure te demande comment faire concrètement :

### A. La technique : QLoRA (Quantized Low-Rank Adaptation)
- **Modèle de base :** `Qwen 2.5 7B` ou `Llama 3.1 8B`.
- On compresse le modèle en **4 bits** (Normal Float 4) pour qu'il tienne en mémoire.
- On gèle 99,8% des poids et on n'entraîne que de petites matrices d'adaptation (LoRA Adapters, rank $r=16$) sur les couches d'attention.
- **Matériel requis :** Un simple GPU grand public (ex: RTX 3060/4060 avec 8-12 Go VRAM) ou un notebook **Google Colab gratuit (T4 GPU)**. Temps d'entraînement : **~1h30**.

### B. D'où viennent les données d'entraînement ? (Distillation Synthétique)
Puisqu'il n'existe pas de dataset public "BIFlow BI Report" sur Kaggle, on utilise la méthode **Teacher-Student** :
1. On rassemble 500 résumés statistiques de datasets variés (Kaggle, Open Data).
2. On utilise un modèle frontière très puissant (ex: **GPT-4o** ou **Claude 3.5 Sonnet** = le *Teacher*) avec un prompt parfait pour générer 500 rapports d'excellence avec le bloc JSON irréprochable.
3. Un script Python filtre et valide que les 500 JSONs sont 100% parseables.
4. On obtient un fichier `train_bi_agent.jsonl` de 500 paires `{instruction, input, output}`.
5. On entraîne notre petit modèle 7B local (*Student*) sur ce dataset.

---

## 6. Ce que cela change concrètement (Le ROI)

| Critère | Sans Fine-Tuning (Prompt Actuel) | Avec Fine-Tuning QLoRA |
| :--- | :--- | :--- |
| **Taille du Prompt** | 50+ lignes de consignes strictes | 5 lignes suffisent (le modèle "sait" déjà) |
| **Latence d'inférence** | 8 à 15 secondes | **3 à 6 secondes** (-50% de temps) |
| **Taux de parsing JSON** | ~92-95% (nécessite regex/fallback) | **> 99,5%** de succès immédiat |
| **Autonomie locale** | Dépend souvent d'APIs Cloud (Gemini/Groq) | **100% autonome en local** sur Ollama |

---

## 7. Résumé à retenir pour la Soutenance devant le Professeur

Voici la réponse exacte à prononcer si la professeure te demande :
*« Pourquoi ne pas avoir fine-tuné vos modèles ? »*

> « Nous avons volontairement priorisé en Phase 1 une architecture basée sur **l'In-Context Learning (Prompt Engineering structuré + Moteur déterministe de fallback)**, car elle offre une flexibilité maximale sans coût de réentraînement.
> 
> Cependant, dans notre analyse d'architecture, nous avons identifié que le **BI Analyst Agent** est le candidat parfait pour un fine-tuning par **QLoRA** sur un modèle 7B (Llama 3.1 ou Qwen 2.5). 
> 
> Grâce à une distillation synthétique Teacher-Student de 500 exemples, ce fine-tuning permettrait de figer la grammaire exacte de nos rapports exécutifs et le schéma JSON attendu par Plotly directement dans les poids neuronaux, éliminant le besoin d'un prompt système verbeux et réduisant la latence d'inférence de près de 50% en local. »
