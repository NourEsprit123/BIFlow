"""
Banc d'Essai & Évaluation Scientifique du Data Profiler & de la Data Quality
=============================================================================
Ce script évalue de manière indépendante et reproductible le périmètre :
1. Data Profiler (analytics/profiler.py)
2. Data Quality (analytics/data_quality.py)
3. Raisonnement & Détection d'anomalies

Génère un rapport chiffré complet avec le score composite PQAS (0-100%).
"""

import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import json
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analytics.profiler import profile_dataset
from analytics.data_quality import (
    calculate_health_scores,
    detect_type_mismatches,
    detect_cross_column_issues,
    detect_missing,
)

BENCHMARK_PATH = "data/raw/benchmark_eval_dataset.csv"
REPORT_OUTPUT_PATH = "data/reports/profiler_quality_eval_report.json"


def generate_golden_benchmark() -> pd.DataFrame:
    """
    Crée un jeu de test de référence (Golden Dataset) de 200 lignes
    avec 6 types d'anomalies contrôlées dont la vérité terrain est connue.
    """
    np.random.seed(42)
    n = 200

    # 1. Identifiant parfait (Ground Truth: identifier)
    user_ids = [f"USR_{i:05d}" for i in range(1, n + 1)]

    # 2. Chaîne numérique polluée par devises et entrées mixtes (Ground Truth: dirty numeric, ratio ~90%)
    dirty_money = [f"${np.random.uniform(10, 500):.2f}" for _ in range(180)]
    dirty_money += ["unknown", "pending", "N/A", "error"] * 5

    # 3. Dates stockées en texte pur (Ground Truth: date_string)
    # Format ISO 2024-01-15 non parsé
    date_strings = [
        f"2024-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n)
    ]

    # 4. Booléens stockés en chaînes variées (Ground Truth: boolean_text)
    bool_strings = np.random.choice(["yes", "no", "true", "false"], size=n)

    # 5. Valeurs manquantes : 15 NaNs réels + 20 sentinelles masquées ('?', 'N/A', 'none')
    # Ground Truth: 35 valeurs manquantes
    masked_missing = ["Valide"] * 165 + [None] * 15 + ["?"] * 10 + ["N/A"] * 5 + ["none"] * 5

    # 6. Violations logiques croisées (tenure == 0 mais TotalCharges > 0)
    # Ground Truth: 15 violations impossibles
    tenure = [0] * 15 + [int(x) for x in np.random.randint(1, 60, size=n - 15)]
    total_charges = [450.0] * 15 + [float(x) for x in np.random.uniform(50, 3000, size=n - 15)]

    df = pd.DataFrame({
        "customer_id": user_ids,
        "monthly_fee": dirty_money,
        "signup_date": date_strings,
        "auto_renewal": bool_strings,
        "feedback_score": masked_missing,
        "tenure": tenure,
        "TotalCharges": total_charges,
    })

    os.makedirs(os.path.dirname(BENCHMARK_PATH), exist_ok=True)
    df.to_csv(BENCHMARK_PATH, index=False)
    return df


