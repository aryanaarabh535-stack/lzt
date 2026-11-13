from __future__ import annotations

from datetime import datetime, date
from typing import Optional, Any

from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, Date, Text, JSON, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    session_path: Mapped[str] = mapped_column(String(512))
    has_2fa: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="online")  # online | limited | banned | offline
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Country(Base):
    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    iso: Mapped[str] = mapped_column(String(8), index=True)
    name: Mapped[str] = mapped_column(String(64))
    phone_code: Mapped[str] = mapped_column(String(16), index=True)  # e.g. "+964"
    sell_price: Mapped[float] = mapped_column(Float, default=0.0)
    max_buy: Mapped[float] = mapped_column(Float, default=0.0)
    receiver_bot: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | full | stopped
    quantity_limit: Mapped[int] = mapped_column(Integer, default=0)  # 0 = unlimited
    bought_count: Mapped[int] = mapped_column(Integer, default=0)
    filters_json: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("phone_code", "receiver_bot", name="uq_code_receiver"),)


class Purchase(Base):
    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    phone: Mapped[str] = mapped_column(String(32))
    country_iso: Mapped[str] = mapped_column(String(8))
    country_name: Mapped[str] = mapped_column(String(64))
    buy_price: Mapped[float] = mapped_column(Float)
    sell_price: Mapped[float] = mapped_column(Float)
    receiver_bot: Mapped[str] = mapped_column(String(64))
    session_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="bought")  # bought | exported | sold | error
    bought_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    raw_meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class DailySpend(Base):
    __tablename__ = "daily_spend"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_iso: Mapped[str] = mapped_column(String(8), index=True)
    receiver_bot: Mapped[str] = mapped_column(String(64))
    sell_price: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CountryPause(Base):
    __tablename__ = "country_pauses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_iso: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    pause_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(128), default="")
