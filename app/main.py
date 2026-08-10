import asyncio
import contextlib
import logging

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db, SessionLocal
from app.models.models import ParserConfig, ParseRun, Product
from app.services.parser import run_parser
from app.services.telegram_bot import telegram_polling_loop

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)
templates = Jinja2Templates(directory="app/templates")

PARSER_CONFIG_ID = 1
AUTO_PARSE_ENABLED = True
AUTO_PARSE_INTERVAL_SECONDS = 5 * 60
PARSER_MANUAL_ENABLED = True
_parse_lock = asyncio.Lock()
_runtime_tasks: list[asyncio.Task] = []

# Run parser once
async def run_parser_once(config_id: int = PARSER_CONFIG_ID, *, source: str = "manual") -> str:
    if _parse_lock.locked():
        return "Парсер уже запущен, второй запуск пропущен."

    async with _parse_lock:
        try:
            async with SessionLocal() as db:
                run_id = await run_parser(db, config_id)
                run = await db.get(ParseRun, run_id)
                if not run:
                    return f"Парсер завершился, run_id={run_id}."
                return (
                    f"Парсер завершён.\n"
                    f"Источник запуска: {source}\n"
                    f"run_id: {run.id}\n"
                    f"status: {run.status}\n"
                    f"просмотрено: {run.products_seen}\n"
                    f"создано новых: {run.products_created}\n"
                    f"дублей: {run.products_skipped_existing}\n"
                    f"причина остановки: {run.stopped_reason or '-'}"
                )
        except Exception as exc:
            logger.exception("Parser run failed")
            return f"Парсер завершился ошибкой: {exc}"


async def background_run(config_id: int):
    if not PARSER_MANUAL_ENABLED:
        logger.info("Parser manual run skipped: disabled until prompt is finalized")
        return
    await run_parser_once(config_id, source="api/admin")


async def config_has_chat_ids(config_id: int = PARSER_CONFIG_ID) -> bool:
    async with SessionLocal() as db:
        cfg = await db.get(ParserConfig, config_id)
        return bool(cfg and cfg.telegram_chat_ids)


async def auto_parser_loop() -> None:
    if not AUTO_PARSE_ENABLED:
        logger.info("Auto parser loop disabled until prompt is finalized")
        return
    logger.info("Auto parser loop started; interval=%ss", AUTO_PARSE_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.sleep(AUTO_PARSE_INTERVAL_SECONDS)
            if not await config_has_chat_ids(PARSER_CONFIG_ID):
                logger.info("Auto parser skipped: no Telegram chat ids saved in DB yet")
                continue
            result = await run_parser_once(PARSER_CONFIG_ID, source="auto_5m")
            logger.info("Auto parser result: %s", result.replace("\n", " | "))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Auto parser loop error")
            await asyncio.sleep(30)


async def parser_from_telegram(source: str, chat_id: int | str) -> str:
    return await run_parser_once(PARSER_CONFIG_ID, source=source)


@app.on_event("startup")
async def startup_tasks() -> None:
    _runtime_tasks.append(asyncio.create_task(telegram_polling_loop(parser_from_telegram)))
    if AUTO_PARSE_ENABLED:
        _runtime_tasks.append(asyncio.create_task(auto_parser_loop()))


@app.on_event("shutdown")
async def shutdown_tasks() -> None:
    for task in _runtime_tasks:
        task.cancel()
    for task in _runtime_tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


@app.get("/health")
async def health():
    return {"success": True, "service": settings.app_name}


@app.get("/admin", response_class=HTMLResponse)
async def admin(request: Request, db: AsyncSession = Depends(get_db)):
    configs = (await db.scalars(select(ParserConfig).order_by(ParserConfig.id.desc()))).all()
    return templates.TemplateResponse("admin_list.html", {"request": request, "configs": configs})


@app.get("/admin/configs/new", response_class=HTMLResponse)
async def admin_new(request: Request):
    return templates.TemplateResponse("config_form.html", {"request": request, "config": None, "action": "/admin/configs"})


async def apply_form_to_config(form, cfg: ParserConfig | None = None) -> ParserConfig:
    cfg = cfg or ParserConfig()
    cfg.name = form.get("name") or "Parser"
    cfg.enabled = form.get("enabled") == "true"
    cfg.start_url = form.get("start_url") or ""
    cfg.pagination_container_selector = form.get("pagination_container_selector") or None
    cfg.pagination_link_selector = form.get("pagination_link_selector") or None
    cfg.max_pages = int(form.get("max_pages") or 1)
    cfg.product_link_selector = form.get("product_link_selector") or "a"
    cfg.product_description_selector = form.get("product_description_selector") or "body"
    cfg.ai_prompt_file = form.get("ai_prompt_file") or "prompts/default_product_prompt.txt"
    cfg.duplicate_stop_limit = int(form.get("duplicate_stop_limit") or 10)
    cfg.request_timeout_seconds = int(form.get("request_timeout_seconds") or 25)
    cfg.use_playwright_fallback = form.get("use_playwright_fallback") == "true"
    cfg.telegram_enabled = form.get("telegram_enabled") == "true"
    return cfg


@app.post("/admin/configs")
async def admin_create(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    cfg = await apply_form_to_config(form)
    db.add(cfg)
    await db.commit()
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/configs/{config_id}/edit", response_class=HTMLResponse)
async def admin_edit(config_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    cfg = await db.get(ParserConfig, config_id)
    if not cfg:
        raise HTTPException(404, "config not found")
    return templates.TemplateResponse("config_form.html", {"request": request, "config": cfg, "action": f"/admin/configs/{config_id}"})


@app.post("/admin/configs/{config_id}")
async def admin_update(config_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    cfg = await db.get(ParserConfig, config_id)
    if not cfg:
        raise HTTPException(404, "config not found")
    form = await request.form()
    await apply_form_to_config(form, cfg)
    await db.commit()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/configs/{config_id}/parse")
async def admin_run(config_id: int, background_tasks: BackgroundTasks):
    if not PARSER_MANUAL_ENABLED:
        raise HTTPException(423, "Parser is disabled until prompt is finalized")
    background_tasks.add_task(background_run, config_id)
    return RedirectResponse("/admin", status_code=303)


@app.get("/api/configs")
async def api_configs(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(ParserConfig).order_by(ParserConfig.id.desc()))).all()


@app.post("/api/parse/{config_id}")
async def api_parse(config_id: int, background_tasks: BackgroundTasks, background: bool = True, db: AsyncSession = Depends(get_db)):
    if not PARSER_MANUAL_ENABLED:
        raise HTTPException(423, "Parser is disabled until prompt is finalized")
    if not await db.get(ParserConfig, config_id):
        raise HTTPException(404, "config not found")
    if background:
        background_tasks.add_task(background_run, config_id)
        return {"success": True, "status": "started_background"}
    result = await run_parser_once(config_id, source="api_sync")
    return {"success": True, "result": result}


@app.get("/api/runs")
async def api_runs(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(ParseRun).order_by(ParseRun.id.desc()).limit(50))).all()


@app.get("/api/products")
async def api_products(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(Product).order_by(Product.id.desc()).limit(100))).all()
