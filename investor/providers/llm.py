"""
Claude: tag headlines (sentiment / impact / one-line summary) and write the
daily morning digest. Optional — everything works without an API key.
"""

import json
import logging

import anthropic

import config

logger = logging.getLogger(__name__)

_FALLBACK_BETA = "server-side-fallback-2026-07-01"

_TAG_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "sentiment": {"type": "number", "description": "-1 very negative … 1 very positive for the stock"},
                    "impact": {"type": "string", "enum": ["low", "medium", "high"]},
                    "summary": {"type": "string", "description": "≤ 25 words: what happened and why it matters to shareholders"},
                },
                "required": ["id", "sentiment", "impact", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def available() -> bool:
    return bool(config.get("anthropic_key"))


def _client():
    return anthropic.Anthropic(api_key=config.get("anthropic_key"))


def _create(**kw):
    resp = _client().beta.messages.create(
        model=config.get("llm_model"),
        betas=[_FALLBACK_BETA],
        fallbacks="default",
        **kw,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Request declined by the model")
    return resp


def _text(resp) -> str:
    return "".join(b.text for b in resp.content if b.type == "text")


def tag_headlines(items: list) -> list:
    """items: news rows with id/ticker/title. Returns [{id, sentiment, impact, summary}]."""
    if not items:
        return []
    lines = "\n".join(f'{i["id"]}\t{i["ticker"]}\t{i["title"]}' for i in items)
    resp = _create(
        max_tokens=16000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": _TAG_SCHEMA}},
        system=("You rate financial news headlines for long-term investors. For each line "
                "(id, ticker, headline) give the sentiment for that ticker's shareholders, the likely "
                "impact on the investment case, and a plain-English summary a beginner understands. "
                "Do not invent facts beyond the headline."),
        messages=[{"role": "user", "content": lines}],
    )
    return json.loads(_text(resp)).get("items", [])


def daily_digest(context: dict) -> str:
    """context: compact JSON of top picks, movers, notable news. Returns plain text."""
    resp = _create(
        max_tokens=16000,
        output_config={"effort": "medium"},
        system=("You write a short morning brief for everyday investors using ONLY the data provided. "
                "Plain text, 4 short paragraphs max: market mood; 2–3 value ideas; 2–3 growth ideas; "
                "what's buzzing and any hype warnings. Mention tickers in caps. Explain jargon briefly. "
                "End with: 'Educational only — not financial advice.'"),
        messages=[{"role": "user", "content": json.dumps(context, default=str)}],
    )
    return _text(resp).strip()
