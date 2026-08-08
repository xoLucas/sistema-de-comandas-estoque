import asyncio
import logging
import socket
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.database import async_session
from app.services.notification_service import (
    create_printer_failure_notification,
    notification_to_dict,
)
from app.services.settings_service import get_setting, get_setting_as_int

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


def _format_money(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _print_terminal_preview(title: str, lines: list[str]) -> None:
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

    b.align_center()
    b.bold_on()
    b.line(store_info.get("name", "LADS BEER"))
    b.bold_off()

    for field in ["address", "phone", "cnpj"]:
        value = store_info.get(field)
        if value:
            b.line(value)

    b.separator()

    b.align_left()
    b.bold_on()
    b.line("NOTA NAO FISCAL")
    b.bold_off()
    b.line(f"Comanda: #{order_data.get('order_id', '')}")
    b.line(f"Mesa: {order_data.get('table_label', '')}")
    if order_data.get("customer_name"):
        b.line(f"Cliente: {order_data['customer_name']}")

    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    b.line(f"Data: {now.strftime('%d/%m/%Y %H:%M')}")
    b.separator()

    b.line("ITENS CONSUMIDOS")
    b.separator()

    for item in order_data.get("items", []):
        b.item_line(
            name=item.get("product_name", ""),
            qty=item.get("quantity", 1),
            unit_price=item.get("unit_price", 0.0),
            total=item.get("subtotal", 0.0),
        )

    b.separator()

    total = order_data.get("total", 0.0)
    service_charge = order_data.get("service_charge_amount", 0.0)
    final_total = order_data.get("final_total", total)

    if service_charge > 0:
        b.total_line("Subtotal", total)
        b.total_line(f"Taxa Servico ({order_data.get('service_charge_pct', 0):.0f}%)", service_charge)
        b.double_separator()
        b.bold_on()
        b.total_line("TOTAL", final_total)
        b.bold_off()
    else:
        b.bold_on()
        b.total_line("TOTAL", total)
        b.bold_off()

    if order_data.get("payment_method"):
        b.line(f"Forma de pagamento: {order_data['payment_method']}")

    if order_data.get("partial_payment", 0) > 0:
        b.total_line("Pago anteriormente", order_data["partial_payment"])
        b.total_line("Restante a pagar", max(0, final_total - order_data["partial_payment"]))

    b.separator()
    b.align_center()
    footer = store_info.get("ticket_footer")
    if footer:
        b.line(footer)
    b.line("Documento sem valor fiscal")
    b.line("Obrigado pela preferencia!")
    b.cut()

    preview_lines = [
        store_info.get("name", "LADS BEER"),
        f"NOTA NAO FISCAL - Comanda #{order_data.get('order_id', '')}",
        f"Mesa: {order_data.get('table_label', '')}",
    ]
    if order_data.get("customer_name"):
        preview_lines.append(f"Cliente: {order_data['customer_name']}")
    preview_lines.append(f"Data: {now.strftime('%d/%m/%Y %H:%M')}")
    preview_lines.append("-" * 32)
    for item in order_data.get("items", []):
        preview_lines.append(f"{item.get('quantity', 1)}x {item.get('product_name', '')} - {_format_money(item.get('subtotal', 0.0))}")
    preview_lines.append("-" * 32)
    preview_lines.append(f"TOTAL: {_format_money(total if service_charge <= 0 else final_total)}")
    if order_data.get("payment_method"):
        preview_lines.append(f"Pagamento: {order_data['payment_method']}")
    _print_terminal_preview("NOTA", preview_lines)

    return b.build()


def build_kitchen_ticket(
    table_number: int,
    round_number: int,
    prep_items: list[dict],
    waiter_name: str,
    customer_name: str | None,
    order_id: int | None,
    printer_width: int = 32,
) -> bytes:
    b = EscPosBuilder(width=printer_width)

    b.align_center()
    b.bold_on()
    b.line("COZINHA")
    b.bold_off()
    b.separator()

    b.align_left()
    b.line(f"MESA: {table_number}")
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
    b.separator()

    b.cut()

    preview_lines = [
        "COZINHA",
        f"MESA: {table_number}",
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
) -> bytes:
    b = EscPosBuilder(width=printer_width)

    b.align_center()
    b.bold_on()
    b.line("BAR")
    b.bold_off()
    b.separator()

    b.align_left()
    b.line(f"MESA: {table_number}")
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
    b.separator()

    b.cut()

    preview_lines = [
        "BAR",
        f"MESA: {table_number}",
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
    _print_terminal_preview("BAR", preview_lines)

    return b.build()
