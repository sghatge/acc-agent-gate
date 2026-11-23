"""Gemini API provider for OPSFORGE."""

import os
from google import genai


class GeminiProvider:
    """Thin, injectable wrapper around the official Google Gen AI SDK."""

    def __init__(self, api_key=None, model=None, client=None):
        # Explicit argument wins; GEMINI_API_KEY is the canonical variable.
        # Keep GEMINI_API_1 as a temporary backwards-compatible fallback.
        self.api_key = (
            api_key
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("GEMINI_API_1")
        )

        if not self.api_key and client is None:
            raise RuntimeError(
                "Gemini API key missing. Set GEMINI_API_KEY (recommended) "
                "or GOOGLE_API_KEY."
            )

        self.model = (
            model
            or os.getenv("GEMINI_MODEL")
            or "gemini-3.8-flash"
        )

        # Client injection keeps tests offline and enables alternate transports.
        self.client = client or genai.Client(api_key=self.api_key)

    def generate_text(self, prompt: str) -> str:
        """Generate text and return the model's text response."""
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Prompt must be a non-empty string.")

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
        )

        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError(
                "Gemini returned no text. Check model access and response safety."
            )

        return text
