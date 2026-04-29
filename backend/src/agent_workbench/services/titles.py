"""LLM-generated short chat titles."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request


def _fallback_title(prompt: str) -> str:
    cleaned = re.sub(r"\s+", " ", prompt).strip()
    if not cleaned:
        return "Chat"
    words = cleaned.split(" ")
    return " ".join(words[:4])[:36].strip() or "Chat"


def _normalize_model(model: str) -> str:
    if model.startswith("openai:"):
        return model.split("openai:", 1)[1]
    return model


def generate_short_title(prompt: str, model: str) -> str:
    key = os.getenv("OPENAI_API_KEY") or os.getenv("FIREWORKS_API_KEY")
    if not key:
        return _fallback_title(prompt)

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.fireworks.ai/inference/v1").rstrip("/")
    url = f"{base_url}/chat/completions"
    payload = {
        "model": _normalize_model(model),
        "temperature": 0.2,
        "max_tokens": 16,
        "messages": [
            {
                "role": "system",
                "content": "Generate a very short chat title (2-4 words). No punctuation. No quotes.",
            },
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return _fallback_title(prompt)

    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    if not isinstance(content, str):
        return _fallback_title(prompt)
    title = re.sub(r"[\n\r\t]+", " ", content).strip().strip("\"'`")
    title = re.sub(r"[^\w\s-]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        return _fallback_title(prompt)
    words = title.split(" ")[:4]
    normalized = " ".join(words).strip()
    return normalized[:36] if normalized else _fallback_title(prompt)

