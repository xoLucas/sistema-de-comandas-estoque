import csv
import io
import zipfile
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.stock_history import StockHistory
from app.models.category import Category
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.customer import Customer
from app.models.employee import Employee
from app.models.supplier import Supplier
from app.models.consignment import ConsignmentOrder, ConsignmentPayment
from app.models.cash_register_session import CashRegisterSession
from app.models.cash_register_movement import CashRegisterMovement
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
    "pagamentos_consignados": ConsignmentPayment,
    "caixa_sessoes": CashRegisterSession,
    "caixa_movimentacoes": CashRegisterMovement,
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
