import os
import json
import logging
import time
import requests
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class LLMClient:
    """
    Unified LLM Client for BIFlow supporting Ollama (Local Qwen 2.5 / Llama 3.1)
    and cloud providers (Gemini) with automatic JSON extraction.
    """

    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "ollama").lower()
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.model_name = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")

    def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """
        Sends a prompt to the LLM and returns the parsed JSON response.
        """
        raw_response = self.generate_text(prompt, system_prompt)
        return self._extract_json(raw_response)

    def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Generates text output from the configured LLM provider.
        """
        if self.provider == "ollama":
            return self._call_ollama(prompt, system_prompt)
        elif self.provider == "gemini":
            return self._call_gemini(prompt, system_prompt)
        else:
            return self._call_ollama(prompt, system_prompt)

    def _call_ollama(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Calls local Ollama API server (e.g. Qwen 2.5 7B / 3B).
        """
        url = f"{self.ollama_host.rstrip('/')}/api/generate"
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }
        if system_prompt:
            payload["system"] = system_prompt

        try:
            response = requests.post(url, json=payload, timeout=180)
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")
        except Exception as e:
            logger.warning(f"Ollama call failed ({e}). Returning fallback JSON.")
            return "{}"

    def _call_gemini(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Calls Google Gemini API using the google-genai SDK with retry/backoff.
        """
        if not self.gemini_api_key:
            logger.error("GEMINI_API_KEY not set in .env file")
            return "{}"

        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            logger.error(f"Failed to import google.genai: {e}. Install with: pip install google-genai")
            return "{}"

        try:
            client = genai.Client(api_key=self.gemini_api_key)
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.3,
                max_output_tokens=8192,
            ) if system_prompt else types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=8192,
            )

            max_retries = 2  # Reduced from 3 for faster failure
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info(f"Calling Gemini API (attempt {attempt}/{max_retries})...")
                    # Use gemini-flash-latest which is an alias to the latest stable flash model
                    response = client.models.generate_content(
                        model="gemini-flash-latest",
                        contents=prompt,
                        config=config
                    )
                    logger.info(f"Gemini API call successful")
                    return response.text
                except Exception as e:
                    logger.error(f"Gemini API call failed: {e}")
                    if attempt < max_retries:
                        wait = 2
                        logger.warning(f"Retrying in {wait}s...")
                        time.sleep(wait)
                    else:
                        return "{}"
            return "{}"
        except Exception as e:
            logger.error(f"Unexpected error in _call_gemini: {e}")
            return "{}"

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """
        Extracts valid JSON object from LLM response string.
        """
        if not text or not text.strip():
            return {}

        text_clean = text.strip()
        if text_clean.startswith("```json"):
            text_clean = text_clean[7:]
        if text_clean.startswith("```"):
            text_clean = text_clean[3:]
        if text_clean.endswith("```"):
            text_clean = text_clean[:-3]

        text_clean = text_clean.strip()

        try:
            return json.loads(text_clean)
        except json.JSONDecodeError:
            start = text_clean.find("{")
            end = text_clean.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text_clean[start:end+1])
                except json.JSONDecodeError:
                    pass
            logger.error(f"Failed to parse JSON from response: {text[:100]}...")
            return {}
