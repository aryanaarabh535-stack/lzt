from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from datetime import datetime, time, timezone

# ensure project root on path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loguru import logger
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import get_settings, SESSIONS_DIR, DATA_DIR
from database import init_db
from middleware import OwnerOnlyMiddleware
from handlers_owner import router as owner_router
from telethon_worker import worker_manager
from capacity_poller import CapacityPoller
from buyer import BuyerLoop
from lzt import lzt_service
from safety import Notifier, notifier as _notifier_global
from grok_monitor import GrokMonitor, grok as _grok
from analytics import get_spend_stats


async def daily_summary_task(bot: Bot) -> None:
    """Simple daily summary at 00:05 UTC."""
    while True:
        now = datetime.now(timezone.utc)
        target = datetime.combine(now.date(), time(0, 5), tzinfo=timezone.utc)
        if now >= target:
            target = target.replace(day=target.day + 1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            stats = await get_spend_stats()
            text = (
                f"📊 Daily Summary\n"
                f"Today: ${stats['today']:.2f}\n"
                f"Week: ${stats['week']:.2f}\n"
                f"All-time: ${stats['all_time']:.2f}\n"
                f"Success: {stats['success_rate']:.1f}% ({stats['total_purchases']} buys)\n"
                f"Avg buy ${stats['avg_buy']:.2f} / sell ${stats['avg_sell']:.2f}"
            )
            await bot.send_message(get_settings().owner_id, text)
        except Exception as e:
            logger.exception(f"Daily summary failed: {e}")


async def main() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)
    logger.add(DATA_DIR / "log", rotation="10 MB", level="DEBUG")

    await init_db()

    bot = Bot(token=settings.bot_token)
    # global notifier
    import safety as safety_mod
    safety_mod.notifier = Notifier(bot)

    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(OwnerOnlyMiddleware())
    dp.callback_query.middleware(OwnerOnlyMiddleware())
    dp.include_router(owner_router)

    primary = await worker_manager.get_primary_client()
    poller = CapacityPoller(telethon_client=primary)
    buyer = BuyerLoop(bot=bot, channel_id=settings.ids_channel_id, poller=poller)

    dp.workflow_data.update(buyer=buyer, poller=poller)


    # Grok AI monitor
    global_grok = GrokMonitor(bot=bot)
    await global_grok.load_rules()
    import grok_monitor
    grok_monitor.grok = global_grok
    logger.info(f"Grok monitor started with {len(global_grok.rules)} rules")

    await poller.start()
    await buyer.start()
    asyncio.create_task(daily_summary_task(bot))

    logger.info("Bot starting (owner-only)")
    try:
        await dp.start_polling(bot)
    finally:
        await poller.stop()
        await buyer.stop()
        await worker_manager.disconnect_all()
        lzt_service.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass
    asyncio.run(main())
