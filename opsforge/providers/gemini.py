
import os
from google import genai


class GeminiProvider:
    """Gemini API integration for OPSFORGE."""

    def __init__(self, api_key=None, model=None):
        self.api_key = (
            api_key
            or os.getenv("GEMINI_API_1")
            or os.getenv("GEMINI_API_KEY")
        )

        if not self.api_key:
            raise RuntimeError(
                "GEMINI_API_KEY environment variable is missing."
            )

        self.model = (
            model
            or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        )

        self.client = genai.Client(api_key=self.api_key)

    def generate_text(self, prompt: str) -> str:
        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty.")

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
        )

        if not response.text:
            raise RuntimeError("Gemini returned an empty response.")

        return response.text
