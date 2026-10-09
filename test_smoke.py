"""
BIFlow Smoke Test
=================
Tests:
  1. Ollama LLMClient connectivity (Qwen 2.5:7b)
  2. DataEngineeringAgent.run_audit() on telco_churn.csv
"""
import sys
import os
import json

# Make sure project root is in path
sys.path.insert(0, os.path.dirname(__file__))

from agents.llm_client import LLMClient
from agents.data_engineering_agent import DataEngineeringAgent

DATASET_PATH = "data/raw/telco_churn.csv"


def test_llm_client():
    print("\n" + "="*60)
    print("[TEST 1] LLM Client (Ollama Qwen 2.5:7b)")
    print("="*60)
    client = LLMClient()
    print(f"  Provider : {client.provider}")
    print(f"  Model    : {client.model_name}")
    print(f"  Host     : {client.ollama_host}")

    result = client.generate_json(
        prompt='Return a JSON object with key "status" and value "ok".',
        system_prompt="You are a helpful assistant. Always respond with valid JSON only."
    )
    print(f"  Response : {result}")
    assert result.get("status") == "ok", f"Unexpected response: {result}"
    print("  LLM Client OK!")


def test_data_engineering_agent():
    print("\n" + "="*60)
    print("[TEST 2] DataEngineeringAgent.run_audit()")
    print("="*60)

    if not os.path.exists(DATASET_PATH):
        print(f"  Dataset not found at {DATASET_PATH} -- skipping audit test.")
        return

    agent = DataEngineeringAgent()
    result = agent.run_audit(DATASET_PATH)

    profile = result["profile"]
    health  = result["health"]
    strategy = result["cleaning_strategy"]

    print(f"  Rows         : {profile['rows']}")
    print(f"  Columns      : {profile['columns']}")
    print(f"  Health Score : {health['overall_health_score']}%")
    print(f"  Recommendation: {strategy.get('recommendation_summary', 'N/A')}")
    print(f"  Imputation Plan: {list(strategy.get('imputation_plan', {}).keys())}")
    print("  DataEngineeringAgent OK!")


if __name__ == "__main__":
    print("\nBIFlow Smoke Test Starting...")
    try:
        test_llm_client()
        test_data_engineering_agent()
        print("\n" + "="*60)
        print("ALL TESTS PASSED! BIFlow is ready to go!")
        print("="*60 + "\n")
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
