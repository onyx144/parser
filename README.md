# Ultimate Parser FastAPI

A standalone FastAPI project for universal product list parsing, product page fetching, AI-powered description processing, and storing the results in MySQL.

## Workflow

1. The parser configuration is created through the admin panel and stored in MySQL instead of `.env`.
2. The parser opens the `start_url` using a standard GET request via `httpx`.
3. If the GET request fails and `use_playwright_fallback` is enabled, the page is loaded using Playwright.
4. Product links are extracted using the `product_link_selector`.
5. If a product already exists in the `products` table, it is skipped.
6. If `duplicate_stop_limit` consecutive existing products are encountered, the parser stops processing the list. The default value is `10`.
7. New product pages are fetched using GET with an optional Playwright fallback.
8. The product description is extracted using the `product_description_selector`.
9. The parser loads the selected prompt file, for example `prompts/default_product_prompt.txt`.
10. The AI receives the prompt with the `{product_url}` and `{description}` placeholders.
11. The product is saved to the database with either the `complete` or `error` status.
12. If Telegram notifications are enabled and both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are configured, the bot sends the product URL along with the AI response.

## Project Structure

```text
app/main.py                 FastAPI routes + admin panel
app/models/models.py        MySQL models
app/services/parser.py      Main parser workflow
app/services/fetcher.py     HTTP GET + Playwright fallback
app/services/ai_client.py   OpenAI-compatible AI client
app/services/telegram.py    Telegram sendMessage integration
app/db/init_db.py           Database initialization
prompts/default_product_prompt.txt
.env.example
```

## Installation

```bash
cd /root/projects/ultimate-parser-fastapi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Configure your MySQL, AI, and Telegram credentials
python -m playwright install chromium
python -m app.db.init_db
uvicorn app.main:app --host 0.0.0.0 --port 8088
```

## Admin Panel

```text
http://127.0.0.1:8088/admin
```

## API Endpoints

```text
GET  /health
GET  /api/configs
POST /api/parse/{config_id}
GET  /api/runs
GET  /api/products
```

## Admin Panel Configuration

- **Start URL** — The initial product list or catalog URL.
- **Pagination Container Selector** — CSS selector for the pagination container.
- **Pagination Link Selector** — CSS selector for pagination links.
- **Max Pages** — Maximum number of pages to crawl.
- **Product Link Selector** — CSS selector for product links within the product list.
- **Product Description Selector** — CSS selector for the product description on the product page.
- **AI Prompt File** — Prompt template file used for AI processing.
- **Duplicate Stop Limit** — Number of consecutive already-existing products before stopping the parser. Default: `10`.
- **Telegram Enabled** — Whether to send parsing results to Telegram.