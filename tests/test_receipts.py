from contextlib import redirect_stdout
from io import StringIO
import unittest

from app.services.notification_service import create_printer_failure_notification
from app.services.printer_service import build_order_receipt


class ReceiptRenderingTests(unittest.TestCase):
    def _render(self, data: dict) -> tuple[str, str]:
        terminal = StringIO()
        with redirect_stdout(terminal):
            receipt = build_order_receipt(
                data,
                {"name": "Lads Beer", "ticket_footer": "Volte sempre"},
                48,
            )
        return receipt.decode("cp850", errors="ignore"), terminal.getvalue()

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
            self.assertIn("A PAGAR SEM TAXA", output)
            self.assertIn("A PAGAR COM TAXA", output)
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
