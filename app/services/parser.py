from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ParserConfig, Product, ParseRun
from app.services.fetcher import fetch_html
from app.services.ai_client import render_prompt, generate_ai_response
from app.services.telegram import send_product_result

PROJECT_ROOT = Path(__file__).resolve().parents[2]

def absolute_url(base: str, href: str | None) -> str | None:
    if not href:
        return None
    return urljoin(base, href.strip())

def extract_product_links(html: str, page_url: str, selector: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    for node in soup.select(selector):
        href = node.get("href")
        if not href:
            child = node.select_one("a")
            href = child.get("href") if child else None
        full = absolute_url(page_url, href)
        if full and full not in links:
            links.append(full)
    return links

def extract_description(html: str, selector: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    node = soup.select_one(selector)
    return node.get_text("\n", strip=True) if node else ""

def next_page_url(html: str, current_url: str, cfg: ParserConfig, next_page_number: int) -> str | None:
    if not cfg.pagination_container_selector or not cfg.pagination_link_selector:
        return None
    soup = BeautifulSoup(html, "lxml")
    container = soup.select_one(cfg.pagination_container_selector)
    if not container:
        return None
    links = container.select(cfg.pagination_link_selector)
    for link in links:
        if link.get_text(" ", strip=True) == str(next_page_number):
            return absolute_url(current_url, link.get("href"))
    for link in links:
        href = link.get("href") or ""
        if f"page={next_page_number}" in href or f"/page/{next_page_number}" in href:
            return absolute_url(current_url, href)
    return None

def load_prompt(path_str: str) -> str:
    path = Path(path_str)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.read_text(encoding="utf-8")

async def run_parser(db: AsyncSession, config_id: int) -> int:
    cfg = await db.get(ParserConfig, config_id)
    if not cfg:
        raise ValueError(f"ParserConfig {config_id} not found")
    if not cfg.enabled:
        raise ValueError(f"ParserConfig {config_id} is disabled")

    run = ParseRun(config_id=config_id, status="running")
    db.add(run)
    await db.commit()
    await db.refresh(run)

    duplicate_streak = 0
    current_url = cfg.start_url

    try:
        prompt_template = load_prompt(cfg.ai_prompt_file)
        for page_number in range(1, max(cfg.max_pages, 1) + 1):
            html = await fetch_html(current_url, cfg.request_timeout_seconds, cfg.use_playwright_fallback)
            run.pages_seen += 1
            product_links = extract_product_links(html, current_url, cfg.product_link_selector)

            for product_url in product_links:
                run.products_seen += 1
                existing = await db.scalar(select(Product).where(Product.product_url == product_url))
                if existing:
                    duplicate_streak += 1
                    run.products_skipped_existing += 1
                    if duplicate_streak >= (cfg.duplicate_stop_limit or 10):
                        run.status = "complete"
                        run.stopped_reason = f"duplicate_streak_reached_{duplicate_streak}"
                        await db.commit()
                        return run.id
                    continue

                duplicate_streak = 0
                product = Product(config_id=cfg.id, product_url=product_url, source_page_url=current_url, status="processing")
                db.add(product)
                await db.commit()
                await db.refresh(product)

                try:
                    product_html = await fetch_html(product_url, cfg.request_timeout_seconds, cfg.use_playwright_fallback)
                    description = extract_description(product_html, cfg.product_description_selector)
                    ai_prompt = render_prompt(prompt_template, product_url=product_url, description=description)
                    ai_answer = await generate_ai_response(ai_prompt)
                    product.description_text = description
                    product.ai_response = ai_answer
                    product.status = "complete"
                    run.products_created += 1
                    if cfg.telegram_enabled:
                        product.telegram_sent = await send_product_result(product_url, ai_answer)
                except Exception as exc:
                    product.status = "error"
                    product.error = str(exc)
                await db.commit()

            if page_number >= cfg.max_pages:
                break
            next_url = next_page_url(html, current_url, cfg, page_number + 1)
            if not next_url:
                run.stopped_reason = "pagination_next_link_not_found"
                break
            current_url = next_url

        run.status = "complete"
        if not run.stopped_reason:
            run.stopped_reason = "max_pages_or_list_finished"
    except Exception as exc:
        run.status = "error"
        run.error = str(exc)

    await db.commit()
    return run.id
