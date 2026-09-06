import asyncio
import logging
import socket
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.core.database import async_session
from app.services.notification_service import (
    create_printer_failure_notification,
    notification_to_dict,
)
from app.services.settings_service import get_setting, get_setting_as_int
from app.services.money_service import money, rate

logger = logging.getLogger(__name__)


ESC = b"\x1b"
GS = b"\x1d"


def _cmd(*parts: bytes) -> bytes:
    return b"".join(parts)


def _text(text: str) -> bytes:
    try:
        return text.encode("cp850")
    except UnicodeEncodeError:
        return text.encode("ascii", errors="ignore")


def _center(text: str, width: int) -> str:
    if len(text) >= width:
        return text
    padding = (width - len(text)) // 2
    return " " * padding + text


def _right(text: str, width: int) -> str:
    if len(text) >= width:
        return text
    return " " * (width - len(text)) + text


def _line(char: str = "-", width: int = 32) -> str:
    return char * width


def _format_money(value: object) -> str:
    amount = money(value)
    return f"R$ {amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _format_rate(value: object) -> str:
    amount = rate(value)
    text = format(amount, "f").rstrip("0").rstrip(".")
    return text or "0"


def _receipt_total_line(label: str, value: object, width: int) -> str:
    value_text = _format_money(value)
    available = width - len(value_text)
    label_text = label[: max(available - 2, 0)]
    return f"{label_text}{' ' * (available - len(label_text))}{value_text}"


def _receipt_item_lines(
    name: str,
    quantity: object,
    unit_price: object,
    subtotal: object,
    width: int,
) -> list[str]:
    max_name_len = max(1, width - 10)
    display_name = str(name)[:max_name_len]
    quantity_text = f"{quantity}x"
    first_line = f"{display_name:<{max_name_len}} {quantity_text:>8}"
    values = f"{_format_money(unit_price)}  {_format_money(subtotal)}"
    return [first_line, _right(values, width)]


def _wrap_text(text: str, width: int) -> list[str]:
    """Wrap a text into lines of at most `width` characters, breaking on spaces."""
    text = text.strip()
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(word) > width:
            if current:
                lines.append(current)
                current = ""
            for i in range(0, len(word), width):
                lines.append(word[i : i + width])
            continue
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _print_terminal_preview(
    title: str, lines: list[str], *, exact_receipt: bool = False
) -> None:
    if exact_receipt:
        print("\n".join(lines))
        return
    print()
    print("=" * 40)
    print(f"IMPRESSORA TERMINAL - {title}")
    print("=" * 40)
    for line in lines:
        print(line)
    print("=" * 40)
    print()


class EscPosBuilder:
    def __init__(self, width: int = 32):
        self.width = width
        self.data = bytearray()
        self.data.extend(_cmd(ESC, b"@"))  # Initialize

    def align_center(self):
        self.data.extend(_cmd(ESC, b"a", b"\x01"))

    def align_left(self):
        self.data.extend(_cmd(ESC, b"a", b"\x00"))

    def align_right(self):
        self.data.extend(_cmd(ESC, b"a", b"\x02"))

    def bold_on(self):
        self.data.extend(_cmd(ESC, b"E", b"\x01"))

    def bold_off(self):
        self.data.extend(_cmd(ESC, b"E", b"\x00"))

    def text(self, text: str):
        self.data.extend(_text(text))

    def line(self, text: str = ""):
        self.text(text + "\n")

    def separator(self):
        self.line(_line("-", self.width))

    def double_separator(self):
        self.line(_line("=", self.width))

    def item_line(self, name: str, qty: int, unit_price: float, total: float):
        max_name_len = self.width - 10
        display_name = name[:max_name_len]
        qty_str = f"{qty}x"
        self.line(f"{display_name:<{max_name_len}} {qty_str:>8}")
        unit_str = _format_money(unit_price)
        total_str = _format_money(total)
        right_text = f"{unit_str}  {total_str}"
        self.line(_right(right_text, self.width))

    def total_line(self, label: str, value: float):
        value_str = _format_money(value)
        available = self.width - len(value_str)
        label_truncated = label[: max(available - 2, 0)]
        self.line(f"{label_truncated}{' ' * (available - len(label_truncated))}{value_str}")

    def cut(self):
        self.data.extend(b"\n\n\n")
        self.data.extend(_cmd(GS, b"V", b"\x00"))

    def size(self, width: int, height: int):
        """Altera o tamanho da fonte. width e height devem ser de 1 a 8."""
        # O protocolo ESC/POS aceita valores de 0 a 7 (que representam 1x a 8x)
        w = max(0, min(7, width - 1))
        h = max(0, min(7, height - 1))
        # O byte é calculado juntando a largura e a altura
        n = (w << 4) | h
        self.data.extend(_cmd(GS, b"!", bytes([n])))

    def build(self) -> bytes:
        return bytes(self.data)


