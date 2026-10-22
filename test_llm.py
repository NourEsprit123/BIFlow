#!/usr/bin/env python3
"""Quick test to verify LLM client is working."""
import logging
from agents.llm_client import LLMClient

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

print("=" * 60)
print("Testing LLM Client...")
print("=" * 60)

client = LLMClient()
print(f"Provider: {client.provider}")
print(f"Model: {client.model_name if client.provider == 'ollama' else 'gemini-2.0-flash-exp'}")
print(f"API Key set: {bool(client.gemini_api_key)}")
print()

result = client.generate_json('Return a JSON object with one field: {"status": "working"}')
print("Result:", result)

if result and "status" in result:
    print("\n✅ LLM Client is WORKING!")
else:
    print("\n❌ LLM Client FAILED - check logs above")
