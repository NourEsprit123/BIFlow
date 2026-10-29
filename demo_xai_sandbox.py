import os
import json
import ollama

print("🔍 Démarrage de l'Agent XAI (Audit & Traçabilité des transformations)...")

# 1. Préparation des données d'entrée (Simulation des logs du Data Engineer)
log_audit_simule = {
    "source_file": "donnees_brutes.csv",
    "transformations_appliquees": [
        {"action": "imputation_valeurs_manquantes", "colonne": "prix_unitaire", "methode": "mediane"},
        {"action": "suppression_doublons", "lignes_supprimees": 14},
        {"action": "filtrage_outliers", "colonne": "total_vente", "seuil": "> 3 standard deviations"}
    ],
    "qualite_initiale_score": 72.5,
    "qualite_finale_score": 96.8
}

prompt = f"""
Tu es l'agent XAI (Explainable AI & Data Governance) de la plateforme BIFlow[cite: 1].
Voici l'audit de transformation fourni par le Data Engineer :

{json.dumps(log_audit_simule, indent=2)}

Génère un objet JSON valide et structuré (sans texte autour, uniquement le JSON) contenant :
1. "transformation_log_id": un ID unique.
2. "quality_score_before": 72.5
3. "quality_score_after": 96.8
4. "explainability_summary": Une explication concise en français de la raison et de la conformité de chaque transformation.
5. "governance_status": "COMPLIANT" ou "NON_COMPLIANT".
"""

# Connexion vers Ollama hébergé sur la machine hôte depuis Docker
host_ollama = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
client = ollama.Client(host=host_ollama)

print("⏳ Génération du rapport de traçabilité JSON via qwen2.5:7b...")
response = client.chat(
    model='qwen2.5:7b',
    messages=[{'role': 'user', 'content': prompt}]
)

json_output = response['message']['content']

# Nettoyage minimal pour s'assurer d'avoir du JSON pur
if "```json" in json_output:
    json_output = json_output.split("```json")[1].split("```")[0].strip()

# 2. Sauvegarde du fichier de sortie structuré
dossier_sortie = "sandbox_xai/reports_output"
os.makedirs(dossier_sortie, exist_ok=True)
chemin_json = os.path.join(dossier_sortie, "donnees_propres_bi_transformation_log.json")

with open(chemin_json, "w", encoding="utf-8") as f:
    f.write(json_output)

print(f"✅ Fichier de traçabilité généré avec succès dans : '{chemin_json}' !")