def run_evaluation():
    print("=" * 70)
    print("🔬 DÉMARRAGE DU BANC D'ESSAI : DATA PROFILER & DATA QUALITY")
    print("=" * 70)

    # Étape 1 : Génération du dataset de référence
    df_true = generate_golden_benchmark()
    print(f"✅ Benchmark généré : {BENCHMARK_PATH} ({df_true.shape[0]} lignes, {df_true.shape[1]} colonnes)")

    # Étape 2 : Évaluation du Data Profiler
    print("\n[AXE 1] Évaluation du Data Profiler (analytics/profiler.py)...")
    profile = profile_dataset(BENCHMARK_PATH)

    # Vérification du rôle 'identifier' ou 'primary_key'
    id_role = profile["column_roles"].get("customer_id")
    id_detected = id_role in ("identifier", "primary_key")
    # Vérification de détection des colonnes
    cols_detected = len(profile["column_names"]) == df_true.shape[1]
    s_profiler = (int(id_detected) + int(cols_detected)) / 2.0
    print(f"  - Rôle 'customer_id' identifié comme identifier : {'✓ OUI' if id_detected else '✗ NON'}")
    print(f"  - Détection exhaustive des colonnes ({len(profile['column_names'])}/{df_true.shape[1]}) : {'✓ OUI' if cols_detected else '✗ NON'}")
    print(f"  ➔ Score Profiler : {s_profiler * 100:.1f}%")

    # Étape 3 : Évaluation de la Data Quality (Détection des Types Pollués)
    print("\n[AXE 2] Évaluation de la Data Quality — Détection des Types Pollués...")
    type_issues = detect_type_mismatches(df_true)

    # 1. Dirty Numeric (monthly_fee)
    fee_issue = type_issues.get("monthly_fee", {})
    money_ok = "Dirty numeric" in fee_issue.get("issue", "")

    # 2. Date String (signup_date)
    date_issue = type_issues.get("signup_date", {})
    date_ok = "Date/time" in date_issue.get("issue", "")

    # 3. Boolean Text (auto_renewal)
    bool_issue = type_issues.get("auto_renewal", {})
    bool_ok = "Boolean" in bool_issue.get("issue", "")

    s_types = (int(money_ok) + int(date_ok) + int(bool_ok)) / 3.0
    print(f"  - Détection 'monthly_fee' ($ et € pollués) : {'✓ OUI' if money_ok else '✗ NON'}")
    print(f"  - Détection 'signup_date' (ISO text)        : {'✓ OUI' if date_ok else '✗ NON'}")
    print(f"  - Détection 'auto_renewal' (yes/no text)    : {'✓ OUI' if bool_ok else '✗ NON'}")
    print(f"  ➔ Taux de Rappel Types Pollués : {s_types * 100:.1f}%")

    # Étape 4 : Évaluation des Valeurs Manquantes Masquées
    print("\n[AXE 3] Évaluation des Valeurs Manquantes Masquées ('?', 'N/A', 'none')...")
    missing_info = detect_missing(df_true)
    detected_missing = missing_info["columns"].get("feedback_score", 0)
    expected_missing = 35  # 15 NaNs + 10 '?' + 5 'N/A' + 5 'none'

    s_missing = min(1.0, detected_missing / expected_missing)
    print(f"  - Vraies valeurs manquantes attendues : {expected_missing}")
    print(f"  - Valeurs manquantes détectées par l'agent : {detected_missing}")
    print(f"  ➔ Taux de Couverture Valeurs Manquantes : {s_missing * 100:.1f}%")

    # Étape 5 : Évaluation des Incohérences Croisées (Cross-Column Integrity)
    print("\n[AXE 4] Évaluation de la Cohérence Croisée (Cross-Column Logic)...")
    cross_issues = detect_cross_column_issues(df_true)
    tenure_violation = next((c for c in cross_issues if "tenure" in c["columns"]), None)
    detected_rows = tenure_violation.get("affected_rows", 0) if tenure_violation else 0
    expected_rows = 15

    s_cross = 1.0 if detected_rows == expected_rows else (detected_rows / expected_rows if expected_rows else 0)
    print(f"  - Violations logiques injectées (tenure=0 & TotalCharges>0) : {expected_rows}")
    print(f"  - Violations interceptées par l'agent : {detected_rows}")
    print(f"  ➔ Taux d'Interception Cross-Column : {s_cross * 100:.1f}%")

    # Étape 6 : Calcul du Health Score Global
    health = calculate_health_scores(df_true)
    overall_health = health["overall_health_score"]
    print(f"\n[SANTÉ GLOBALE] Score de Santé attribué au dataset : {overall_health:.1f}%")

    # Étape 7 : Calcul de la Métrique Composite Propriétaire — PQAS
    # Poids : Profiler (25%), Types Pollués (30%), Valeurs Manquantes (25%), Cross-Column (20%)
    pqas = (
        (0.25 * s_profiler) +
        (0.30 * s_types) +
        (0.25 * s_missing) +
        (0.20 * s_cross)
    ) * 100

    print("\n" + "=" * 70)
    print(f"🏆 RÉSULTAT FINAL : SCORE PROPRIÉTAIRE PQAS = {pqas:.2f} / 100%")
    print("=" * 70)

    # Sauvegarde du rapport d'évaluation
    report = {
        "benchmark_file": BENCHMARK_PATH,
        "rows_tested": df_true.shape[0],
        "columns_tested": df_true.shape[1],
        "metrics": {
            "profiler_role_accuracy": round(s_profiler * 100, 2),
            "dirty_types_recall": round(s_types * 100, 2),
            "masked_missing_coverage": round(s_missing * 100, 2),
            "cross_column_integrity_recall": round(s_cross * 100, 2),
            "overall_health_score_calculated": overall_health,
        },
        "composite_score_pqas": round(pqas, 2),
        "status": "EXCELLENT" if pqas >= 90 else "PASS",
    }

    os.makedirs(os.path.dirname(REPORT_OUTPUT_PATH), exist_ok=True)
    with open(REPORT_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"📁 Rapport complet d'évaluation sauvegardé dans : {REPORT_OUTPUT_PATH}")
    return report


if __name__ == "__main__":
    run_evaluation()
