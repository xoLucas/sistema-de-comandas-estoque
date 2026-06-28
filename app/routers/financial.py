from datetime import datetime, date
from collections import defaultdict
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func, extract, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from fpdf import FPDF
import io

from app.core.database import get_db
from app.models.order import Order
from app.models.table import Table
from app.models.user import User
from app.routers.auth_deps import get_current_user

router = APIRouter(prefix="/api/financeiro", tags=["financeiro"])


from app.models.order_item import OrderItem
from app.models.product import Product


CARD_FEE_RATES = {
    "dinheiro": 0.0,
    "pix": 0.0,
    "cartao_debito": 1.5,
    "cartao_credito": 3.5,
    "nao_informado": 0.0,
}


PAYMENT_LABELS = {
    "dinheiro": "Dinheiro",
    "pix": "Pix",
    "cartao_debito": "Cartão Débito",
    "cartao_credito": "Cartão Crédito",
    "nao_informado": "Não Informado",
}


def _method_label(method: str) -> str:
    return PAYMENT_LABELS.get(method, method)


def _service_amount(order: Order) -> float:
    return order.total * (order.service_charge_pct / 100)


def _card_fee_for_payment(amount: float, method: str) -> float:
    return amount * (CARD_FEE_RATES.get(method, 0.0) / 100)


