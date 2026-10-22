# 🔌 Guide d'utilisation de l'Ollama local partagé

Pour économiser les ressources de vos machines et éviter de saturer les quotas des APIs cloud (Gemini/Groq), vous pouvez consommer directement le modèle **Qwen2.5:7b** qui s'exécute sur mon PC via notre réseau LAN.

## 🛠️ Configuration en 3 étapes

### 1. Récupérer la bonne branche Git
Placez-vous sur la branche dédiée au partage des ressources :
```powershell
git fetch origin
git checkout feature/shared-ollama-setup
```

### 2. Installer les dépendances
Assurez-vous que votre environnement virtuel (`venv`) est activé, puis mettez à jour vos packages :
```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Configurer votre fichier `.env`
Copiez le fichier exemple ou mettez à jour votre `.env` actuel avec les paramètres réseau de mon hôte Windows :
```env
# Moteur d'exécution (Force l'utilisation du PC de votre collègue)
LLM_MODE=LOCAL

# URI exacte de l'Ollama actif sur le réseau LAN
PARTAGED_OLLAMA_URL=http://10.151.68.206:11435
```

---

## 🧪 Valider la connexion

Pour vérifier que votre machine communique correctement avec mon processeur et ma carte graphique sans rien télécharger chez vous, exécutez le script de test :

```powershell
python test_shared_ollama.py
```

### Résultats attendus :
* **Si `[SUCCÈS]` s'affiche :** Tout est parfait ! Vos requêtes applicatives transiteront de manière transparente vers mon instance locale.
* **Si `[ÉCHEC]` s'affiche :** Vérifiez que vous êtes bien connectés sur le même réseau Wi-Fi/LAN que moi, ou tentez d'ouvrir l'URL `http://10.151.68.206:11435` dans votre navigateur pour tester la route réseau.

---

## 🔒 Note concernant le Télétravail (À la maison)
Ce setup fonctionne actuellement via notre réseau local (**LAN**). Dès que nous basculerons à distance, nous sécuriserons cette canalisation via un tunnel chiffré (**Tailscale** ou **Ngrok**). L'URL `PARTAGED_OLLAMA_URL` de votre fichier `.env` sera la seule variable à modifier.
