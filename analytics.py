from __future__ import annotations

from datetime import datetime, timedelta, timezone, date
from sqlalchemy import select, func, desc
from loguru import logger

from database import SessionLocal
from models import Purchase, Country, DailySpend, PriceHistory


async def get_spend_stats() -> dict:
    today = date.today()
    week_ago = today - timedelta(days=7)
    async with SessionLocal() as session:
        # today
        daily = await session.get(DailySpend, today)
        today_spend = daily.amount if daily else 0.0

        # week
        stmt = select(func.sum(DailySpend.amount)).where(DailySpend.day >= week_ago)
        week_res = await session.execute(stmt)
        week_spend = week_res.scalar() or 0.0

        # all time
        stmt = select(func.sum(Purchase.buy_price))
        all_res = await session.execute(stmt)
        all_spend = all_res.scalar() or 0.0

        # success rate (bought vs total attempts – approximate by status)
        total = await session.scalar(select(func.count(Purchase.id))) or 0
        bought = await session.scalar(
            select(func.count(Purchase.id)).where(Purchase.status == "bought")
        ) or 0
        success = (bought / total * 100) if total else 0.0

        # avg prices
        avg_buy = await session.scalar(select(func.avg(Purchase.buy_price))) or 0.0
        avg_sell = await session.scalar(select(func.avg(Purchase.sell_price))) or 0.0

        # best / worst country by profit (sell - buy)
        stmt = (
            select(
                Purchase.country_iso,
                func.avg(Purchase.sell_price - Purchase.buy_price).label("profit"),
                func.count(Purchase.id).label("cnt"),
            )
            .group_by(Purchase.country_iso)
            .order_by(desc("profit"))
            .limit(5)
        )
        best = (await session.execute(stmt)).all()

        stmt_worst = (
            select(
                Purchase.country_iso,
                func.avg(Purchase.sell_price - Purchase.buy_price).label("profit"),
                func.count(Purchase.id).label("cnt"),
            )
            .group_by(Purchase.country_iso)
            .order_by("profit")
            .limit(5)
        )
        worst = (await session.execute(stmt_worst)).all()

    return {
        "today": today_spend,
        "week": week_spend,
        "all_time": all_spend,
        "success_rate": success,
        "avg_buy": avg_buy,
        "avg_sell": avg_sell,
        "best": best,
        "worst": worst,
        "total_purchases": total,
    }


async def record_price(iso: str, receiver: str, price: float) -> None:
    async with SessionLocal() as session:
        session.add(PriceHistory(country_iso=iso, receiver_bot=receiver, sell_price=price))
        await session.commit()


async def recent_price_change(iso: str, receiver: str, hours: int = 24) -> float | None:
    """Return % change vs average of last N hours, or None."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    async with SessionLocal() as session:
        stmt = select(func.avg(PriceHistory.sell_price)).where(
            PriceHistory.country_iso == iso,
            PriceHistory.receiver_bot == receiver,
            PriceHistory.recorded_at >= since,
        )
        avg = await session.scalar(stmt)
        if not avg:
            return None
        # latest
        stmt = (
            select(PriceHistory.sell_price)
            .where(
                PriceHistory.country_iso == iso,
                PriceHistory.receiver_bot == receiver,
            )
            .order_by(desc(PriceHistory.recorded_at))
            .limit(1)
        )
        latest = await session.scalar(stmt)
        if not latest or avg == 0:
            return None
        return (latest - avg) / avg * 100
