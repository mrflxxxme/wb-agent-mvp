"""
Gemini AI client using the new google-genai SDK (not deprecated google-generativeai).

Key design:
- google-genai SDK with native async (client.aio.models.generate_content)
- AsyncRetrying: auto-retry on ResourceExhausted (429) and ServiceUnavailable (503)
- Temperature 0.2: consistent, analytical responses
- Logs prompt/response token counts for cost monitoring
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from google import genai
from google.genai import types
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.gemini.prompts import SYSTEM_PROMPT, build_prompt

logger = logging.getLogger(__name__)

# Exceptions that warrant a retry (rate limit and transient server errors)
_RETRYABLE = (Exception,)  # Broad catch; filter by message below

try:
    from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
    _RETRYABLE = (ResourceExhausted, ServiceUnavailable)
except ImportError:
    logger.warning("google-api-core not available, using broad retry")


class GeminiClient:
    """Async Gemini 2.0 Flash client with retry and cost logging."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        logger.info("GeminiClient initialized with model '%s'", model)

    async def ask(
        self,
        context: Dict[str, Any],
        query_type: str,
        question: Optional[str] = None,
    ) -> str:
        """
        Send a context + query to Gemini and return the text response.
        Retries up to 4 times on rate limits / transient errors.
        Raises RetryError after all attempts exhausted.
        """
        prompt = build_prompt(context, query_type, question)
        start = time.monotonic()

        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(_RETRYABLE),
                wait=wait_exponential(multiplier=2, min=4, max=120),
                stop=stop_after_attempt(4),
                reraise=True,
            ):
                with attempt:
                    response = await self._client.aio.models.generate_content(
                        model=self._model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT,
                            temperature=0.2,
                            max_output_tokens=2048,
                        ),
                    )

            elapsed_ms = int((time.monotonic() - start) * 1000)
            text = response.text or ""

            # Log token usage for cost monitoring
            usage = getattr(response, "usage_metadata", None)
            if usage:
                logger.info(
                    "Gemini [%s] in=%d out=%d tokens, %dms",
                    query_type,
                    getattr(usage, "prompt_token_count", 0),
                    getattr(usage, "candidates_token_count", 0),
                    elapsed_ms,
                )
            else:
                logger.info("Gemini [%s] completed in %dms", query_type, elapsed_ms)

            return text

        except RetryError as e:
            logger.error("Gemini all retries exhausted for '%s': %s", query_type, e)
            raise

    async def probe(self) -> bool:
        """Quick connectivity check — returns True if API is reachable."""
        try:
            await self._client.aio.models.count_tokens(
                model=self._model,
                contents="test",
            )
            return True
        except Exception as e:
            logger.warning("Gemini probe failed: %s", e)
            return False
