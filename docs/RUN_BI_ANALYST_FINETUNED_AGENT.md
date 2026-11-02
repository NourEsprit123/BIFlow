# 🚀 Guide d'Exécution : BI Analyst Agent & Modèle Fine-Tuné (Qwen 2.5 3B LoRA)

> **Projet :** BIFlow — Plateforme Multi-Agents Autonome de Business Intelligence  
> **Composant :** Agent 2 (BI Analyst Agent) — Moteur Hybride Local LoRA & Cloud API  
> **Fichiers clés :**
> - Code de l'agent : [`agents/bi_analyst_agent.py`](../agents/bi_analyst_agent.py)
> - Interface utilisateur : [`dashboard/pages/5_BI_Analysis.py`](../dashboard/pages/5_BI_Analysis.py)
> - Script de test autonome : [`scripts/test_finetuned_agent.py`](../scripts/test_finetuned_agent.py)
> - Poids de l'adaptateur LoRA : `adapter/`

---

## 1. Vue d'Ensemble de l'Architecture Hybride

Le **BI Analyst Agent** de BIFlow a été conçu pour offrir le meilleur des deux mondes :

```
                          ┌──────────────────────────────┐
                          │   Dataset Nettoyé (CSV/DF)   │
                          └──────────────┬───────────────┘
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   ▼                                           ▼
      ⚡ MODE LOCAL FINE-TUNÉ (LoRA)                ☁️ MODE CLOUD API (Groq/Gemini)
  ┌───────────────────────────────────────┐   ┌───────────────────────────────────────┐
  │ • Qwen 2.5 3B (Quantifié 4-bit NF4)   │   │ • Groq (Llama-3.3 70B) ou Gemini      │
  │ • LoRA Adapter (adapter_model)        │   │ • Long Prompt Engineering (8 000+ car)│
  │ • Résumé Statistique Compact (350 car)│   │ • Consignes, Persona, Few-Shots       │
  │ • 100% Hors-ligne, Privé, 0 Latence Net│   │ • Haute capacité de raisonnement cloud│
  └───────────────────┬───────────────────┘   └───────────────────┬───────────────────┘
                      │                                           │
                      └─────────────────────┬─────────────────────┘
                                            ▼
                           ┌─────────────────────────────────┐
                           │   Rapport Exécutif Markdown     │
                           │   + Bloc JSON Validé            │
                           │   (4 KPIs + Graphiques Plotly)  │
                           └─────────────────────────────────┘
```

---

## 2. Prérequis & Installation de l'Environnement

### A. Dépendances Python
Pour exécuter l'inférence locale accélérée par GPU avec quantification 4-bit, installez les paquets suivants :

```bash
# 1. PyTorch avec support CUDA (si vous avez un GPU NVIDIA)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 2. Bibliothèques Hugging Face & Inférence 4-bit
pip install transformers peft bitsandbytes accelerate

# 3. Dépendances standards du projet
pip install -r requirements.txt
```

### B. Configuration Matérielle
- **Recommandé (Mode Local) :** GPU NVIDIA avec support CUDA (ex: RTX 3050, RTX 3060, RTX 4050, RTX 4060, etc.). Grâce à la quantification **4-bit NF4 (`bitsandbytes`)**, le modèle ne consomme que **~2.1 Go de VRAM**.
- **Sans GPU ou Configuration Légère :** Aucun problème ! L'agent dispose d'un basculement automatique vers le **Mode Cloud API (Groq Llama-3 / Gemini)** ou vers le **Moteur Statistique Déterministe**, garantissant que l'application ne plante jamais.

---

## 3. Mise en Place des Fichiers de l'Adaptateur LoRA (`adapter/`)

Le dépôt Git contient déjà tous les fichiers de configuration nécessaires dans le dossier `adapter/` :
- `adapter/adapter_config.json`
- `adapter/chat_template.jinja`
- `adapter/tokenizer_config.json`
- `adapter/README.md`

### Comment obtenir les poids `adapter_model.safetensors` (~119.8 Mo) ?

Le fichier de poids binaire `adapter_model.safetensors` a été volontairement exclu du dépôt Git pour garder le projet léger (< 15 Mo). Vous avez deux façons simples de l'obtenir :

#### Option A : Récupérer depuis l'entraînement Google Colab
Si vous ou votre binôme avez entraîné le modèle sur Google Colab via le guide [`docs/COLAB_FINETUNING_NOTEBOOK_QWEN_LORA.md`](./COLAB_FINETUNING_NOTEBOOK_QWEN_LORA.md) :
1. Dans Colab, à la fin du fine-tuning, téléchargez le dossier exporté `adapter/`.
2. Déposez simplement le fichier `adapter_model.safetensors` dans votre dossier local `biflow/adapter/` :
   ```
   biflow/
   └── adapter/
       ├── adapter_config.json
       ├── adapter_model.safetensors  <-- Placez le fichier ici (119.8 Mo)
       ├── chat_template.jinja
       └── tokenizer_config.json
   ```

