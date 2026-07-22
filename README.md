# Ultimate Parser FastAPI

Отдельный FastAPI-проект для универсального парсинга списков товаров, догрузки карточек товара, обработки описаний через AI-промпт и сохранения результата в MySQL.

## Логика

1. Конфиг парсера создаётся в админке и хранится в MySQL, не в `.env`.
2. Парсер открывает `start_url` обычным GET-запросом через `httpx`.
3. Если GET не прошёл и включён `use_playwright_fallback`, страница открывается через Playwright.
4. По `product_link_selector` собираются ссылки товаров.
5. Если товар уже есть в таблице `products`, он не грузится повторно.
6. Если подряд встретилось `duplicate_stop_limit` уже существующих товаров — проход по списку останавливается. По умолчанию `10`.
7. Новый товар грузится GET/Playwright fallback.
8. Из карточки берётся описание по `product_description_selector`.
9. Берётся prompt-файл, например `prompts/default_product_prompt.txt`.
10. AI получает prompt с `{product_url}` и `{description}`.
11. Товар сохраняется в БД со статусом `complete` или `error`.
12. Если включён Telegram и заполнены `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`, бот отправляет ссылку товара и AI-ответ.

## Структура

```text
app/main.py                 FastAPI routes + admin panel
app/models/models.py        MySQL таблицы
app/services/parser.py      Основной обход страниц/товаров
app/services/fetcher.py     GET + Playwright fallback
app/services/ai_client.py   OpenAI-compatible AI call
app/services/telegram.py    Telegram sendMessage
app/db/init_db.py           Создание таблиц
prompts/default_product_prompt.txt
.env.example
```

## Запуск

```bash
cd /root/projects/ultimate-parser-fastapi
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# заполнить .env своими MySQL/AI/Telegram значениями
python -m playwright install chromium
python -m app.db.init_db
uvicorn app.main:app --host 0.0.0.0 --port 8088
```

Админка:

```text
http://127.0.0.1:8088/admin
```

API:

```text
GET  /health
GET  /api/configs
POST /api/parse/{config_id}
GET  /api/runs
GET  /api/products
```

## В админке указываются

- `Start URL` — список/каталог.
- `Pagination container selector` — див/контейнер пагинации.
- `Pagination link selector` — ссылки внутри пагинации.
- `Max pages` — до какой страницы идти.
- `Product link selector` — класс/селектор ссылки товара в списке.
- `Product description selector` — класс/селектор описания в карточке товара.
- `AI prompt file` — файл промпта.
- `Duplicate stop limit` — сколько подряд уже существующих товаров встретить до остановки. По умолчанию `10`.
- `Telegram enabled` — отправлять ли результат в Telegram.

## Безопасность

Реальные ключи/пароли не внесены. В `.env.example` стоят временные значения или пустые поля.
