from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.seed import run_seed
from app.core.scheduler import start_scheduler, shutdown_scheduler
from app.routers.tables import router as tables_router
from app.routers.orders import router as orders_router
from app.routers.products import router as products_router
from app.routers.auth import router as auth_router
from app.routers.stock import router as stock_router
from app.routers.categories import router as categories_router
from app.routers.financial import router as financial_router
from app.routers.ws import router as ws_router
from app.routers.suppliers import router as suppliers_router
from app.routers.promotions import router as promotions_router
from app.routers.settings import router as settings_router
from app.routers.employees import router as employees_router
from app.routers.cash_register import router as cash_register_router
from app.routers.customers import router as customers_router
from app.routers.consignments import router as consignments_router
from app.routers.notifications import router as notifications_router
from app.routers.dashboards import router as dashboards_router
from app.routers.backup import router as backup_router
from app.routers.auth_deps import get_current_user_optional

BASE_DIR = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_seed()
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="Lads Beer - Sistema de Comandas", lifespan=lifespan)

logger = logging.getLogger("uvicorn.error")


@app.get("/health/live", include_in_schema=False)
async def health_live():
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def health_ready(db: AsyncSession = Depends(get_db)):
    try:
        await db.scalar(text("SELECT 1"))
    except Exception:
        logger.exception("Readiness database check failed")
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ready"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Log unexpected errors and return a JSON response instead of an HTML stack page."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "Erro interno no servidor"},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return validation errors using the project's standard error shape."""
    messages = []
    for error in exc.errors():
        loc = " -> ".join(str(item) for item in error.get("loc", []))
        msg = error.get("msg", "Erro de validação")
        messages.append(f"{loc}: {msg}".lstrip(" -> "))
    return JSONResponse(
        status_code=422,
        content={"error": messages[0] if messages else "Dados inválidos"},
    )


app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app.include_router(tables_router)
app.include_router(orders_router)
app.include_router(products_router)
app.include_router(auth_router)
app.include_router(stock_router)
app.include_router(categories_router)
app.include_router(financial_router)
app.include_router(suppliers_router)
app.include_router(promotions_router)
app.include_router(settings_router)
app.include_router(employees_router)
app.include_router(cash_register_router)
app.include_router(customers_router)
app.include_router(consignments_router)
app.include_router(notifications_router)
app.include_router(dashboards_router)
app.include_router(backup_router)
app.include_router(ws_router)


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/mesa/{table_id}")
async def table_page(request: Request, table_id: int):
    return templates.TemplateResponse(
        "mesa.html", {"request": request, "table_id": table_id}
    )


@app.get("/estoque")
async def stock_page(request: Request):
    return templates.TemplateResponse("estoque.html", {"request": request})


@app.get("/financeiro")
async def financial_page(request: Request):
    return templates.TemplateResponse("financeiro.html", {"request": request})


@app.get("/fornecedores")
async def suppliers_page(request: Request):
    return templates.TemplateResponse("fornecedores.html", {"request": request})


@app.get("/promocoes")
async def promotions_page(request: Request):
    return templates.TemplateResponse("promocoes.html", {"request": request})


@app.get("/configuracoes")
async def settings_page(request: Request):
    return templates.TemplateResponse("configuracoes.html", {"request": request})


@app.get("/funcionarios")
async def employees_page(request: Request):
    return templates.TemplateResponse("funcionarios.html", {"request": request})


@app.get("/clientes")
async def customers_page(request: Request):
    return templates.TemplateResponse("clientes.html", {"request": request})


@app.get("/consignados")
async def consignments_page(request: Request):
    return templates.TemplateResponse("consignados.html", {"request": request})


@app.get("/dashboards")
async def dashboards_page(request: Request):
    return templates.TemplateResponse("dashboards.html", {"request": request})


@app.get("/balcao/{table_id}")
async def balcao_page(request: Request, table_id: int):
    return templates.TemplateResponse(
        "balcao.html", {"request": request, "table_id": table_id}
    )