#### Option B : Utiliser le Mode Cloud API (Aucun téléchargement requis)
Si vous ne souhaitez pas télécharger les poids locaux, vous pouvez utiliser immédiatement l'Agent en Mode Cloud API en définissant votre clé Groq ou Gemini dans le fichier `.env` ou directement dans l'interface graphique.

---

## 4. Test Autonome en Ligne de Commande

Avant de lancer l'interface graphique, vous pouvez valider le bon fonctionnement du modèle fine-tuné et la validité de ses sorties JSON via le script dédié :

```bash
python scripts/test_finetuned_agent.py
```

### Ce que fait ce script :
1. Charge le modèle de base `Qwen/Qwen2.5-3B-Instruct` quantifié en 4-bit (`BitsAndBytesConfig`).
2. Attache l'adaptateur LoRA depuis `adapter/`.
3. Génère le résumé statistique compact d'un dataset de test (`data/raw/telco_churn.csv`).
4. Exécute l'inférence neuronale locale sur votre GPU.
5. Vérifie que le rapport contient :
   - Un rapport d'analyse exécutif complet en 5 sections.
   - Un bloc ```` ```json ... ``` ```` 100% parseable.
   - Exactement 4 KPIs avec `title`, `value`, `subtitle`.
   - Entre 4 et 6 graphiques recommandés dont les colonnes existent réellement dans le dataset.
6. Sauvegarde le résultat dans [`data/reports/finetuned_eval_telco_churn.md`](../data/reports/finetuned_eval_telco_churn.md).

---

## 5. Utilisation dans l'Interface Streamlit (`dashboard/app.py`)

Lancez la plateforme BIFlow :

```bash
streamlit run dashboard/app.py
```

1. Dans la barre latérale, naviguez vers la page **5 BI Analysis**.
2. Choisissez un dataset (ex: `data/raw/telco_churn.csv`).
3. Vous remarquerez en haut de la page et dans la barre latérale le **🔀 Commutateur de Moteur BI** :
   - **⚡ Local Fine-Tuned (Qwen 2.5 3B LoRA)** : Traitement 100% hors-ligne sur votre GPU local avec le prompt statistique compact.
   - **☁️ Cloud API (Groq / Gemini)** : Traitement via API distante avec le long prompt exhaustif de prompt engineering.
4. En bas de la page, cliquez sur l'onglet **"🔍 Prompt Engineering & Engine Telemetry"** :
   - Vous pouvez visualiser en direct le **texte exact du prompt envoyé au modèle**.
   - Vous observerez ainsi la différence fondamentale : ~350 caractères condensés pour le modèle fine-tuné contre plus de 8 000 caractères pour le modèle API Cloud.

---

## 6. Dépannage & Bonnes Pratiques

| Problème rencontré | Cause | Solution |
| :--- | :--- | :--- |
| `FileNotFoundError: adapter/adapter_model.safetensors` | Le fichier de poids n'a pas encore été placé dans `adapter/` | Déposez le fichier `.safetensors` dans `adapter/` ou basculez en mode "Cloud API" sur la page. |
| `BitsAndBytes` introuvable sur Windows | Version obsolète de `bitsandbytes` | Exécutez `pip install bitsandbytes>=0.50.0` (support natif de Windows CUDA). |
| Erreur Protobuf / TensorFlow | Conflit de version gencode Protobuf | Définissez `os.environ["USE_TF"] = "0"` (déjà intégré au code de `bi_analyst_agent.py`). |
| Mémoire VRAM insuffisante (GPU < 4 Go) | Modèle chargé en FP16 sans quantification | Vérifiez que `bitsandbytes` est installé afin que le modèle soit chargé en 4-bit (2.1 Go VRAM). |

---

## 7. Fichiers et Ressources Associées

- [Documentation Complète de la Stratégie Fine-Tuning](file:///c:/Users/moham/Desktop/Med/biflow/docs/BI_ANALYST_AGENT_AND_FINETUNING_GUIDE.md)
- [Notebook Google Colab d'Entraînement LoRA](file:///c:/Users/moham/Desktop/Med/biflow/docs/COLAB_FINETUNING_NOTEBOOK_QWEN_LORA.md)
- [Dataset d'Entraînement Synthétique (500 exemples)](file:///c:/Users/moham/Desktop/Med/biflow/train_bi_agent.jsonl)
- [Générateur de Datasets Synthétiques](file:///c:/Users/moham/Desktop/Med/biflow/generate_1000_dataset.py)
