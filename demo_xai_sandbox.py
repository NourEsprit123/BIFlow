import os
import ollama

print("🔍 Démarrage de l'agent XAI (Explainable AI) dans la sandbox...")

# 1. Lecture des données d'entrée (par exemple, le rapport ou un résumé du BI Analyst)
input_path = "sandbox/reports_output/rapport_bi_analyst.md"
if not os.path.exists(input_path):
    # Fallback si le rapport du BI Analyst n'est pas encore généré
    contexte_donnees = "Analyse des ventes globales : forte performance de la catégorie Électronique portée par les PC Portables."
else:
    with open(input_path, "r", encoding="utf-8") as f:
        contexte_donnees = f.read()

# 2. Prompt orienté XAI (transparence, justification, facteurs d'influence)
prompt = f"""
Tu es l'agent XAI (Explainable AI) de la plateforme BIFlow[cite: 1]. 
À partir des résultats et rapports d'analyse suivants :
{contexte_donnees}

Génère un rapport d'explicabilité transparent contenant :
1. **Facteurs clés d'influence :** Pourquoi ces résultats ont-ils été obtenus ? (Justification logique).
2. **Niveau de confiance et limites :** Évaluation de la robustesse des insights.
3. **Traduction pour non-initiés :** Explication claire et simple des décisions ou tendances sous-jacentes.
"""

print("⏳ Interrogation de qwen2.5:7b pour l'explicabilité...")
response = ollama.chat(
    model='qwen2.5:7b',
    messages=[{'role': 'user', 'content': prompt}]
)

rapport_xai = response['message']['content']

# 3. Sauvegarde sécurisée dans la sandbox XAI
output_path = "sandbox_xai/reports_output/rapport_xai_explicabilite.md"
with open(output_path, "w", encoding="utf-8") as f:
    f.write("# 🤖 Rapport d'Explicabilité - XAI Agent (BIFlow)\n\n")
    f.write(rapport_xai)

print(f"✅ Rapport XAI généré avec succès dans : '{output_path}' !")