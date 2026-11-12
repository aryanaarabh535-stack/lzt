from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_dashboard(
    *,
    auto_buy: bool = True,
    auto_sell: bool = False,
    mode_live: bool = True,
    daily_spend: float = 0.0,
    daily_limit: float = 1.0,
    pending: int = 0,
    receivers: int = 0,
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="📊 Market Matrix", callback_data="menu:matrix"),
        InlineKeyboardButton(text="🎯 Country Rules", callback_data="menu:rules"),
    )
    b.row(
        InlineKeyboardButton(
            text=f"⚡ Auto-Buy: {'ON 🟢' if auto_buy else 'OFF 🔴'}",
            callback_data="toggle:autobuy",
        ),
        InlineKeyboardButton(
            text=f"🛒 Auto-Sell: {'ON 🟢' if auto_sell else 'OFF 🔴'}",
            callback_data="toggle:autosell",
        ),
    )
    b.row(
        InlineKeyboardButton(
            text=f"Mode: {'LIVE' if mode_live else 'PAPER'}",
            callback_data="toggle:mode",
        ),
        InlineKeyboardButton(text="📦 Export Sessions", callback_data="menu:export"),
    )
    b.row(
        InlineKeyboardButton(text="🛑 STOP ALL TRADING", callback_data="action:stop_all"),
        InlineKeyboardButton(text="📈 Analytics", callback_data="menu:analytics"),
    )
    b.row(
        InlineKeyboardButton(text="📥 Receivers", callback_data="menu:receivers"),
        InlineKeyboardButton(text=f"⚠ Pending ({pending})", callback_data="menu:pending"),
    )
    b.row(
        InlineKeyboardButton(text="💼 Workers", callback_data="menu:workers"),
        InlineKeyboardButton(text="📒 Trade Ledger", callback_data="menu:ledger"),
    )
    b.row(
        InlineKeyboardButton(
            text=f"💰 Budget ${daily_spend:.2f}/${daily_limit:.2f}",
            callback_data="menu:budget",
        ),
        InlineKeyboardButton(text="⏸ Pause Country", callback_data="menu:pause_country"),
    )
    b.row(
        InlineKeyboardButton(text="🔄 Refresh Rates", callback_data="action:refresh"),
        InlineKeyboardButton(text="➕ Add Worker", callback_data="menu:add_worker"),
    )
    return b.as_markup()


def confirm_kb(action: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ Confirm", callback_data=f"confirm:{action}"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="confirm:cancel"),
    )
    return b.as_markup()


def back_kb(to: str = "menu:main") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="« Back", callback_data=to))
    return b.as_markup()


def matrix_nav(page: int, total_pages: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    row = []
    if page > 1:
        row.append(InlineKeyboardButton(text="◀ Prev", callback_data=f"matrix:page:{page-1}"))
    row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        row.append(InlineKeyboardButton(text="Next ▶", callback_data=f"matrix:page:{page+1}"))
    b.row(*row)
    b.row(InlineKeyboardButton(text="« Dashboard", callback_data="menu:main"))
    return b.as_markup()
