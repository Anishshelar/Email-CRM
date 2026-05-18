"""
LLM client abstraction — Phase 2.

Design rationale:
  LLMClientProtocol is a typing.Protocol (structural subtyping) so tests can pass
  a plain Python class as a mock without inheriting from anything or using MagicMock.
  The real GeminiClient is the only production implementation for now.

  Keeping the client as a separate injectable object means ClassificationService
  can be unit-tested without any live API calls and without monkeypatching.
"""

import logging
from typing import Protocol, runtime_checkable

from app.config import settings

logger = logging.getLogger(__name__)


@runtime_checkable
class LLMClientProtocol(Protocol):
    """
    Minimal interface that ClassificationService depends on.
    Any object with a `generate(prompt: str) -> str` method satisfies this.
    """

    def generate(self, prompt: str) -> str:
        ...


class GeminiClient:
    """
    Production Gemini client.

    Uses JSON mode (response_mime_type="application/json") so the model is
    constrained to return valid JSON on every call. This eliminates the most
    common failure mode (markdown fences, preamble text) before we even reach
    the retry layer.

    Temperature is set to 0.1 — low enough for consistent structured output
    while allowing minor lexical variation in suggested_reply drafts.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        import google.generativeai as genai

        api_key = api_key or settings.gemini_api_key
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. Add it to .env before using the "
                "classification service."
            )
        model = model or settings.gemini_model
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(
            model_name=model,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.1,
                max_output_tokens=1024,
            ),
        )
        logger.info("GeminiClient initialised with model=%s", model)

    def generate(self, prompt: str) -> str:
        response = self._model.generate_content(prompt)
        return response.text


def get_default_client() -> GeminiClient:
    """
    Factory for the singleton production client.
    Call once at app startup (e.g. in a FastAPI lifespan handler) and inject
    the result into ClassificationService.
    """
    return GeminiClient()
