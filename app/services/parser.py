import asyncio
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
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


def looks_like_rss(url: str, payload: str) -> bool:
    head = payload[:500].lower()
    return url.lower().split("?", 1)[0].endswith(".rss") or "<rss" in head or "<channel" in head


def clean_html_text(value: str | None) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "lxml")
    return soup.get_text("\n", strip=True)


def extract_rss_items(xml_text: str, page_url: str) -> list[dict]:
    soup = BeautifulSoup(xml_text, "xml")
    items: list[dict[str, str]] = []
    for item in soup.select("item"):
        link_node = item.find("link")
        title_node = item.find("title")
        desc_node = item.find("description")
        pub_node = item.find("pubDate")
        category_nodes = item.find_all("category")
        link = absolute_url(page_url, link_node.get_text(strip=True) if link_node else None)
        if not link:
            continue
        # Drop RSS analytics params so duplicates are stable.
        canonical_link = link.split("?", 1)[0]
        title = title_node.get_text(" ", strip=True) if title_node else ""
        description = clean_html_text(desc_node.get_text("\n", strip=True) if desc_node else "")
        pub_date = pub_node.get_text(" ", strip=True) if pub_node else ""
        categories = [node.get_text(" ", strip=True) for node in category_nodes if node.get_text(" ", strip=True)]
        items.append(
            {
                "url": canonical_link,
                "title": title,
                "description": description,
                "pub_date": pub_date,
                "categories": categories,
            }
        )
    return items


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
            links.append(full.split("?", 1)[0])
    return links


