from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from loguru import logger
from aiogram import Bot

from config import get_settings
from database import SessionLocal, get_setting
from models import PriceHistory, CountryPause
from sqlalchemy import select


class Notifier:
    def __init__(self, bot: Bot | None = None):
        self.bot = bot
        self.owner_id = get_settings().owner_id
        self.channel_id = get_settings().ids_channel_id

    async def alert_owner(self, text: str, critical: bool = False) -> None:
        if not self.bot:
            logger.warning(f"Notifier no bot: {text}")
            return
        try:
            prefix = "🚨 CRITICAL " if critical else "⚠️ "
            await self.bot.send_message(self.owner_id, f"{prefix}{text}")
        except Exception as e:
            logger.error(f"Failed to alert owner: {e}")

    async def alert_channel(self, text: str) -> None:
        if not self.bot or not self.channel_id:
            return
        try:
            await self.bot.send_message(self.channel_id, text)
        except Exception as e:
            logger.warning(f"Channel alert failed: {e}")

    async def budget_warning(self, spent: float, limit: float) -> None:
        pct = (spent / limit * 100) if limit else 0
        if pct >= 80:
            await self.alert_owner(
                f"Daily budget {pct:.0f}% used (${spent:.2f}/${limit:.2f})"
            )

    async def country_status_change(self, name: str, iso: str, old: str, new: str, bot: str) -> None:
        await self.alert_owner(
            f"Country {name} ({iso}) @{bot}: {old} → {new}"
        )

    async def buy_failed(self, item_id: int, country: str, price: float, reason: str) -> None:
        await self.alert_owner(
            f"Buy FAILED item {item_id} {country} @ ${price:.2f}\nReason: {reason}",
            critical=True,
        )

    async def daily_summary(self) -> None:
        # placeholder – filled by analytics later
        await self.alert_owner("📊 Daily summary ready. Open Analytics in ")


class SafetyManager:
    """Country pauses and emergency stop helpers."""

    @staticmethod
    async def pause_country(iso: str, minutes: int, reason: str = "") -> None:
        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        async with SessionLocal() as session:
            result = await session.execute(select(CountryPause).where(CountryPause.country_iso == iso)); row = result.scalar_one_or_none()
            if row:
                row.pause_until = until
                row.reason = reason
            else:
                session.add(CountryPause(country_iso=iso, pause_until=until, reason=reason))
            await session.commit()
        logger.info(f"Paused {iso} until {until} ({reason})")

    @staticmethod
    async def is_paused(iso: str) -> bool:
        async with SessionLocal() as session:
            result = await session.execute(select(CountryPause).where(CountryPause.country_iso == iso)); row = result.scalar_one_or_none()
            if not row:
                return False
            return row.pause_until > datetime.now(timezone.utc)

    @staticmethod
    async def clear_expired() -> None:
        now = datetime.now(timezone.utc)
        async with SessionLocal() as session:
            stmt = select(CountryPause).where(CountryPause.pause_until <= now)
            res = await session.execute(stmt)
            for r in res.scalars():
                await session.delete(r)
            await session.commit()


notifier: Notifier | None = None
safety = SafetyManager()


# Global notifier instance – reassigned in main.py
notifier = None
