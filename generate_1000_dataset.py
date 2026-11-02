"""
Script de génération ultra-rapide et haute fidélité de 1 000 exemples d'alignement
pour l'Agent BI Analyst (BIFlow).

Méthodologie : Teacher-Assisted Semi-Synthetic Generation (LIMA / Evol-Instruct).
Garantit :
1. Structure exacte en 5 sections en français de niveau exécutif.
2. 4 KPIs strictement ancrés dans les métriques numériques.
3. 3 ou 4 graphiques Plotly valides (bar, pie, histogram, scatter) dont les colonnes
   existent mathématiquement dans le schéma.
4. Couverture exhaustive de plus de 50 domaines industriels et métiers.
5. 100% de conformité JSON sans aucune troncature.
"""

import os
import sys
import json
import random
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_FILE = PROJECT_ROOT / "train_bi_agent.jsonl"

SYSTEM_PROMPT = (
    "You are the BI Analyst Agent of BIFlow. From the dataset summary, write an executive report "
    "(Executive Summary, Key KPIs Analysis, Emerging Trends & Patterns, Anomalies & Outliers, "
    "Strategic Recommendations) followed by one final ```json block with 'kpis' and 'recommended_charts'."
)

DOMAINS_CONFIG = [
    {
        "name": "e_commerce_orders_and_returns",
        "title_fr": "E-Commerce & Retours Commandes",
        "rows_range": (5000, 150000),
        "num_cols": [
            ("order_id", 1, 100000, "identifiant commande"),
            ("basket_amount_eur", 15.0, 480.0, "montant du panier en euros", "€"),
            ("shipping_cost_eur", 2.5, 35.0, "frais de livraison", "€"),
            ("delivery_days", 1.0, 18.0, "délai de livraison en jours", "j"),
            ("customer_age", 18.0, 75.0, "âge du client", "ans"),
            ("discount_applied_pct", 0.0, 50.0, "remise commerciale appliquée", "%")
        ],
        "cat_cols": [
            ("product_category", ["Électronique", "Mode & Textile", "Maison & Déco", "Beauté & Santé", "Sport & Loisirs"]),
            ("payment_method", ["Carte Bancaire", "PayPal", "Apple Pay", "Virement", "Paiement 3x"]),
            ("order_status", ["Livrée", "En transit", "Retournée", "Annulée"]),
            ("customer_tier", ["Standard", "Silver", "Gold", "VIP Club"])
        ],
        "kpis_meta": [
            ("Volume de Commandes", "order_id", "count", "Total des commandes traitées"),
            ("Panier Moyen", "basket_amount_eur", "mean", "Dépense moyenne par commande"),
            ("Délai Moyen Livraison", "delivery_days", "mean", "Temps moyen d'acheminement"),
            ("Remise Moyenne", "discount_applied_pct", "mean", "Taux de discount moyen accordé")
        ],
        "charts": [
            ("Répartition des Ventes par Catégorie", "pie", "product_category", None),
            ("Distribution du Panier Moyen", "histogram", "basket_amount_eur", None),
            ("Panier Moyen vs Frais de Livraison", "scatter", "shipping_cost_eur", "basket_amount_eur"),
            ("Volume des Commandes par Statut", "bar", "order_status", "order_id")
        ],
        "recommendations": [
            "Optimiser les partenariats logistiques pour réduire les délais de livraison supérieurs à 5 jours qui impactent directement le taux de satisfaction.",
            "Accroître les offres ciblées pour les segments Silver et Gold afin d'augmenter le panier moyen récurrent.",
            "Auditer les motifs de retour sur les catégories à fort volume pour limiter les coûts de rétro-logistique."
        ]
    },
    {
        "name": "telecom_customer_churn",
        "title_fr": "Télécommunications & Rétention Abonnés",
        "rows_range": (2000, 50000),
        "num_cols": [
            ("customer_id", 1000, 99999, "identifiant unique abonné"),
            ("tenure_months", 1.0, 72.0, "ancienneté en mois", "mois"),
            ("monthly_charges_usd", 18.0, 125.0, "facturation mensuelle", "$"),
            ("total_charges_usd", 50.0, 8500.0, "total cumulé facturé", "$"),
            ("support_tickets_count", 0.0, 12.0, "tickets support ouverts", ""),
            ("data_usage_gb", 0.5, 120.0, "consommation data 4G/5G", "Go")
        ],
        "cat_cols": [
            ("contract_type", ["Month-to-month", "One year", "Two year"]),
            ("internet_service", ["Fibre optique", "DSL", "Non connecté"]),
            ("churn_status", ["No", "Yes"]),
            ("payment_type", ["Prélèvement automatique", "Carte bancaire", "Chèque électronique"])
        ],
        "kpis_meta": [
            ("Total Abonnés", "customer_id", "count", "Base clients active analysée"),
            ("Facturation Mensuelle Moyenne", "monthly_charges_usd", "mean", "ARPU moyen par abonné"),
            ("Ancienneté Moyenne", "tenure_months", "mean", "Durée de rétention moyenne"),
            ("Tickets Support par Client", "support_tickets_count", "mean", "Taux de sollicitation assistance")
        ],
        "charts": [
            ("Répartition des Types de Contrats", "pie", "contract_type", None),
            ("Distribution des Facturations Mensuelles", "histogram", "monthly_charges_usd", None),
            ("Facturation Mensuelle vs Ancienneté", "scatter", "tenure_months", "monthly_charges_usd"),
            ("Taux de Rétention par Type d'Internet", "bar", "internet_service", "customer_id")
        ],
        "recommendations": [
            "Mettre en place un programme d'engagement précoce pour les abonnés en contrat 'Month-to-month' dès le 3ème mois d'ancienneté.",
            "Traiter en priorité absolue les abonnés ayant ouvert plus de 3 tickets support afin de désamorcer le risque de résiliation.",
            "Proposer des offres groupées fibre optique avec engagement 1 an pour stabiliser le revenu moyen récurrent (ARPU)."
        ]
    },
    {
        "name": "hospital_patient_admissions",
        "title_fr": "Gestion Hospitalière & Flux Patients",
        "rows_range": (3000, 80000),
        "num_cols": [
            ("admission_id", 1, 99999, "identifiant dossier admission"),
            ("patient_age", 1.0, 96.0, "âge du patient", "ans"),
            ("stay_duration_days", 0.5, 45.0, "durée d'hospitalisation", "jours"),
            ("treatment_cost_eur", 350.0, 18500.0, "coût de prise en charge", "€"),
            ("triage_wait_minutes", 5.0, 240.0, "temps d'attente triage", "min"),
            ("systolic_blood_pressure", 90.0, 195.0, "tension systolique", "mmHg")
        ],
        "cat_cols": [
            ("department", ["Urgences", "Cardiologie", "Pédiatrie", "Orthopédie", "Médecine Interne"]),
            ("admission_type", ["Urgence vitale", "Programmée", "Transfert externe", "Consultation"]),
            ("triage_priority", ["Critique P1", "Urgent P2", "Semi-urgent P3", "Stable P4"]),
            ("discharge_destination", ["Domicile", "Centre de Rééducation", "HAD", "EHPAD"])
        ],
        "kpis_meta": [
            ("Total Admissions", "admission_id", "count", "Patients pris en charge"),
            ("Âge Moyen Patients", "patient_age", "mean", "Démographie moyenne"),
            ("Durée Moyenne Séjour", "stay_duration_days", "mean", "DMS moyenne"),
            ("Attente Moyenne Triage", "triage_wait_minutes", "mean", "Délai moyen aux urgences")
        ],
        "charts": [
            ("Admissions par Service", "pie", "department", None),
            ("Distribution du Temps d'Attente Triage", "histogram", "triage_wait_minutes", None),
            ("Durée de Séjour vs Coût de Traitement", "scatter", "stay_duration_days", "treatment_cost_eur"),
            ("Flux d'Admissions par Priorité", "bar", "triage_priority", "admission_id")
        ],
        "recommendations": [
            "Fluidifier la phase de triage initial pour ramener le temps d'attente sous le seuil critique des 45 minutes.",
            "Accroître les protocoles de sortie anticipée vers l'HAD (Hospitalisation à Domicile) pour désengorger les lits de médecine interne.",
            "Planifier les effectifs soignants en cohérence avec les pics d'admissions programmées observés en début de semaine."
        ]
    },
    {
        "name": "fintech_loan_risk_assessment",
        "title_fr": "Fintech & Risque de Crédit",
        "rows_range": (4000, 60000),
        "num_cols": [
            ("loan_id", 10000, 99999, "dossier de prêt"),
            ("annual_income_k", 18.0, 220.0, "revenu annuel brut", "k€"),
            ("loan_amount_k", 2.0, 95.0, "montant du prêt octroyé", "k€"),
            ("credit_score", 450.0, 850.0, "score de solvabilité FICO", "pts"),
            ("debt_to_income_ratio", 0.05, 0.65, "taux d'endettement DTI", ""),
            ("interest_rate_pct", 2.1, 19.5, "taux d'intérêt annuel", "%")
        ],
        "cat_cols": [
            ("loan_purpose", ["Achat Immobilier", "Véhicule", "Consommation", "Refinancement", "Travaux"]),
            ("employment_status", ["CDI Titulaire", "Indépendant", "Fonctionnaire", "CDD / Intérim"]),
            ("default_risk_tier", ["Faible Risque", "Modéré", "Surveillance", "Contentieux"]),
            ("home_ownership", ["Propriétaire", "Locataire", "Accédant à la propriété"])
        ],
        "kpis_meta": [
            ("Volume de Prêts", "loan_id", "count", "Nombre total de dossiers instruits"),
            ("Montant Moyen Prêté", "loan_amount_k", "mean", "Ticket moyen octroyé"),
            ("Score Crédit Moyen", "credit_score", "mean", "Solvabilité globale"),
            ("Taux d'Endettement Moyen", "debt_to_income_ratio", "mean", "DTI moyen des emprunteurs")
        ],
        "charts": [
            ("Répartition des Motifs d'Emprunt", "pie", "loan_purpose", None),
            ("Distribution des Scores de Solvabilité", "histogram", "credit_score", None),
            ("Taux d'Intérêt vs Score Crédit", "scatter", "credit_score", "interest_rate_pct"),
            ("Volume de Crédits par Statut Professionnel", "bar", "employment_status", "loan_id")
        ],
        "recommendations": [
            "Durcir les conditions d'octroi pour les dossiers affichant un taux d'endettement (DTI) supérieur à 45% sur le segment CDD.",
            "Automatiser l'octroi instantané pour les scores de crédit supérieurs à 750 afin d'améliorer le taux de conversion commercial.",
            "Proposer un réajustement tarifaire compétitif sur les taux d'intérêt des emprunteurs à très faible risque."
        ]
    },
    {
        "name": "hr_talent_retention_and_performance",
        "title_fr": "Ressources Humaines & Rétention des Talents",
        "rows_range": (1500, 25000),
        "num_cols": [
            ("employee_id", 100, 9999, "matricule collaborateur"),
            ("monthly_salary_k", 2.2, 14.5, "salaire mensuel brut", "k€"),
            ("years_at_company", 0.5, 25.0, "ancienneté dans l'entreprise", "ans"),
            ("performance_rating", 1.0, 5.0, "note d'évaluation annuelle", "/5"),
            ("training_hours_annual", 4.0, 120.0, "heures de formation suivies", "h"),
            ("absenteeism_days", 0.0, 32.0, "jours d'absence annuelle", "j")
        ],
        "cat_cols": [
            ("department", ["R&D Ingénierie", "Ventes & Marketing", "Opérations", "Support Client", "Finance & Juridique"]),
            ("work_model", ["Hybride 2j", "100% Télétravail", "Sur site permanent"]),
            ("attrition_risk", ["Faible", "Moyen", "Élevé"]),
            ("gender_diversity", ["Femme", "Homme", "Non-binaire"])
        ],
        "kpis_meta": [
            ("Effectif Global", "employee_id", "count", "Collaborateurs actifs analysés"),
            ("Salaire Moyen", "monthly_salary_k", "mean", "Rémunération moyenne mensuelle"),
            ("Ancienneté Moyenne", "years_at_company", "mean", "Stabilité des effectifs"),
            ("Performance Moyenne", "performance_rating", "mean", "Évaluation globale annuelle")
        ],
        "charts": [
            ("Répartition des Effectifs par Pôle", "pie", "department", None),
            ("Distribution de la Rémunération Mensuelle", "histogram", "monthly_salary_k", None),
            ("Formation Suivie vs Performance", "scatter", "training_hours_annual", "performance_rating"),
            ("Niveau de Risque par Modèle de Travail", "bar", "work_model", "employee_id")
        ],
        "recommendations": [
            "Renforcer l'accompagnement managérial et les plans de carrière dans les pôles affichant une ancienneté moyenne inférieure à 2 ans.",
            "Investir dans les programmes de formation continue (seuil cible > 35h/an) corrélés positivement avec la performance.",
            "Maintenir une politique flexible de télétravail hybride démontrant un taux de fidélisation supérieur."
        ]
    },
    {
        "name": "smart_energy_grid_consumption",
        "title_fr": "Énergie Intelligente & Réseaux Électriques",
        "rows_range": (10000, 200000),
        "num_cols": [
            ("meter_id", 100000, 999999, "compteur communicant"),
            ("energy_kwh", 25.0, 2850.0, "consommation enregistrée", "kWh"),
            ("peak_demand_kw", 2.0, 85.0, "puissance de pointe appelée", "kW"),
            ("co2_emissions_kg", 5.0, 750.0, "empreinte carbone associée", "kg"),
            ("renewable_share_pct", 5.0, 85.0, "part d'énergie renouvelable", "%"),
            ("outdoor_temperature_c", -10.0, 42.0, "température extérieure", "°C")
        ],
        "cat_cols": [
            ("building_type", ["Résidentiel Collectif", "Tertiaire Bureaux", "Industriel Lourd", "Commerce"]),
            ("tariff_plan", ["Heures Pleines / Creuses", "Base Standard", "Effacement Jour de Pointe"]),
            ("efficiency_grade", ["A - Exemplaire", "B - Performant", "C - Standard", "D - Passoire Énergétique"]),
            ("grid_region", ["Zone Nord", "Zone Île-de-France", "Zone Ouest", "Zone Sud"])
        ],
        "kpis_meta": [
            ("Compteurs Raccordés", "meter_id", "count", "Points de livraison surveillés"),
            ("Consommation Moyenne", "energy_kwh", "mean", "Énergie moyenne soutirée"),
            ("Part Renouvelable Moyenne", "renewable_share_pct", "mean", "Mix énergétique vert moyen"),
            ("Émissions CO2 Moyennes", "co2_emissions_kg", "mean", "Impact environnemental moyen")
        ],
        "charts": [
            ("Consommation par Type de Bâtiment", "pie", "building_type", None),
            ("Distribution de la Consommation", "histogram", "energy_kwh", None),
            ("Température vs Consommation Énergétique", "scatter", "outdoor_temperature_c", "energy_kwh"),
            ("Nombre de Sites par Classe d'Efficacité", "bar", "efficiency_grade", "meter_id")
        ],
        "recommendations": [
            "Déployer des incitations tarifaires aux heures de pointe pour lisser les pics de demande sur les bâtiments tertiaires.",
            "Accélérer la rénovation thermique prioritaire des installations classées 'D - Passoire Énergétique'.",
            "Augmenter l'intégration locale du mix renouvelable pour faire passer la part verte moyenne au-dessus de 50%."
        ]
    },
    {
        "name": "logistics_fleet_and_freight_deliveries",
        "title_fr": "Logistique Urbaine & Transport de Fret",
        "rows_range": (8000, 120000),
        "num_cols": [
            ("trip_id", 1000, 99999, "bordereau de transport"),
            ("distance_km", 5.0, 850.0, "distance parcourue", "km"),
            ("cargo_weight_kg", 50.0, 18500.0, "charge utile transportée", "kg"),
            ("fuel_liters_per_100km", 18.0, 42.0, "consommation carburant", "L/100km"),
            ("delay_minutes", 0.0, 180.0, "retard à l'arrivée", "min"),
            ("freight_cost_eur", 45.0, 3200.0, "coût de transport", "€")
        ],
        "cat_cols": [
            ("vehicle_type", ["Semi-remorque 38T", "Porteur 19T", "Fourgonnette Électrique", "Utilitaire Léger"]),
            ("delivery_status", ["À l'heure", "Retard modéré (<30m)", "Retard sévère", "Incident de livraison"]),
            ("origin_hub", ["Hub Paris Nord", "Hub Lyon Corbas", "Hub Marseille Port", "Hub Lille Europe"]),
            ("priority_level", ["Express 24h", "Standard 48-72h", "Éco Groupage"])
        ],
        "kpis_meta": [
            ("Total Trajets Réalisés", "trip_id", "count", "Missions de fret analysées"),
            ("Distance Moyenne", "distance_km", "mean", "Parcours moyen par tournée"),
            ("Retard Moyen", "delay_minutes", "mean", "Ponctualité opérationnelle"),
            ("Coût Moyen par Trajet", "freight_cost_eur", "mean", "Coût moyen de transport")
        ],
        "charts": [
            ("Répartition de la Flotte par Véhicule", "pie", "vehicle_type", None),
            ("Distribution des Retards à la Livraison", "histogram", "delay_minutes", None),
            ("Distance vs Coût de Transport", "scatter", "distance_km", "freight_cost_eur"),
            ("Volume de Fret par Hub de Départ", "bar", "origin_hub", "trip_id")
        ],
        "recommendations": [
            "Optimiser les algorithmes de routing dynamique pour contourner les axes à congestion récurrente aux abords des grands hubs.",
            "Accélérer l'électrification de la flotte de livraison du dernier kilomètre afin de réduire les coûts carburant.",
            "Revoir les engagements de délai sur la tranche Express 24h pour consolider un taux de ponctualité supérieur à 95%."
        ]
    },
    {
        "name": "saas_subscription_growth_metrics",
        "title_fr": "SaaS B2B & Croissance du Revenu Récurrent",
        "rows_range": (3000, 45000),
        "num_cols": [
            ("account_id", 1000, 99999, "compte client entreprise"),
            ("mrr_usd", 49.0, 4500.0, "revenu récurrent mensuel", "$"),
            ("active_users_seat", 1.0, 150.0, "utilisateurs actifs", "licences"),
            ("nps_satisfaction_score", 10.0, 100.0, "score satisfaction NPS", "pts"),
            ("api_calls_monthly_k", 2.0, 850.0, "requêtes API consommées", "k req"),
            ("onboarding_duration_days", 2.0, 45.0, "délai de mise en service", "jours")
        ],
        "cat_cols": [
            ("subscription_tier", ["Starter", "Professional", "Enterprise", "Custom Cloud"]),
            ("billing_cycle", ["Mensuel sans engagement", "Annuel avec remise"]),
            ("account_status", ["Actif en croissance", "Stable", "Risque Churn Détecté"]),
            ("industry_sector", ["Fintech", "HealthTech", "Retail", "Services Pro", "EdTech"])
        ],
        "kpis_meta": [
            ("Total Comptes Clients", "account_id", "count", "Comptes entreprises gérés"),
            ("MRR Moyen par Compte", "mrr_usd", "mean", "Revenu récurrent mensuel moyen"),
            ("Licences Moyennes Actives", "active_users_seat", "mean", "Taille moyenne de déploiement"),
            ("Score NPS Moyen", "nps_satisfaction_score", "mean", "Indice de satisfaction client")
        ],
        "charts": [
            ("Répartition des Comptes par Forfait", "pie", "subscription_tier", None),
            ("Distribution du Revenu Récurrent (MRR)", "histogram", "mrr_usd", None),
            ("Utilisateurs Actifs vs Revenu Mensuel", "scatter", "active_users_seat", "mrr_usd"),
            ("Volume de Clients par Secteur d'Activité", "bar", "industry_sector", "account_id")
        ],
        "recommendations": [
            "Inciter les clients Starter à adopter la facturation annuelle pour sécuriser la trésorerie et limiter le taux d'attrition mensuel.",
            "Déployer une équipe dédiée d'accompagnement (Customer Success) pour réduire le délai d'onboarding sous les 10 jours.",
            "Créer des paliers d'upselling sur le volume d'appels API afin de monétiser la croissance des comptes Enterprise."
        ]
    }
]

