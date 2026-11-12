from __future__ import annotations

import asyncio
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from loguru import logger

from config import get_settings
from keyboards import main_dashboard, confirm_kb, back_kb, matrix_nav
from database import (
    get_daily_spend,
    get_active_buy_targets,
    SessionLocal,
    set_setting,
    get_setting,
)
from models import Country, Purchase, Worker
from telethon_worker import worker_manager
from analytics import get_spend_stats
from safety import safety
from sqlalchemy import select, desc
from pathlib import Path
from datetime import datetime, timedelta, timezone
import zipfile
from io import BytesIO
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, BufferedInputFile

router = Router(name="owner")


class AddWorker(StatesGroup):
    phone = State()
    code = State()
    password = State()

class PauseCountry(StatesGroup):
    iso_minutes = State()


def status_text(
    auto_buy: bool,
    mode_live: bool,
    daily: float,
    limit: float,
    active_countries: int,
    receivers: int,
) -> str:
    return (
        f"<b>AUTONOMOUS ACCOUNT TRADING WORKER</b>\n\n"
        f"• Status: {'🟢 ACTIVE' if auto_buy else '🔴 PAUSED'} | "
        f"Mode: {'🟢 LIVE' if mode_live else '🟡 PAPER'}\n"
        f"• Auto-Buy: {'ENABLED 🟢' if auto_buy else 'DISABLED 🔴'}\n"
        f"• Daily Spend: ${daily:.2f} / ${limit:.2f}\n"
        f"• Active Countries: {active_countries}\n"
        f"• Receivers loaded: {receivers}\n\n"
        f"Select an operational module below:"
    )


