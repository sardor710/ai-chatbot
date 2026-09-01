"""LLM provider abstraction and OpenAI-compatible implementation."""

import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.ai.response import AIResponse, parse_ai_json_output

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    async def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 300,
        temperature: float = 0.7,
    ) -> AIResponse | None:
        """Generate structured AI response."""

    @abstractmethod
    async def generate_summary(
        self,
        prompt: str,
        max_tokens: int = 250,
    ) -> str | None:
        """Generate concise summary text."""


class OpenAICompatibleProvider(LLMProvider):
    """Provider targeting OpenAI or any OpenAI-compatible API endpoint (OpenRouter, local Ollama, vLLM, etc.)."""

    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        # Ensure base_url does not end with a slash
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 300,
        temperature: float = 0.7,
    ) -> AIResponse | None:
        """Send chat completion request and parse JSON structured output."""
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=self._get_headers())
                if response.status_code != 200:
                    logger.error(
                        f"LLM API returned error status {response.status_code}: {response.text[:300]}"
                    )
                    return None

                data = response.json()
                content = data["choices"][0]["message"]["content"]
                parsed = parse_ai_json_output(content)
                if not parsed:
                    logger.warning(f"Failed to parse valid structured JSON from LLM: {content}")
                return parsed

        except httpx.TimeoutException:
            logger.error("LLM API request timed out.")
            return None
        except Exception as e:
            logger.error(f"Error during LLM API call: {e}")
            return None

    async def generate_summary(
        self,
        prompt: str,
        max_tokens: int = 250,
    ) -> str | None:
        """Generate text summary of past dialogue."""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a concise conversation summarizer."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=self._get_headers())
                if response.status_code == 200:
                    data = response.json()
                    return data["choices"][0]["message"]["content"].strip()
                logger.error(f"Failed to generate summary: {response.text[:200]}")
                return None
        except Exception as e:
            logger.error(f"Error during summarization LLM call: {e}")
            return None
