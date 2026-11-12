"""
Grok AI Monitor for LZT Autobuyer
- Receives status, errors, and custom rules
- Owner can add/edit rules from the bot
- Sends reports to owner (and optionally to xAI API if key is set)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from loguru import logger
from aiogram import Bot

from config import get_settings


class GrokMonitor:
    def __init__(self, bot: Bot | None = None):
        self.bot = bot
        self.owner_id = get_settings().owner_id
        self.rules: list[str] = []  # in-memory; also stored in DB
        self._lock = asyncio.Lock()

    async def load_rules(self) -> None:
        """Load rules from database settings."""
        from database import get_setting
        raw = await get_setting("grok_rules", "")
        self.rules = [r.strip() for r in raw.split("|||") if r.strip()] if raw else []

    async def save_rules(self) -> None:
        from database import set_setting
        await set_setting("grok_rules", "|||".join(self.rules))

    async def add_rule(self, rule: str) -> str:
        async with self._lock:
            rule = rule.strip()
            if not rule:
                return "Empty rule ignored."
            if rule in self.rules:
                return "Rule already exists."
            self.rules.append(rule)
            await self.save_rules()
            return f"✅ Rule added ({len(self.rules)} total):\n{rule}"

    async def list_rules(self) -> str:
        if not self.rules:
            return "No custom rules yet. Use /rule <text> to add one."
        lines = ["<b>Current Grok Rules:</b>"]
        for i, r in enumerate(self.rules, 1):
            lines.append(f"{i}. {r}")
        return "\n".join(lines)

    async def clear_rules(self) -> str:
        async with self._lock:
            self.rules.clear()
            await self.save_rules()
            return "All custom rules cleared."

    async def report(self, event: str, details: str = "", critical: bool = False) -> None:
        """Send a monitoring report to the owner (and optionally to Grok API)."""
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        prefix = "🚨" if critical else "📊"
        text = f"{prefix} <b>Grok Monitor</b> [{ts}]\n<b>{event}</b>\n{details}"

        # Always DM the owner
        if self.bot:
            try:
                await self.bot.send_message(self.owner_id, text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Grok monitor DM failed: {e}")

        # Optional: call xAI / Grok API if GROK_API_KEY is set
        settings = get_settings()
        api_key = getattr(settings, "grok_api_key", None)
        if api_key:
            await self._ask_ai(event, details)

    async def _ask_ai(self, event: str, details: str) -> None:
        """Ask Grok if key exists, otherwise fall back to Gemini."""
        settings = get_settings()
        grok_key = getattr(settings, "grok_api_key", None)
        gemini_key = getattr(settings, "gemini_api_key", None)

        rules_text = "\n".join(f"- {r}" for r in self.rules) or "No custom rules."
        prompt = (
            "You are the monitoring AI for a private Telegram bot that automatically buys Telegram accounts from LZT Market (lzt.market) and resells them at a profit.\n\n"
            "BOT PURPOSE:\n"
            "- Poll several receiver bots every few minutes for country capacity and sell prices.\n"
            "- Calculate a safe buy price (normally 50% of the sell price).\n"
            "- Search LZT Market for matching accounts (filters: session age, no password, mail login, no spam block).\n"
            "- Before buying, re-check that the country is still available on the receiver bot.\n"
            "- Buy the account with real money via LZT API, then download the credentials (login:pass:token) and send them to a private channel.\n"
            "- Respect daily budget, quantity limits, and owner-set pauses.\n"
            "- Only the bot owner can control it.\n\n"
            "YOUR JOB AS MONITOR:\n"
            "- Explain what just happened in simple terms.\n"
            "- Judge the risk (Low / Medium / High) especially around money, capacity, or token issues.\n"
            "- Suggest the safest next action (or say 'no action needed').\n"
            "- Follow any custom owner rules listed below.\n"
            "- Never suggest actions that spend money without clear owner approval.\n"
            "- Be short and direct.\n\n"
            f"Custom owner rules:\n{rules_text}\n\n"
            f"Event: {event}\nDetails: {details}\n\n"
            "Reply format:\n"
            "1) What happened\n"
            "2) Risk level\n"
            "3) Recommended action"
        )

        reply = None
        source = None

        # 1. Try Grok
        if grok_key:
            reply = await self._call_grok(prompt, grok_key)
            source = "Grok"

        # 2. Fall back to Gemini
        if not reply and gemini_key:
            reply = await self._call_gemini(prompt, gemini_key)
            source = "Gemini"

        if reply and self.bot:
            try:
                await self.bot.send_message(
                    self.owner_id,
                    f"🤖 <b>{source} says:</b>\n{reply}",
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"Failed to send AI reply: {e}")
        elif not reply:
            logger.debug("No AI key configured or both calls failed")

    async def _call_grok(self, prompt: str, api_key: str) -> str | None:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.x.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "grok-3",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 300,
                    },
                )
                data = resp.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content")
        except Exception as e:
            logger.warning(f"Grok API failed: {e}")
            return None

    async def _call_gemini(self, prompt: str, api_key: str) -> str | None:
        try:
            import httpx
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    url,
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                )
                data = resp.json()
                return (
                    data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text")
                )
        except Exception as e:
            logger.warning(f"Gemini API failed: {e}")
            return None


# global instance (set in main.py)
grok: GrokMonitor | None = None
