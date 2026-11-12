from __future__ import annotations

import asyncio
from pathlib import Path
from loguru import logger
from aiogram.types import FSInputFile

from config import get_settings, SESSIONS_DIR
from database import (
    get_active_buy_targets,
    get_daily_spend,
    add_daily_spend,
    record_purchase,
    get_setting,
)
from lzt import lzt_service
from safety import notifier, safety


class BuyerLoop:
    def __init__(self, bot=None, channel_id: int | None = None, poller=None):
        self.bot = bot  # aiogram Bot instance for channel posts
        self.channel_id = channel_id
        self.poller = poller  # CapacityPoller for live availability checks
        self._running = False
        self._task: asyncio.Task | None = None
        self._pause = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Buyer loop started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Buyer loop stopped")

    def pause(self) -> None:
        self._pause = True
        logger.info("Buyer paused")

    def resume(self) -> None:
        self._pause = False
        logger.info("Buyer resumed")

    @property
    def is_paused(self) -> bool:
        return self._pause

    async def _loop(self) -> None:
        s = get_settings()
        while self._running:
            if not self._pause:
                try:
                    await self._scan_once()
                except Exception as e:
                    logger.exception(f"Buyer scan error: {e}")
                    if notifier:
                        await notifier.alert_owner(f"Buyer loop error: {e}", critical=True)
            await asyncio.sleep(s.lzt_scan_seconds)

    async def _scan_once(self) -> None:
        s = get_settings()
        daily = await get_daily_spend()
        if daily >= s.daily_budget_usd:
            logger.debug("Daily budget reached – skip scan")
            from grok_monitor import grok
            if grok:
                await grok.report("Daily budget reached", f"Spent ${daily:.2f} / ${s.daily_budget_usd:.2f}")
            return

        if notifier and daily >= s.daily_budget_usd * 0.8:
            await notifier.budget_warning(daily, s.daily_budget_usd)

        await safety.clear_expired()
        targets = await get_active_buy_targets()
        if not targets:
            return

        for country in targets:
            if await safety.is_paused(country.iso):
                continue
            if country.quantity_limit and country.bought_count >= country.quantity_limit:
                continue
            if country.max_buy <= 0:
                continue

            # Live capacity re-check before buying
            if self.poller and country.receiver_bot:
                available = await self.poller.is_country_available(
                    country.receiver_bot, country.phone_code
                )
                if not available:
                    logger.info(f"{country.name} ({country.phone_code}) no longer available on @{country.receiver_bot} – skip")
                    continue

            filters = country.filters_json or {}
            session_days = int(filters.get("session_days", s.default_session_days))
            password = filters.get("password", s.default_password)
            login_mail = filters.get("login_mail", s.default_login_mail)
            spam = filters.get("spam", s.default_spam_block)

            try:
                items = await lzt_service.search_telegram(
                    pmax=country.max_buy,
                    country_name=country.name,
                    session_days=session_days,
                    password=password,
                    login_mail=login_mail,
                    spam=spam,
                )
            except Exception as e:
                logger.exception(f"LZT search failed for {country.name}: {e}")
                if notifier:
                    await notifier.alert_owner(f"LZT search error {country.name}: {e}")
                continue

            for item in items:
                item_id = item.get("item_id") or item.get("id")
                price = float(item.get("price") or item.get("price_rub") or 0)
                if not item_id or price <= 0 or price > country.max_buy:
                    continue

                daily = await get_daily_spend()
                if daily + price > s.daily_budget_usd:
                    logger.info("Would exceed daily budget – stop this cycle")
                    return

                logger.info(
                    f"Buying item {item_id} {country.name} @ ${price:.2f} "
                    f"(max ${country.max_buy:.2f})"
                )
                try:
                    result = await lzt_service.fast_buy(int(item_id), price)
                except Exception as e:
                    logger.exception(f"fast_buy exception: {e}")
                    if notifier:
                        await notifier.buy_failed(int(item_id), country.name, price, str(e))
                    from grok_monitor import grok
                    if grok:
                        await grok.report("Buy failed", f"{country.name} item {item_id} @ ${price:.2f}: {e}", critical=True)
                    continue

                if result.get("error"):
                    logger.warning(f"Buy failed: {result}")
                    if notifier:
                        await notifier.buy_failed(
                            int(item_id), country.name, price, str(result.get("error"))
                        )
                    continue

                phone = (
                    item.get("telegram_phone")
                    or item.get("phone")
                    or item.get("login")
                    or "unknown"
                )
                await add_daily_spend(price)
                purchase = await record_purchase(
                    item_id=int(item_id),
                    phone=str(phone),
                    country_iso=country.iso,
                    country_name=country.name,
                    buy_price=price,
                    sell_price=country.sell_price,
                    receiver_bot=country.receiver_bot,
                    raw_meta=item,
                )

                # notify + download account data from LZT and send to channel
                text = (
                    f"{country.name} ({country.iso}) — {phone} "
                    f"bought for ${price:.2f} "
                    f"(Sells for ${country.sell_price:.2f} on @{country.receiver_bot})"
                )

                # Download credentials (login:pass:token) from LZT after purchase
                account_data = await lzt_service.download_account(int(item_id), fmt="login:pass:token")
                cred_path = SESSIONS_DIR / f"{phone.replace('+', '').replace(' ', '')}.txt"

                if self.bot and self.channel_id:
                    try:
                        await self.bot.send_message(self.channel_id, text)
                        if account_data:
                            cred_path.write_text(account_data, encoding="utf-8")
                            await self.bot.send_document(
                                self.channel_id,
                                FSInputFile(cred_path),
                                caption=f"Account for {phone}\nFormat: login:pass:token",
                            )
                            # Try automatic conversion to .session
                            session_file = await convert_token_to_session(phone, account_data)
                            if session_file and session_file.exists():
                                await self.bot.send_document(
                                    self.channel_id,
                                    FSInputFile(session_file),
                                    caption=f"Telethon session for {phone}",
                                )
                        else:
                            # fallback to local .session if it exists
                            session_file = SESSIONS_DIR / f"{phone.replace('+', '').replace(' ', '')}.session"
                            if session_file.exists():
                                await self.bot.send_document(
                                    self.channel_id,
                                    FSInputFile(session_file),
                                    caption=f"Session for {phone}",
                                )
                            else:
                                await self.bot.send_message(
                                    self.channel_id,
                                    f"⚠️ Could not download account data for {phone}. Check LZT manually.",
                                )
                    except Exception as e:
                        logger.warning(f"Channel notify/send failed: {e}")
                        if notifier:
                            await notifier.alert_owner(f"Failed to post session to channel: {e}")

                logger.success(text)
                break  # one buy per country per cycle


async def convert_token_to_session(phone: str, token_line: str) -> Path | None:
    """
    Try to turn an LZT login:pass:token line into a Telethon .session file.
    token_line example: +1234567890:password:auth_token_here
    """
    try:
        parts = token_line.strip().split(":")
        if len(parts) < 3:
            return None
        phone_num = parts[0]
        # auth token is usually the last part
        auth_token = parts[-1]

        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from config import get_settings

        s = get_settings()
        # Use StringSession with the token if possible
        client = TelegramClient(StringSession(), s.api_id, s.api_hash)
        await client.connect()
        # Many LZT tokens are already Telethon-compatible string sessions
        try:
            # If the token is a valid StringSession, this works
            await client.start(phone=phone_num)
        except Exception:
            pass
        session_path = SESSIONS_DIR / f"{phone_num.replace('+', '')}.session"
        # Save whatever session we have
        if client.session:
            client.session.save()
            # Copy to file if needed
            if hasattr(client.session, "filename"):
                return Path(client.session.filename)
        await client.disconnect()
        return session_path if session_path.exists() else None
    except Exception as e:
        logger.warning(f"Session conversion failed for {phone}: {e}")
        return None
