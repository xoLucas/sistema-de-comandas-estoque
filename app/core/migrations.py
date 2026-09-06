"""Small, transactional schema migration runner for on-premise deployments."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.database import engine


Migration = tuple[str, Callable[[AsyncConnection], Awaitable[None]]]


async def _financial_integrity_schema(conn: AsyncConnection) -> None:
    statements = [
        "ALTER TABLE consignment_orders ADD COLUMN IF NOT EXISTS product_total NUMERIC(14,2) NOT NULL DEFAULT 0",
        "ALTER TABLE consignment_orders ADD COLUMN IF NOT EXISTS service_total NUMERIC(14,2) NOT NULL DEFAULT 0",
        "ALTER TABLE consignment_payments ADD COLUMN IF NOT EXISTS product_portion NUMERIC(14,2) NOT NULL DEFAULT 0",
        "ALTER TABLE consignment_payments ADD COLUMN IF NOT EXISTS card_fee_rate NUMERIC(7,4) NOT NULL DEFAULT 0",
        "ALTER TABLE consignment_payments ADD COLUMN IF NOT EXISTS card_fee_amount NUMERIC(14,2) NOT NULL DEFAULT 0",
        "ALTER TABLE consignment_payments ADD COLUMN IF NOT EXISTS cash_session_id INTEGER REFERENCES cash_register_sessions(id)",
        "ALTER TABLE consignment_payments ADD COLUMN IF NOT EXISTS source_order_payment_id INTEGER REFERENCES order_payments(id)",
        "ALTER TABLE consignment_payments ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)",
        "ALTER TABLE consignment_payments ADD COLUMN IF NOT EXISTS is_legacy_inferred BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE stock_history ADD COLUMN IF NOT EXISTS unit_cost_snapshot NUMERIC(14,4)",
        "ALTER TABLE stock_history ADD COLUMN IF NOT EXISTS source_product_id INTEGER REFERENCES products(id)",
        "ALTER TABLE stock_history ADD COLUMN IF NOT EXISTS source_quantity INTEGER",
        "ALTER TABLE stock_history ADD COLUMN IF NOT EXISTS conversion_factor INTEGER",
        "ALTER TABLE cash_position_movements ADD COLUMN IF NOT EXISTS refund_id INTEGER REFERENCES payment_refunds(id)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS close_idempotency_key VARCHAR(64)",
        "ALTER TABLE payment_refunds ALTER COLUMN payment_id DROP NOT NULL",
        "ALTER TABLE payment_refunds ALTER COLUMN order_id DROP NOT NULL",
        "ALTER TABLE payment_refunds ADD COLUMN IF NOT EXISTS consignment_payment_id INTEGER REFERENCES consignment_payments(id)",
        "ALTER TABLE payment_refunds ADD COLUMN IF NOT EXISTS consignment_order_id INTEGER REFERENCES consignment_orders(id)",
        "ALTER TABLE products ALTER COLUMN cost TYPE NUMERIC(14,4) USING ROUND(cost::numeric, 4)",
        "ALTER TABLE products ALTER COLUMN margin_pct TYPE NUMERIC(7,4) USING ROUND(margin_pct::numeric, 4)",
        "ALTER TABLE products ALTER COLUMN price TYPE NUMERIC(14,2) USING ROUND(price::numeric, 2)",
        "ALTER TABLE promotions ALTER COLUMN discount_pct TYPE NUMERIC(7,4) USING ROUND(discount_pct::numeric, 4)",
        "ALTER TABLE orders ALTER COLUMN total TYPE NUMERIC(14,2) USING ROUND(total::numeric, 2)",
        "ALTER TABLE orders ALTER COLUMN partial_payment TYPE NUMERIC(14,2) USING ROUND(partial_payment::numeric, 2)",
        "ALTER TABLE orders ALTER COLUMN partial_service_charge TYPE NUMERIC(14,2) USING ROUND(partial_service_charge::numeric, 2)",
        "ALTER TABLE orders ALTER COLUMN service_charge_pct TYPE NUMERIC(7,4) USING ROUND(service_charge_pct::numeric, 4)",
        "ALTER TABLE orders ALTER COLUMN service_charge_amount TYPE NUMERIC(14,2) USING ROUND(service_charge_amount::numeric, 2)",
        "ALTER TABLE order_items ALTER COLUMN unit_price TYPE NUMERIC(14,2) USING ROUND(unit_price::numeric, 2)",
        "ALTER TABLE order_items ALTER COLUMN unit_cost TYPE NUMERIC(14,4) USING ROUND(unit_cost::numeric, 4)",
        "ALTER TABLE consignment_orders ALTER COLUMN total TYPE NUMERIC(14,2) USING ROUND(total::numeric, 2)",
        "ALTER TABLE consignment_orders ALTER COLUMN amount_paid TYPE NUMERIC(14,2) USING ROUND(amount_paid::numeric, 2)",
        "ALTER TABLE consignment_orders ALTER COLUMN balance TYPE NUMERIC(14,2) USING ROUND(balance::numeric, 2)",
        "ALTER TABLE consignment_order_items ALTER COLUMN unit_price TYPE NUMERIC(14,2) USING ROUND(unit_price::numeric, 2)",
        "ALTER TABLE consignment_order_items ALTER COLUMN unit_cost TYPE NUMERIC(14,4) USING ROUND(unit_cost::numeric, 4)",
        "ALTER TABLE consignment_payments ALTER COLUMN amount TYPE NUMERIC(14,2) USING ROUND(amount::numeric, 2)",
        "ALTER TABLE consignment_payments ALTER COLUMN service_portion TYPE NUMERIC(14,2) USING ROUND(service_portion::numeric, 2)",
        "ALTER TABLE cash_register_sessions ALTER COLUMN initial_cash TYPE NUMERIC(14,2) USING ROUND(initial_cash::numeric, 2)",
        "ALTER TABLE cash_register_sessions ALTER COLUMN final_cash TYPE NUMERIC(14,2) USING ROUND(final_cash::numeric, 2)",
        "ALTER TABLE cash_register_movements ALTER COLUMN amount TYPE NUMERIC(14,2) USING ROUND(amount::numeric, 2)",
        "ALTER TABLE cash_position_movements ALTER COLUMN amount TYPE NUMERIC(14,2) USING ROUND(amount::numeric, 2)",
        "ALTER TABLE daily_payments ALTER COLUMN amount TYPE NUMERIC(14,2) USING ROUND(amount::numeric, 2)",
        "ALTER TABLE expenses ALTER COLUMN amount TYPE NUMERIC(14,2) USING ROUND(amount::numeric, 2)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_cash_register_single_open ON cash_register_sessions ((status)) WHERE status = 'open'",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_consignment_source_order ON consignment_orders (source_order_id) WHERE source_order_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_consignment_payment_source_order_payment ON consignment_payments (source_order_payment_id) WHERE source_order_payment_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_consignment_payment_idempotency ON consignment_payments (idempotency_key) WHERE idempotency_key IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_cash_position_refund ON cash_position_movements (refund_id) WHERE refund_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_close_idempotency ON orders (close_idempotency_key) WHERE close_idempotency_key IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_payment_refunds_consignment_payment_id ON payment_refunds (consignment_payment_id)",
        "CREATE INDEX IF NOT EXISTS ix_payment_refunds_consignment_order_id ON payment_refunds (consignment_order_id)",
    ]
    for statement in statements:
        await conn.execute(text(statement))


async def _refund_service_recognition_schema(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            "ALTER TABLE payment_refunds "
            "ADD COLUMN IF NOT EXISTS service_was_recognized "
            "BOOLEAN NOT NULL DEFAULT TRUE"
        )
    )


async def _refund_sale_recognition_schema(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            "ALTER TABLE payment_refunds "
            "ADD COLUMN IF NOT EXISTS sale_was_recognized "
            "BOOLEAN NOT NULL DEFAULT TRUE"
        )
    )


async def _consignment_credited_waiter_schema(conn: AsyncConnection) -> None:
    statements = [
        "ALTER TABLE consignment_orders ADD COLUMN IF NOT EXISTS credited_waiter_id INTEGER REFERENCES employees(id) ON DELETE SET NULL",
        "ALTER TABLE consignment_orders ADD COLUMN IF NOT EXISTS credited_waiter_name VARCHAR(100)",
        "CREATE INDEX IF NOT EXISTS ix_consignment_orders_credited_waiter_id ON consignment_orders (credited_waiter_id)",
    ]
    for statement in statements:
        await conn.execute(text(statement))


async def _payment_refund_compatibility_schema(conn: AsyncConnection) -> None:
    statements = [
        "ALTER TABLE payment_refunds ADD COLUMN IF NOT EXISTS refund_group_key VARCHAR(64)",
        "ALTER TABLE payment_refunds ADD COLUMN IF NOT EXISTS service_already_repassed BOOLEAN",
        "UPDATE payment_refunds SET refund_group_key = 'legacy-refund:' || id WHERE refund_group_key IS NULL OR btrim(refund_group_key) = ''",
        """
        UPDATE payment_refunds AS refund
        SET service_already_repassed = CASE
            WHEN source_session.closed_at IS NOT NULL
             AND source_session.closed_at <= refund.created_at
            THEN TRUE
            ELSE FALSE
        END
        FROM order_payments AS payment
        LEFT JOIN cash_register_sessions AS source_session
          ON source_session.id = payment.cash_session_id
        WHERE refund.service_already_repassed IS NULL
          AND refund.payment_id = payment.id
        """,
        """
        UPDATE payment_refunds AS refund
        SET service_already_repassed = CASE
            WHEN source_session.closed_at IS NOT NULL
             AND source_session.closed_at <= refund.created_at
            THEN TRUE
            ELSE FALSE
        END
        FROM consignment_payments AS payment
        LEFT JOIN cash_register_sessions AS source_session
          ON source_session.id = payment.cash_session_id
        WHERE refund.service_already_repassed IS NULL
          AND refund.consignment_payment_id = payment.id
        """,
        "UPDATE payment_refunds SET service_already_repassed = FALSE WHERE service_already_repassed IS NULL",
        "ALTER TABLE payment_refunds ALTER COLUMN refund_group_key SET NOT NULL",
        "ALTER TABLE payment_refunds ALTER COLUMN service_already_repassed SET DEFAULT FALSE",
        "ALTER TABLE payment_refunds ALTER COLUMN service_already_repassed SET NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_payment_refunds_refund_group_key ON payment_refunds (refund_group_key)",
    ]
    for statement in statements:
        await conn.execute(text(statement))


async def _product_pack_validation_schema(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'ck_product_pack_configuration'
                ) THEN
                    ALTER TABLE products
                    ADD CONSTRAINT ck_product_pack_configuration
                    CHECK (
                        (pack_unit_product_id IS NULL AND pack_size = 1)
                        OR
                        (pack_unit_product_id IS NOT NULL AND pack_size >= 2)
                    ) NOT VALID;
                END IF;
            END
            $$
            """
        )
    )


MIGRATIONS: tuple[Migration, ...] = (
    ("20260905_01_financial_integrity_schema", _financial_integrity_schema),
    ("20260906_03_refund_service_recognition", _refund_service_recognition_schema),
    ("20260906_04_refund_sale_recognition", _refund_sale_recognition_schema),
    ("20260906_05_consignment_credited_waiter", _consignment_credited_waiter_schema),
    ("20260906_06_payment_refund_compatibility", _payment_refund_compatibility_schema),
    ("20260906_07_product_pack_validation", _product_pack_validation_schema),
)


async def run_migrations() -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(100) PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )

    for version, migration in MIGRATIONS:
        async with engine.begin() as conn:
            applied = await conn.scalar(
                text("SELECT 1 FROM schema_migrations WHERE version = :version"),
                {"version": version},
            )
            if applied:
                continue
            await migration(conn)
            await conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": version},
            )
