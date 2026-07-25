import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.models import ParserConfig
from app.services.telegram import add_chat_id, send_text_to_chat

logger = logging.getLogger(__name__)

ParserCallback = Callable[[str, int | str], Awaitable[str]]


def _message_from_update(update: dict) -> dict | None:
    return update.get("message") or update.get("channel_post") or update.get("edited_message")


def _command_name(text: str) -> str:
    first = text.strip().split(maxsplit=1)[0].lower()
    return first.split("@", 1)[0]


async def save_chat_id_to_db(chat_id: int | str, *, config_id: int = 1) -> list[str]:
    async with SessionLocal() as db:
        cfg = await db.get(ParserConfig, config_id)
        if not cfg:
            raise ValueError(f"ParserConfig {config_id} not found")
        cfg.telegram_chat_ids = add_chat_id(cfg.telegram_chat_ids, chat_id)
        await db.commit()
        await db.refresh(cfg)
        return cfg.telegram_chat_ids or []


async def telegram_polling_loop(on_parser: ParserCallback, *, poll_timeout: int = 20) -> None:
    """Long-poll Telegram updates.

    Current mode:
    - /start and /star persist chat_id into parser_configs.telegram_chat_ids.
    - /parser runs parser config id=1 immediately.
    """
    if not settings.telegram_bot_token:
        logger.warning("Telegram bot token is empty; polling disabled")
        return

    api_base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    offset: int | None = None
    logger.info("Telegram polling loop started")

    async with httpx.AsyncClient(timeout=poll_timeout + 10) as client:
        while True:
            try:
                params = {"timeout": poll_timeout, "limit": 20}
                if offset is not None:
                    params["offset"] = offset
                response = await client.get(f"{api_base}/getUpdates", params=params)
                response.raise_for_status()
                payload = response.json()
                if not payload.get("ok"):
                    logger.warning("Telegram getUpdates returned ok=false: %s", payload)
                    await asyncio.sleep(5)
                    continue

                for update in payload.get("result", []):
                    offset = int(update["update_id"]) + 1
                    message = _message_from_update(update)
                    if not message:
                        continue
                    chat = message.get("chat") or {}
                    chat_id = chat.get("id")
                    text = (message.get("text") or "").strip()
                    if not chat_id or not text.startswith("/"):
                        continue

                    command = _command_name(text)
                    if command in ("/start", "/star"):
                        await save_chat_id_to_db(chat_id, config_id=1)
                        await send_text_to_chat(
                            "ваш id добавлен",
                            chat_id=chat_id,
                            disable_web_page_preview=True,
                        )
                    elif command == "/parser":
                        await save_chat_id_to_db(chat_id, config_id=1)
                        await send_text_to_chat("Запускаю RSS-парсер Freelancehunt сейчас.", chat_id=chat_id, disable_web_page_preview=True)
                        result_text = await on_parser("telegram_command", chat_id)
                        await send_text_to_chat(result_text, chat_id=chat_id, disable_web_page_preview=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Telegram polling loop error")
                await asyncio.sleep(10)
