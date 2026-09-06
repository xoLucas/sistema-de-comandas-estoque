from decimal import Decimal
import unittest

from app.services.money_service import cost, money, percentage_amount, rate
from app.services.payment_service import distribute_service_amount
from app.services.pricing_service import (
    calculate_margin_pct,
    calculate_selling_price,
)
from app.services.promotion_service import calculate_discounted_price
from app.services.stock_service import validate_pack_configuration
from app.models.product import Product
from app.services.backup_service import EXPORTABLE_ENTITIES
from app.routers.orders import _confirmed_receipt_items
from types import SimpleNamespace


class FinancialCalculationTests(unittest.TestCase):
    def test_money_uses_half_up_rounding(self) -> None:
        self.assertEqual(money("1.005"), Decimal("1.01"))
        self.assertEqual(money("1.004"), Decimal("1.00"))
        self.assertEqual(money(0.1 + 0.2), Decimal("0.30"))

    def test_cost_and_rate_keep_four_decimal_places(self) -> None:
        self.assertEqual(cost("1.23445"), Decimal("1.2345"))
        self.assertEqual(rate("3.45675"), Decimal("3.4568"))

    def test_percentage_amount_rounds_only_to_money_precision(self) -> None:
        self.assertEqual(
            percentage_amount(Decimal("33.35"), Decimal("10")),
            Decimal("3.34"),
        )

    def test_discounted_price_uses_canonical_money_rounding(self) -> None:
        self.assertEqual(
            calculate_discounted_price(Decimal("10.05"), Decimal("50.0000")),
            Decimal("5.03"),
        )

    def test_margin_round_trip_uses_margin_over_selling_price(self) -> None:
        selling_price = calculate_selling_price(
            Decimal("60.0000"), Decimal("40.0000")
        )
        self.assertEqual(selling_price, Decimal("100.00"))
        self.assertEqual(
            calculate_margin_pct(Decimal("60.0000"), selling_price),
            Decimal("40.0000"),
        )

    def test_invalid_margin_does_not_divide_by_zero(self) -> None:
        self.assertEqual(
            calculate_selling_price(Decimal("10"), Decimal("100")),
            Decimal("0.00"),
        )

    def test_service_distribution_preserves_exact_total(self) -> None:
        shares = distribute_service_amount(
            [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")],
            Decimal("10.00"),
        )
        self.assertEqual(shares, [Decimal("3.33"), Decimal("3.33"), Decimal("3.34")])
        self.assertEqual(sum(shares), Decimal("10.00"))

    def test_service_distribution_assigns_rounding_residue_to_last_item(self) -> None:
        shares = distribute_service_amount(
            [Decimal("0.01"), Decimal("0.01"), Decimal("0.01")],
            Decimal("0.01"),
        )
        self.assertEqual(sum(shares), Decimal("0.01"))
        self.assertEqual(shares[-1], Decimal("0.01"))

    def test_invalid_pack_configuration_blocks_stock_operations(self) -> None:
        product = Product(
            name="Invalid Pack",
            category="Test",
            price=Decimal("10.00"),
            pack_unit_product_id=123,
            pack_size=1,
        )
        with self.assertRaisesRegex(ValueError, "quantidade por engradado inválida"):
            validate_pack_configuration(product)

    def test_csv_exports_include_normalized_financial_ledger(self) -> None:
        required = {
            "pagamentos_comandas",
            "alocacoes_pagamentos_comandas",
            "estornos_pagamentos",
            "itens_estornos_pagamentos",
            "itens_consignados",
            "pagamentos_consignados",
            "caixa_sessoes",
            "caixa_movimentacoes",
            "movimentos_posicao_caixa",
            "pagamentos_diarias",
            "despesas",
        }
        self.assertTrue(required.issubset(EXPORTABLE_ENTITIES))

    def test_pending_items_are_never_in_receipt_items(self) -> None:
        product = SimpleNamespace(name="Product")
        order = SimpleNamespace(
            items=[
                SimpleNamespace(
                    product=product,
                    quantity=1,
                    unit_price=Decimal("10.00"),
                    is_pending=False,
                ),
                SimpleNamespace(
                    product=product,
                    quantity=2,
                    unit_price=Decimal("5.00"),
                    is_pending=True,
                ),
            ]
        )
        items = _confirmed_receipt_items(order)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["subtotal"], 10.0)


if __name__ == "__main__":
    unittest.main()
