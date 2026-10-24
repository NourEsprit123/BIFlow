import os
import pandas as pd
import ollama

print("🚀 Démarrage de l'agent BI Analyst dans l'environnement Sandbox (Docker)...")

chemin_csv = "sandbox/data_input/donnees_propres_bi.csv"
if not os.path.exists(chemin_csv):
    print(f"❌ Erreur : Fichier {chemin_csv} introuvable.")
    exit(1)

df = pd.read_csv(chemin_csv)

# Synthèse des données pour le contexte restreint du modèle 7B
resume_stats = f"""
Total des transactions : {len(df)}
Ventes totales (TND) : {df['total_vente_tnd'].sum():.2f} TND
Ventes par catégorie (TND) :
{df.groupby('categorie')['total_vente_tnd'].sum().to_string()}
Top 3 des produits les plus vendus :
{df.groupby('produit')['total_vente_tnd'].sum().nlargest(3).to_string()}
"""

prompt = f"""
Tu es l'agent BI Analyst de la plateforme BIFlow[cite: 1]. 
Voici la synthèse des données nettoyées fournies par l'agent Data Engineer :

{resume_stats}

Rédige un rapport synthétique d'analyse de business intelligence au format Markdown contenant :
1. Une analyse globale des performances.
2. Les KPI clés à retenir.
3. Une recommandation stratégique basée sur les tops ventes.
"""

# Connexion vers Ollama hébergé sur la machine hôte depuis Docker
host_ollama = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
client = ollama.Client(host=host_ollama)

print("⏳ Envoi du résumé d'analyse à qwen2.5:7b via Ollama local...")
response = client.chat(
    model='qwen2.5:7b',
    messages=[{'role': 'user', 'content': prompt}],
    # CUDA is failing in the host Ollama server; default to CPU, configurable via OLLAMA_NUM_GPU.
    options={'num_gpu': int(os.getenv('OLLAMA_NUM_GPU', '0'))}
)

rapport_md = response['message']['content']

# Sauvegarde sécurisée dans le dossier de sortie sandbox
os.makedirs("sandbox/reports_output", exist_ok=True)
chemin_rapport = "sandbox/reports_output/rapport_bi_analyst.md"
with open(chemin_rapport, "w", encoding="utf-8") as f:
    f.write("# 📊 Rapport d'Analyse BI Analyst - BIFlow\n\n")
    f.write(rapport_md)

print(f"✅ Rapport généré avec succès dans le sandbox : '{chemin_rapport}' !")