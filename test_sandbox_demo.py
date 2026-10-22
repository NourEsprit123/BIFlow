"""
Démonstration du Sandbox - Comment le LLM crée et teste des fonctions custom.

Ce script montre:
1. Comment le LLM génère du code Python pour vérifier une colonne
2. Comment le sandbox exécute ce code de façon sécurisée
3. Comment les résultats sont intégrés dans le rapport
"""

import sys
import pandas as pd
from analytics.data_quality import run_sandboxed_check
from agents.llm_client import LLMClient


def demo_1_basic_sandbox():
    """Demo 1: Exécution basique du sandbox avec code LLM-généré."""
    print("\n" + "=" * 70)
    print("DEMO 1: Exécution Basique du Sandbox")
    print("=" * 70)
    
    # Données de test: TotalCharges avec valeurs problématiques
    test_data = pd.Series([
        '29.85', '1889.5', '108.15', ' ', '1840.75',  # Valeurs normales + 1 vide
        '151.65', '820.5', '3046.05', '-50.00',       # Valeurs normales + 1 négative
        '15000.00'                                     # 1 valeur trop élevée
    ])
    
    print(f"\n📊 Données de Test (TotalCharges):")
    print(f"   Total: {len(test_data)} valeurs")
    print(f"   Samples: {list(test_data[:5])}")
    print(f"   Issues: 1 vide, 1 négative, 1 >10000")
    
    # Code généré par le LLM (simulé)
    llm_generated_code = """
def custom_check(series):
    '''Verify TotalCharges values are in valid billing range [0, 10000].'''
    import pandas as pd
    
    # Convert to numeric (coerce errors to NaN)
    numeric_series = pd.to_numeric(series, errors='coerce')
    
    # Check range [0, 10000]
    valid_mask = (numeric_series >= 0) & (numeric_series <= 10000)
    valid_count = valid_mask.sum()
    total_count = len(numeric_series.dropna())
    
    # Calculate ratio
    valid_ratio = valid_count / total_count if total_count > 0 else 0
    
    return {
        "passed": valid_ratio > 0.95,
        "metric": round(valid_ratio, 4),
        "details": f"{valid_count}/{total_count} values in valid range [0, 10000]"
    }
"""
    
    print(f"\n🤖 Code Généré par le LLM:")
    print(f"   Fonction: custom_check(series)")
    print(f"   But: Vérifier que les valeurs sont dans [0, 10000]")
    print(f"   Threshold: 95% de valeurs valides")
    
    # Exécution dans le sandbox
    print(f"\n🔒 Exécution dans le Sandbox...")
    result = run_sandboxed_check(llm_generated_code, test_data, timeout_sec=8)
    
    # Résultats
    print(f"\n✅ Résultats:")
    print(f"   Passed: {result['passed']}")
    print(f"   Metric: {result['metric']} ({result['metric']*100:.1f}%)")
    print(f"   Details: {result['details']}")
    print(f"   Error: {result['error']}")
    
    # Interprétation
    print(f"\n💡 Interprétation:")
    if result['passed']:
        print(f"   ✅ Check PASSED - Plus de 95% des valeurs sont valides")
    else:
        print(f"   ❌ Check FAILED - Moins de 95% des valeurs sont valides")
        print(f"   → Il y a des valeurs hors de la plage [0, 10000]")
        print(f"   → Recommandation: Nettoyer ces valeurs ou les marquer comme outliers")


