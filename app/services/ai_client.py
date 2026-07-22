import asyncio
import os
from app.core.config import settings


def render_prompt(template: str, *, product_url: str, description: str) -> str:
    return template.format(product_url=product_url, description=description)


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
