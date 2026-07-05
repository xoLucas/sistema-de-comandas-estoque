from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

from app.core.seed import run_seed
from app.routers.tables import router as tables_router
from app.routers.orders import router as orders_router
from app.routers.products import router as products_router
from app.routers.auth import router as auth_router
from app.routers.stock import router as stock_router
from app.routers.financial import router as financial_router
from app.routers.ws import router as ws_router
from app.routers.suppliers import router as suppliers_router
from app.routers.promotions import router as promotions_router
from app.routers.settings import router as settings_router
from app.routers.employees import router as employees_router
from app.routers.auth_deps import (
    get_current_user_optional,
    get_current_user,
    require_role,
    can_view_financial,
    can_view_suppliers,
    can_view_settings,
    can_view_employees,
)

BASE_DIR = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_seed()
    yield


app = FastAPI(title="Lads Beer - Sistema de Comandas", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app.include_router(tables_router)
app.include_router(orders_router)
app.include_router(products_router)
app.include_router(auth_router)
app.include_router(stock_router)
app.include_router(financial_router)
app.include_router(suppliers_router)
app.include_router(promotions_router)
app.include_router(settings_router)
app.include_router(employees_router)
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
async def financial_page(
    request: Request,
    user=Depends(require_role("gerente", "caixa")),
):
    return templates.TemplateResponse("financeiro.html", {"request": request})


@app.get("/fornecedores")
async def suppliers_page(
    request: Request,
    user=Depends(require_role("gerente", "estoquista", "caixa")),
):
    return templates.TemplateResponse("fornecedores.html", {"request": request})


@app.get("/promocoes")
async def promotions_page(request: Request):
    return templates.TemplateResponse("promocoes.html", {"request": request})


@app.get("/configuracoes")
async def settings_page(
    request: Request,
    user=Depends(require_role("gerente")),
):
    return templates.TemplateResponse("configuracoes.html", {"request": request})


@app.get("/funcionarios")
async def employees_page(
    request: Request,
    user=Depends(require_role("gerente")),
):
    return templates.TemplateResponse("funcionarios.html", {"request": request})
