"""
Multi-provider LLM client with automatic fallback.

Tries the primary provider first (Gemini), and falls back to
the secondary provider (OpenAI) if the primary is rate-limited
or fails.
"""

from __future__ import annotations

import os
from typing import Optional


class LLMClient:
    """
    Unified LLM client that wraps multiple providers with fallback.

    Usage:
        client = LLMClient()  # Uses Gemini primary, OpenAI fallback
        client = LLMClient(provider="openai")  # Forces OpenAI only
        client = LLMClient(provider="gemini")  # Forces Gemini only (no fallback)
    """

    def __init__(self, provider: str = "auto"):
        """
        Initialize the LLM client.

        Args:
            provider: "auto" (Gemini + OpenAI fallback), "gemini", or "openai"
        """
        self.provider = provider
        self._primary = None
        self._fallback = None
        self._active_provider_name = None

        if provider == "auto":
            # Try to init both — gracefully handle missing keys
            self._primary = self._try_init_gemini()
            self._fallback = self._try_init_openai()

            if self._primary is None and self._fallback is None:
                raise ValueError(
                    "No LLM provider available. Set GEMINI_API_KEY or OPENAI_API_KEY "
                    "in your .env file."
                )

            if self._primary:
                self._active_provider_name = "gemini"
            else:
                # Gemini not available, use OpenAI as primary
                self._primary = self._fallback
                self._fallback = None
                self._active_provider_name = "openai"

        elif provider == "gemini":
            from .gemini_client import GeminiClient
            self._primary = GeminiClient()
            self._active_provider_name = "gemini"

        elif provider == "openai":
            from .openai_client import OpenAIClient
            self._primary = OpenAIClient()
            self._active_provider_name = "openai"

        else:
            raise ValueError(f"Unknown provider: {provider}. Use 'auto', 'gemini', or 'openai'.")

    def _try_init_gemini(self):
        """Try to initialize Gemini client. Returns None if not available."""
        if not os.getenv("GEMINI_API_KEY"):
            return None
        try:
            from .gemini_client import GeminiClient
            return GeminiClient()
        except Exception as e:
            print(f"  Warning: Gemini init failed: {e}")
            return None

    def _try_init_openai(self):
        """Try to initialize OpenAI client. Returns None if not available."""
        if not os.getenv("OPENAI_API_KEY"):
            return None
        try:
            from .openai_client import OpenAIClient
            return OpenAIClient()
        except Exception as e:
            print(f"  Warning: OpenAI init failed: {e}")
            return None

    @property
    def model_name(self) -> str:
        """Return the model name of the active provider."""
        return self._primary.model_name

    @property
    def MAX_INPUT_TOKENS(self) -> int:
        """Return max input tokens for the active provider."""
        return self._primary.MAX_INPUT_TOKENS

    def generate(self, prompt: str, max_retries: int = 3) -> Optional[dict]:
        """
        Send a prompt to the LLM with automatic fallback.

        Tries the primary provider first. If it fails (rate limit, error),
        falls back to the secondary provider.

        Args:
            prompt: The full prompt text
            max_retries: Number of retries per provider

        Returns:
            Parsed JSON dict, or None if all providers fail
        """
        # Try primary
        result = self._primary.generate(prompt, max_retries=max_retries)

        if result is not None:
            return result

        # Primary failed — try fallback
        if self._fallback is not None:
            fallback_name = "openai" if self._active_provider_name == "gemini" else "gemini"
            print(f"  Primary ({self._active_provider_name}) failed → falling back to {fallback_name}")
            self._active_provider_name = fallback_name

            result = self._fallback.generate(prompt, max_retries=max_retries)

            if result is not None:
                # Fallback worked — swap it to primary for remaining items
                # to avoid hammering the rate-limited provider
                print(f"  Switching to {fallback_name} for remaining items")
                self._primary, self._fallback = self._fallback, self._primary
                return result

        return None

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count using the active provider."""
        return self._primary.estimate_tokens(text)

    def truncate_for_context(self, text: str, max_tokens: int = None) -> str:
        """Truncate text using the active provider."""
        return self._primary.truncate_for_context(text, max_tokens)
