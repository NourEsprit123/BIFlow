# 🔌 Guide d'utilisation de l'Ollama local partagé

Pour économiser les ressources de vos machines et éviter de saturer les quotas des APIs cloud (Gemini/Groq), vous pouvez consommer directement le modèle **Qwen2.5:7b** qui s'exécute sur mon PC.

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
Copiez le fichier exemple ou mettez à jour votre `.env` actuel en fonction de notre scénario réseau (LAN ou WAN). 

⚠️ **ATTENTION : Les adresses IP et les liens réseaux ne sont plus hardcodés. Veuillez communiquer directement avec votre collègue Amine pour obtenir l'adresse IP locale actuelle ou le lien Pinggy actif du jour.**

#### Scénario A : Nous sommes sur le même réseau (Au Labo / LAN)
```env
LLM_MODE=LOCAL
# NOTE : Demander à Amine son adresse IP locale actuelle (ex: 10.151.68.X)
PARTAGED_OLLAMA_URL=http://<IP_ACTUELLE_COMMUNIQUEE_PAR_AMINE>:11435
```

#### Scénario B : Nous sommes chez nous (À la maison / WAN)
```env
LLM_MODE=LOCAL
# NOTE : Demander à Amine le lien de tunnel sécurisé Pinggy généré pour la session actuelle
PARTAGED_OLLAMA_URL=https://<LIEN_PINGGY_ACTUEL_COMMUNIQUE_PAR_AMINE>.run.pinggy-free.link
```

---

## 🧪 Valider la connexion

Pour vérifier que votre machine communique correctement avec mon processeur et ma carte graphique sans rien télécharger chez vous, exécutez le script de test :

```powershell
python test_shared_ollama.py
```

### Résultats attendus :
* **Si `[SUCCÈS]` s'affiche :** Tout est parfait ! Vos requêtes applicatives transiteront de manière transparente vers mon instance locale.
* **Si `[ÉCHEC]` s'affiche :** Vérifiez que vous avez saisi la bonne URL active communiquée par Amine dans votre fichier `.env`.

---

## 🔒 Note pour l'hébergeur (Comment ouvrir le canal WAN)
Pour générer les liens sécurisés à distance sans aucun mot de passe ni logiciel à installer, récupérez d'abord votre adresse IP réseau actuelle, puis exécutez cette commande dans PowerShell :
```powershell
# Remplacer <VOTRE_IP_LAN_ACTUELLE> par celle de votre carte réseau avant d'exécuter
ssh -R 443:<VOTRE_IP_LAN_ACTUELLE>:11435 pinggy@a.pinggy.io -p 443
```
