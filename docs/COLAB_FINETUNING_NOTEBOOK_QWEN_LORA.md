# 🚀 Notebook Google Colab : Fine-Tuning Qwen 2.5 3B avec LoRA (PEFT)
> **Projet :** BIFlow — BI Analyst Agent  
> **Modèle cible :** `Qwen/Qwen2.5-3B-Instruct`  
> **Environnement :** Google Colab (GPU Nvidia T4 - 16 Go VRAM)  
> **Temps d'entraînement estimé :** ~15 à 25 minutes pour 5 époques  
> **Poids LoRA finaux :** ~15 Mo sauvegardés automatiquement dans Google Drive  

---

## Guide d'Exécution sur Google Colab

1. Rendez-vous sur [Google Colab](https://colab.research.google.com/).
2. Créez un nouveau notebook (`Nouveau notebook`).
3. **Activer le GPU :** Cliquez sur **Exécution** > **Modifier le type d'exécution** > Sélectionnez **T4 GPU** > Cliquez sur **Enregistrer**.
4. Copiez et exécutez chacune des 7 cellules ci-dessous dans l'ordre.

---

```python
# ============================================================
# CELLULE 1 - Montage Google Drive & Détection GPU
# ============================================================
from google.colab import drive
drive.mount('/content/drive')

import torch
print(f"PyTorch: {torch.__version__}")
print(f"CUDA disponible: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
else:
    raise SystemExit("⚠️ Activez le GPU T4 : Exécution > Modifier le type d'exécution > T4 GPU")
```

```python
# ============================================================
# CELLULE 2 - Installation des dépendances (Hugging Face & PEFT)
# ============================================================
!pip install -q transformers==4.44.0 peft==0.12.0 accelerate==0.33.0 datasets trl
```

```python
# ============================================================
# CELLULE 3 - Dataset d'entraînement pour le BI Analyst
# ============================================================
import json

# Exemple de données d'entraînement pour BIFlow
training_data = [
  {
    "input": "Dataset: telco_churn.csv (7043 rows, 21 cols). Target: Churn (Yes: 26.5%, No: 73.5%). MonthlyCharges (mean=64.76, max=118.75). Contract (Month-to-month: 55%, Two year: 24%). TotalCharges nulls: 11.",
    "output": """# 📊 Executive Business Intelligence Report

## 1. Executive Summary
L'analyse porte sur 7,043 clients. Le taux d'attrition global atteint 26.5%, représentant un risque financier direct sur les revenus récurrents.

## 2. Key Performance Indicators
- **Taux de Churn**: `26.5%` (1 869 clients résiliés)
- **Revenu Moyen**: `64.76 $` (Par abonné mensuel)
- **Part Contrats Mensuels**: `55.0%` (Segment le plus volatile)
- **Pertes Estimées**: `121,000 $` (Impact direct du churn)

## 3. Emerging Trends & Patterns
Les abonnés en contrat mois-par-mois présentent un taux d'attrition 4 fois plus élevé que les contrats pluriannuels.

## 4. Anomalies & Data Observations
Présence de 11 valeurs manquantes sur TotalCharges correspondant à de nouveaux clients (tenure=0).

## 5. Strategic Recommendations
1. Inciter à la migration vers des contrats annuels par des remises ciblées.
2. Déployer un programme de fidélisation dès le 3ème mois d'abonnement.
3. Automatiser l'imputation à 0 des charges pour les nouveaux inscrits.

```json
{
  "kpis": [
    {"title": "Taux de Churn", "value": "26.5%", "subtitle": "1 869 résiliations"},
    {"title": "Revenu Moyen", "value": "64.76 $", "subtitle": "Par mois et par client"},
    {"title": "Part Contrats Mensuels", "value": "55.0%", "subtitle": "Segment critique"},
    {"title": "Pertes Estimées", "value": "121,000 $", "subtitle": "Revenu récurrent perdu"}
  ],
  "recommended_charts": [
    {"title": "Répartition du Churn par Contrat", "type": "bar", "column_x": "Contract", "column_y": "TotalCharges"},
    {"title": "Distribution des Charges Mensuelles", "type": "histogram", "column_x": "MonthlyCharges", "column_y": null},
    {"title": "Proportion Globale du Churn", "type": "pie", "column_x": "Churn", "column_y": null}
  ]
}
```"""
  },
  {
    "input": "Dataset: retail_sales.csv (10000 rows, 12 cols). Total Revenue: 1,450,000 $. Top Category: Electronics (42%). Avg Order Value: 145 $. Returns: 8.2%.",
    "output": """# 📊 Executive Business Intelligence Report

## 1. Executive Summary
Le chiffre d'affaires cumulé atteint 1,450,000 $ sur 10,000 transactions. La catégorie Électronique génère à elle seule 42% du revenu total.

## 2. Key Performance Indicators
- **Chiffre d'Affaires Global**: `1,450,000 $` (Volume annuel)
- **Panier Moyen**: `145 $` (Par commande)
- **Taux de Retour**: `8.2%` (Moyenne sectorielle maîtrisée)
- **Part Électronique**: `42.0%` (Segment moteur)

## 3. Emerging Trends & Patterns
Forte saisonnalité sur le quatrième trimestre avec un panier moyen en hausse de 28% lors des périodes promotionnelles.

## 4. Anomalies & Data Observations
Faible dispersion sur les délais de livraison mais pics de retours observés sur la catégorie Habillement.

## 5. Strategic Recommendations
1. Renforcer les stocks sur les accessoires à forte marge complémentaires à l'électronique.
2. Optimiser les fiches tailles pour réduire le taux de retour en habillement.
3. Mettre en place un programme VIP pour les clients avec panier > 250 $.

```json
{
  "kpis": [
    {"title": "Chiffre d'Affaires", "value": "1.45M $", "subtitle": "10 000 commandes"},
    {"title": "Panier Moyen", "value": "145 $", "subtitle": "Par transaction"},
    {"title": "Taux de Retour", "value": "8.2%", "subtitle": "Niveau acceptable"},
    {"title": "Part Électronique", "value": "42%", "subtitle": "Leader des ventes"}
  ],
  "recommended_charts": [
    {"title": "Ventes par Catégorie de Produits", "type": "bar", "column_x": "Category", "column_y": "Revenue"},
    {"title": "Distribution du Montant des Commandes", "type": "histogram", "column_x": "OrderAmount", "column_y": null},
    {"title": "Répartition des Modes de Paiement", "type": "pie", "column_x": "PaymentType", "column_y": null}
  ]
}
```"""
  }
]

print(f"Total d'exemples d'entraînement : {len(training_data)}")
```

```python
# ============================================================
# CELLULE 4 - Formatage avec le Chat Template officiel de Qwen 2.5
# ============================================================
from datasets import Dataset
from transformers import AutoTokenizer

MODEL_NAME = "Qwen/Qwen2.5-3B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

SYSTEM_PROMPT = (
    "Tu es le BI Analyst Agent de la plateforme BIFlow. "
    "Tu dois analyser les métriques d'un jeu de données et générer un rapport exécutif Markdown "
    "suivi obligatoirement d'un bloc ```json pour l'affichage de graphiques Plotly."
)