async def _load_printer_config(printer_id: str) -> dict | None:
    async with async_session() as db:
        ip = await get_setting(db, f"printer_{printer_id}_ip", "")
        if not ip:
            return None
        return {
            "ip": ip,
            "port": await get_setting_as_int(db, f"printer_{printer_id}_port", 9100),
            "width": await get_setting_as_int(db, f"printer_{printer_id}_width", 48),
        }


async def get_printer_for_function(function: str) -> dict | None:
    async with async_session() as db:
        printer_id = await get_setting(db, f"printer_{function}", "")
        if not printer_id:
            return None
        ip = await get_setting(db, f"printer_{printer_id}_ip", "")
        if not ip:
            return None
        return {
            "id": printer_id,
            "name": await get_setting(db, f"printer_{printer_id}_name", f"Impressora {printer_id}"),
            "ip": ip,
            "port": await get_setting_as_int(db, f"printer_{printer_id}_port", 9100),
            "width": await get_setting_as_int(db, f"printer_{printer_id}_width", 48),
        }


def _send_data_to_socket(ip: str, port: int, data: bytes) -> None:
    """Synchronous helper to send data to a network printer."""
    with socket.create_connection((ip, port), timeout=5) as sock:
        sock.sendall(data)


async def _send_to_printer_backend(data: bytes, printer: dict) -> None:
    """Send raw ESC/POS data to a network printer over TCP."""
    await asyncio.to_thread(_send_data_to_socket, printer["ip"], printer["port"], data)


