import os
import requests
import json
import subprocess

# --- 1. FONCTIONS DU SYSTÈME (LES BRAS) ---
def creer_fichier_local(nom_fichier: str, contenu: str) -> str:
    try:
        chemin_propre = os.path.basename(nom_fichier)
        with open(chemin_propre, "w", encoding="utf-8") as f:
            f.write(contenu)
        return f"[SYSTEME] Le fichier '{chemin_propre}' a été créé avec succès."
    except Exception as e:
        return f"[SYSTEME] Erreur : {str(e)}"

def executer_commande_git(arguments_git: str) -> str:
    if any(interdit in arguments_git for interdit in ["push", "remote", "reset --hard"]):
        return "[SYSTEME] Action Git interdite par politique de sécurité."
    try:
        resultat = subprocess.run(f"git {arguments_git}", shell=True, capture_output=True, text=True, check=True)
        return f"[SYSTEME] Sortie Git :\n{resultat.stdout if resultat.stdout else 'Commande exécutée sans sortie.'}"
    except subprocess.CalledProcessError as e:
        return f"[SYSTEME] Erreur Git :\n{e.stderr}"

# Dictionnaire de mapping pour exécuter dynamiquement la fonction demandée par le LLM
CARTOGRAPHIE_FONCTIONS = {
    "creer_fichier_local": creer_fichier_local,
    "executer_commande_git": executer_commande_git
}

# --- 2. DÉFINITION DES OUTILS POUR OLLAMA ---
OUTILS_BIFLOW = [
    {
        "type": "function",
        "function": {
            "name": "creer_fichier_local",
            "description": "Crée un nouveau fichier dans le projet avec un contenu textuel ou du code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nom_fichier": {"type": "string"},
                    "contenu": {"type": "string"}
                },
                "required": ["nom_fichier", "contenu"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "executer_commande_git",
            "description": "Exécute des commandes Git comme 'status', 'diff', ou 'add .'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "arguments_git": {"type": "string"}
                },
                "required": ["arguments_git"]
            }
        }
    }
]

# --- 3. BOUCLE DE L'AGENT ---
def executer_agent(prompt_utilisateur: str):
    url = "http://localhost:11434/api/chat"  # Utilisation de l'API /api/chat pour gérer les messages et les outils
    
    messages = [{"role": "user", "content": prompt_utilisateur}]
    payload = {
        "model": "qwen2.5:7b",
        "messages": messages,
        "tools": OUTILS_BIFLOW,
        "stream": False
    }
    
    print(f"[AGENT] Demande utilisateur : '{prompt_utilisateur}'")
    try:
        response = requests.post(url, json=payload, timeout=30)
        reponse_json = response.json()
        message_ia = reponse_json.get("message", {})
        
        # Vérifier si l'IA demande l'exécution d'un outil (Function Calling)
        if "tool_calls" in message_ia:
            for call in message_ia["tool_calls"]:
                nom_fonction = call["function"]["name"]
                arguments = call["function"]["arguments"]
                
                print(f"[AGENT] L'IA a décidé d'appeler l'outil : {nom_fonction} avec {arguments}")
                
                if nom_fonction in CARTOGRAPHIE_FONCTIONS:
                    # Exécution de l'action réelle sur le PC
                    resultat_action = CARTOGRAPHIE_FONCTIONS[nom_fonction](**arguments)
                    print(resultat_action)
                    
                    # On renvoie le résultat de l'action à l'IA pour qu'elle puisse formuler sa réponse finale
                    messages.append(message_ia)
                    messages.append({"role": "tool", "content": resultat_action, "name": nom_fonction})
                    
                    # Deuxième appel à l'IA avec le résultat de l'outil
                    payload_final = {"model": "qwen2.5:7b", "messages": messages, "stream": False}
                    reponse_finale = requests.post(url, json=payload_final, timeout=30)
                    print(f"\n[IA] Réponse finale : {reponse_finale.json()['message']['content']}")
                else:
                    print(f"[AGENT] Erreur : L'outil '{nom_fonction}' n'existe pas dans le code Python.")
        else:
            # L'IA a répondu directement sans utiliser d'outil
            print(f"\n[IA] Réponse directe : {message_ia.get('content', '')}")
            
    except requests.exceptions.ConnectionError:
        print("[AGENT] Erreur : Ollama local n'est pas lancé.")

if __name__ == "__main__":
    # Test 1 : Demander une action Git
    print("=== TEST ACTION 1 ===")
    executer_agent("Regarde le status de mon dépôt git actuel s'il te plaît.")
    
    print("\n" + "="*30 + "\n")
    
    # Test 2 : Demander la création d'un fichier
    print("=== TEST ACTION 2 ===")
    executer_agent("Crée un fichier nommé 'documentation_pipeline.txt' contenant le texte 'Pipeline BIFlow validé par l'agent.'")
