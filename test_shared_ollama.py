import os
import requests
from dotenv import load_dotenv

# Charger les variables depuis le fichier .env
load_dotenv()

def tester_connexion_ollama():
    mode = os.getenv("LLM_MODE", "LOCAL").upper()
    ollama_url = os.getenv("PARTAGED_OLLAMA_URL", "http://10.151.68.206:11435")

    print(f"[INFO] Mode configuré : {mode}")
    if mode != "LOCAL":
        print("[ANNULATION] Le mode n'est pas configuré sur 'LOCAL'.")
        return

    # Cibler directement l'API native d'Ollama pour éviter les bugs de structure du SDK OpenAI
    endpoint_generate = f"{ollama_url}/api/generate"
    print(f"[TEST] Envoi de la requête au serveur Ollama sur : {endpoint_generate}...")

    payload = {
        "model": "qwen2.5:7b",
        "prompt": "Réponds par le mot 'OK' si tu reçois ce message correctement.",
        "stream": False
    }

    try:
        # Envoi de la requête POST directe
        response = requests.post(endpoint_generate, json=payload, timeout=30)
        
        if response.status_code == 200:
            resultat = response.json()
            print("\n[SUCCÈS] Connexion établie avec succès !")
            print("-" * 50)
            print(f"Réponse de ton Qwen2.5 local : {resultat.get('response')}")
            print("-" * 50)
        else:
            print(f"\n[ÉCHEC] Le serveur a répondu avec un code erreur : {response.status_code}")

    except Exception as e:
        print("\n[ÉCHEC] Impossible de joindre l'Ollama partagé.")
        print(f"Détails de l'erreur : {e}")

if __name__ == "__main__":
    tester_connexion_ollama()
