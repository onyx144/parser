import httpx
from app.core.config import settings

async def send_product_result(product_url: str, ai_response: str) -> bool:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False

    text = f"Товар: {product_url}\n\nAI ответ:\n{ai_response}"
    api_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            api_url,
            json={"chat_id": settings.telegram_chat_id, "text": text[:4000], "disable_web_page_preview": False},
        )
        response.raise_for_status()
        return True
