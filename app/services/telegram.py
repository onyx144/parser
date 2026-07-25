import httpx

from app.core.config import settings


def normalize_chat_ids(value) -> list[str]:
    """Accept DB null/list/string and return a clean de-duplicated chat_id list."""
    if value is None:
        return []
    if isinstance(value, (str, int)):
        raw_items = [str(value)]
    elif isinstance(value, list):
        raw_items = [str(item) for item in value if item is not None]
    else:
        return []

    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        chat_id = item.strip()
        if not chat_id or chat_id in seen:
            continue
        seen.add(chat_id)
        result.append(chat_id)
    return result


def add_chat_id(existing, chat_id: int | str) -> list[str]:
    ids = normalize_chat_ids(existing)
    value = str(chat_id).strip()
    if value and value not in ids:
        ids.append(value)
    return ids


def _extract_title(description: str | None) -> str:
    if not description:
        return "Новый проект"
    for line in description.splitlines():
        line = line.strip()
        if line:
            return line[:180]
    return "Новый проект"


async def send_text_to_chat(
    text: str,
    *,
    chat_id: str | int,
    disable_web_page_preview: bool = False,
) -> bool:
    if not settings.telegram_bot_token:
        return False
    api_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            api_url,
            json={
                "chat_id": str(chat_id),
                "text": text[:4000],
                "disable_web_page_preview": disable_web_page_preview,
            },
        )
        response.raise_for_status()
        return True


async def send_text_to_chats(
    text: str,
    chat_ids,
    *,
    disable_web_page_preview: bool = False,
) -> int:
    sent = 0
    for chat_id in normalize_chat_ids(chat_ids):
        ok = await send_text_to_chat(
            text,
            chat_id=chat_id,
            disable_web_page_preview=disable_web_page_preview,
        )
        if ok:
            sent += 1
    return sent


async def send_product_result(
    product_url: str,
    ai_response: str,
    description: str | None = None,
    *,
    chat_ids=None,
    category=None,
) -> bool:
    target_chat_ids = normalize_chat_ids(chat_ids)
    if not settings.telegram_bot_token or not target_chat_ids:
        return False

    title = _extract_title(description)
    project_text = f"Новый проект Freelancehunt\n\n{title}\n\n{product_url}"
    response_text = f"Отзыв на вакансию:\n\n{ai_response}" if ai_response else "Отзыв на вакансию:\n\n[пустой ответ Hermes]"

    project_sent = await send_text_to_chats(project_text, target_chat_ids, disable_web_page_preview=False)
    response_sent = await send_text_to_chats(response_text, target_chat_ids, disable_web_page_preview=True)
    return project_sent > 0 and response_sent > 0