async def _build_daily_report(
    close_date: date, db: AsyncSession, closed_by: str
) -> dict:
    result = await db.execute(
        select(Order)
        .where(
            Order.status == "finalizada",
            cast(Order.closed_at, Date) == close_date,
        )
        .options(
            selectinload(Order.table),
            selectinload(Order.waiter),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
        .order_by(Order.closed_at)
    )
    orders = result.scalars().all()

    if not orders:
        return {"error": "Nenhuma venda encontrada nesta data"}

    report = {
        "date": close_date.isoformat(),
        "closed_by": closed_by,
        "generated_at": datetime.now().isoformat(),
        "orders": [],
        "summary": {
            "total_sales": 0.0,
            "total_service_charge": 0.0,
            "total_partial_payments": 0.0,
            "total_card_fees": 0.0,
            "gross_total": 0.0,
            "net_total": 0.0,
            "orders_count": len(orders),
        },
        "by_payment_method": {},
        "by_waiter": {},
        "by_table": {},
        "by_hour": {},
        "items_ranking": [],
    }

    method_totals = {}
    waiter_totals = defaultdict(lambda: {"service_charge": 0.0, "orders": 0, "sales": 0.0})
    table_totals = defaultdict(lambda: {"total": 0.0, "orders": 0})
    hour_totals = defaultdict(float)
    item_totals = defaultdict(lambda: {"quantity": 0, "total": 0.0})

    for o in orders:
        service_amount = _service_amount(o)
        product_remaining = max(0.0, o.total - o.partial_payment)
        service_remaining = max(0.0, service_amount - o.partial_service_charge)
        final = product_remaining + service_remaining
        close_method = o.payment_method or "nao_informado"
        close_fee = _card_fee_for_payment(final, close_method)

        report["summary"]["total_sales"] += o.total
        report["summary"]["total_service_charge"] += service_amount
        report["summary"]["total_partial_payments"] += o.partial_payment + o.partial_service_charge
        report["summary"]["total_card_fees"] += close_fee
        report["summary"]["gross_total"] += final

        waiter_name = o.waiter.name if o.waiter else "N/A"
        waiter_totals[waiter_name]["service_charge"] += service_amount
        waiter_totals[waiter_name]["orders"] += 1
        waiter_totals[waiter_name]["sales"] += o.total

        table_label = f"Mesa {o.table.number}" if (o.table and not o.table.is_balcao) else "Balcão"
        table_totals[table_label]["total"] += o.total
        table_totals[table_label]["orders"] += 1

        hour_key = o.closed_at.strftime("%H:00") if o.closed_at else "00:00"
        hour_totals[hour_key] += final

        for item in o.items:
            item_totals[item.product.name]["quantity"] += item.quantity
            item_totals[item.product.name]["total"] += item.unit_price * item.quantity

        if close_method not in method_totals:
            method_totals[close_method] = {
                "gross": 0.0,
                "fee_pct": CARD_FEE_RATES.get(close_method, 0.0),
                "fee": 0.0,
                "net": 0.0,
                "count": 0,
            }
        method_totals[close_method]["gross"] += final
        method_totals[close_method]["fee"] += close_fee
        method_totals[close_method]["net"] += final - close_fee
        method_totals[close_method]["count"] += 1

        if o.partial_payments_detail:
            for pd in o.partial_payments_detail:
                p_amount = float(pd.get("amount", 0))
                p_product = float(pd.get("product_portion", p_amount))
                p_service = float(pd.get("service_portion", 0))
                p_method = pd.get("method", "nao_informado")
                p_fee = _card_fee_for_payment(p_amount, p_method)

                report["summary"]["total_card_fees"] += p_fee
                report["summary"]["gross_total"] += p_amount

                key = f"parcial_{p_method}"
                if key not in method_totals:
                    method_totals[key] = {
                        "gross": 0.0,
                        "fee_pct": CARD_FEE_RATES.get(p_method, 0.0),
                        "fee": 0.0,
                        "net": 0.0,
                        "count": 0,
                        "label": f"Parcial - {_method_label(p_method)}",
                    }
                method_totals[key]["gross"] += p_amount
                method_totals[key]["fee"] += p_fee
                method_totals[key]["net"] += p_amount - p_fee
                method_totals[key]["count"] += 1

        report["orders"].append(
            {
                "order_id": o.id,
                "table": table_label,
                "waiter": waiter_name,
                "total": float(o.total),
                "service_charge": round(service_amount, 2),
                "partial_payment": float(o.partial_payment),
                "partial_service_charge": float(o.partial_service_charge),
                "final_total": round(final, 2),
                "payment_method": close_method,
                "closed_at": o.closed_at.strftime("%H:%M") if o.closed_at else "",
            }
        )

    report["summary"]["total_sales"] = round(report["summary"]["total_sales"], 2)
    report["summary"]["total_service_charge"] = round(report["summary"]["total_service_charge"], 2)
    report["summary"]["total_partial_payments"] = round(report["summary"]["total_partial_payments"], 2)
    report["summary"]["total_card_fees"] = round(report["summary"]["total_card_fees"], 2)
    report["summary"]["gross_total"] = round(report["summary"]["gross_total"], 2)
    report["summary"]["net_total"] = round(
        report["summary"]["gross_total"]
        - report["summary"]["total_service_charge"]
        - report["summary"]["total_card_fees"],
        2,
    )

    for method, values in method_totals.items():
        method_totals[method]["gross"] = round(values["gross"], 2)
        method_totals[method]["fee"] = round(values["fee"], 2)
        method_totals[method]["net"] = round(values["net"], 2)

    for waiter, values in waiter_totals.items():
        waiter_totals[waiter]["service_charge"] = round(values["service_charge"], 2)
        waiter_totals[waiter]["sales"] = round(values["sales"], 2)

    for table, values in table_totals.items():
        table_totals[table]["total"] = round(values["total"], 2)

    report["by_payment_method"] = method_totals
    report["by_waiter"] = dict(waiter_totals)
    report["by_table"] = dict(table_totals)
    report["by_hour"] = dict(sorted(hour_totals.items()))
    report["items_ranking"] = sorted(
        [
            {"name": k, "quantity": v["quantity"], "total": round(v["total"], 2)}
            for k, v in item_totals.items()
        ],
        key=lambda x: x["total"],
        reverse=True,
    )

    return report


@router.get("/vendas")
async def list_sales(
    date_filter: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("caixa", "gerente"):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    query = (
        select(Order)
        .where(Order.status == "finalizada")
        .options(
            selectinload(Order.table),
            selectinload(Order.waiter),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
        .order_by(Order.closed_at.desc())
    )

    if date_filter:
        try:
            filter_date = datetime.strptime(date_filter, "%Y-%m-%d").date()
            query = query.where(cast(Order.closed_at, Date) == filter_date)
        except ValueError:
            pass

    result = await db.execute(query)
    orders = result.scalars().all()

    data = []
    total_day = 0.0
    total_service = 0.0

    for o in orders:
        service_amount = _service_amount(o)
        product_remaining = max(0.0, o.total - o.partial_payment)
        service_remaining = max(0.0, service_amount - o.partial_service_charge)
        final = product_remaining + service_remaining
        total_day += o.total
        total_service += service_amount

        data.append(
            {
                "order_id": o.id,
                "table_number": o.table.number if o.table else 0,
                "is_balcao": o.table.is_balcao if o.table else False,
                "waiter_name": o.waiter.name if o.waiter else "N/A",
                "items_count": sum(item.quantity for item in o.items),
                "total": float(o.total),
                "service_charge_pct": float(o.service_charge_pct),
                "service_charge_amount": round(float(service_amount), 2),
                "partial_payment": float(o.partial_payment),
                "partial_service_charge": float(o.partial_service_charge),
                "final_total": float(final),
                "payment_method": o.payment_method or "nao_informado",
                "closed_at": o.closed_at.isoformat() if o.closed_at else None,
            }
        )

    return {
        "sales": data,
        "summary": {
            "total_sales": round(total_day, 2),
            "total_service_charge": round(total_service, 2),
            "orders_count": len(data),
        },
    }


@router.get("/dashboard")
async def dashboard(
    period: str = Query("daily"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("caixa", "gerente"):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    today = date.today()

    result = await db.execute(
        select(
            func.coalesce(func.sum(Order.total), 0),
            func.coalesce(func.sum(Order.total * Order.service_charge_pct / 100), 0),
            func.count(Order.id),
        ).where(
            Order.status == "finalizada",
            cast(Order.closed_at, Date) == today,
        )
    )
    today_total, today_service, today_count = result.one()

    result = await db.execute(
        select(
            func.coalesce(func.sum(Order.total), 0),
            func.count(Order.id),
        ).where(
            Order.status == "finalizada",
            extract("year", Order.closed_at) == today.year,
            extract("month", Order.closed_at) == today.month,
        )
    )
    month_total, month_count = result.one()

    result = await db.execute(
        select(
            func.coalesce(func.sum(Order.total), 0),
            func.count(Order.id),
        ).where(
            Order.status == "finalizada",
            extract("year", Order.closed_at) == today.year,
            extract("week", Order.closed_at) == today.isocalendar()[1],
        )
    )
    week_total, week_count = result.one()

    return {
        "today": {
            "total": round(float(today_total), 2),
            "service_charge": round(float(today_service), 2),
            "orders": today_count,
        },
        "week": {
            "total": round(float(week_total), 2),
            "orders": week_count,
        },
        "month": {
            "total": round(float(month_total), 2),
            "orders": month_count,
        },
    }


class DailyCloseRequest(BaseModel):
    date: str


@router.post("/fechamento-diario")
async def daily_close(
    req: DailyCloseRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("caixa", "gerente"):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    try:
        close_date = datetime.strptime(req.date, "%Y-%m-%d").date()
    except ValueError:
        return {"error": "Data inválida. Use formato YYYY-MM-DD"}

    return await _build_daily_report(close_date, db, user.name)


class ReportPdfRequest(BaseModel):
    date: str


@router.post("/relatorio-pdf")
async def report_pdf(
    req: ReportPdfRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("caixa", "gerente"):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    try:
        close_date = datetime.strptime(req.date, "%Y-%m-%d").date()
    except ValueError:
        return {"error": "Data inválida. Use formato YYYY-MM-DD"}

    report = await _build_daily_report(close_date, db, user.name)
    if "error" in report:
        return report

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)

    pdf.cell(0, 10, "LADS BEER - Relatório Financeiro Diário", ln=True, align="C")
    pdf.set_font("Arial", "", 11)
    pdf.cell(0, 6, f"Data: {report['date']}  |  Fechado por: {report['closed_by']}", ln=True, align="C")
    pdf.cell(0, 6, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
    pdf.ln(8)

    # Resumo geral
    pdf.set_font("Arial", "B", 13)
    pdf.cell(0, 8, "Resumo Geral", ln=True)
    pdf.set_font("Arial", "", 11)
    summary = report["summary"]
    rows = [
        ("Vendas Brutas", f"R$ {summary['total_sales']:.2f}"),
        ("Taxa de Serviço (10%)", f"R$ {summary['total_service_charge']:.2f}"),
        ("Taxas de Cartão", f"R$ {summary['total_card_fees']:.2f}"),
        ("Total Bruto Recebido", f"R$ {summary['gross_total']:.2f}"),
        ("Total Líquido (caixa)", f"R$ {summary['net_total']:.2f}"),
        ("Comandas", str(summary["orders_count"])),
    ]
    for label, value in rows:
        pdf.cell(90, 7, label, border=0)
        pdf.cell(0, 7, value, border=0, ln=True)
    pdf.ln(6)

    # Por forma de pagamento
    pdf.set_font("Arial", "B", 13)
    pdf.cell(0, 8, "Por Forma de Pagamento", ln=True)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(60, 7, "Forma", border="B")
    pdf.cell(30, 7, "Bruto", border="B", align="R")
    pdf.cell(30, 7, "Taxa", border="B", align="R")
    pdf.cell(30, 7, "Líquido", border="B", align="R")
    pdf.cell(20, 7, "Qtd", border="B", align="R", ln=True)
    pdf.set_font("Arial", "", 10)
    for method, vals in report["by_payment_method"].items():
        label = vals.get("label", _method_label(method))
        pdf.cell(60, 6, label)
        pdf.cell(30, 6, f"R$ {vals['gross']:.2f}", align="R")
        pdf.cell(30, 6, f"R$ {vals['fee']:.2f}", align="R")
        pdf.cell(30, 6, f"R$ {vals['net']:.2f}", align="R")
        pdf.cell(20, 6, str(vals["count"]), align="R", ln=True)
    pdf.ln(6)

    # Por garçom
    pdf.set_font("Arial", "B", 13)
    pdf.cell(0, 8, "Por Garçom", ln=True)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(70, 7, "Garçom", border="B")
    pdf.cell(35, 7, "Taxa a Receber", border="B", align="R")
    pdf.cell(35, 7, "Vendas", border="B", align="R")
    pdf.cell(30, 7, "Comandas", border="B", align="R", ln=True)
    pdf.set_font("Arial", "", 10)
    for waiter, vals in report["by_waiter"].items():
        pdf.cell(70, 6, waiter)
        pdf.cell(35, 6, f"R$ {vals['service_charge']:.2f}", align="R")
        pdf.cell(35, 6, f"R$ {vals['sales']:.2f}", align="R")
        pdf.cell(30, 6, str(vals["orders"]), align="R", ln=True)
    pdf.ln(6)

    # Por mesa
    pdf.set_font("Arial", "B", 13)
    pdf.cell(0, 8, "Por Mesa", ln=True)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(80, 7, "Mesa", border="B")
    pdf.cell(50, 7, "Total", border="B", align="R")
    pdf.cell(40, 7, "Comandas", border="B", align="R", ln=True)
    pdf.set_font("Arial", "", 10)
    for table, vals in report["by_table"].items():
        pdf.cell(80, 6, table)
        pdf.cell(50, 6, f"R$ {vals['total']:.2f}", align="R")
        pdf.cell(40, 6, str(vals["orders"]), align="R", ln=True)
    pdf.ln(6)

    # Ranking de itens
    pdf.set_font("Arial", "B", 13)
    pdf.cell(0, 8, "Ranking de Itens Vendidos", ln=True)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(90, 7, "Item", border="B")
    pdf.cell(35, 7, "Qtd", border="B", align="R")
    pdf.cell(45, 7, "Total", border="B", align="R", ln=True)
    pdf.set_font("Arial", "", 10)
    for item in report["items_ranking"][:15]:
        pdf.cell(90, 6, item["name"])
        pdf.cell(35, 6, str(item["quantity"]), align="R")
        pdf.cell(45, 6, f"R$ {item['total']:.2f}", align="R", ln=True)
    pdf.ln(6)

    # Vendas por hora
    pdf.set_font("Arial", "B", 13)
    pdf.cell(0, 8, "Vendas por Hora", ln=True)
    pdf.set_font("Arial", "", 10)
    for hour, total in report["by_hour"].items():
        pdf.cell(40, 6, hour)
        pdf.cell(0, 6, f"R$ {total:.2f}", ln=True)

    buffer = io.BytesIO()
    pdf.output(buffer)
    buffer.seek(0)

    filename = f"relatorio_ladsbeer_{report['date']}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
