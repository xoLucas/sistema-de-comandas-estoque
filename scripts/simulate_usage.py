"""End-to-end simulation of a realistic business day for the Lads Beer system.

Creates two cash-register sessions, several orders, payments, expenses, stock
losses and consignments, back-dates the timestamps to two different days, and
prints the resulting dashboard and reports.

Run with: python3 scripts/simulate_usage.py

Requires dev dependencies from requirements-dev.txt (requests).
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

BASE_URL = "http://localhost:8000"
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
WORK_DIR = "/home/xolucas/projects/mvp-sistema-lads-beer"

PRODUCTS = {
    "water": {"id": 77, "price": 5.0, "cost": 2.5},
    "amstel_can": {"id": 6, "price": 7.0, "cost": 4.0},
    "amstel_bottle": {"id": 1, "price": 9.0, "cost": 6.0},  # discounted
    "vodka": {"id": 40, "price": 120.0, "cost": 50.0},
}

CUSTOMERS = {}
EMPLOYEES = {}

USERS = {
    "gerente": ("gerente", "admin123"),
    "caixa": ("caixa", "caixa123"),
    "estoquista": ("estoquista", "estoque123"),
    "lara": ("Lara", "123456"),
    "lucy": ("Lucy", "123456"),
}

TABLES = {
    "t3": 3,
    "t4": 4,
    "t5": 5,
    "t6": 6,
    "t7": 7,
    "balcao": 14,  # upserted table number 100
}


def local_to_utc(local_iso: str) -> str:
    """Convert a local Brasília datetime string to UTC ISO format."""
    dt = datetime.fromisoformat(local_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(timezone.utc).isoformat()


def get_token(username: str, password: str) -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def api_call(method: str, path: str, token: str, data=None):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.request(
        method, f"{BASE_URL}{path}", headers=headers, json=data, timeout=10
    )
    try:
        return r.json()
    except Exception as exc:
        return {"error": f"non-json response: {r.text}", "status_code": r.status_code}


def run_sql(sql: str):
    """Run a SQL script inside the Postgres container via psql (stdin)."""
    subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "postgres",
            "-d",
            "ladsbeer",
            "-f",
            "-",
        ],
        cwd=WORK_DIR,
        input=sql,
        text=True,
        check=True,
    )


def prepare_products():
    """Update costs and stock for the products used in the simulation."""
    sql = ""
    for key, p in PRODUCTS.items():
        sql += (
            f"UPDATE products SET cost = {p['cost']}, stock = 200 "
            f"WHERE id = {p['id']};\n"
        )
    sql += (
        "INSERT INTO tables (number, status, is_balcao) "
        "VALUES (100, 'vazia', true) "
        "ON CONFLICT (number) DO UPDATE SET is_balcao = true;\n"
    )
    run_sql(sql)

    # Resolve the balcao table id dynamically so the script works on a clean seed.
    result = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "db", "psql",
            "-U", "postgres", "-d", "ladsbeer", "-t", "-A", "-c",
            "SELECT id FROM tables WHERE is_balcao = true ORDER BY (number = 100) DESC, number LIMIT 1;",
        ],
        cwd=WORK_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    balcao_id = int(result.stdout.strip().splitlines()[0])
    TABLES["balcao"] = balcao_id


def create_customer(token: str, name: str, customer_type: str = "pf"):
    return api_call(
        "POST",
        "/api/clientes",
        token,
        {"name": name, "customer_type": customer_type, "active": True},
    )


def create_employee(token: str, name: str, role: str, username: str | None = None, password: str | None = None):
    data = {
        "name": name,
        "role": role,
        "active": True,
        "create_login": bool(username and password),
        "username": username,
        "password": password,
        "login_role": "garcom" if role == "garcom" else role,
    }
    return api_call("POST", "/api/funcionarios", token, data)


def open_cash(token: str, initial: float):
    return api_call("POST", "/api/caixa/abrir", token, {"initial_cash": initial})


def close_cash(token: str, final: float):
    return api_call("POST", "/api/caixa/fechar", token, {"final_cash": final})


def add_movement(token: str, movement_type: str, amount: float, note: str):
    return api_call(
        "POST",
        "/api/caixa/movimentacoes",
        token,
        {"type": movement_type, "amount": amount, "note": note},
    )


def open_order(token: str, table_id: int, customer_name: str):
    return api_call(
        "POST",
        "/api/comanda/abrir",
        token,
        {"table_id": table_id, "customer_name": customer_name},
    )


def add_items(token: str, table_id: int, order_id: int, items: list):
    return api_call(
        "POST",
        "/api/comanda/pedido",
        token,
        {"table_id": table_id, "order_id": order_id, "items": items},
    )


def partial_payment(token: str, table_id: int, order_id: int, amount: float, method: str):
    return api_call(
        "POST",
        "/api/comanda/pagamento-parcial",
        token,
        {
            "table_id": table_id,
            "order_id": order_id,
            "amount": amount,
            "payment_method": method,
        },
    )


def close_order(token: str, table_id: int, order_id: int, method: str):
    return api_call(
        "POST",
        "/api/comanda/fechar",
        token,
        {"table_id": table_id, "order_id": order_id, "payment_method": method},
    )


def create_consignment(token: str, customer_id: int, items: list):
    return api_call(
        "POST",
        "/api/consignados",
        token,
        {"customer_id": customer_id, "items": items},
    )


def pay_consignment(token: str, consignment_id: int, amount: float, method: str):
    return api_call(
        "POST",
        f"/api/consignados/{consignment_id}/pagamento",
        token,
        {"amount": amount, "payment_method": method},
    )


def pay_daily(token: str, employee_id: int, amount: float, payment_date: str):
    return api_call(
        "POST",
        "/api/funcionarios/diaria",
        token,
        {"employee_id": employee_id, "amount": amount, "payment_date": payment_date},
    )


def stock_movement(token: str, product_id: int, quantity: int, note: str):
    return api_call(
        "POST",
        f"/api/estoque/{product_id}/movimentacao",
        token,
        {"type": "saida", "quantity": quantity, "note": note},
    )


def get_active_cash(token: str):
    return api_call("GET", "/api/caixa/ativo", token)


def get_dashboard(token: str):
    return api_call("GET", "/api/financeiro/dashboard", token)


def get_daily_report(token: str, date_str: str):
    return api_call(
        "POST", "/api/financeiro/fechamento-diario", token, {"date": date_str}
    )


def get_session_report(token: str, session_id: int):
    return api_call(
        "GET", f"/api/financeiro/sessao/{session_id}/relatorio-final", token
    )


def get_pdf(token: str, session_id: int):
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.post(
        f"{BASE_URL}/api/financeiro/relatorio-pdf",
        headers=headers,
        json={"session_id": session_id},
        timeout=30,
    )
    return r.status_code, len(r.content)


class Simulation:
    def __init__(self):
        # Get the gerente token first so we can create customers and employees.
        gerente_token = get_token("gerente", "admin123")
        self._prepare_entities(gerente_token)
        self.tokens = {role: get_token(u, p) for role, (u, p) in USERS.items()}
        self.state = []
        self.sql_updates = []

    def _prepare_entities(self, gerente_token: str):
        """Create customers and employees (with login) required by the simulation."""
        global CUSTOMERS, EMPLOYEES
        for key, name in [
            ("lucas", "Lucas"),
            ("jenna", "Jenna Ortega"),
            ("pinao", "Pinao"),
        ]:
            result = create_customer(gerente_token, name)
            if "error" in result:
                raise RuntimeError(f"Failed to create customer {name}: {result}")
            CUSTOMERS[key] = result["id"]

        for key, name, username in [
            ("lucy", "Lucy Greyrat", "Lucy"),
            ("lara", "Lara Greyrat", "Lara"),
            ("lily", "Lily Greyrat", "Lily"),
        ]:
            result = create_employee(
                gerente_token, name, "garcom", username=username, password="123456"
            )
            if "error" in result:
                raise RuntimeError(f"Failed to create employee {name}: {result}")
            EMPLOYEES[key] = result["id"]

    def record_session(self, session_id: int, opened_local: str, closed_local: str):
        self.sql_updates.append(
            f"UPDATE cash_register_sessions SET opened_at = '{local_to_utc(opened_local)}', "
            f"closed_at = '{local_to_utc(closed_local)}' WHERE id = {session_id};"
        )

    def record_movement(self, movement_id: int, local_time: str):
        self.sql_updates.append(
            f"UPDATE cash_register_movements SET created_at = '{local_to_utc(local_time)}' "
            f"WHERE id = {movement_id};"
        )

    def record_order(
        self,
        order_id: int,
        created_local: str,
        closed_local: str | None,
        partial_payments: list,
    ):
        self.sql_updates.append(
            f"UPDATE orders SET created_at = '{local_to_utc(created_local)}' "
            f"WHERE id = {order_id};"
        )
        if closed_local:
            self.sql_updates.append(
                f"UPDATE orders SET closed_at = '{local_to_utc(closed_local)}' "
                f"WHERE id = {order_id};"
            )
        if partial_payments:
            details = []
            for i, pp in enumerate(partial_payments):
                details.append(
                    {
                        "amount": pp["amount"],
                        "product_portion": pp["amount"],  # no service charge
                        "service_portion": 0.0,
                        "method": pp["method"],
                        "card_machine": None,
                        "apply_service_charge": False,
                        "created_at": local_to_utc(pp["time"]),
                    }
                )
            self.sql_updates.append(
                f"UPDATE orders SET partial_payments_detail = '{json.dumps(details)}'::json "
                f"WHERE id = {order_id};"
            )

    def record_consignment(
        self,
        consignment_id: int,
        created_local: str,
        payments: list,
    ):
        self.sql_updates.append(
            f"UPDATE consignment_orders SET created_at = '{local_to_utc(created_local)}' "
            f"WHERE id = {consignment_id};"
        )
        for payment_id, local_time in payments:
            self.sql_updates.append(
                f"UPDATE consignment_payments SET created_at = '{local_to_utc(local_time)}' "
                f"WHERE id = {payment_id};"
            )

    def record_stock_loss(self, note: str, local_time: str):
        self.sql_updates.append(
            f"UPDATE stock_history SET created_at = '{local_to_utc(local_time)}' "
            f"WHERE id = (SELECT MAX(id) FROM stock_history WHERE note = '{note}');"
        )

    def record_expense_created_at(self, expense_id: int, local_time: str):
        self.sql_updates.append(
            f"UPDATE expenses SET created_at = '{local_to_utc(local_time)}' "
            f"WHERE id = {expense_id};"
        )

    def record_daily_payment_expense(self, daily_payment_id: int, local_time: str):
        self.sql_updates.append(
            f"UPDATE expenses SET created_at = '{local_to_utc(local_time)}' "
            f"WHERE reference_id = {daily_payment_id} AND reference_type = 'daily_payment';"
        )

    def add_order(
        self,
        waiter_token: str,
        table: str,
        customer: str,
        items: list,
        payments: list,
        final_method: str,
        created_time: str,
        closed_time: str,
    ):
        table_id = TABLES[table]
        customer_id = CUSTOMERS[customer]
        order = open_order(waiter_token, table_id, customer)
        if "error" in order:
            raise RuntimeError(f"open_order failed: {order}")
        order_id = order["order_id"]

        item_list = [
            {"product_id": PRODUCTS[key]["id"], "quantity": qty} for key, qty in items
        ]
        added = add_items(waiter_token, table_id, order_id, item_list)
        if "error" in added:
            raise RuntimeError(f"add_items failed: {added}")

        for amount, method, time in payments:
            pp = partial_payment(waiter_token, table_id, order_id, amount, method)
            if "error" in pp:
                raise RuntimeError(f"partial_payment failed: {pp}")

        closed = close_order(waiter_token, table_id, order_id, final_method)
        if "error" in closed:
            raise RuntimeError(f"close_order failed: {closed}")

        self.record_order(
            order_id,
            created_time,
            closed_time,
            [{"amount": a, "method": m, "time": t} for a, m, t in payments],
        )
        return order_id

    def run_session_a(self):
        print("\n=== Session A - 2026-08-01 ===")
        session = open_cash(self.tokens["caixa"], 200.0)
        session_id = session["session"]["id"]
        print(f"Opened session {session_id}")

        sup = add_movement(self.tokens["caixa"], "suprimento", 30.0, "Troco")
        self.record_movement(sup["movement"]["id"], "2026-08-01T19:00:00")

        sang = add_movement(self.tokens["gerente"], "sangria", 50.0, "Cofre")
        self.record_movement(sang["movement"]["id"], "2026-08-01T20:00:00")

        self.add_order(
            self.tokens["lara"],
            "t3",
            "lucas",
            [("water", 2), ("amstel_can", 1)],
            [(10.0, "dinheiro", "2026-08-01T19:00:00")],
            "dinheiro",
            "2026-08-01T18:30:00",
            "2026-08-01T21:00:00",
        )

        self.add_order(
            self.tokens["lucy"],
            "t4",
            "jenna",
            [("amstel_bottle", 2)],
            [],
            "cartao_credito",
            "2026-08-01T19:00:00",
            "2026-08-01T20:00:00",
        )

        self.add_order(
            self.tokens["gerente"],
            "t5",
            "pinao",
            [("vodka", 1)],
            [],
            "pix",
            "2026-08-01T20:00:00",
            "2026-08-01T22:00:00",
        )

        self.add_order(
            self.tokens["lara"],
            "t6",
            "lucas",
            [("water", 4), ("amstel_can", 2)],
            [
                (20.0, "dinheiro", "2026-08-01T19:30:00"),
                (10.0, "dinheiro", "2026-08-01T20:30:00"),
            ],
            "dinheiro",
            "2026-08-01T18:45:00",
            "2026-08-01T22:30:00",
        )

        # Consignment order (fiado) created by gerente, paid by caixa
        cons = create_consignment(
            self.tokens["gerente"],
            CUSTOMERS["jenna"],
            [{"product_id": PRODUCTS["amstel_bottle"]["id"], "quantity": 1}],
        )
        cons_id = cons["id"]
        pay = pay_consignment(self.tokens["caixa"], cons_id, 5.0, "dinheiro")
        self.record_consignment(
            cons_id,
            "2026-08-01T21:30:00",
            [(pay["id"], "2026-08-01T22:45:00")],
        )

        # Expense and daily payment
        daily = pay_daily(
            self.tokens["gerente"], EMPLOYEES["lucy"], 40.0, "2026-08-01T22:00:00"
        )
        self.record_daily_payment_expense(daily["id"], "2026-08-01T22:00:00")

        # Manual expense
        expense_sql = (
            "INSERT INTO expenses (description, amount, category, expense_date, created_by_id) "
            "VALUES ('Compra fornecedor', 80.0, 'fornecedor', %(utc)s, 2) RETURNING id;"
        ) % {"utc": f"'{local_to_utc('2026-08-01T21:00:00')}'"}
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", "db", "psql", "-U", "postgres", "-d", "ladsbeer", "-t", "-c", expense_sql],
            cwd=WORK_DIR,
            capture_output=True,
            text=True,
            check=True,
        )
        expense_id = int(result.stdout.strip().split()[0])
        self.record_expense_created_at(expense_id, "2026-08-01T21:00:00")

        # Stock loss
        stock_movement(self.tokens["estoquista"], PRODUCTS["water"]["id"], 3, "Perda simulada A")
        self.record_stock_loss("Perda simulada A", "2026-08-01T20:00:00")

        active = get_active_cash(self.tokens["gerente"])
        expected = active["session"]["expected_cash"]
        print(f"Session A expected cash before closing: {expected}")

        closed = close_cash(self.tokens["gerente"], expected)
        if "error" in closed:
            raise RuntimeError(f"close_cash failed: {closed}")
        print(f"Closed session {session_id} with final cash {expected}")

        self.record_session(session_id, "2026-08-01T18:00:00", "2026-08-01T23:00:00")
        return session_id

    def run_session_b(self):
        print("\n=== Session B - 2026-08-02 ===")
        session = open_cash(self.tokens["gerente"], 150.0)
        session_id = session["session"]["id"]
        print(f"Opened session {session_id}")

        sang = add_movement(self.tokens["gerente"], "sangria", 20.0, "Cofre")
        self.record_movement(sang["movement"]["id"], "2026-08-02T19:00:00")

        sup = add_movement(self.tokens["caixa"], "suprimento", 40.0, "Troco")
        self.record_movement(sup["movement"]["id"], "2026-08-02T20:00:00")

        self.add_order(
            self.tokens["lucy"],
            "t3",
            "lucas",
            [("water", 2), ("amstel_can", 1)],
            [(5.0, "dinheiro", "2026-08-02T19:00:00")],
            "dinheiro",
            "2026-08-02T18:30:00",
            "2026-08-02T21:00:00",
        )

        self.add_order(
            self.tokens["lara"],
            "t4",
            "jenna",
            [("amstel_bottle", 1)],
            [],
            "cartao_debito",
            "2026-08-02T19:00:00",
            "2026-08-02T20:00:00",
        )

        self.add_order(
            self.tokens["gerente"],
            "t5",
            "pinao",
            [("vodka", 1)],
            [],
            "pix",
            "2026-08-02T20:00:00",
            "2026-08-02T22:00:00",
        )

        self.add_order(
            self.tokens["lucy"],
            "t6",
            "lucas",
            [("water", 2)],
            [(10.0, "dinheiro", "2026-08-02T19:30:00")],
            "dinheiro",
            "2026-08-02T18:45:00",
            "2026-08-02T22:00:00",
        )

        # Balcao order left open
        balcao_order = open_order(
            self.tokens["lara"], TABLES["balcao"], "jenna"
        )
        balcao_order_id = balcao_order["order_id"]
        add_items(
            self.tokens["lara"],
            TABLES["balcao"],
            balcao_order_id,
            [{"product_id": PRODUCTS["amstel_bottle"]["id"], "quantity": 1}],
        )
        partial_payment(self.tokens["lara"], TABLES["balcao"], balcao_order_id, 5.0, "dinheiro")
        self.record_order(
            balcao_order_id,
            "2026-08-02T20:00:00",
            None,
            [{"amount": 5.0, "method": "dinheiro", "time": "2026-08-02T20:30:00"}],
        )

        # Consignment order
        cons = create_consignment(
            self.tokens["gerente"],
            CUSTOMERS["jenna"],
            [{"product_id": PRODUCTS["amstel_can"]["id"], "quantity": 2}],
        )
        cons_id = cons["id"]
        pay = pay_consignment(self.tokens["caixa"], cons_id, 7.0, "pix")
        self.record_consignment(
            cons_id,
            "2026-08-02T21:30:00",
            [(pay["id"], "2026-08-02T22:00:00")],
        )

        # Expenses
        daily = pay_daily(
            self.tokens["gerente"], EMPLOYEES["lara"], 50.0, "2026-08-02T21:00:00"
        )
        self.record_daily_payment_expense(daily["id"], "2026-08-02T21:00:00")

        expense_sql = (
            "INSERT INTO expenses (description, amount, category, expense_date, created_by_id) "
            "VALUES ('Manutencao', 30.0, 'outros', %(utc)s, 2) RETURNING id;"
        ) % {"utc": f"'{local_to_utc('2026-08-02T20:00:00')}'"}
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", "db", "psql", "-U", "postgres", "-d", "ladsbeer", "-t", "-c", expense_sql],
            cwd=WORK_DIR,
            capture_output=True,
            text=True,
            check=True,
        )
        expense_id = int(result.stdout.strip().split()[0])
        self.record_expense_created_at(expense_id, "2026-08-02T20:00:00")

        # Stock loss
        stock_movement(self.tokens["estoquista"], PRODUCTS["amstel_can"]["id"], 2, "Perda simulada B")
        self.record_stock_loss("Perda simulada B", "2026-08-02T21:00:00")

        active = get_active_cash(self.tokens["gerente"])
        expected = active["session"]["expected_cash"]
        print(f"Session B expected cash before closing (with open balcao): {expected}")

        closed = close_cash(self.tokens["gerente"], expected)
        if "error" in closed:
            raise RuntimeError(f"close_cash failed: {closed}")
        print(f"Closed session {session_id} with final cash {expected}")

        self.record_session(session_id, "2026-08-02T18:00:00", "2026-08-02T23:45:00")
        return session_id

    def apply_backdating(self):
        print("\nApplying back-dating...")
        run_sql("\n".join(self.sql_updates))
        print("Back-dating applied.")

    def run_session_c(self):
        print("\n=== Session C - 2026-08-03 (today) ===")
        session = open_cash(self.tokens["gerente"], 100.0)
        session_id = session["session"]["id"]
        print(f"Opened session {session_id}")

        self.add_order(
            self.tokens["gerente"],
            "t3",
            "lucas",
            [("water", 2), ("amstel_can", 1)],
            [],
            "dinheiro",
            "2026-08-03T19:00:00",
            "2026-08-03T20:00:00",
        )

        self.add_order(
            self.tokens["lucy"],
            "t4",
            "jenna",
            [("amstel_bottle", 2)],
            [],
            "cartao_credito",
            "2026-08-03T20:00:00",
            "2026-08-03T21:00:00",
        )

        daily = pay_daily(
            self.tokens["gerente"], EMPLOYEES["lily"], 20.0, "2026-08-03T22:00:00"
        )
        self.record_daily_payment_expense(daily["id"], "2026-08-03T22:00:00")

        active = get_active_cash(self.tokens["gerente"])
        expected = active["session"]["expected_cash"]
        print(f"Session C expected cash before closing: {expected}")

        closed = close_cash(self.tokens["gerente"], expected)
        if "error" in closed:
            raise RuntimeError(f"close_cash failed: {closed}")
        print(f"Closed session {session_id} with final cash {expected}")

        self.record_session(session_id, "2026-08-03T18:00:00", "2026-08-03T22:30:00")
        return session_id

    def print_results(
        self,
        session_a_id: int,
        session_b_id: int,
        session_c_id: int,
    ):
        print("\n=== Dashboard ===")
        print(json.dumps(get_dashboard(self.tokens["gerente"]), indent=2, ensure_ascii=False))

        print("\n=== Daily Report 2026-08-01 ===")
        print(json.dumps(get_daily_report(self.tokens["gerente"], "2026-08-01"), indent=2, ensure_ascii=False))

        print("\n=== Daily Report 2026-08-02 ===")
        print(json.dumps(get_daily_report(self.tokens["gerente"], "2026-08-02"), indent=2, ensure_ascii=False))

        print("\n=== Daily Report 2026-08-03 ===")
        print(json.dumps(get_daily_report(self.tokens["gerente"], "2026-08-03"), indent=2, ensure_ascii=False))

        print("\n=== Session A Final Report ===")
        print(json.dumps(get_session_report(self.tokens["gerente"], session_a_id), indent=2, ensure_ascii=False))

        print("\n=== Session B Final Report ===")
        print(json.dumps(get_session_report(self.tokens["gerente"], session_b_id), indent=2, ensure_ascii=False))

        print("\n=== Session C Final Report ===")
        print(json.dumps(get_session_report(self.tokens["gerente"], session_c_id), indent=2, ensure_ascii=False))

        print("\n=== PDF sizes ===")
        for sid in [session_a_id, session_b_id, session_c_id]:
            status, size = get_pdf(self.tokens["gerente"], sid)
            print(f"Session {sid}: HTTP {status}, {size} bytes")


def main():
    prepare_products()
    sim = Simulation()
    session_a_id = sim.run_session_a()
    session_b_id = sim.run_session_b()
    session_c_id = sim.run_session_c()
    sim.apply_backdating()
    sim.print_results(session_a_id, session_b_id, session_c_id)


if __name__ == "__main__":
    main()
