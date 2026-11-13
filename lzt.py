from __future__ import annotations

import asyncio
from typing import Any
from loguru import logger

from config import get_settings


class LZTService:
    """Thin async wrapper around official lolzteam MarketClient."""

    def __init__(self) -> None:
        self._client = None
        self._lock = asyncio.Lock()

    def _ensure(self):
        if self._client is None:
            from lolzteam import MarketClient
            s = get_settings()
            self._client = MarketClient(
                token=s.lzt_token,
                proxy=s.lzt_proxy or None,
                language="en",
            )
        return self._client

    async def search_telegram(
        self,
        *,
        pmax: float,
        country_name: str | None = None,
        session_days: int = 1,
        password: str = "no",
        login_mail: str = "yes",
        spam: str = "no",
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """
        Search Telegram category with the default buy filters.
        LZT accepts extra kwargs that map to query params (spam, password, etc.).
        """
        client = self._ensure()

        def _call():
            kwargs: dict[str, Any] = {
                "pmax": pmax,
                "page": page,
                "order_by": "price_to_up",
            }
            # origin / country filter – LZT uses title or specific origin params
            if country_name:
                kwargs["title"] = country_name
            # filter flags – names taken from OpenAPI / observed behaviour
            if spam.lower() in ("no", "0", "false"):
                kwargs["spam"] = "no"
            if password.lower() in ("no", "0", "false"):
                kwargs["password"] = "no"
            # session age is often exposed as day / days / origin filters
            kwargs["nsb"] = True  # not sold before – safer for fresh accounts

            try:
                resp = client.categories.telegram.get(**kwargs)
                if hasattr(resp, "json"):
                    data = resp.json()
                else:
                    data = resp
                return data.get("items") or data.get("list") or []
            except Exception as e:
                logger.warning(f"LZT search error: {e}")
                return []

        async with self._lock:
            return await asyncio.to_thread(_call)

    async def fast_buy(self, item_id: int, price: float) -> dict[str, Any]:
        client = self._ensure()

        def _call():
            try:
                resp = client.purchasing.purchasing_fast_buy(item_id=item_id, price=price)
                if hasattr(resp, "json"):
                    return resp.json()
                return resp if isinstance(resp, dict) else {"raw": str(resp)}
            except Exception as e:
                logger.error(f"LZT buy failed item={item_id}: {e}")
                return {"error": str(e)}

        async with self._lock:
            return await asyncio.to_thread(_call)

    async def get_item(self, item_id: int) -> dict[str, Any]:
        client = self._ensure()

        def _call():
            try:
                resp = client.managing.managing_get(item_id=item_id)
                if hasattr(resp, "json"):
                    return resp.json()
                return resp if isinstance(resp, dict) else {}
            except Exception as e:
                logger.warning(f"LZT get item {item_id}: {e}")
                return {}

        async with self._lock:
            return await asyncio.to_thread(_call)


    async def download_account(self, item_id: int, fmt: str = "login:pass:token") -> str | None:
        """Download purchased account data from LZT (login:pass:token or session)."""
        client = self._ensure()

        def _call():
            try:
                # LZT mass action / download endpoint (common pattern)
                resp = client.purchasing.purchasing_download(
                    item_id=item_id,
                    format=fmt,
                )
                if hasattr(resp, "text"):
                    return resp.text
                if isinstance(resp, dict):
                    return resp.get("data") or resp.get("content") or str(resp)
                return str(resp) if resp else None
            except Exception as e:
                logger.warning(f"LZT download failed for {item_id}: {e}")
                return None

        async with self._lock:
            return await asyncio.to_thread(_call)

    def close(self) -> None:
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None


lzt_service = LZTService()
