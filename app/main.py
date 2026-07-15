from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db, SessionLocal
from app.models.models import ParserConfig, ParseRun, Product
from app.services.parser import run_parser

app = FastAPI(title=settings.app_name)
templates = Jinja2Templates(directory="app/templates")

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

async def background_run(config_id: int):
    async with SessionLocal() as db:
        await run_parser(db, config_id)

@app.post("/admin/configs/{config_id}/parse")
async def admin_run(config_id: int, background_tasks: BackgroundTasks):
    background_tasks.add_task(background_run, config_id)
    return RedirectResponse("/admin", status_code=303)

@app.get("/api/configs")
async def api_configs(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(ParserConfig).order_by(ParserConfig.id.desc()))).all()

@app.post("/api/parse/{config_id}")
async def api_parse(config_id: int, background_tasks: BackgroundTasks, background: bool = True, db: AsyncSession = Depends(get_db)):
    if not await db.get(ParserConfig, config_id):
        raise HTTPException(404, "config not found")
    if background:
        background_tasks.add_task(background_run, config_id)
        return {"success": True, "status": "started_background"}
    run_id = await run_parser(db, config_id)
    return {"success": True, "run_id": run_id}

@app.get("/api/runs")
async def api_runs(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(ParseRun).order_by(ParseRun.id.desc()).limit(50))).all()

@app.get("/api/products")
async def api_products(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(Product).order_by(Product.id.desc()).limit(100))).all()
