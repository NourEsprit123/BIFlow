import os
import requests

def executer_requete_llm(prompt: str) -> str:
    # Récupère la variable d'environnement (par défaut LOCAL)
    LLM_MODE = os.getenv("LLM_MODE", "LOCAL").upper()
    
    if LLM_MODE == "LOCAL":
        url = "http://localhost:11434/api/generate"
        payload = {"model": "qwen2.5:7b", "prompt": prompt, "stream": False}
        try:
            print("[TEST] Tentative d'appel Ollama Local...")
            response = requests.post(url, json=payload, timeout=10)
            return response.json().get("response", "Aucune réponse")
        except requests.exceptions.ConnectionError:
            return "[FAIL] Ollama n'est pas lancé localement ou l'URL est incorrecte."
    else:
        print("[TEST] Mode API détecté. Simulation de l'appel externe...")
        return f"[SUCCESS] Simulation API externe réussie."

if __name__ == "__main__":
    print("--- TEST 1 : Mode Local (Par défaut) ---")
    print(executer_requete_llm("Dis bonjour brièvement"))
    
    print("\n--- TEST 2 : Bascule dynamique en mode API ---")
    os.environ["LLM_MODE"] = "API"
    print(executer_requete_llm("Dis bonjour brièvement"))
