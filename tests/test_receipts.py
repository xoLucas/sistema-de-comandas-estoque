from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from app.services import printer_service
from app.services.notification_service import create_printer_failure_notification
from app.services.printer_service import (
    build_bar_ticket,
    build_ficha_ticket,
    build_kitchen_ticket,
    build_order_receipt,
)

# Register the complete model graph before this isolated notification test
# instantiates an ORM object.
import app.core.seed  # noqa: F401


def _strip_raster(data: bytes) -> bytes:
    """Remove ESC/POS raster bitmap commands (GS v 0) from raw ticket bytes."""
    output = bytearray()
    index = 0
    while index < len(data):
        if data[index : index + 3] == b"\x1dv0" and index + 8 <= len(data):
            width_bytes = data[index + 4] + (data[index + 5] << 8)
            height = data[index + 6] + (data[index + 7] << 8)
            index += 8 + width_bytes * height
            continue
        output.append(data[index])
        index += 1
    return bytes(output)


class ReceiptRenderingTests(unittest.TestCase):
    def _render(self, data: dict) -> tuple[str, str]:
        terminal = StringIO()
        with redirect_stdout(terminal):
            receipt = build_order_receipt(
                data,
                {"name": "Lads Beer", "ticket_footer": "Volte sempre"},
                48,
            )
        printed_text = _strip_raster(receipt).decode("cp850", errors="ignore")
        printed_lines = re.sub(r"\x1b@|\x1ba.|\x1bE.|\x1dV\x00", "", printed_text)
        printed_lines = [line.strip() for line in printed_lines.splitlines() if line.strip()]
        terminal_lines = [
            line.strip()
            for line in terminal.getvalue().splitlines()
            if line.strip() and line.strip() != "[LOGO]"
        ]
        self.assertEqual(printed_lines, terminal_lines)
        return printed_text, terminal.getvalue()

    def test_table_quote_always_shows_both_service_options(self) -> None:
        receipt, terminal = self._render(
            {
                "receipt_type": "table_quote",
                "order_id": 1,
                "table_label": "Mesa 1",
                "items": [
                    {
                        "product_name": "Espetinho",
                        "quantity": 2,
                        "unit_price": 10,
                        "subtotal": 20,
                    }
                ],
                "total": 20,
                "partial_payment": 5,
                "partial_service_charge": 0,
                "service_charge_pct": 10,
                "optional_service_amount": 1.5,
                "amount_without_service": 15,
                "amount_with_service": 16.5,
                "printed_at": "2026-09-06T12:00:00+00:00",
            }
        )

        for output in (receipt, terminal):
            self.assertIn("SUBTOTAL", output)
            self.assertIn("TAXA OPCIONAL (10%)", output)
            self.assertIn("TOTAL", output)
            self.assertIn("R$ 15,00", output)
            self.assertIn("R$ 16,50", output)
        self.assertNotIn("IMPRESSORA TERMINAL", terminal)

    def test_counter_receipt_shows_received_and_change(self) -> None:
        receipt, terminal = self._render(
            {
                "receipt_type": "counter_receipt",
                "order_id": 2,
                "table_label": "Balcão",
                "items": [
                    {
                        "product_name": "Cerveja",
                        "quantity": 1,
                        "unit_price": 12,
                        "subtotal": 12,
                    }
                ],
                "total": 12,
                "service_charge_pct": 10.5,
                "service_charge_amount": 1.26,
                "partial_payment": 0,
                "partial_service_charge": 0,
                "final_total": 13.26,
                "payment_method": "dinheiro",
                "amount_received": 20,
                "change_amount": 6.74,
                "printed_at": "2026-09-06T12:00:00+00:00",
            }
        )

        for output in (receipt, terminal):
            self.assertIn("TAXA ATUAL (10.5%)", output)
            self.assertIn("VALOR RECEBIDO", output)
            self.assertIn("TROCO", output)
            self.assertIn("R$ 20,00", output)
            self.assertIn("R$ 6,74", output)

    def test_refunded_receipt_is_marked_not_to_charge(self) -> None:
        receipt, terminal = self._render(
            {
                "receipt_type": "counter_receipt",
                "status_text": "NOTA ESTORNADA",
                "order_id": 3,
                "table_label": "Mesa 3",
                "items": [
                    {
                        "product_name": "Produto",
                        "quantity": 1,
                        "unit_price": 10,
                        "subtotal": 10,
                    }
                ],
                "total": 10,
                "service_charge_amount": 1,
                "printed_at": "2026-09-06T12:00:00+00:00",
            }
        )

        for output in (receipt, terminal):
            self.assertIn("NOTA ESTORNADA", output)
            self.assertIn("NAO COBRAR", output)
            self.assertIn("VALOR ORIGINAL", output)


class ReceiptFailureSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_printer_failure_keeps_the_complete_receipt_snapshot(self) -> None:
        class MemorySession:
            notification = None

            def add(self, value) -> None:
                self.notification = value

            async def commit(self) -> None:
                return None

            async def refresh(self, value) -> None:
                return None

        db = MemorySession()
        receipt_data = {
            "receipt_type": "counter_receipt",
            "total": 10,
            "amount_received": 20,
            "change_amount": 10,
            "printed_at": "2026-09-06T12:00:00+00:00",
        }
        notification = await create_printer_failure_notification(
            db,
            function="nota",
            failed_printer_id="1",
            failed_printer_name="Nota",
            error="offline",
            receipt_data=receipt_data,
            receipt_store_info={"name": "Lads Beer"},
        )

        self.assertEqual(notification.details["receipt_data"], receipt_data)
        self.assertEqual(
            notification.details["receipt_store_info"], {"name": "Lads Beer"}
        )


class LogoRasterTests(unittest.TestCase):
    def _make_logo(self, directory: str, name: str = "logo.png") -> Path:
        path = Path(directory) / name
        image = Image.new("RGBA", (1368, 514), (255, 255, 255, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((100, 100, 1268, 414), fill=(0, 0, 0, 255))
        image.save(path)
        return path

    def test_raster_header_and_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_logo(tmp)
            with patch.object(printer_service, "LOGO_CANDIDATES", (path,)):
                raster = printer_service.load_logo_raster(48)

        self.assertIsNotNone(raster)
        self.assertEqual(raster[:4], b"\x1dv0\x00")
        width_bytes = raster[4] + (raster[5] << 8)
        height = raster[6] + (raster[7] << 8)
        self.assertEqual(width_bytes, 43)
        self.assertEqual(height, 129)
        self.assertEqual(len(raster) - 8, width_bytes * height)

    def test_transparent_background_becomes_white(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_logo(tmp)
            with patch.object(printer_service, "LOGO_CANDIDATES", (path,)):
                raster = printer_service.load_logo_raster(48)

        width_bytes = raster[4] + (raster[5] << 8)
        bitmap = raster[8:]
        self.assertEqual(bitmap[:width_bytes], b"\x00" * width_bytes)
        self.assertIn(0xFF, bitmap)

    def test_missing_logo_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.png"
            with patch.object(printer_service, "LOGO_CANDIDATES", (missing,)):
                self.assertIsNone(printer_service.load_logo_raster(48))

    def test_repo_logo_renders_for_both_widths(self) -> None:
        self.assertIsNotNone(printer_service.load_logo_raster(48))
        self.assertIsNotNone(printer_service.load_logo_raster(32))

    def test_nota_and_ficha_include_logo_but_production_tickets_do_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_logo(tmp)
            with patch.object(printer_service, "LOGO_CANDIDATES", (path,)):
                with redirect_stdout(StringIO()):
                    nota = build_order_receipt({"items": [], "total": 0}, {"name": "Lads"}, 48)
                    ficha = build_ficha_ticket("Lads", "Espetinho", 48)
                    kitchen = build_kitchen_ticket(1, 1, [{"quantity": 1, "name": "X"}], "Ana", None, 1, 48)
                    bar = build_bar_ticket(1, 1, [{"quantity": 1, "name": "Y"}], "Ana", None, 1, 48)

        self.assertIn(b"\x1dv0", nota)
        self.assertIn(b"\x1dv0", ficha)
        self.assertNotIn(b"\x1dv0", kitchen)
        self.assertNotIn(b"\x1dv0", bar)
