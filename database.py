from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, update, func
from datetime import date, datetime, timezone

from config import DB_PATH, DATA_DIR, get_settings
from models import Base, Worker, Country, Purchase, Setting, DailySpend


engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_setting(key: str, default: str | None = None) -> str | None:
    async with SessionLocal() as session:
        row = await session.get(Setting, key)
        return row.value if row else default


async def set_setting(key: str, value: str) -> None:
    async with SessionLocal() as session:
        row = await session.get(Setting, key)
        if row:
            row.value = value
        else:
            session.add(Setting(key=key, value=value))
        await session.commit()


async def add_daily_spend(amount: float) -> float:
    today = date.today()
    async with SessionLocal() as session:
        row = await session.get(DailySpend, today)
        if not row:
            row = DailySpend(day=today, amount=0.0)
            session.add(row)
        row.amount += amount
        await session.commit()
        return row.amount


async def get_daily_spend() -> float:
    today = date.today()
    async with SessionLocal() as session:
        row = await session.get(DailySpend, today)
        return row.amount if row else 0.0


async def upsert_country(
    iso: str,
    name: str,
    phone_code: str,
    sell_price: float,
    receiver_bot: str,
    multiplier: float,
    status: str = "active",
) -> Country:
    max_buy = round(sell_price * multiplier, 4)
    async with SessionLocal() as session:
        stmt = select(Country).where(
            Country.phone_code == phone_code,
            Country.receiver_bot == receiver_bot,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            row.sell_price = sell_price
            row.max_buy = max_buy
            row.name = name
            row.iso = iso
            if status == "active" and row.status == "full":
                row.status = "active"
            elif status == "full":
                row.status = "full"
            row.updated_at = datetime.now(timezone.utc)
        else:
            row = Country(
                iso=iso,
                name=name,
                phone_code=phone_code,
                sell_price=sell_price,
                max_buy=max_buy,
                receiver_bot=receiver_bot,
                status=status,
                filters_json={},
            )
            session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def mark_missing_as_full(receiver_bot: str, seen_codes: set[str]) -> list[str]:
    """Any previously active country for this receiver that is not in seen_codes → full."""
    changed: list[str] = []
    async with SessionLocal() as session:
        stmt = select(Country).where(
            Country.receiver_bot == receiver_bot,
            Country.status == "active",
        )
        result = await session.execute(stmt)
        for row in result.scalars():
            if row.phone_code not in seen_codes:
                row.status = "full"
                changed.append(f"{row.name} ({row.phone_code})")
        await session.commit()
    return changed


async def get_active_buy_targets() -> list[Country]:
    """Return active countries, keeping only the receiver with the highest sell price per phone_code."""
    async with SessionLocal() as session:
        stmt = select(Country).where(Country.status == "active")
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

    # Multi-receiver choice: best sell price wins
    best: dict[str, Country] = {}
    for row in rows:
        key = row.phone_code
        if key not in best or (row.sell_price or 0) > (best[key].sell_price or 0):
            best[key] = row
    return list(best.values())


async def record_purchase(
    item_id: int,
    phone: str,
    country_iso: str,
    country_name: str,
    buy_price: float,
    sell_price: float,
    receiver_bot: str,
    session_path: str | None = None,
    raw_meta: dict | None = None,
) -> Purchase:
    async with SessionLocal() as session:
        p = Purchase(
            item_id=item_id,
            phone=phone,
            country_iso=country_iso,
            country_name=country_name,
            buy_price=buy_price,
            sell_price=sell_price,
            receiver_bot=receiver_bot,
            session_path=session_path,
            raw_meta=raw_meta,
        )
        session.add(p)
        # bump bought_count
        stmt = select(Country).where(Country.iso == country_iso, Country.status == "active")
        res = await session.execute(stmt)
        for c in res.scalars():
            c.bought_count += 1
        await session.commit()
        await session.refresh(p)
        return p
