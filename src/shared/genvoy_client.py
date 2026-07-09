"""
genvoy_client.py — thin wrapper around Flipkart's internal Gemini proxy.

The proxy exposes Google's native Gemini REST shape at
`POST <GEMINI_API_URL>` (typically `/<model>/:generateContent`) but with
Azure APIM auth: BOTH the subscription key (`Ocp-Apim-Subscription-Key`)
AND a short-lived JWT bearer (`Authorization: Bearer <JWT>`) are required.
Neither alone is enough.

Public surface:
    gemini_describe_image(image_path, prompt) -> str
    is_configured() -> bool
    GeminiUnavailable

Any non-200 / network / config error raises `GeminiUnavailable` so the
caller can fall back to a Claude-only vision path without crashing the
pipeline. The proxy IP (10.83.64.112) only resolves on the Flipkart corp
network, and `GENVOY_TOKEN` expires hourly — both are normal failure
modes worth a graceful fallback.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Union

import requests

GENVOY_TOKEN_ENV = "GENVOY_TOKEN"

MIME_BY_EXT = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif":  "image/gif",
}


class GeminiUnavailable(Exception):
    """Raised when Gemini cannot be called — the caller should fall back."""


def is_configured() -> bool:
    return bool(
        os.environ.get("GEMINI_API_URL")
        and os.environ.get("GEMINI_API_KEY")
        and os.environ.get(GENVOY_TOKEN_ENV)
    )


def _headers() -> dict:
    return {
        "Content-Type":              "application/json",
        "Ocp-Apim-Subscription-Key": os.environ.get("GEMINI_API_KEY", ""),
        "Authorization":             f"Bearer {os.environ.get(GENVOY_TOKEN_ENV, '')}",
    }


def gemini_describe_image(
    image_path: Union[str, Path],
    prompt:     str,
    max_output_tokens: int = 800,
    timeout:           int = 60,
) -> str:
    """
    Send one image + a text prompt to Gemini and return the model's reply
    as plain text. Raises GeminiUnavailable on any failure.
    """
    if not is_configured():
        raise GeminiUnavailable(
            "Gemini not configured — set GEMINI_API_URL, GEMINI_API_KEY, "
            "and GENVOY_TOKEN in .env"
        )

    image_path = Path(image_path)
    if not image_path.exists():
        raise GeminiUnavailable(f"image not found: {image_path}")

    mime = MIME_BY_EXT.get(image_path.suffix.lower())
    if not mime:
        raise GeminiUnavailable(f"unsupported image extension: {image_path.suffix}")

    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    body = {
        "contents": [{
            "role":  "user",
            "parts": [
                {"inlineData": {"mimeType": mime, "data": encoded}},
                {"text": prompt},
            ],
        }],
        "generationConfig": {
            "maxOutputTokens": max_output_tokens,
            "temperature":     0,
        },
    }

    url = os.environ["GEMINI_API_URL"]
    try:
        r = requests.post(url, headers=_headers(), json=body, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise GeminiUnavailable(f"network error: {type(e).__name__}: {e}") from e

    if r.status_code == 401:
        raise GeminiUnavailable(
            "401 — GENVOY_TOKEN expired or invalid. Refresh and retry."
        )
    if r.status_code != 200:
        raise GeminiUnavailable(f"HTTP {r.status_code}: {r.text[:300]}")

    try:
        j     = r.json()
        cand  = j["candidates"][0]
        parts = cand.get("content", {}).get("parts", []) or []
        text  = "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, ValueError) as e:
        raise GeminiUnavailable(f"unexpected response shape: {e}") from e

    if not text:
        # Empty content usually means maxOutputTokens was eaten by Gemini 2.5's
        # internal "thinking" budget. Surface that explicitly so the fallback
        # path is taken instead of returning an empty description downstream.
        raise GeminiUnavailable(
            f"Gemini returned no text (finishReason={cand.get('finishReason')}, "
            f"usage={j.get('usageMetadata', {})})"
        )

    return text
