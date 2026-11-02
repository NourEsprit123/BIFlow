import os
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

# 1. Charger les variables du fichier .env
load_dotenv()
base_url = os.environ.get("CUSTOM_LLM_BASE_URL")
model_name = os.environ.get("CUSTOM_LLM_MODEL_NAME", "qwen-2.5-3b-bi-analyst")

print(f"🔗 Base URL chargée : {base_url}")
print(f"🤖 Modèle configuré : {model_name}")

if not base_url:
    print("❌ Erreur : CUSTOM_LLM_BASE_URL est introuvable ou vide dans le fichier .env !")
    exit(1)

# 2. Initialiser le client OpenAI pointant EXCLUSIVEMENT vers votre Colab/ngrok
client = OpenAI(base_url=base_url, api_key="not-needed")

# 3. Créer un dataset de test simple
df = pd.DataFrame({
    "category": ["Tech", "Finance", "Tech", "Operations", "Finance"],
    "revenue": [12000, 45000, 15000, 30000, 60000],
    "profit_margin": [0.15, 0.22, 0.18, 0.10, 0.25]
})

prompt = f"""Analyze this dataset with {len(df)} rows and provide an executive report with KPIs and charts in JSON format.
- Columns: {list(df.columns)}
- Sample data: {df.to_dict(orient='records')}
"""

try:
    print("\n📡 Envoi de la requête directe au modèle GGUF sur Colab...")
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": "You are an expert Business Intelligence data analyst."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        max_tokens=1500
    )
    
    print("\n✅ Succès ! Réponse reçue du serveur Colab :")
    print("=" * 60)
    print(response.choices[0].message.content)
    print("=" * 60)

except Exception as e:
    print(f"\n❌ Erreur de communication directe avec l'API Colab : {e}")