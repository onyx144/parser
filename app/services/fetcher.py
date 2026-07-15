import httpx
from playwright.async_api import async_playwright

async def fetch_html(url: str, timeout: int = 25, use_playwright_fallback: bool = True) -> str:
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 UltimateParser/1.0"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
    except Exception:
        if not use_playwright_fallback:
            raise

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
        html = await page.content()
        await browser.close()
        return html
