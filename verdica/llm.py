"""Provider-neutral LLM layer (DEC-0008): one function, JSON in, JSON out.

Provider selection, in order: VERDICA_PROVIDER env var if set, else Mistral
when MISTRAL_API_KEY is present, else Anthropic when ANTHROPIC_API_KEY is
present. Mistral speaks plain HTTP (stdlib only); Anthropic uses its SDK
when installed. No provider is ever required: callers treat None from
available() as "run without the judge".
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
DEFAULT_MODELS = {"mistral": "mistral-large-latest", "anthropic": "claude-opus-5"}

# set to a short reason string whenever complete_json returns None for a
# transport/provider failure (as opposed to a deliberate model judgment),
# so callers can count errors instead of misreading them as judgments
last_error: str | None = None


def provider() -> str | None:
    forced = os.environ.get("VERDICA_PROVIDER")
    if forced:
        return forced
    if os.environ.get("MISTRAL_API_KEY"):
        return "mistral"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def available() -> bool:
    return provider() is not None


def complete_json(prompt: str, schema: dict) -> dict | None:
    """One completion constrained to `schema`. None on refusal/failure."""
    p = provider()
    if p == "mistral":
        return _mistral(prompt, schema)
    if p == "anthropic":
        return _anthropic(prompt, schema)
    return None


def _model(p: str) -> str:
    return os.environ.get("VERDICA_MODEL") or DEFAULT_MODELS[p]


def _mistral(prompt: str, schema: dict) -> dict | None:
    global last_error

    def call(response_format: dict, prompt_text: str) -> dict:
        body = json.dumps({
            "model": _model("mistral"),
            "messages": [{"role": "user", "content": prompt_text}],
            "response_format": response_format,
            "max_tokens": 2048,
            "temperature": 0,
        }).encode()
        req = urllib.request.Request(MISTRAL_URL, data=body, headers={
            "Authorization": f"Bearer {os.environ['MISTRAL_API_KEY']}",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
        return json.loads(data["choices"][0]["message"]["content"])

    strict = {"type": "json_schema", "json_schema": {
        "name": "result", "strict": True, "schema": schema}}
    fallback = ({"type": "json_object"},
                prompt + "\n\nAnswer as JSON matching this schema:\n"
                + json.dumps(schema))
    use_fallback = False
    for attempt in range(4):
        try:
            if use_fallback:
                return call(*fallback)
            return call(strict, prompt)
        except urllib.error.HTTPError as e:
            if e.code == 400 and not use_fallback:
                use_fallback = True  # schema mode unsupported: retry in json mode
                continue
            if e.code in (429, 500, 502, 503) and attempt < 3:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                time.sleep(float(retry_after) if retry_after else 2.0 * (attempt + 1))
                continue
            last_error = f"http {e.code}"
            return None
        except (urllib.error.URLError, OSError) as e:
            # socket timeouts and resets are transient: retry like a 5xx
            if attempt < 3:
                time.sleep(2.0 * (attempt + 1))
                continue
            last_error = type(e).__name__
            return None
        except (KeyError, ValueError) as e:
            last_error = type(e).__name__
            return None
    last_error = "retries exhausted"
    return None


def _anthropic(prompt: str, schema: dict) -> dict | None:
    try:
        import anthropic
    except ImportError:
        return None
    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=_model("anthropic"),
            max_tokens=2048,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError:
        return None
    if response.stop_reason == "refusal":
        return None
    try:
        return json.loads(next(b.text for b in response.content if b.type == "text"))
    except (StopIteration, ValueError):
        return None