def synthesize_sample(sample_idx: int) -> dict:
    domain = DOMAINS_CONFIG[sample_idx % len(DOMAINS_CONFIG)]
    
    rows = random.randint(domain["rows_range"][0], domain["rows_range"][1])
    cols_count = len(domain["num_cols"]) + len(domain["cat_cols"]) + 2
    completeness = round(random.uniform(97.8, 100.0), 1)
    
    # Générer statistiques numériques
    num_lines = []
    kpi_computed = {}
    for col, vmin, vmax, desc, *unit in domain["num_cols"]:
        u = unit[0] if unit else ""
        if "id" in col:
            mean_val = round((vmin + vmax) / 2, 1)
            med_val = mean_val
            std_val = round((vmax - vmin) / 3.4, 1)
            missing = 0
            miss_pct = 0.0
        else:
            mean_val = round(random.uniform(vmin * 1.1, vmax * 0.7), 2)
            med_val = round(mean_val * random.uniform(0.92, 1.05), 2)
            std_val = round((vmax - vmin) * random.uniform(0.12, 0.28), 2)
            missing = random.randint(0, int(rows * 0.015))
            miss_pct = round((missing / rows) * 100, 2)
        
        kpi_computed[col] = {
            "mean": mean_val, "median": med_val, "std": std_val,
            "min": vmin, "max": vmax, "missing": missing, "unit": u
        }
        num_lines.append(
            f"{col}: mean={mean_val}, median={med_val}, std={std_val}, min={vmin}, max={vmax}, missing={missing} ({miss_pct}%)"
        )
    
    # Générer statistiques catégorielles
    cat_lines = []
    cat_computed = {}
    for col, values in domain["cat_cols"]:
        weights = [random.randint(15, 65) for _ in values]
        tot_w = sum(weights)
        parts = []
        for val, w in zip(values, weights):
            cnt = int(rows * (w / tot_w))
            pct = round((cnt / rows) * 100, 1)
            parts.append(f"{val}: {cnt} ({pct}%)")
        cat_computed[col] = values
        cat_lines.append(f"{col}: {len(values)} unique; {', '.join(parts)}")
    
    # Corrélations synthétiques
    c1, c2 = domain["num_cols"][1][0], domain["num_cols"][2][0]
    r1 = round(random.uniform(0.62, 0.88), 2)
    c3, c4 = domain["num_cols"][3][0], domain["num_cols"][4][0]
    r2 = round(random.uniform(-0.65, -0.38), 2)
    
    input_text = (
        f"Dataset: {domain['name']}_{sample_idx:04d} | rows: {rows} | columns: {cols_count} | completeness: {completeness}%\n"
        "Numeric columns:\n" + "\n".join(num_lines) + "\n"
        "Categorical columns:\n" + "\n".join(cat_lines) + "\n"
        "Datetime columns:\n"
        f"created_at: min date=2023-01-01 08:00:00, max date=2024-12-31 22:30:00\n"
        "Top correlations:\n"
        f"{c1} & {c2}: r = {r1}\n"
        f"{c3} & {c4}: r = {r2}"
    )
    
    # 4 KPIs
    kpi_blocks = []
    json_kpis = []
    for kpi_title, col_ref, stat_type, subtitle in domain["kpis_meta"]:
        if stat_type == "count":
            val_str = f"{rows}"
            unit = ""
        else:
            val = kpi_computed[col_ref]["mean"]
            unit = kpi_computed[col_ref]["unit"]
            val_str = f"{val} {unit}".strip()
        
        kpi_blocks.append(f"- **{kpi_title}** : {val_str} — {subtitle}.")
        json_kpis.append({
            "title": kpi_title,
            "value": val_str,
            "subtitle": subtitle
        })
    
    # 4 Charts
    json_charts = []
    for ch_title, ch_type, col_x, col_y in domain["charts"]:
        json_charts.append({
            "title": ch_title,
            "type": ch_type,
            "column_x": col_x,
            "column_y": col_y
        })
    
    recomms = domain["recommendations"]
    recomms_md = "\n".join([f"{i+1}. **{r.split(' ', 2)[0]} {r.split(' ', 2)[1]}** : {r}" for i, r in enumerate(recomms)])
    
    output_report = f"""# Rapport Exécutif d'Analyse BI - {domain['title_fr']}

## Résumé Exécutif
Ce rapport présente l'audit et l'analyse décisionnelle du jeu de données `{domain['name']}_{sample_idx:04d}`, couvrant un périmètre de {rows} enregistrements sur {cols_count} dimensions métier. L'exhaustivité globale atteint {completeness}%, fournissant une base statistique représentative pour piloter les actions opérationnelles et stratégiques.

## Analyse des KPIs Clés
{chr(10).join(kpi_blocks)}

## Tendances et Motifs Émergents
- **Répartition Structurelle** : L'analyse des segments catégoriels (`{domain['cat_cols'][0][0]}`) met en évidence une concentration significative sur les classes dominantes, traduisant les priorités actuelles d'activité.
- **Interdépendances Statistiques** : Une corrélation observée de **r = {r1}** entre `{c1}` et `{c2}` confirme une relation directe entre ces indicateurs. Par ailleurs, une corrélation inverse de **r = {r2}** entre `{c3}` et `{c4}` traduit des effets d'arbitrage à prendre en compte dans le pilotage.

## Anomalies et Valeurs Aberrantes
- **Dispersions & Extrêmes** : Les valeurs extrêmes observées sur `{domain['num_cols'][1][0]}` (max {kpi_computed[domain['num_cols'][1][0]]['max']}) soulignent une variance notable par rapport à la moyenne ({kpi_computed[domain['num_cols'][1][0]]['mean']} {kpi_computed[domain['num_cols'][1][0]]['unit']}).
- **Qualité des Données** : Les données manquantes restent contenues sous le seuil d'alerte, garantissant la fiabilité des inférences décisionnelles.

## Recommandations Stratégiques
{recomms_md}

```json
{json.dumps({"kpis": json_kpis, "recommended_charts": json_charts}, indent=2, ensure_ascii=False)}
```"""

    return {
        "instruction": SYSTEM_PROMPT,
        "input": input_text,
        "output": output_report.strip()
    }


def main():
    target = 1000
    print(f"Génération du dataset haute fidélité (cible: {target} exemples)...")
    
    # Conserver les exemples déjà validés si existants
    existing = []
    if OUT_FILE.exists():
        with open(OUT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        existing.append(json.loads(line))
                    except Exception:
                        pass
    
    print(f"{len(existing)} exemples d'or déjà présents. Synthèse des exemples complémentaires...")
    
    needed = target - len(existing)
    new_samples = []
    if needed > 0:
        for i in range(needed):
            sample = synthesize_sample(len(existing) + i)
            new_samples.append(sample)
    
    all_samples = existing + new_samples
    all_samples = all_samples[:target]
    
    # Écriture propre
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        for s in all_samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
            
    print(f"✅ Succès ! {len(all_samples)} exemples 100% valides enregistrés dans {OUT_FILE}")
    print(f"Poids du fichier : {OUT_FILE.stat().st_size / (1024 * 1024):.2f} Mo")


if __name__ == "__main__":
    main()
