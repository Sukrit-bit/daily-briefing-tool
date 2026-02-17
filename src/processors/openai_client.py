"""
OpenAI API client wrapper.

Handles communication with OpenAI's API (GPT-4o),
including rate limiting, retries, timeout protection,
and response parsing.

Used as a fallback when Gemini is rate-limited.
"""

from __future__ import annotations

import os
import json
import time
from typing import Optional

import httpx
from openai import OpenAI, APITimeoutError

# Per-request timeout for LLM API calls (seconds).
# Prevents the pipeline from hanging indefinitely on a single request.
REQUEST_TIMEOUT_SECONDS = 120


class OpenAIClient:
    """
    Wrapper around the OpenAI API.

    Implements the same interface as GeminiClient so they're interchangeable.
    """

    # GPT-4o has 128K context window
    MAX_INPUT_TOKENS = 120_000  # Leave room for the prompt template

    def __init__(self, api_key: str = None, model: str = "gpt-4o"):
        """
        Initialize the OpenAI client.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Model to use (default: gpt-4o)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key not found. Set OPENAI_API_KEY in your .env file "
                "or pass it directly."
            )

        self.model_name = model
        self.client = OpenAI(
            api_key=self.api_key,
            timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=10.0),
        )

    def generate(self, prompt: str, max_retries: int = 3) -> Optional[dict]:
        """
        Send a prompt to OpenAI and get a parsed JSON response.

        Args:
            prompt: The full prompt text
            max_retries: Number of retries on failure

        Returns:
            Parsed JSON dict, or None if all retries fail
        """
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a sharp tech/business analyst. Always respond with valid JSON only, no markdown formatting."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=0.3,
                    max_tokens=4096,
                    response_format={"type": "json_object"},
                )

                text = response.choices[0].message.content.strip()

                # Sometimes wraps JSON in markdown code blocks
                if text.startswith("```json"):
                    text = text[7:]
                if text.startswith("```"):
                    text = text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

                result = json.loads(text)
                return result

            except json.JSONDecodeError as e:
                print(f"  JSON parse error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)

            except APITimeoutError as e:
                print(f"  TIMEOUT (attempt {attempt + 1}/{max_retries}): OpenAI API call timed out after {REQUEST_TIMEOUT_SECONDS}s")
                # Don't retry timeouts — they'll likely time out again.
                # Re-raise so the caller (LLMClient/Summarizer) can handle it.
                raise

            except Exception as e:
                error_str = str(e).lower()

                # Rate limit — OpenAI free tier can be strict
                if "429" in error_str or "rate" in error_str:
                    wait_time = 30 * (attempt + 1)  # 30s, 60s, 90s
                    print(f"  Rate limited, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)

                # Server error
                elif "500" in error_str or "503" in error_str:
                    wait_time = 2 ** attempt
                    print(f"  Server error, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)

                else:
                    print(f"  OpenAI API error (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)

        return None

    def estimate_tokens(self, text: str) -> int:
        """
        Rough estimate of token count.
        GPT uses ~1 token per 4 characters for English text.
        """
        return len(text) // 4

    def truncate_for_context(self, text: str, max_tokens: int = None) -> str:
        """
        Truncate text to fit within the context window.

        Args:
            text: Input text
            max_tokens: Maximum tokens (defaults to MAX_INPUT_TOKENS)

        Returns:
            Truncated text if needed
        """
        if max_tokens is None:
            max_tokens = self.MAX_INPUT_TOKENS

        estimated = self.estimate_tokens(text)
        if estimated <= max_tokens:
            return text

        # Truncate to fit, leaving some margin
        max_chars = max_tokens * 4
        truncated = text[:max_chars]

        # Try to break at a sentence boundary
        last_period = truncated.rfind('. ')
        if last_period > max_chars * 0.8:
            truncated = truncated[:last_period + 1]

        return truncated + "\n\n[Content truncated due to length]"