async def send_to_printer(data: bytes, printer_id: str | None = None) -> dict:
    config = None
    if printer_id:
        config = await _load_printer_config(printer_id)
    if not config:
        return {"success": False, "error": "Impressora não configurada"}

    try:
        await _send_to_printer_backend(data, config)
        return {"success": True}
    except socket.timeout:
        return {"success": False, "error": "Tempo esgotado ao conectar na impressora"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def send_to_function_printer(data: bytes, function: str) -> dict:
    printer = await get_printer_for_function(function)
    if not printer:
        return {"success": False, "error": f"Nenhuma impressora configurada para {function}"}

    try:
        await _send_to_printer_backend(data, printer)
        return {"success": True, "printer_name": printer["name"]}
    except socket.timeout:
        return {"success": False, "error": f"Tempo esgotado ao conectar em {printer['name']}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _background_send_to_function_printer(
    data: bytes,
    function: str,
    context: dict | None = None,
) -> None:
    from app.routers.ws import broadcast_notification

    try:
        result = await send_to_function_printer(data, function)
        if result.get("success"):
            return

        logger.warning("Printer %s failed (1st attempt): %s", function, result.get("error"))

        # Wait 2 seconds and retry once
        await asyncio.sleep(2)
        result = await send_to_function_printer(data, function)
        if result.get("success"):
            return

        logger.warning("Printer %s failed (2nd attempt): %s", function, result.get("error"))

        # Create notification after both attempts failed
        context = context or {}
        failed_printer_id = context.get("failed_printer_id") or ""
        failed_printer_name = context.get("failed_printer_name") or f"Impressora {failed_printer_id}"
        async with async_session() as db:
            notification = await create_printer_failure_notification(
                db,
                function=function,
                failed_printer_id=failed_printer_id,
                failed_printer_name=failed_printer_name,
                error=result.get("error", "Erro desconhecido"),
                order_id=context.get("order_id"),
                table_id=context.get("table_id"),
                table_number=context.get("table_number"),
                table_label=context.get("table_label"),
                round_number=context.get("round_number"),
                items=context.get("items"),
                customer_name=context.get("customer_name"),
                waiter_name=context.get("waiter_name"),
                observation=context.get("observation"),
                ficha_mode=bool(context.get("ficha_mode")),
                receipt_data=context.get("receipt_data"),
                receipt_store_info=context.get("receipt_store_info"),
            )
            await broadcast_notification(notification_to_dict(notification))
    except Exception:
        logger.exception("Unexpected error sending to printer %s", function)


def schedule_function_printer_send(
    data: bytes,
    function: str,
    context: dict | None = None,
) -> None:
    asyncio.create_task(_background_send_to_function_printer(data, function, context))


def build_order_receipt(
    order_data: dict,
    store_info: dict,
    printer_width: int = 32,
) -> bytes:
    b = EscPosBuilder(width=printer_width)

    preview_lines: list[str] = []

    def write_line(text: str, *, align: str = "left", bold: bool = False) -> None:
        if align == "center":
            b.align_center()
            preview_lines.append(_center(text, printer_width))
        else:
            b.align_left()
            preview_lines.append(text)
        if bold:
            b.bold_on()
        else:
            b.bold_off()
        b.line(text)

    def write_total(label: str, value: object, *, bold: bool = False) -> None:
        write_line(_receipt_total_line(label, value, printer_width), bold=bold)

    def separator(char: str = "-") -> None:
        write_line(_line(char, printer_width))

    printed_at = order_data.get("printed_at")
    if isinstance(printed_at, str):
        try:
            printed_at = datetime.fromisoformat(printed_at)
        except ValueError:
            printed_at = None
    if not isinstance(printed_at, datetime):
        printed_at = datetime.now(ZoneInfo("America/Sao_Paulo"))
    elif printed_at.tzinfo is None:
        printed_at = printed_at.replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
    else:
        printed_at = printed_at.astimezone(ZoneInfo("America/Sao_Paulo"))

    receipt_type = order_data.get("receipt_type", "counter_receipt")
    status_text = (order_data.get("status_text") or "").strip()
    product_total = money(order_data.get("total", 0))
    paid_product = money(order_data.get("partial_payment", 0))
    paid_service = money(order_data.get("partial_service_charge", 0))
    service_total = money(order_data.get("service_charge_amount", 0))
    service_pct = rate(order_data.get("service_charge_pct", 0))
    payment_method = order_data.get("payment_method")
    payment_labels = {
        "dinheiro": "Dinheiro",
        "pix": "PIX",
        "cartao_credito": "Cartão de crédito",
        "cartao_debito": "Cartão de débito",
        "nao_informado": "Não informado",
    }

    write_line(store_info.get("name", "LADS BEER"), align="center", bold=True)
    separator()
    write_line("NOTA NAO FISCAL", bold=True)
    if receipt_type == "table_quote" and not status_text:
        write_line("OPCOES DE PAGAMENTO", bold=True)
    if status_text:
        separator("=")
        write_line(status_text, align="center", bold=True)
        write_line("NAO COBRAR", align="center", bold=True)
        separator("=")
    write_line(f"Comanda: #{order_data.get('order_id', '')}")
    write_line(f"Mesa: {order_data.get('table_label', '')}")
    if order_data.get("customer_name"):
        write_line(f"Cliente: {order_data['customer_name']}")
    write_line(f"Data: {printed_at.strftime('%d/%m/%Y %H:%M')}")
    separator()
    write_line("ITENS CONSUMIDOS", bold=True)
    separator()

    for item in order_data.get("items", []):
        for item_line in _receipt_item_lines(
            item.get("product_name", ""),
            item.get("quantity", 1),
            item.get("unit_price", 0),
            item.get("subtotal", 0),
            printer_width,
        ):
            write_line(item_line)

    separator()

    if status_text:
        write_total("VALOR ORIGINAL", money(product_total + service_total), bold=True)
    elif receipt_type == "table_quote":
        remaining_product = money(
            order_data.get("amount_without_service", max(Decimal("0.00"), product_total - paid_product))
        )
        optional_service = money(order_data.get("optional_service_amount", 0))
        amount_with_service = money(
            order_data.get("amount_with_service", remaining_product + optional_service)
        )
        write_total("TOTAL PRODUTOS", product_total)
        if paid_product > 0:
            write_total("PAGO ANTES (PRODUTOS)", paid_product)
        if paid_service > 0:
            write_total("GORJETA JA PAGA", paid_service)
        write_total("RESTANTE PRODUTOS", remaining_product)
        write_total(f"TAXA OPCIONAL ({_format_rate(service_pct)}%)", optional_service)
        separator("=")
        write_total("A PAGAR SEM TAXA", remaining_product, bold=True)
        write_total("A PAGAR COM TAXA", amount_with_service, bold=True)
    else:
        remaining_service = money(max(Decimal("0.00"), service_total - paid_service))
        paid_now = money(
            order_data.get(
                "final_total",
                max(Decimal("0.00"), product_total - paid_product) + remaining_service,
            )
        )
        gross_total = money(product_total + service_total)
        write_total("TOTAL PRODUTOS", product_total)
        if paid_service > 0:
            write_total("GORJETA JA PAGA", paid_service)
        if remaining_service > 0:
            service_label = (
                f"TAXA ATUAL ({_format_rate(service_pct)}%)"
                if service_pct > 0
                else "GORJETA ATUAL"
            )
            write_total(service_label, remaining_service)
        if paid_product > 0 or paid_service > 0:
            write_total("TOTAL DA COMANDA", gross_total)
            write_total("PAGO ANTES", money(paid_product + paid_service))
            separator("=")
            write_total("PAGO AGORA", paid_now, bold=True)
        else:
            write_total("TOTAL PAGO", paid_now, bold=True)
        if payment_method:
            write_line(
                f"Pagamento: {payment_labels.get(payment_method, payment_method)}"
            )
        if order_data.get("amount_received") is not None:
            write_total("VALOR RECEBIDO", order_data["amount_received"])
        if order_data.get("change_amount") is not None:
            write_total("TROCO", order_data["change_amount"])

    separator()
    footer = store_info.get("ticket_footer")
    if footer:
        write_line(footer, align="center")
    write_line("Obrigado pela preferencia!", align="center")
    b.cut()

    _print_terminal_preview("NOTA", preview_lines, exact_receipt=True)

    return b.build()

def build_ficha_ticket(
    store_name: str,
    product_name: str,
    printer_width: int = 32, # 48 colunas para impressora 80mm
) -> bytes:
    """Build a minimal "ficha" ticket: store name, date/time and product."""
    b = EscPosBuilder(width=printer_width)

    b.align_center()
    b.bold_on()
    b.line(store_name)
    b.bold_off()

    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    b.line(now.strftime("%d/%m/%Y %H:%M"))
    
    b.bold_on()
    
    b.size(2, 2) 

    b.line(product_name)

    # Retorna para o tamanho normal
    b.size(1, 1)

    b.bold_off()
    b.separator()

    b.cut()

    preview_lines = [
        store_name,
        now.strftime("%d/%m/%Y %H:%M"),
        f"** {product_name} **",
    ]
    _print_terminal_preview("FICHA", preview_lines)

    return b.build()

def build_kitchen_ticket(
    table_number: int,
    round_number: int,
    prep_items: list[dict],
    waiter_name: str,
    customer_name: str | None,
    order_id: int | None,
    printer_width: int = 32,
    observation: str | None = None,
    table_label: str | None = None,
) -> bytes:
    b = EscPosBuilder(width=printer_width)

    b.align_center()
    b.bold_on()
    b.line("COZINHA")
    b.bold_off()
    b.separator()

    b.align_left()
    display_table = table_label if table_label else f"Mesa {table_number}"
    b.line(f"MESA: {display_table}")
    if order_id:
        b.line(f"COMANDA: {order_id}")
    b.line(f"PEDIDO: {round_number}")
    if customer_name:
        b.line(f"CLIENTE: {customer_name}")
    b.line(f"GARCOM: {waiter_name}")
    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    b.line(f"HORA: {now.strftime('%H:%M')}")
    b.separator()

    b.line("ITENS:")
    for p in prep_items:
        b.line(f"  {p['quantity']}x {p['name']}")

    if observation:
        b.separator()
        b.bold_on()
        b.line("OBSERVACAO:")
        b.bold_off()
        for obs_line in _wrap_text(observation, printer_width):
            b.line(obs_line)

    b.separator()

    b.cut()

    preview_lines = [
        "COZINHA",
        f"MESA: {display_table}",
    ]
    if order_id:
        preview_lines.append(f"COMANDA: {order_id}")
    preview_lines.append(f"PEDIDO: {round_number}")
    if customer_name:
        preview_lines.append(f"CLIENTE: {customer_name}")
    preview_lines.append(f"GARCOM: {waiter_name}")
    preview_lines.append(f"HORA: {now.strftime('%H:%M')}")
    preview_lines.append("-" * 32)
    for p in prep_items:
        preview_lines.append(f"  {p['quantity']}x {p['name']}")
    if observation:
        preview_lines.append("-" * 32)
        preview_lines.append("OBSERVACAO:")
        preview_lines.extend(_wrap_text(observation, 32))
    _print_terminal_preview("COZINHA", preview_lines)

    return b.build()


def build_bar_ticket(
    table_number: int,
    round_number: int,
    bar_items: list[dict],
    waiter_name: str,
    customer_name: str | None,
    order_id: int | None,
    printer_width: int = 32,
    observation: str | None = None,
    table_label: str | None = None,
) -> bytes:
    b = EscPosBuilder(width=printer_width)

    b.align_center()
    b.bold_on()
    b.line("BAR")
    b.bold_off()
    b.separator()

    b.align_left()
    display_table = table_label if table_label else f"Mesa {table_number}"
    b.line(f"MESA: {display_table}")
    if order_id:
        b.line(f"COMANDA: {order_id}")
    b.line(f"PEDIDO: {round_number}")
    if customer_name:
        b.line(f"CLIENTE: {customer_name}")
    b.line(f"GARCOM: {waiter_name}")
    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    b.line(f"HORA: {now.strftime('%H:%M')}")
    b.separator()

    b.line("BEBIDAS:")
    for b_item in bar_items:
        b.line(f"  {b_item['quantity']}x {b_item['name']}")

    if observation:
        b.separator()
        b.bold_on()
        b.line("OBSERVACAO:")
        b.bold_off()
        for obs_line in _wrap_text(observation, printer_width):
            b.line(obs_line)

    b.separator()

    b.cut()

    preview_lines = [
        "BAR",
        f"MESA: {display_table}",
    ]
    if order_id:
        preview_lines.append(f"COMANDA: {order_id}")
    preview_lines.append(f"PEDIDO: {round_number}")
    if customer_name:
        preview_lines.append(f"CLIENTE: {customer_name}")
    preview_lines.append(f"GARCOM: {waiter_name}")
    preview_lines.append(f"HORA: {now.strftime('%H:%M')}")
    preview_lines.append("-" * 32)
    for b_item in bar_items:
        preview_lines.append(f"  {b_item['quantity']}x {b_item['name']}")
    if observation:
        preview_lines.append("-" * 32)
        preview_lines.append("OBSERVACAO:")
        preview_lines.extend(_wrap_text(observation, 32))
    _print_terminal_preview("BAR", preview_lines)

    return b.build()