def format_chat(example):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Analyse ces métriques de dataset :\n{example['input']}"},
        {"role": "assistant", "content": example['output']}
    ]
    # Applique automatiquement les balises <|im_start|> et <|im_end|> de Qwen
    return {"text": tokenizer.apply_chat_template(messages, tokenize=False)}

dataset = Dataset.from_list([format_chat(ex) for ex in training_data])
dataset = dataset.train_test_split(test_size=0.2, seed=42)

print("Exemple formaté avec les balises ChatML de Qwen :")
print(dataset["train"][0]["text"][:400])
```

```python
# ============================================================
# CELLULE 5 - Chargement de Qwen 2.5 3B en FP16
# ============================================================
from transformers import AutoModelForCausalLM
import torch

print(f"Chargement de {MODEL_NAME}...")
model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    torch_dtype=torch.float16,
    device_map="auto"
)
model.config.use_cache = False
print(f"Paramètres du modèle de base : {sum(p.numel() for p in model.parameters()) / 1e9:.2f} Milliards")
```

```python
# ============================================================
# CELLULE 6 - Configuration LoRA (Rank 16, Alpha 32)
# ============================================================
from peft import LoraConfig, get_peft_model, TaskType

lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type=TaskType.CAUSAL_LM
)

model = get_peft_model(model, lora_config)
model.print_trainable_parameters()
```

```python
# ============================================================
# CELLULE 7 - Entraînement sur Colab (Sauvegarde Google Drive)
# ============================================================
from transformers import TrainingArguments, Trainer, DataCollatorForLanguageModeling

OUTPUT_DIR = "/content/drive/MyDrive/biflow-bi-lora"

def tokenize_fn(examples):
    result = tokenizer(examples["text"], truncation=True, max_length=1500)
    result["labels"] = result["input_ids"].copy()
    return result

tokenized_train = dataset["train"].map(tokenize_fn, batched=True, remove_columns=["text"])
tokenized_eval  = dataset["test"].map(tokenize_fn, batched=True, remove_columns=["text"])

training_args = TrainingArguments(
    output_dir=OUTPUT_DIR,
    num_train_epochs=5,
    per_device_train_batch_size=1,
    gradient_accumulation_steps=8,       # Batch effectif = 8
    learning_rate=2e-4,
    warmup_steps=10,
    logging_steps=5,
    evaluation_strategy="epoch",
    save_strategy="epoch",
    save_total_limit=2,
    load_best_model_at_end=True,
    fp16=True,
    optim="adamw_torch",
    report_to="none"
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=tokenized_train,
    eval_dataset=tokenized_eval,
    data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)
)

print("Lancement de l'entraînement...")
trainer.train()

# Sauvegarde des adaptateurs LoRA finaux (~15 Mo)
model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)
print(f"\n✅ Adaptateurs LoRA sauvegardés avec succès dans : {OUTPUT_DIR}")
```
