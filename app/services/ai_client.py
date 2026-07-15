import httpx
from app.core.config import settings

def render_prompt(template: str, *, product_url: str, description: str) -> str:
    return template.replace("{product_url}", product_url).replace("{description}", description)

async def generate_ai_response(prompt: str) -> str:
    if not settings.ai_api_key:
        return "AI_API_KEY is empty. Placeholder response. Fill .env to enable AI generation."

    url = settings.ai_api_base.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.ai_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
    }
    headers = {"Authorization": f"Bearer {settings.ai_api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
