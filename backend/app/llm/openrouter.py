"""OpenRouter provider — reaches Claude models via the OpenAI-compatible API.

The user directed us to route LLM traffic through their OpenRouter key. We use the
official `openai` SDK pointed at OpenRouter's base URL. Every agent prompt asks the
model to return strict JSON ({"findings": [...], "extra": {...}}) which we parse.
"""
from __future__ import annotations

import json

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import Settings
from .base import AgentResult

_JSON_INSTRUCTION = (
    '\n\nReturn ONLY a JSON object: {"findings": [...], "extra": {}} where each '
    "item in \"findings\" matches the output schema described above. "
    "No markdown fences, no prose."
)


class OpenRouterProvider:
    def __init__(self, settings: Settings):
        if not settings.openrouter_api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Set it, or use llm.provider=mock."
            )
        self.settings = settings
        self.client = OpenAI(
            base_url=settings.llm.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            default_headers={
                "HTTP-Referer": "https://nxtwave.local/assessment-review",
                "X-Title": "Assessment Review Pipeline",
            },
        )

    def run_agent(self, phase: str, model: str, system_prompt: str, payload: dict) -> AgentResult:
        user = json.dumps(payload, ensure_ascii=False)
        return self._call(model, system_prompt + _JSON_INSTRUCTION, user)

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        reraise=True,
    )
    def _call(self, model: str, system: str, user: str) -> AgentResult:
        resp = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
            response_format={"type": "json_object"},
            max_tokens=2048,
        )
        text = resp.choices[0].message.content or "{}"
        data = _safe_json(text)
        usage = resp.usage
        return AgentResult(
            findings=data.get("findings", []) or [],
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            extra=data.get("extra", {}) or {},
        )


def _safe_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # last resort: slice the first {...} block
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return {}
        return {}
