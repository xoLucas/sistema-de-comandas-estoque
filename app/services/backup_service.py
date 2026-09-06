import csv
import asyncio
import io
import os
import zipfile
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import DATABASE_URL
from app.models.product import Product
from app.models.stock_history import StockHistory
from app.models.category import Category
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.customer import Customer
from app.models.employee import Employee
from app.models.supplier import Supplier
from app.models.consignment import ConsignmentOrder, ConsignmentOrderItem, ConsignmentPayment
from app.models.cash_register_session import CashRegisterSession
from app.models.cash_register_movement import CashRegisterMovement
from app.models.cash_position_movement import CashPositionMovement
from app.models.daily_payment import DailyPayment
from app.models.expense import Expense
from app.models.payment import (
    OrderPayment,
    OrderPaymentAllocation,
    PaymentRefund,
    PaymentRefundItem,
)
from app.models.user import User


EXPORTABLE_ENTITIES = {
    "produtos": Product,
    "historico_estoque": StockHistory,
    "categorias": Category,
    "comandas": Order,
    "itens_comanda": OrderItem,
    "clientes": Customer,
    "funcionarios": Employee,
    "fornecedores": Supplier,
    "consignados": ConsignmentOrder,
    "itens_consignados": ConsignmentOrderItem,
    "pagamentos_consignados": ConsignmentPayment,
    "pagamentos_comandas": OrderPayment,
    "alocacoes_pagamentos_comandas": OrderPaymentAllocation,
    "estornos_pagamentos": PaymentRefund,
    "itens_estornos_pagamentos": PaymentRefundItem,
    "caixa_sessoes": CashRegisterSession,
    "caixa_movimentacoes": CashRegisterMovement,
    "movimentos_posicao_caixa": CashPositionMovement,
    "pagamentos_diarias": DailyPayment,
    "despesas": Expense,
    "usuarios": User,
}


def _model_to_row(instance: Any) -> dict[str, Any]:
    row = {}
    for column in instance.__table__.columns:
        value = getattr(instance, column.name)
        if value is None:
            row[column.name] = ""
        elif hasattr(value, "isoformat"):
            row[column.name] = value.isoformat()
        elif isinstance(value, bool):
            row[column.name] = "1" if value else "0"
        else:
            row[column.name] = str(value)
    return row


async def export_entity_csv(db: AsyncSession, entity_key: str) -> tuple[str, str]:
    model = EXPORTABLE_ENTITIES.get(entity_key)
    if not model:
        raise ValueError(f"Entidade desconhecida: {entity_key}")

    result = await db.execute(select(model))
    rows = result.scalars().all()

    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].__table__.columns.keys()), delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow(_model_to_row(row))
    else:
        columns = list(model.__table__.columns.keys())
        writer = csv.DictWriter(output, fieldnames=columns, delimiter=";")
        writer.writeheader()

    filename = f"{entity_key}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return filename, output.getvalue()


async def export_entities_zip(db: AsyncSession, entity_keys: list[str]) -> tuple[str, bytes]:
    valid_keys = [k for k in entity_keys if k in EXPORTABLE_ENTITIES]
    if not valid_keys:
        raise ValueError("Nenhuma entidade válida selecionada")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for key in valid_keys:
            filename, content = await export_entity_csv(db, key)
            zip_file.writestr(filename, content.encode("utf-8-sig"))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"backup_ladsbeer_{timestamp}.zip"
    return zip_filename, zip_buffer.getvalue()


def _postgres_connection_args() -> tuple[list[str], dict[str, str]]:
    url = make_url(DATABASE_URL)
    if not url.drivername.startswith("postgresql"):
        raise ValueError("O backup completo requer PostgreSQL")
    if not url.database:
        raise ValueError("Banco de dados não configurado")

    args = ["--dbname", url.database]
    if url.host:
        args.extend(["--host", url.host])
    if url.port:
        args.extend(["--port", str(url.port)])
    if url.username:
        args.extend(["--username", url.username])

    environment = os.environ.copy()
    if url.password:
        environment["PGPASSWORD"] = url.password
    return args, environment


async def export_full_database() -> tuple[str, bytes]:
    """Create a transactionally consistent, restorable PostgreSQL custom dump."""
    connection_args, environment = _postgres_connection_args()
    try:
        process = await asyncio.create_subprocess_exec(
            "pg_dump",
            *connection_args,
            "--format=custom",
            "--compress=9",
            "--no-owner",
            "--no-acl",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
        )
    except FileNotFoundError as exc:
        raise ValueError("Ferramenta pg_dump não instalada no servidor") from exc

    content, stderr = await process.communicate()
    if process.returncode != 0 or not content:
        raise ValueError(
            "Não foi possível gerar o backup completo do banco de dados"
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"backup_ladsbeer_completo_{timestamp}.dump", content