def extract_description(html: str, selector: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    node = soup.select_one(selector)
    return node.get_text("\n", strip=True) if node else ""


def increment_page_param(current_url: str, next_page_number: int) -> str:
    """Build next list URL by changing only page=N and preserving all repeated skills[] params."""
    parts = urlsplit(current_url)
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    found_page = False
    new_pairs: list[tuple[str, str]] = []
    for key, value in query_pairs:
        if key == "page":
            new_pairs.append((key, str(next_page_number)))
            found_page = True
        else:
            new_pairs.append((key, value))
    if not found_page:
        new_pairs.insert(0, ("page", str(next_page_number)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(new_pairs, doseq=True), parts.fragment))


def next_page_url(html: str, current_url: str, cfg: ParserConfig, next_page_number: int) -> str | None:
    if cfg.pagination_container_selector and cfg.pagination_link_selector:
        soup = BeautifulSoup(html, "lxml")
        container = soup.select_one(cfg.pagination_container_selector)
        if container:
            links = container.select(cfg.pagination_link_selector)
            for link in links:
                if link.get_text(" ", strip=True) == str(next_page_number):
                    return absolute_url(current_url, link.get("href"))
            for link in links:
                href = link.get("href") or ""
                if f"page={next_page_number}" in href or f"/page/{next_page_number}" in href:
                    return absolute_url(current_url, href)

    # Fallback for Freelancehunt filtered lists: /projects?page=N&skills[]=...
    if "freelancehunt.com/projects" in current_url:
        return increment_page_param(current_url, next_page_number)
    return None


def load_prompt(path_str: str) -> str:
    path = Path(path_str)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.read_text(encoding="utf-8")


PROGRAMMING_MARKERS = (
    "программ", "програм", "кодинг", "написать код", "исправить код", "доработать код",
    "скрипт", "веб-программ", "web development", "javascript", "typescript",
    "python", "php", "node", "node.js", "nestjs", "nest.js", "sails", "sails.js",
    "express", "express.js", "react", "next.js", "nextjs", "vue", "angular",
    "backend", "back-end", "frontend", "front-end", "full-stack", "fullstack",
    "fastapi", "django", "flask", "laravel", "yii", "symfony",
    "llm", "rag", "парс", "базы данных", "база данных", "sql", "postgres",
    "mysql", "mongodb", "devops", "интеграц", "webhook", "вебхук",
    "n8n", "hermes", "ai-бот", "ии-бот", "іі-бот", "чат-бот", "chatbot",
    "ai assistant", "ai agent", "ии агент", "ai агент", "ии-систем", "ai-систем",
    "wordpress", "word press", "woocommerce", "opencart", "open cart", "e-commerce",
    "интернет-магаз", "cms", "плагин", "plugin", "модуль opencart", "модуль wordpress",
    "html css", "html/css", "css html", "верстка сайта", "верстка лендинга", "лендинг",
)

PROGRAMMING_WORD_MARKERS = ("бот", "telegram", "api", "jsx", "tsx")
PROGRAMMING_CATEGORY_MARKERS = (
    "веб-программирование", "разработка ботов", "javascript", "typescript", "python",
    "php", "парсинг данных", "базы данных", "devops", "cms", "wordpress",
    "opencart", "woocommerce", "криптовалюта", "blockchain", "ai и машинное обучение",
)
NON_PROGRAMMING_NEGATIVE_MARKERS = (
    "дизайн", "логотип", "баннер", "презентац", "копирайт", "текст", "перевод",
    "обработка фото", "ретуш", "монтаж", "видео", "аудио", "озвуч", "smm",
    "таргет", "реклама", "маркетинг", "seo", "контент", "пост", "сторис", "креатив",
    "инстаграм", "instagram", "canva", "figma", "after effects", "анимац", "моушн",
    "обложка", "книга", "журнал", "эскиз", "тату", "рисунок", "иллюстрац",
    "google ads", "google shopping", "ppc", "контекстная реклама", "административн",
    "ассистента", "профиль", "roblox", "age verification", "удаленный доступ", "бухгалтер",
)
NON_PROGRAMMING_CATEGORY_MARKERS = (
    "реклама", "социальных медиа", "дизайн", "живопись", "графика", "анимация",
    "векторная графика", "обработка видео", "аудио", "видео монтаж", "ai в дизайне",
    "ai cоздание видео", "контекстная реклама", "копирайтинг", "контент-менеджер",
    "маркетинговые исследования", "поиск и сбор информации", "обработка данных",
    "работа с клиентами", "инжиниринг", "машино", "приборостроение",
)


def normalize_categories(categories=None) -> list[str]:
    if not categories:
        return []
    if isinstance(categories, str):
        raw = [part.strip() for part in categories.split(",")]
    else:
        raw = [str(part).strip() for part in categories if part]
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def is_programming_project(description: str, categories=None) -> bool:
    normalized_categories = [c for c in normalize_categories(categories) if c != "Программирование"]
    category_text = " ".join(normalized_categories).lower()
    description_text = (description or "").lower()
    haystack = " ".join([category_text, description_text]).strip()

    category_is_programming = any(marker in category_text for marker in PROGRAMMING_CATEGORY_MARKERS)
    category_is_non_programming = any(marker in category_text for marker in NON_PROGRAMMING_CATEGORY_MARKERS)
    has_positive = category_is_programming or any(marker in haystack for marker in PROGRAMMING_MARKERS) or any(
        re.search(rf"(?<![\wа-яіїєґ]){re.escape(marker)}(?![\wа-яіїєґ])", haystack, re.IGNORECASE)
        for marker in PROGRAMMING_WORD_MARKERS
    )
    if not has_positive:
        return False

    has_negative = category_is_non_programming or any(marker in haystack for marker in NON_PROGRAMMING_NEGATIVE_MARKERS)
    strong_dev_markers = (
        "python", "javascript", "typescript", "php", "node", "react", "next.js", "backend",
        "frontend", "fastapi", "django", "flask", "laravel", "wordpress", "woocommerce",
        "opencart", "api", "sql", "postgres", "mysql", "бот", "telegram", "скрипт", "парс",
        "плагин", "n8n", "hermes", "ai-бот", "ии-бот", "іі-бот", "чат-бот", "chatbot",
        "llm", "rag", "webhook", "вебхук", "crm", "cms", "jsx", "tsx",
    )
    has_strong_dev = category_is_programming or any(marker in haystack for marker in strong_dev_markers)
    if has_negative and not has_strong_dev:
        return False
    # Explicit non-programming categories win over weak generic words like AI/automation/project/site.
    if category_is_non_programming and not has_strong_dev:
        return False
    return True


def project_category_for_db(description: str, categories=None) -> list[str] | None:
    normalized = normalize_categories(categories)
    if is_programming_project(description, normalized) and "Программирование" not in normalized:
        normalized.append("Программирование")
    return normalized or None


def product_request_delay(cfg: ParserConfig) -> int:
    value = getattr(cfg, "product_request_delay_seconds", None)
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 6


async def maybe_sleep_between_products(cfg: ParserConfig) -> None:
    delay = product_request_delay(cfg)
    if delay > 0:
        await asyncio.sleep(delay)


async def create_product_from_description(
    db: AsyncSession,
    cfg: ParserConfig,
    run: ParseRun,
    *,
    product_url: str,
    source_page_url: str,
    description: str,
    prompt_template: str,
    categories=None,
) -> None:
    category = project_category_for_db(description, categories)
    is_programming = bool(category and "Программирование" in category)
    product = Product(config_id=cfg.id, product_url=product_url, source_page_url=source_page_url, status="processing", category=category)
    db.add(product)
    await db.commit()
    await db.refresh(product)

    try:
        product.description_text = description
        if is_programming:
            ai_prompt = render_prompt(prompt_template, product_url=product_url, description=description, categories=category)
            ai_answer = await generate_ai_response(ai_prompt)
        else:
            ai_answer = "/*не касается программирования*/"
        product.ai_response = ai_answer
        product.status = "complete"
        run.products_created += 1
        if cfg.telegram_enabled and is_programming:
            product.telegram_sent = await send_product_result(product_url, ai_answer, description, chat_ids=cfg.telegram_chat_ids, category=category)
        elif not is_programming:
            product.telegram_sent = False
    except Exception as exc:
        product.status = "error"
        product.error = str(exc)
    await db.commit()


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

            if looks_like_rss(current_url, html):
                rss_items = extract_rss_items(html, current_url)
                for item in rss_items:
                    product_url = item["url"]
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
                    await maybe_sleep_between_products(cfg)
                    raw_categories = item.get("categories") or []
                    category_line = ", ".join(normalize_categories(raw_categories))
                    description_parts = [p for p in [item.get("title", ""), f"Категории: {category_line}" if category_line else "", item.get("description", ""), item.get("pub_date", "")] if p]
                    description = "\n\n".join(description_parts)
                    await create_product_from_description(
                        db,
                        cfg,
                        run,
                        product_url=product_url,
                        source_page_url=current_url,
                        description=description,
                        prompt_template=prompt_template,
                        categories=raw_categories,
                    )
                run.stopped_reason = "rss_feed_processed"
                break

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
                try:
                    await maybe_sleep_between_products(cfg)
                    product_html = await fetch_html(product_url, cfg.request_timeout_seconds, cfg.use_playwright_fallback)
                    description = extract_description(product_html, cfg.product_description_selector)
                    await create_product_from_description(
                        db,
                        cfg,
                        run,
                        product_url=product_url,
                        source_page_url=current_url,
                        description=description,
                        prompt_template=prompt_template,
                        categories=cfg.category,
                    )
                except Exception as exc:
                    product = Product(config_id=cfg.id, product_url=product_url, source_page_url=current_url, status="error", error=str(exc))
                    db.add(product)
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
