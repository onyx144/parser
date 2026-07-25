import re
import asyncio
import os
from app.core.config import settings


def detect_project_language(description: str | None) -> str:
    """Return target response language: ukrainian, russian, or english."""
    text = description or ""
    # Do not let internal Russian service labels bias language detection.
    text = "\n".join(line for line in text.splitlines() if not line.strip().lower().startswith("категории:"))
    lower = text.lower()

    ukrainian_markers = (
        "і", "ї", "є", "ґ", "потрібно", "потрібен", "потрібна", "необхідно",
        "розроб", "додаток", "застосунок", "сайт", "шукаємо", "замовник",
        "україн", "створити", "налаштувати", "виправити", "доробити",
    )
    russian_markers = (
        "нужно", "нужен", "нужна", "необходимо", "требуется", "разработ",
        "приложение", "сайт", "ищем", "заказчик", "русск", "создать", "настроить",
        "исправить", "доработать",
    )

    cyrillic_count = len(re.findall(r"[а-яіїєґ]", lower, re.IGNORECASE))
    latin_count = len(re.findall(r"[a-z]", lower, re.IGNORECASE))

    if any(marker in lower for marker in ukrainian_markers):
        return "ukrainian"
    if cyrillic_count == 0 and latin_count > 0:
        return "english"
    if cyrillic_count > 0 and any(marker in lower for marker in russian_markers):
        return "russian"
    if cyrillic_count > 0:
        return "russian"
    return "english"


def language_instruction(language: str) -> str:
    if language == "ukrainian":
        return "CRITICAL OUTPUT LANGUAGE: Write the final bid in Ukrainian only. Do not write Russian."
    if language == "english":
        return "CRITICAL OUTPUT LANGUAGE: Write the final bid in English only. Do not write Russian."
    return "CRITICAL OUTPUT LANGUAGE: Write the final bid in Russian only."


def render_prompt(template: str, *, product_url: str, description: str, categories=None) -> str:
    categories_text = ", ".join(categories or []) if isinstance(categories, list) else (categories or "")
    project_language = detect_project_language(description)
    rendered = template.format(product_url=product_url, description=description, categories=categories_text or "null")
    instruction = language_instruction(project_language)
    return f"{instruction}\n\n{rendered}\n\n{instruction}\nFinal answer must follow this output language instruction exactly."


async def generate_with_hermes(prompt: str) -> str:
    """Generate a response through the local Hermes CLI when external AI key is empty."""
    env = os.environ.copy()
    env.setdefault("HERMES_ACCEPT_HOOKS", "1")
    proc = await asyncio.create_subprocess_exec(
        "hermes",
        "chat",
        "-q",
        prompt,
        "-Q",
        "--source",
        "ultimate-parser-fastapi",
        "--max-turns",
        "1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=settings.ai_timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise TimeoutError(f"Hermes generation timed out after {settings.ai_timeout_seconds}s")

    out = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"Hermes CLI failed with exit={proc.returncode}: {err[-1000:]}")
    clean_lines = []
    for line in out.splitlines():
        if line.startswith("Warning: Unknown toolsets:"):
            continue
        clean_lines.append(line)
    return "\n".join(clean_lines).strip()


async def generate_ai_response(prompt: str) -> str:
    if not settings.ai_api_key:
        return await generate_with_hermes(prompt)

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.ai_api_key, base_url=settings.ai_api_base, timeout=settings.ai_timeout_seconds)
    response = await client.chat.completions.create(
        model=settings.ai_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return response.choices[0].message.content or ""
