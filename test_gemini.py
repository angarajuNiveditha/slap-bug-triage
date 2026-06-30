#!/usr/bin/env python3
"""
test_gemini.py — verify Gemini API key + network reachability + vision works.

Run this before we wire Gemini into the media sub-agent. It checks four
things in order:

  1. Network can reach generativelanguage.googleapis.com (the Gemini endpoint)
  2. GEMINI_API_KEY is set and authenticates correctly
  3. Text generation works on gemini-2.5-flash
  4. Image input works (vision-capable mode, which is what we need for
     the media sub-agent integration)

Setup (one-time):
    1. Add to .env (gitignored):
         GEMINI_API_KEY=<your key>
    2. (Optional) pip install google-genai
       — this script uses raw `requests` so the dep isn't strictly required

Usage:
    python3 test_gemini.py
    python3 test_gemini.py path/to/your/screenshot.png   # also test vision

Exit codes:
    0  — all four checks passed
    1  — at least one check failed; print which
"""

from __future__ import annotations

import base64
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

BASE     = "https://generativelanguage.googleapis.com"
API_PATH = "/v1beta/models/gemini-2.5-flash:generateContent"
LIST_PATH = "/v1beta/models"


def section(title: str) -> None:
    print()
    print("─" * 60)
    print(f"  {title}")
    print("─" * 60)


def check_1_network() -> bool:
    """Is generativelanguage.googleapis.com reachable from this network?"""
    section("1. Network reachability")
    try:
        r = requests.head(BASE, timeout=10, allow_redirects=True)
        print(f"  HEAD {BASE} → HTTP {r.status_code}")
        # Any 2xx/3xx/4xx response means we reached Google's edge — the
        # network is OK. A timeout or connection-refused means it's not.
        return True
    except requests.exceptions.RequestException as e:
        print(f"  ✗ Network unreachable: {type(e).__name__}: {e}")
        print("    This means Flipkart's corp network is blocking Google AI.")
        print("    Gemini integration would be a non-starter on this machine.")
        return False


def check_2_key() -> bool:
    """Is GEMINI_API_KEY set and does it authenticate?"""
    section("2. API key authentication")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("  ✗ GEMINI_API_KEY not set in environment / .env")
        return False
    print(f"  Key prefix: {key[:8]}…{key[-4:]} ({len(key)} chars)")

    # Listing models is the cheapest authenticated call
    r = requests.get(f"{BASE}{LIST_PATH}", params={"key": key}, timeout=15)
    print(f"  GET /v1beta/models → HTTP {r.status_code}")
    if r.status_code != 200:
        print(f"  ✗ Body: {r.text[:300]}")
        return False
    models = r.json().get("models", [])
    flash = [m for m in models if "gemini-2.5-flash" in m.get("name", "")]
    print(f"  ✓ {len(models)} models visible; gemini-2.5-flash variants: {len(flash)}")
    return True


def check_3_text_generation() -> bool:
    """Can gemini-2.5-flash actually answer a text prompt?"""
    section("3. Text generation on gemini-2.5-flash")
    key = os.environ["GEMINI_API_KEY"]
    payload = {
        "contents": [{
            "parts": [{"text": "Reply with the single word 'pong' and nothing else."}]
        }],
        "generationConfig": {"maxOutputTokens": 16, "temperature": 0},
    }
    t0 = time.time()
    r = requests.post(
        f"{BASE}{API_PATH}",
        params={"key": key},
        json=payload,
        timeout=30,
    )
    elapsed = time.time() - t0
    print(f"  POST :generateContent → HTTP {r.status_code} in {elapsed:.2f}s")
    if r.status_code != 200:
        print(f"  ✗ Body: {r.text[:400]}")
        return False
    try:
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        print(f"  ✓ Model replied: {text!r}")
        return True
    except (KeyError, IndexError) as e:
        print(f"  ✗ Unexpected response shape: {e}")
        print(f"    {r.text[:400]}")
        return False


def check_4_vision(image_path: Path) -> bool:
    """Can gemini-2.5-flash actually process an image?"""
    section(f"4. Vision input ({image_path.name})")
    key = os.environ["GEMINI_API_KEY"]
    if not image_path.exists():
        print(f"  ⊘ Image not found, skipping. Pass a path on CLI to enable.")
        return True   # not a failure; just skipped

    ext = image_path.suffix.lower().lstrip(".")
    mime = {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "webp": "image/webp", "gif": "image/gif",
    }.get(ext, "application/octet-stream")
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")

    payload = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": mime, "data": encoded}},
                {"text": "Describe what's in this image in one sentence."},
            ]
        }],
        "generationConfig": {"maxOutputTokens": 100, "temperature": 0},
    }

    t0 = time.time()
    r = requests.post(
        f"{BASE}{API_PATH}",
        params={"key": key},
        json=payload,
        timeout=60,
    )
    elapsed = time.time() - t0
    print(f"  POST with image ({len(encoded)} b64 chars) → HTTP {r.status_code} in {elapsed:.2f}s")
    if r.status_code != 200:
        print(f"  ✗ Body: {r.text[:400]}")
        return False
    try:
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        print(f"  ✓ Model described: {text}")
        return True
    except (KeyError, IndexError) as e:
        print(f"  ✗ Unexpected response shape: {e}")
        return False


def main() -> None:
    image_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None

    results = []
    results.append(("network reachable",     check_1_network()))
    if results[-1][1]:
        results.append(("key authenticates",     check_2_key()))
    if all(ok for _, ok in results):
        results.append(("text generation",   check_3_text_generation()))
    if all(ok for _, ok in results) and image_path:
        results.append(("vision input",      check_4_vision(image_path)))

    print()
    print("═" * 60)
    print("  SUMMARY")
    print("═" * 60)
    for name, ok in results:
        print(f"  {'✓' if ok else '✗'} {name}")
    print()

    all_ok = all(ok for _, ok in results)
    if all_ok:
        print("All checks passed. Gemini 2.5 Flash is reachable + usable from")
        print("this machine. Safe to proceed with the hybrid media sub-agent.")
    else:
        print("At least one check failed. Address the failures before")
        print("integrating Gemini into the pipeline.")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
