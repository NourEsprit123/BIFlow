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

    def __init__(self, provider: Optional[str] = None, model_name: Optional[str] = None):
        self.provider = (provider or os.getenv("LLM_PROVIDER", "ollama")).lower()
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        if "localhost" in self.ollama_host:
            self.ollama_host = self.ollama_host.replace("localhost", "127.0.0.1")
        self.model_name = model_name or os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")

    def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """
        Sends a prompt to the LLM and returns the parsed JSON response.
        """
        raw_response = self.generate_text(prompt, system_prompt)
        return self._extract_json(raw_response)

    def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Generates text output from the configured LLM provider with auto-fallback.
        """
        if self.provider == "groq" or (not self.gemini_api_key and self.groq_api_key):
            res = self._call_groq(prompt, system_prompt)
            if res and res.strip() and res.strip() != "{}":
                return res

        if self.provider == "gemini":
            res = self._call_gemini(prompt, system_prompt)
            if res and res.strip() and res.strip() != "{}":
                return res
            # Fallback automatique vers Groq si Gemini échoue (ex: 429 quota)
            if self.groq_api_key:
                logger.info("Falling back from Gemini to Groq...")
                res_groq = self._call_groq(prompt, system_prompt)
                if res_groq and res_groq.strip() and res_groq.strip() != "{}":
                    return res_groq

        if self.provider == "ollama":
            return self._call_ollama(prompt, system_prompt)

        return "{}"

    def _call_groq(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Calls Groq API (Llama 3.3 70B / 8B).
        """
        if not self.groq_api_key:
            return "{}"
        try:
            from groq import Groq
            client = Groq(api_key=self.groq_api_key)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            # Liste de modèles compatibles Groq (priorise les modèles disponibles sur le compte)
            candidates = [
                os.getenv("GROQ_MODEL", "").strip(),
                "openai/gpt-oss-120b",
                "openai/gpt-oss-20b",
                "qwen/qwen3.8-27b",
                "llama-3.3-70b-versatile",
                "llama-3.1-8b-instant",
            ]
            candidates = [c for c in candidates if c]

            for model_name in candidates:
                try:
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=messages,
                        temperature=0.2,
                        response_format={"type": "json_object"},
                    )
                    text = response.choices[0].message.content
                    if text and len(text.strip()) > 2:
                        return text
                except Exception as model_err:
                    logger.debug("Groq model %s failed: %s", model_name, model_err)
            return "{}"
        except Exception as e:
            logger.warning(f"Groq API call failed: {e}")
            return "{}"

    def _call_ollama(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Calls local Ollama API server (e.g. Qwen 2.5 7B / 3B).
        """
        # Fast health check to avoid 180s freeze if Ollama is not running
        try:
            r = requests.get(f"{self.ollama_host.rstrip('/')}/api/tags", timeout=1.5)
            if r.status_code != 200:
                return "{}"
        except Exception:
            return "{}"

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
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")
        except Exception as e:
            logger.warning(f"Ollama call failed ({e}). Returning fallback JSON.")
            return "{}"

    def _call_gemini(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Calls Google Gemini API using the google-genai SDK.
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
                temperature=0.15,
                top_p=0.85,
                top_k=40,
                max_output_tokens=8192,
            ) if system_prompt else types.GenerateContentConfig(
                temperature=0.15,
                top_p=0.85,
                top_k=40,
                max_output_tokens=8192,
            )

            max_retries = 2
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info(f"Calling Gemini API (attempt {attempt}/{max_retries})...")
                    model_to_use = os.getenv("GEMINI_MODEL", "models/gemini-3.5-flash")
                    response = client.models.generate_content(
                        model=model_to_use,
                        contents=prompt,
                        config=config
                    )
                    logger.info("Gemini API call successful")
                    return response.text
                except Exception as e:
                    err_str = str(e)
                    logger.error(f"Gemini API call failed: {e}")
                    # Quota dépassé (429) -> Inutile de retenter en boucle
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        logger.warning("Gemini quota exhausted (429). Skipping retries.")
                        return "{}"
                    if attempt < max_retries:
                        time.sleep(2)
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
            return json.loads(text_clean, strict=False)
        except json.JSONDecodeError:
            start = text_clean.find("{")
            end = text_clean.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text_clean[start:end+1], strict=False)
                except json.JSONDecodeError:
                    # Sanitize unescaped newlines inside JSON strings
                    try:
                        import re
                        sanitized = re.sub(r'(?<!\\)\n', r'\\n', text_clean[start:end+1])
                        return json.loads(sanitized, strict=False)
                    except Exception:
                        pass
            logger.error(f"Failed to parse JSON from response: {text[:100]}...")
            return {}
