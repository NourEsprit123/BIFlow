import pandas as pd
import random
from datetime import datetime, timedelta

print("⚙️ Génération d'un dataset propre (Sortie simulée du Data Engineer)...")

categories = ['Électronique', 'Mobilier', 'Bureautique', 'Services']
produits = {
    'Électronique': ['PC Portable', 'Écran 27"', 'Clavier Mécanique', 'Souris Sans Fil'],
    'Mobilier': ['Chaise Ergonomique', 'Bureau Assis-Debout', 'Étagère'],
    'Bureautique': ['Papier A4', 'Stylo Pro', 'Organiseur'],
    'Services': ['Support Technique', 'Installation', 'Maintenance']
}

data = []
date_debut = datetime(2026, 1, 1)

for i in range(1, 101):
    cat = random.choice(categories)
    prod = random.choice(produits[cat])
    quantite = random.randint(1, 10)
    prix_unitaire = round(random.uniform(15.0, 800.0), 2)
    total_vente = round(quantite * prix_unitaire, 2)
    date_vente = (date_debut + timedelta(days=random.randint(0, 180))).strftime("%Y-%m-%d")

    data.append({
        "transaction_id": f"TXN-{1000 + i}",
        "date": date_vente,
        "categorie": cat,
        "produit": prod,
        "quantite": quantite,
        "prix_unitaire_tnd": prix_unitaire,
        "total_vente_tnd": total_vente
    })

df = pd.DataFrame(data)
chemin_sortie = "sandbox/data_input/donnees_propres_bi.csv"
df.to_csv(chemin_sortie, index=False, encoding='utf-8')

print(f"✅ Dataset propre généré avec succès dans : '{chemin_sortie}' ({len(df)} lignes) !")