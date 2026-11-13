from __future__ import annotations

import asyncio
from loguru import logger
from telethon import TelegramClient
from telethon.tl.custom.message import Message

from config import get_settings, SESSIONS_DIR
from parsers import parse_for_bot, CapacityHit
from database import upsert_country, mark_missing_as_full
from analytics import record_price
from safety import notifier
from models import Country

# Capacity bots the owner wants polled
CAPACITY_BOTS = [
    "CM_Receiver6_Bot",
    "Crazy_TimeAcc2_robot",
    "tg_get2_bot",
    "sttar1_bot",
    "TBUNLIMITED2_BOT",
    "TGLionAPI_bot",
]

# Commands that trigger capacity reply
CAP_COMMANDS = {
    "CM_Receiver6_Bot": "/cap",
    "Crazy_TimeAcc2_robot": "/cap",
    "tg_get2_bot": "/cap",
    "sttar1_bot": "/cap",
    "TBUNLIMITED2_BOT": "/capacity",
    "TGLionAPI_bot": "/start Prices",  # exact command that returns the price list
}


class CapacityPoller:
    def __init__(self, telethon_client: TelegramClient | None = None):
        self.client = telethon_client
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Capacity poller started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Capacity poller stopped")

    async def _loop(self) -> None:
        s = get_settings()
        while self._running:
            try:
                await self.poll_all()
            except Exception as e:
                logger.exception(f"Capacity poll cycle failed: {e}")
            await asyncio.sleep(s.capacity_poll_seconds)

    async def poll_all(self) -> dict[str, list[CapacityHit]]:
        results: dict[str, list[CapacityHit]] = {}
        if not self.client:
            logger.warning("No Telethon client for capacity poll – skipping")
            return results

        multiplier = get_settings().buy_multiplier

        for bot in CAPACITY_BOTS:
            try:
                hits = await self.poll_one(bot)
                results[bot] = hits
                seen_codes = set()
                for h in hits:
                    seen_codes.add(h.phone_code)
                    # record price history
                    await record_price(h.iso, bot, h.price)
                    await upsert_country(
                        iso=h.iso,
                        name=h.name,
                        phone_code=h.phone_code,
                        sell_price=h.price,
                        receiver_bot=bot,
                        multiplier=multiplier,
                        status="active",
                    )
                if seen_codes:  # only mark full if we actually received some countries
                    full_list = await mark_missing_as_full(bot, seen_codes)
                else:
                    full_list = []
                    logger.warning(f"@{bot} returned no countries – not marking as full")
                if full_list and notifier:
                    for name in full_list:
                        await notifier.country_status_change(name, "", "active", "full", bot)
                    logger.info(f"[{bot}] marked FULL: {full_list}")
            except Exception as e:
                logger.warning(f"Poll {bot} failed: {e}")
        return results

    async def poll_one(self, bot_username: str) -> list[CapacityHit]:
        cmd = CAP_COMMANDS.get(bot_username, "/cap")
        entity = await self.client.get_entity(bot_username)

        # TGLion: send exact "/start Prices"
        if bot_username == "TGLionAPI_bot":
            await self.client.send_message(entity, "/start Prices")
            await asyncio.sleep(2.5)
        else:
            await self.client.send_message(entity, cmd)
            await asyncio.sleep(2.5)

        # Collect reply text
        messages: list[Message] = []
        async for msg in self.client.iter_messages(entity, limit=8):
            if msg.out:
                continue
            messages.append(msg)
            if len(messages) >= 3:
                break

        if not messages:
            logger.warning(f"No reply from @{bot_username}")
            return []

        text = "\n".join(m.message or "" for m in messages)
        hits = parse_for_bot(bot_username, text)
        logger.info(f"@{bot_username}: parsed {len(hits)} countries")
        return hits

    async def is_country_available(self, bot_username: str, phone_code: str) -> bool:
        """Re-check one bot to see if a specific country is still available (not Full)."""
        try:
            hits = await self.poll_one(bot_username)
            for h in hits:
                if h.phone_code == phone_code:
                    return True
            return False
        except Exception as e:
            logger.warning(f"Availability check failed for {bot_username} {phone_code}: {e}")
            return False  # be conservative
