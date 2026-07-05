from sqlalchemy import select, text
from app.core.database import async_session, engine, Base
from app.core.security import hash_password

from app.models.table import Table
from app.models.product import Product
from app.models.user import User
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.order_round import OrderRound
from app.models.supplier import Supplier
from app.models.stock_history import StockHistory
from app.models.promotion import Promotion
from app.models.setting import Setting
from app.models.employee import Employee
from app.models.daily_payment import DailyPayment
from app.models.expense import Expense


SEED_TABLES = [
    {"number": 1, "status": "vazia", "is_balcao": False},
    {"number": 2, "status": "vazia", "is_balcao": False},
    {"number": 3, "status": "vazia", "is_balcao": False},
    {"number": 4, "status": "vazia", "is_balcao": False},
    {"number": 5, "status": "vazia", "is_balcao": False},
    {"number": 6, "status": "vazia", "is_balcao": False},
    {"number": 7, "status": "vazia", "is_balcao": False},
    {"number": 8, "status": "vazia", "is_balcao": False},
    {"number": 9, "status": "vazia", "is_balcao": False},
    {"number": 10, "status": "vazia", "is_balcao": False},
    {"number": 0, "status": "vazia", "is_balcao": True},
]

SEED_PRODUCTS = [
    {"name": "Espetinho de Carne", "category": "Carnes", "price": 12.00, "stock": 20, "min_stock": 15},
    {"name": "Espetinho de Frango", "category": "Carnes", "price": 12.00, "stock": 15, "min_stock": 15},
    {"name": "Espetinho Misto", "category": "Carnes", "price": 14.00, "stock": 5, "min_stock": 10},
    {"name": "Porção de Fritas", "category": "Acompanhamentos", "price": 18.00, "stock": 20, "min_stock": 10},
    {"name": "Porção de Mandioca", "category": "Acompanhamentos", "price": 16.00, "stock": 10, "min_stock": 10},
    {"name": "Cerveja Lata", "category": "Bebidas", "price": 8.00, "stock": 50, "min_stock": 20},
    {"name": "Refrigerante Lata", "category": "Bebidas", "price": 6.00, "stock": 50, "min_stock": 15},
    {"name": "Água Mineral", "category": "Bebidas", "price": 4.00, "stock": 20, "min_stock": 10},
    {"name": "Suco de Laranja", "category": "Bebidas", "price": 7.00, "stock": 0, "min_stock": 5},
    {"name": "Molho de Alho", "category": "Condimentos", "price": 3.00, "stock": 10, "min_stock": 5},
    {"name": "Vinagrete", "category": "Condimentos", "price": 5.00, "stock": 0, "min_stock": 5},
    {"name": "Farofa", "category": "Condimentos", "price": 4.00, "stock": 15, "min_stock": 5},
]

SEED_USERS = [
    {
        "username": "sem_nome",
        "password": "123456",
        "name": "Sem nome",
        "role": "garcom",
        "is_registered": False,
    },
    {
        "username": "gerente",
        "password": "admin123",
        "name": "Gerente",
        "role": "gerente",
        "is_registered": True,
    },
    {
        "username": "caixa",
        "password": "caixa123",
        "name": "Caixa",
        "role": "caixa",
        "is_registered": True,
    },
    {
        "username": "estoquista",
        "password": "estoque123",
        "name": "Estoquista",
        "role": "estoquista",
        "is_registered": True,
    },
]

SEED_SETTINGS = [
    {"key": "store_name", "value": "Lads Beer", "label": "Nome do Estabelecimento", "description": "Nome exibido no sistema e nos tickets", "type": "string"},
    {"key": "store_address", "value": "", "label": "Endereço", "description": "Endereço do estabelecimento", "type": "string"},
    {"key": "store_phone", "value": "", "label": "Telefone", "description": "Telefone de contato", "type": "string"},
    {"key": "store_cnpj", "value": "", "label": "CNPJ", "description": "CNPJ do estabelecimento", "type": "string"},
    {"key": "service_charge_pct", "value": "10", "label": "Taxa de Serviço (%)", "description": "Percentual sugerido no fechamento da mesa", "type": "number"},
    {"key": "card_fee_debit_pct", "value": "1.5", "label": "Taxa Cartão de Débito (%)", "description": "Percentual de taxa para pagamento em débito", "type": "number"},
    {"key": "card_fee_credit_pct", "value": "3.5", "label": "Taxa Cartão de Crédito (%)", "description": "Percentual de taxa para pagamento em crédito", "type": "number"},
    {"key": "ticket_header", "value": "Lads Beer", "label": "Cabeçalho do Ticket", "description": "Texto do cabeçalho impresso nas comandas", "type": "string"},
    {"key": "ticket_footer", "value": "Obrigado pela preferência!", "label": "Rodapé do Ticket", "description": "Texto do rodapé impresso nas comandas", "type": "string"},
]


async def _ensure_columns() -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS partial_service_charge FLOAT NOT NULL DEFAULT 0.0"
            )
        )
        await conn.execute(
            text("ALTER TABLE products ADD COLUMN IF NOT EXISTS code VARCHAR(50) UNIQUE DEFAULT NULL")
        )
        await conn.execute(
            text("ALTER TABLE products ADD COLUMN IF NOT EXISTS cost FLOAT NOT NULL DEFAULT 0.0")
        )
        await conn.execute(
            text("ALTER TABLE products ADD COLUMN IF NOT EXISTS margin_pct FLOAT NOT NULL DEFAULT 0.0")
        )
        await conn.execute(
            text("ALTER TABLE products ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE")
        )
        await conn.execute(
            text("ALTER TABLE stock_history ADD COLUMN IF NOT EXISTS order_id INTEGER REFERENCES orders(id)")
        )
        await conn.execute(
            text("ALTER TABLE stock_history ADD COLUMN IF NOT EXISTS table_id INTEGER REFERENCES tables(id)")
        )


async def ensure_settings(session) -> None:
    for s in SEED_SETTINGS:
        existing = await session.execute(select(Setting).where(Setting.key == s["key"]))
        if existing.scalar_one_or_none() is None:
            session.add(Setting(**s))


async def run_seed() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _ensure_columns()

    async with async_session() as session:
        await ensure_settings(session)

        existing = await session.execute(select(User).limit(1))
        if existing.scalar_one_or_none() is not None:
            await session.commit()
            return

        for t in SEED_TABLES:
            session.add(Table(**t))

        for p in SEED_PRODUCTS:
            session.add(Product(**p))

        for u in SEED_USERS:
            session.add(
                User(
                    username=u["username"],
                    password_hash=hash_password(u["password"]),
                    name=u["name"],
                    role=u["role"],
                    is_registered=u["is_registered"],
                )
            )

        await session.commit()