def demo_2_llm_code_generation():
    """Demo 2: Comment le LLM génère du code pour une colonne spécifique."""
    print("\n" + "=" * 70)
    print("DEMO 2: Génération de Code par le LLM")
    print("=" * 70)
    
    # Initialiser le client LLM
    llm_client = LLMClient()
    
    # Colonnes de test avec descriptions
    test_cases = [
        {
            "column": "Age",
            "dtype": "int64",
            "samples": [25, 34, 56, 23, 150, 89, 45],  # 150 est suspect
            "description": "Verify age values are in realistic range [0, 120]"
        },
        {
            "column": "Email",
            "dtype": "object",
            "samples": ["john@example.com", "invalid.email", "jane@test.org"],
            "description": "Verify email format matches standard pattern"
        },
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'─' * 70}")
        print(f"Test Case {i}: {test_case['column']}")
        print(f"{'─' * 70}")
        
        print(f"\n📋 Contexte:")
        print(f"   Column: {test_case['column']}")
        print(f"   dtype: {test_case['dtype']}")
        print(f"   Samples: {test_case['samples'][:3]}")
        print(f"   Check Description: {test_case['description']}")
        
        # Construire le prompt pour le LLM
        code_prompt = (
            f"Write a Python function to validate a pandas Series column named '{test_case['column']}'.\n"
            f"What to check: {test_case['description']}\n"
            f"Column dtype: {test_case['dtype']}\n"
            f"Sample values: {test_case['samples']}\n\n"
            f"Rules:\n"
            f"- Define ONLY: def custom_check(series: pd.Series) -> dict\n"
            f"- Return: {{\"passed\": bool, \"metric\": float|str, \"details\": str}}\n"
            f"- Use only: pd, np, re, built-in Python functions\n"
            f"- NO imports, NO file I/O, NO external calls\n"
            f"- Keep it under 20 lines\n\n"
            f"Return JSON: {{\"code\": \"<full python code here>\"}}"
        )
        
        print(f"\n🤖 Appel LLM...")
        print(f"   Provider: {llm_client.provider}")
        print(f"   Model: gemini-flash-latest" if llm_client.provider == "gemini" else f"ollama/{llm_client.model_name}")
        
        try:
            # Appeler le LLM pour générer le code
            code_result = llm_client.generate_json(code_prompt)
            
            if code_result and "code" in code_result:
                generated_code = code_result["code"]
                print(f"\n✅ Code Généré:")
                print(f"   Longueur: {len(generated_code)} caractères")
                print(f"   Lignes: {generated_code.count(chr(10)) + 1}")
                
                # Afficher le code (premiers 200 chars)
                preview = generated_code[:200] + "..." if len(generated_code) > 200 else generated_code
                print(f"\n   Preview:")
                for line in preview.split('\n')[:8]:
                    print(f"      {line}")
                
                # Tester le code
                print(f"\n🔒 Test dans le Sandbox...")
                test_series = pd.Series(test_case['samples'])
                result = run_sandboxed_check(generated_code, test_series, timeout_sec=8)
                
                print(f"\n📊 Résultat:")
                print(f"   Passed: {result['passed']}")
                print(f"   Metric: {result['metric']}")
                print(f"   Details: {result['details']}")
                
            else:
                print(f"\n❌ LLM n'a pas généré de code")
                print(f"   Response: {code_result}")
        
        except Exception as e:
            print(f"\n❌ Erreur: {e}")
            print(f"   Le LLM est peut-être indisponible. Voir demo_3 pour test sans LLM.")


def demo_3_sandbox_security():
    """Demo 3: Sécurité du sandbox contre code malveillant."""
    print("\n" + "=" * 70)
    print("DEMO 3: Sécurité du Sandbox")
    print("=" * 70)
    
    test_series = pd.Series([1, 2, 3, 4, 5])
    
    # Test cases de code malveillant
    malicious_tests = [
        {
            "name": "Tentative d'accès fichiers",
            "code": """
def custom_check(series):
    with open('/etc/passwd', 'r') as f:
        data = f.read()
    return {"passed": True, "metric": 1.0, "details": data}
"""
        },
        {
            "name": "Tentative d'import non autorisé",
            "code": """
def custom_check(series):
    import os
    os.system('echo "hacked"')
    return {"passed": True, "metric": 1.0, "details": "hacked"}
"""
        },
        {
            "name": "Tentative de boucle infinie",
            "code": """
def custom_check(series):
    while True:
        pass
    return {"passed": True, "metric": 1.0, "details": "never"}
"""
        },
        {
            "name": "Tentative d'exec arbitraire",
            "code": """
def custom_check(series):
    exec("import sys; sys.exit(1)")
    return {"passed": True, "metric": 1.0, "details": "fail"}
"""
        },
    ]
    
    for i, test in enumerate(malicious_tests, 1):
        print(f"\n{'─' * 70}")
        print(f"Test {i}: {test['name']}")
        print(f"{'─' * 70}")
        
        print(f"\n🦠 Code Malveillant:")
        for line in test['code'].strip().split('\n')[:5]:
            print(f"   {line}")
        
        # Exécuter dans le sandbox
        result = run_sandboxed_check(test['code'], test_series, timeout_sec=2)
        
        # Vérifier que c'est bloqué
        if result['error']:
            print(f"\n✅ BLOQUÉ PAR LE SANDBOX!")
            print(f"   Error: {result['error']}")
        else:
            print(f"\n❌ DANGER: Code malveillant a réussi!")
            print(f"   Result: {result}")


