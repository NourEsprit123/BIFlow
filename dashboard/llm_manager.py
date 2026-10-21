import os
import json
import requests
import subprocess

def charger_env_manuel():
    """Charge le fichier .env s'il existe à la racine ou dans le dossier courant."""
    chemins = [".env", "../.env", "dashboard/.env"]
    for chemin in chemins:
        if os.path.exists(chemin):
            with open(chemin, "r", encoding="utf-8") as f:
                for ligne in f:
                    if ligne.strip() and not ligne.startswith("#"):
                        try:
                            cle, valeur = ligne.strip().split("=", 1)
                            os.environ[cle.strip()] = valeur.strip()
                        except ValueError:
                            continue
            break

# Chargement immédiat de la configuration utilisateur (.env)
charger_env_manuel()

# ==============================================================================
# ACTIONS DU SYSTEME (LES BRAS DE L'AGENT)
# ==============================================================================
def creer_fichier_local(nom_fichier: str, contenu: str) -> str:
    """Outil permettant à l'agent de créer un fichier physique sur le disque."""
    try:
        chemin_propre = os.path.basename(nom_fichier)
        with open(chemin_propre, "w", encoding="utf-8") as f:
            f.write(contenu)
        return f"[SYSTEME] Succès : Le fichier '{chemin_propre}' a été créé."
    except Exception as e:
        return f"[SYSTEME] Échec : {str(e)}"

def executer_commande_git(arguments_git: str) -> str:
    """Outil permettant à l'agent d'inspecter ou d'interagir avec le dépôt Git."""
    # Sécurité : blocage des actions de destruction ou de push distant
    if any(i in arguments_git for i in ["push", "remote", "reset --hard"]):
        return "[SYSTEME] Refus : Action Git interdite par politique de sécurité."
    try:
        resultat = subprocess.run(f"git {arguments_git}", shell=True, capture_output=True, text=True, check=True)
        return f"[SYSTEME] Sortie Git :\n{resultat.stdout if resultat.stdout else 'Commande exécutée sans sortie.'}"
    except subprocess.CalledProcessError as e:
        return f"[SYSTEME] Erreur Git :\n{e.stderr}"

# Table de correspondance pour l'exécution dynamique des outils
CARTOGRAPHIE_FONCTIONS = {
    "creer_fichier_local": creer_fichier_local,
    "executer_commande_git": executer_commande_git
}

# Déclarations des outils au format JSON standard d'Ollama
OUTILS_BIFLOW = [
    {
        "type": "function",
        "function": {
            "name": "creer_fichier_local",
            "description": "Crée un nouveau fichier physique dans le projet avec un contenu textuel (ex: rapports, scripts).",
            "parameters": {
                "type": "object",
                "properties": {
                    "nom_fichier": {"type": "string", "description": "Nom complet du fichier à créer."},
                    "contenu": {"type": "string", "description": "Texte ou code à écrire à l'intérieur."}
                },
                "required": ["nom_fichier", "contenu"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "executer_commande_git",
            "description": "Exécute des commandes d'inspection ou de gestion de version Git (ex: 'status', 'diff', 'add .', 'commit -m').",
            "parameters": {
                "type": "object",
                "properties": {
                    "arguments_git": {"type": "string", "description": "Arguments de la commande git (ex: 'status')."}
                },
                "required": ["arguments_git"]
            }
        }
    }
]

# ==============================================================================
# POINT D'ENTRÉE DU REQUÊTAGE UNIQUE
# ==============================================================================
def executer_requete_llm(prompt: str) -> str:
    """Gère le routage hybride et l'exécution active des requêtes d'intelligence."""
    LLM_MODE = os.getenv("LLM_MODE", "LOCAL").upper()
    
    if LLM_MODE == "LOCAL":
        url = "http://localhost:11434/api/chat"
        messages = [{"role": "user", "content": prompt}]
        payload = {
            "model": "qwen2.5:7b",
            "messages": messages,
            "tools": OUTILS_BIFLOW,
            "stream": False
        }
        try:
            response = requests.post(url, json=payload, timeout=25)
            message_ia = response.json().get("message", {})
            
            # Gestion du Function Calling autonome
            if "tool_calls" in message_ia:
                for call in message_ia["tool_calls"]:
                    nom_fonction = call["function"]["name"]
                    arguments = call["function"]["arguments"]
                    
                    if nom_fonction in CARTOGRAPHIE_FONCTIONS:
                        # Exécution physique de l'action
                        resultat_action = CARTOGRAPHIE_FONCTIONS[nom_fonction](**arguments)
                        
                        # Transmission du résultat à Ollama pour synthèse finale
                        messages.append(message_ia)
                        messages.append({"role": "tool", "content": resultat_action, "name": nom_fonction})
                        
                        payload_final = {"model": "qwen2.5:7b", "messages": messages, "stream": False}
                        reponse_finale = requests.post(url, json=payload_final, timeout=25)
                        return reponse_finale.json()['message']['content']
                        
            return message_ia.get('content', '')
        except requests.exceptions.ConnectionError:
            return "Erreur : Le serveur Ollama local n'est pas démarré. Veuillez basculer sur LLM_MODE=API si nécessaire."
            
    elif LLM_MODE == "API":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return "Erreur : Mode cloud configuré mais la variable GEMINI_API_KEY est manquante dans votre .env."
            
        url = f"https://googleapis.com{api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            response.raise_for_status()
            return response.json()["candidates"]["content"]["parts"]["text"]
        except Exception as e:
            return f"Erreur lors de la communication avec l'API cloud distante : {str(e)}"
            
    return f"Erreur : Le mode de gestion des ressources '{LLM_MODE}' n'est pas reconnu."