@router.message(CommandStart())
@router.message(Command("menu"))
@router.message(Command("trading"))
async def cmd_start(message: Message, state: FSMContext, buyer=None, poller=None):
    await state.clear()
    s = get_settings()
    daily = await get_daily_spend()
    targets = await get_active_buy_targets()
    auto_buy = (await get_setting("auto_buy", "1")) == "1"
    mode_live = (await get_setting("mode_live", "1")) == "1"
    text = status_text(auto_buy, mode_live, daily, s.daily_budget_usd, len(targets), 6)
    await message.answer(
        text,
        reply_markup=main_dashboard(
            auto_buy=auto_buy,
            mode_live=mode_live,
            daily_spend=daily,
            daily_limit=s.daily_budget_usd,
            receivers=6,
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:main")
async def cb_main(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    s = get_settings()
    daily = await get_daily_spend()
    targets = await get_active_buy_targets()
    auto_buy = (await get_setting("auto_buy", "1")) == "1"
    mode_live = (await get_setting("mode_live", "1")) == "1"
    text = status_text(auto_buy, mode_live, daily, s.daily_budget_usd, len(targets), 6)
    await cq.message.edit_text(
        text,
        reply_markup=main_dashboard(
            auto_buy=auto_buy,
            mode_live=mode_live,
            daily_spend=daily,
            daily_limit=s.daily_budget_usd,
            receivers=6,
        ),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data == "toggle:autobuy")
async def toggle_autobuy(cq: CallbackQuery, buyer=None):
    cur = await get_setting("auto_buy", "1")
    new = "0" if cur == "1" else "1"
    await set_setting("auto_buy", new)
    if buyer:
        if new == "1":
            buyer.resume()
        else:
            buyer.pause()
    await cq.answer(f"Auto-Buy {'ENABLED' if new == '1' else 'DISABLED'}")
    s = get_settings()
    daily = await get_daily_spend()
    targets = await get_active_buy_targets()
    auto_buy = new == "1"
    mode_live = (await get_setting("mode_live", "1")) == "1"
    text = status_text(auto_buy, mode_live, daily, s.daily_budget_usd, len(targets), 6)
    await cq.message.edit_text(
        text,
        reply_markup=main_dashboard(
            auto_buy=auto_buy,
            mode_live=mode_live,
            daily_spend=daily,
            daily_limit=s.daily_budget_usd,
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "action:stop_all")
async def stop_all(cq: CallbackQuery, buyer=None):
    await cq.message.edit_text(
        "🛑 Confirm emergency STOP of all buying?",
        reply_markup=confirm_kb("stop_all"),
    )
    await cq.answer()


@router.callback_query(F.data == "confirm:stop_all")
async def confirm_stop(cq: CallbackQuery, buyer=None):
    await set_setting("auto_buy", "0")
    if buyer:
        buyer.pause()
    await cq.answer("All trading stopped")
    await cb_main(cq, None)  # type: ignore


@router.callback_query(F.data == "confirm:cancel")
async def confirm_cancel(cq: CallbackQuery):
    await cq.answer("Cancelled")
    await cb_main(cq, None)  # type: ignore


@router.callback_query(F.data == "action:refresh")
async def refresh_rates(cq: CallbackQuery, poller=None):
    await cq.answer("Refreshing capacity…")
    if poller:
        try:
            results = await poller.poll_all()
            total = sum(len(v) for v in results.values())
            await cq.message.answer(f"✅ Refreshed. {total} country prices updated.")
        except Exception as e:
            await cq.message.answer(f"Refresh error: {e}")
    else:
        await cq.message.answer("Poller not attached yet.")


@router.callback_query(F.data == "menu:matrix")
@router.callback_query(F.data.startswith("matrix:page:"))
async def show_matrix(cq: CallbackQuery):
    page = 1
    if cq.data and cq.data.startswith("matrix:page:"):
        page = int(cq.data.split(":")[-1])
    per_page = 12
    async with SessionLocal() as session:
        result = await session.execute(select(Country).order_by(Country.sell_price.desc()))
        rows = list(result.scalars().all())
    total = len(rows) or 1
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    chunk = rows[(page - 1) * per_page : page * per_page]
    lines = ["<b>MARKET TRADING MATRIX & BUY CEILINGS</b>\n"]
    for c in chunk:
        flag = {"active": "🟢", "full": "🔴", "stopped": "⚫"}.get(c.status, "⚪")
        lines.append(
            f"{flag} <code>{c.phone_code}</code> {c.name}\n"
            f"   Sell ${c.sell_price:.2f} → MaxBuy ${c.max_buy:.2f} | @{c.receiver_bot} [{c.status}]"
        )
    if not chunk:
        lines.append("No countries yet. Run Refresh Rates first.")
    await cq.message.edit_text(
        "\n".join(lines),
        reply_markup=matrix_nav(page, total_pages),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data == "menu:ledger")
async def show_ledger(cq: CallbackQuery):
    async with SessionLocal() as session:
        result = await session.execute(
            select(Purchase).order_by(desc(Purchase.bought_at)).limit(20)
        )
        rows = list(result.scalars().all())
    if not rows:
        text = "Trade ledger is empty."
    else:
        lines = ["<b>TRADE LEDGER (last 20)</b>\n"]
        for p in rows:
            lines.append(
                f"• {p.country_name} {p.phone} — ${p.buy_price:.2f} "
                f"(sell ${p.sell_price:.2f}) <i>{p.bought_at:%Y-%m-%d %H:%M}</i>"
            )
        text = "\n".join(lines)
    await cq.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")
    await cq.answer()


@router.callback_query(F.data == "menu:budget")
async def show_budget(cq: CallbackQuery):
    s = get_settings()
    daily = await get_daily_spend()
    text = (
        f"<b>BUDGET & LIMITS</b>\n\n"
        f"Daily spend: ${daily:.2f} / ${s.daily_budget_usd:.2f}\n"
        f"Total budget: ${s.total_budget_usd:.2f}\n"
        f"Buy multiplier: {s.buy_multiplier}× (max buy = sell × multiplier)\n\n"
        f"Change values in .env and restart, or ask for runtime setters."
    )
    await cq.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")
    await cq.answer()


@router.callback_query(F.data == "menu:add_worker")
async def add_worker_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(AddWorker.phone)
    await cq.message.edit_text(
        "Send the phone number of the worker account (international format, e.g. +79161234567):",
        reply_markup=back_kb(),
    )
    await cq.answer()


@router.message(AddWorker.phone)
async def add_worker_phone(message: Message, state: FSMContext):
    phone = (message.text or "").strip().replace(" ", "")
    if not phone.startswith("+"):
        await message.answer("Phone must start with +")
        return
    await state.update_data(phone=phone)
    try:
        await worker_manager.start_login(phone)
        await state.set_state(AddWorker.code)
        await message.answer("Code sent. Paste the login code you received:")
    except Exception as e:
        await message.answer(f"Failed to request code: {e}")
        await state.clear()


@router.message(AddWorker.code)
async def add_worker_code(message: Message, state: FSMContext):
    data = await state.get_data()
    phone = data["phone"]
    code = (message.text or "").strip()
    ok, msg = await worker_manager.submit_code(phone, code)
    if msg == "2FA_REQUIRED":
        await state.set_state(AddWorker.password)
        await message.answer("2FA enabled. Send the cloud password:")
        return
    if ok:
        await message.answer(f"✅ Worker {phone} logged in and saved.")
        await state.clear()
    else:
        await message.answer(f"Login failed: {msg}")
        await state.clear()


@router.message(AddWorker.password)
async def add_worker_2fa(message: Message, state: FSMContext):
    data = await state.get_data()
    phone = data["phone"]
    password = (message.text or "").strip()
    ok, msg = await worker_manager.submit_2fa(phone, password)
    if ok:
        await message.answer(f"✅ Worker {phone} logged in (2FA).")
    else:
        await message.answer(f"2FA failed: {msg}")
    await state.clear()


@router.callback_query(F.data == "menu:analytics")
async def show_analytics(cq: CallbackQuery):
    stats = await get_spend_stats()
    lines = [
        "<b>📊 ANALYTICS</b>\n",
        f"Today: ${stats['today']:.2f}",
        f"Last 7 days: ${stats['week']:.2f}",
        f"All-time: ${stats['all_time']:.2f}",
        f"Success rate: {stats['success_rate']:.1f}% ({stats['total_purchases']} purchases)",
        f"Avg buy: ${stats['avg_buy']:.2f} | Avg sell: ${stats['avg_sell']:.2f}",
        "",
        "<b>Best countries (profit)</b>",
    ]
    for iso, profit, cnt in stats["best"]:
        lines.append(f"• {iso}: ${profit:.3f} avg ({cnt})")
    lines.append("\n<b>Worst countries</b>")
    for iso, profit, cnt in stats["worst"]:
        lines.append(f"• {iso}: ${profit:.3f} avg ({cnt})")
    await cq.message.edit_text("\n".join(lines), reply_markup=back_kb(), parse_mode="HTML")
    await cq.answer()


@router.callback_query(F.data == "menu:workers")
async def show_workers(cq: CallbackQuery):
    async with SessionLocal() as session:
        result = await session.execute(select(Worker).order_by(Worker.last_used.desc().nullslast()))
        workers = list(result.scalars().all())
    if not workers:
        text = "No workers registered. Use Add Worker."
    else:
        lines = ["<b>WORKERS</b>\n"]
        for w in workers:
            lines.append(
                f"• {w.phone} [{w.status}] active={w.is_active}\n"
                f"  last: {w.last_used or 'never'}"
            )
        text = "\n".join(lines)
    await cq.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")
    await cq.answer()


@router.callback_query(F.data == "menu:export")
async def export_menu(cq: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Last 1 hour", callback_data="export:hours:1"))
    b.row(InlineKeyboardButton(text="Last 6 hours", callback_data="export:hours:6"))
    b.row(InlineKeyboardButton(text="Last 24 hours", callback_data="export:hours:24"))
    b.row(InlineKeyboardButton(text="All sessions", callback_data="export:hours:0"))
    b.row(InlineKeyboardButton(text="« Back", callback_data="menu:main"))
    await cq.message.edit_text("Export sessions bought in the last:", reply_markup=b.as_markup())
    await cq.answer()


@router.callback_query(F.data.startswith("export:hours:"))
async def do_export(cq: CallbackQuery):
    hours = int(cq.data.split(":")[-1])
    since = datetime.now(timezone.utc) - timedelta(hours=hours) if hours else None
    async with SessionLocal() as session:
        stmt = select(Purchase).order_by(desc(Purchase.bought_at))
        if since:
            stmt = stmt.where(Purchase.bought_at >= since)
        result = await session.execute(stmt)
        purchases = list(result.scalars().all())

    if not purchases:
        await cq.answer("No sessions in that window", show_alert=True)
        return

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in purchases:
            if p.session_path and Path(p.session_path).exists():
                zf.write(p.session_path, arcname=Path(p.session_path).name)
            meta = f"{p.country_name} {p.phone} bought ${p.buy_price:.2f}\n"
            zf.writestr(f"{p.phone}_meta.txt", meta)
    buf.seek(0)
    await cq.message.answer_document(
        BufferedInputFile(buf.read(), filename=f"sessions_{hours or 'all'}h.zip"),
        caption=f"Exported {len(purchases)} purchases",
    )
    await cq.answer()


@router.callback_query(F.data == "menu:pause_country")
async def pause_country_menu(cq: CallbackQuery, state: FSMContext):
    await state.set_state(PauseCountry.iso_minutes)
    await cq.message.edit_text(
        "Send country ISO (e.g. JO) and minutes to pause, separated by space.\nExample: JO 30",
        reply_markup=back_kb(),
    )
    await cq.answer()


@router.message(PauseCountry.iso_minutes)
async def handle_pause_input(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    parts = text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Format: JO 30")
        return
    iso, mins = parts[0].upper(), int(parts[1])
    await safety.pause_country(iso, mins, "manual")
    await message.answer(f"Paused {iso} for {mins} minutes.")
    await state.clear()


@router.callback_query(F.data == "noop")
async def noop(cq: CallbackQuery):
    await cq.answer()


@router.callback_query(F.data.startswith("menu:"))
async def stub_menu(cq: CallbackQuery):
    await cq.answer("Module stub – extend as needed", show_alert=False)
    await cq.message.answer(
        f"Section <code>{cq.data}</code> is wired but left as extension point.",
        parse_mode="HTML",
        reply_markup=back_kb(),
    )



# ── Grok Rules ──────────────────────────────────────────
@router.message(Command("rule"))
async def cmd_rule(message: Message):
    """Add a custom rule: /rule pause country if buy fails twice"""
    from grok_monitor import grok
    if not grok:
        await message.answer("Grok monitor not running.")
        return
    text = (message.text or "").replace("/rule", "", 1).strip()
    if not text:
        await message.answer("Usage: /rule <your rule text>")
        return
    reply = await grok.add_rule(text)
    await message.answer(reply)

@router.message(Command("rules"))
async def cmd_rules(message: Message):
    from grok_monitor import grok
    if not grok:
        await message.answer("Grok monitor not running.")
        return
    await message.answer(await grok.list_rules(), parse_mode="HTML")

@router.message(Command("clearrules"))
async def cmd_clearrules(message: Message):
    from grok_monitor import grok
    if not grok:
        await message.answer("Grok monitor not running.")
        return
    await message.answer(await grok.clear_rules())
