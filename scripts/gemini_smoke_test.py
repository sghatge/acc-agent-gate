"""Live Gemini connectivity check for OPSFORGE.

Run with GEMINI_API_KEY set in the environment:
    python scripts/gemini_smoke_test.py

This script sends one short request and never prints the API key.
"""
import os
import sys

from opsforge.providers.gemini import GeminiProvider


def main() -> int:
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_1")):
        print("FAIL: Set GEMINI_API_KEY in your environment first.")
        return 2

    try:
        provider = GeminiProvider()
        answer = provider.generate_text(
            "Reply with exactly: OPSFORGE_GEMINI_CONNECTION_OK"
        )
    except Exception as exc:
        # Do not print environment values or request headers.
        print(f"FAIL: Gemini request failed ({type(exc).__name__}): {exc}")
        return 1

    print(f"Model: {provider.model}")
    print(f"Response: {answer.strip()}")
    if "OPSFORGE_GEMINI_CONNECTION_OK" not in answer:
        print("WARN: Gemini responded, but the response did not match the smoke-test token.")
        return 1
    print("PASS: Gemini API connection is working.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
