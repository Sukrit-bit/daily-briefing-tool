"""
Gemini API client wrapper.

Uses the google.genai SDK (the current, supported library).
Handles communication with Google's Gemini API, including
rate limiting, retries, and response parsing.
"""

import os
import json
import time
from typing import Optional

from google import genai
from google.genai import types


class GeminiClient:
    """
    Wrapper around the Gemini API using the google.genai SDK.

    Handles:
    - API configuration and authentication
    - Sending prompts and getting structured JSON responses
    - Rate limit handling with exponential backoff
    - Token counting for cost tracking
    """

    # Gemini 2.5 Flash has a 1M token context window
    MAX_INPUT_TOKENS = 900_000  # Leave room for the prompt template

    def __init__(self, api_key: str = None, model: str = "gemini-2.5-flash"):
        """
        Initialize the Gemini client.

        Args:
            api_key: Gemini API key (defaults to GEMINI_API_KEY env var)
            model: Model to use (default: gemini-2.5-flash)
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Gemini API key not found. Set GEMINI_API_KEY in your .env file "
                "or pass it directly."
            )

        self.model_name = model
        self.client = genai.Client(api_key=self.api_key)

    def generate(self, prompt: str, max_retries: int = 3) -> Optional[dict]:
        """
        Send a prompt to Gemini and get a parsed JSON response.

        Args:
            prompt: The full prompt text
            max_retries: Number of retries on failure

        Returns:
            Parsed JSON dict, or None if all retries fail
        """
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.3,
                        max_output_tokens=4096,
                        response_mime_type="application/json",
                    ),
                )

                # Parse the JSON response
                text = response.text.strip()

                # Sometimes Gemini wraps JSON in markdown code blocks
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

            except Exception as e:
                error_str = str(e).lower()

                # Rate limit or quota exceeded
                if "429" in error_str or "rate" in error_str or "quota" in error_str:
                    # Check if it's a daily quota exhaustion (no point retrying)
                    if "free_tier" in error_str and "limit: 0" in error_str:
                        print(f"  ERROR: Free tier daily quota exhausted.")
                        print(f"  Enable billing at https://ai.google.dev or wait for quota reset.")
                        return None

                    wait_time = 30 * (attempt + 1)  # 30s, 60s, 90s
                    print(f"  Rate limited, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)

                # Server error (5xx) - retry
                elif "500" in error_str or "503" in error_str:
                    wait_time = 2 ** attempt
                    print(f"  Server error, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)

                else:
                    print(f"  Gemini API error (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)

        return None

    def estimate_tokens(self, text: str) -> int:
        """
        Rough estimate of token count.
        Gemini uses ~1 token per 4 characters for English text.
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
