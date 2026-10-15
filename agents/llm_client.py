import os
import json
import logging
import requests
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class LLMRateLimitError(RuntimeError):
    """Raised when a configured LLM provider rejects a request due to rate limits."""


class LLMClient:
    """
    Unified LLM Client for BIFlow supporting Ollama (Local Qwen 2.5 / Llama 3.1)
    and API providers with automatic JSON extraction.
    """

    def __init__(self):
        self.groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
        self.groq_model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b").strip()
        self.groq_max_completion_tokens = int(
            os.getenv("GROQ_MAX_COMPLETION_TOKENS", "900")
        )
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        configured_provider = os.getenv("LLM_PROVIDER", "").strip().lower()
        self.provider = configured_provider or "groq"
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.model_name = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.ollama_timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))
        self.ollama_num_predict = int(os.getenv("OLLAMA_NUM_PREDICT", "256"))
        self.ollama_keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "10m")
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

    def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Sends a prompt to the LLM and returns the parsed JSON response.
        """
        raw_response = self.generate_text(
            prompt,
            system_prompt,
            max_output_tokens=max_output_tokens,
        )
        return self._extract_json(raw_response)

    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
    ) -> str:
        """
        Generates text output from the configured LLM provider.
        """
        if self.provider == "ollama":
            return self._call_ollama(prompt, system_prompt)
        elif self.provider == "groq":
            return self._call_groq(prompt, system_prompt, max_output_tokens)
        elif self.provider == "openai":
            return self._call_openai(prompt, system_prompt)
        else:
            raise ValueError(f"Unsupported LLM_PROVIDER: {self.provider}")

    def _call_ollama(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Calls local Ollama API server (e.g. Qwen 2.5 7B / 3B).
        """
        url = f"{self.ollama_host.rstrip('/')}/api/generate"
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "keep_alive": self.ollama_keep_alive,
            "options": {"num_predict": self.ollama_num_predict}
        }
        if self.model_name.lower().startswith("qwen3"):
            payload["think"] = False
        if system_prompt:
            payload["system"] = system_prompt

        try:
            response = requests.post(url, json=payload, timeout=self.ollama_timeout)
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")
        except requests.Timeout:
            logger.error(
                "Ollama timed out after %s seconds using %s. "
                "Try a smaller model (for example qwen3:4b) or reduce OLLAMA_NUM_PREDICT. "
                "Returning fallback JSON.",
                self.ollama_timeout,
                self.model_name
            )
            return "{}"
        except (requests.RequestException, ValueError) as e:
            logger.error("Ollama call failed (%s). Returning fallback JSON.", e)
            return "{}"

    def _call_groq(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
    ) -> str:
        """Calls the Groq API and requests a JSON object response."""
        if not self.groq_api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Create a Groq API key, add it to .env, "
                "and set LLM_PROVIDER=groq."
            )

        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=self.groq_api_key,
                base_url="https://api.groq.com/openai/v1",
            )
            response = client.chat.completions.create(
                model=self.groq_model,
                messages=self._build_messages(prompt, system_prompt),
                response_format={"type": "json_object"},
                max_completion_tokens=(
                    max_output_tokens
                    if max_output_tokens is not None
                    else self.groq_max_completion_tokens
                ),
            )
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("Groq returned an empty response.")
            return content
        except RuntimeError:
            raise
        except Exception as e:
            logger.exception("Groq API call failed.")
            if (
                getattr(e, "status_code", None) == 429
                or getattr(e, "code", None) == "rate_limit_exceeded"
            ):
                raise LLMRateLimitError(f"Groq rate limit reached: {e}") from e
            raise RuntimeError(f"Groq API call failed: {e}") from e

    def _call_openai(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Calls the OpenAI API and requests a JSON object response."""
        if not self.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add your OpenAI API key to .env "
                "and set LLM_PROVIDER=openai."
            )

        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.openai_api_key)
            response = client.chat.completions.create(
                model=self.openai_model,
                messages=self._build_messages(prompt, system_prompt),
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("OpenAI returned an empty response.")
            return content
        except RuntimeError:
            raise
        except Exception as e:
            logger.exception("OpenAI API call failed.")
            raise RuntimeError(f"OpenAI API call failed: {e}") from e

    @staticmethod
    def _build_messages(prompt: str, system_prompt: Optional[str]) -> list:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

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