def demo_4_real_world_example():
    """Demo 4: Exemple réel complet avec TotalCharges."""
    print("\n" + "=" * 70)
    print("DEMO 4: Exemple Réel Complet (TotalCharges)")
    print("=" * 70)
    
    # Simuler les données telco_churn TotalCharges
    real_data = pd.Series([
        '29.85', '1889.5', '108.15', ' ', '1840.75',
        '151.65', '820.5', '3046.05', '1990.5', '5320.8',
        '346.45', '1424.05', '7686.25', ' ', '282.55',
        '820.5', '1295.8', '3320.75', '198.85', '5543.8'
    ])
    
    print(f"\n📊 Dataset: telco_churn.csv - TotalCharges")
    print(f"   Total values: {len(real_data)}")
    print(f"   dtype: object (should be float64)")
    print(f"   Issues: 2 empty strings (' ')")
    
    # Étape 1: Python détecte
    numeric_converted = pd.to_numeric(real_data, errors='coerce')
    valid_count = numeric_converted.notna().sum()
    invalid_count = numeric_converted.isna().sum()
    
    print(f"\n1️⃣ Python Détection:")
    print(f"   Valid numeric: {valid_count}/{len(real_data)} ({valid_count/len(real_data)*100:.1f}%)")
    print(f"   Invalid: {invalid_count}")
    print(f"   → Issue: numeric_stored_as_object")
    
    # Étape 2: LLM décide
    print(f"\n2️⃣ LLM Décision:")
    print(f"   severity: HIGH")
    print(f"   agent_reasoning: '{invalid_count} non-numeric values. 90% valid. Convert and impute.'")
    print(f"   needs_custom_check: true")
    print(f"   custom_check_description: 'Verify range [0, 10000] after conversion'")
    
    # Étape 3: LLM génère code
    llm_code = """
def custom_check(series):
    '''Verify TotalCharges in valid billing range.'''
    import pandas as pd
    
    numeric_series = pd.to_numeric(series, errors='coerce')
    valid_mask = (numeric_series >= 0) & (numeric_series <= 10000)
    valid_count = valid_mask.sum()
    total_count = len(numeric_series.dropna())
    
    valid_ratio = valid_count / total_count if total_count > 0 else 0
    
    return {
        "passed": valid_ratio > 0.95,
        "metric": round(valid_ratio, 4),
        "details": f"{valid_count}/{total_count} in range [0, 10000]"
    }
"""
    
    print(f"\n3️⃣ LLM Génération de Code:")
    print(f"   ✅ Code généré (12 lignes)")
    
    # Étape 4: Sandbox exécute
    print(f"\n4️⃣ Sandbox Exécution:")
    result = run_sandboxed_check(llm_code, real_data, timeout_sec=8)
    
    print(f"   Passed: {result['passed']}")
    print(f"   Metric: {result['metric']} ({result['metric']*100:.1f}%)")
    print(f"   Details: {result['details']}")
    
    # Étape 5: Ajouté au rapport
    print(f"\n5️⃣ Ajouté au ProfilingReport.json:")
    profiling_entry = {
        "TotalCharges": {
            "severity": "HIGH",
            "agent_reasoning": f"{invalid_count} non-numeric values. 90% valid. Convert and impute.",
            "sandbox_triggered": True,
            "sandbox_result": result,
            "custom_check_code": llm_code.strip()
        }
    }
    
    print(f"   ✅ Entry créée avec sandbox_result")
    print(f"   → Malek peut lire ce rapport et savoir:")
    print(f"      • La colonne a besoin de conversion (object → float64)")
    print(f"      • 2 valeurs sont invalides (empty strings)")
    print(f"      • Toutes les valeurs converties sont dans [0, 10000]")
    print(f"      • Stratégie: Convert + Impute with median")


def main():
    """Run all demos."""
    print("\n" + "=" * 70)
    print("🔬 SANDBOX DEMONSTRATION - BIFlow Data Engineering Agent")
    print("=" * 70)
    print("\nCe script démontre comment le LLM crée et teste des fonctions custom")
    print("pour vérifier les colonnes à haut risque de façon autonome.")
    
    try:
        # Demo 1: Basic sandbox execution
        demo_1_basic_sandbox()
        
        # Demo 2: LLM code generation (requires LLM API)
        user_input = input("\n\nRun Demo 2 (LLM Code Generation)? Requires Gemini API. (y/n): ")
        if user_input.lower() == 'y':
            demo_2_llm_code_generation()
        else:
            print("\n⏭️  Skipping Demo 2")
        
        # Demo 3: Sandbox security
        demo_3_sandbox_security()
        
        # Demo 4: Real-world example
        demo_4_real_world_example()
        
        print("\n" + "=" * 70)
        print("✅ All Demos Completed!")
        print("=" * 70)
        print("\nKey Takeaways:")
        print("1. ✅ LLM raisonne sur TOUTES les colonnes")
        print("2. ✅ Sandbox utilisé pour 5-10% des colonnes (haut risque)")
        print("3. ✅ LLM génère du code Python custom pour chaque cas")
        print("4. ✅ Sandbox exécute de façon sécurisée (no file access, no imports)")
        print("5. ✅ Résultats intégrés dans ProfilingReport.json pour Agent 2")
        
    except KeyboardInterrupt:
        print("\n\n⏸️  Demo interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
