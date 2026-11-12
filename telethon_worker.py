from __future__ import annotations

import asyncio
from pathlib import Path
from loguru import logger
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from config import get_settings, SESSIONS_DIR


class WorkerManager:
    """Manages Telethon sessions for capacity polling and future login of bought accounts."""

    def __init__(self) -> None:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self._clients: dict[str, TelegramClient] = {}
        self._pending_code: dict[int, asyncio.Future] = {}  # owner_id → future for code
        self._pending_2fa: dict[int, asyncio.Future] = {}

    def session_path(self, phone: str) -> Path:
        safe = phone.replace("+", "").replace(" ", "")
        return SESSIONS_DIR / f"{safe}.session"

    async def start_login(self, phone: str) -> TelegramClient:
        s = get_settings()
        path = str(self.session_path(phone))
        client = TelegramClient(path, s.api_id, s.api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
        self._clients[phone] = client
        return client

    async def submit_code(self, phone: str, code: str) -> tuple[bool, str]:
        client = self._clients.get(phone)
        if not client:
            return False, "No pending login for this phone"
        try:
            await client.sign_in(phone=phone, code=code)
            return True, "Logged in successfully"
        except SessionPasswordNeededError:
            return False, "2FA_REQUIRED"
        except Exception as e:
            return False, str(e)

    async def submit_2fa(self, phone: str, password: str) -> tuple[bool, str]:
        client = self._clients.get(phone)
        if not client:
            return False, "No pending login"
        try:
            await client.sign_in(password=password)
            return True, "2FA accepted – logged in"
        except Exception as e:
            return False, str(e)

    async def get_primary_client(self) -> TelegramClient | None:
        """Return first active worker client (used by capacity poller)."""
        for phone, client in self._clients.items():
            if client.is_connected():
                return client
        # try load any existing session
        s = get_settings()
        for path in SESSIONS_DIR.glob("*.session"):
            try:
                client = TelegramClient(str(path.with_suffix("")), s.api_id, s.api_hash)
                await client.connect()
                if await client.is_user_authorized():
                    self._clients[path.stem] = client
                    return client
            except Exception as e:
                logger.warning(f"Could not load session {path}: {e}")
        return None

    async def disconnect_all(self) -> None:
        for client in self._clients.values():
            try:
                await client.disconnect()
            except Exception:
                pass
        self._clients.clear()


worker_manager = WorkerManager()
