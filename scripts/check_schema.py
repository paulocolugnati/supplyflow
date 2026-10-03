"""EN: Try to break the rules of schema.sql and confirm the database refuses.
    Runs on an in-memory database, so project.db is never touched.
PT: Tenta quebrar as regras do schema.sql e confirma que o banco recusa.
    Roda num banco em memória, então o project.db nunca é alterado.

Usage / Uso (inside project/ | dentro de project/):
    .venv/Scripts/python.exe scripts/check_schema.py
"""

import os
import sqlite3

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "schema.sql")

passed = 0
failed = 0


def check(description, ok):
    """EN: Print PASS/FAIL and count the result. | PT: Mostra PASS/FAIL e conta o resultado."""
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {description}")
    else:
        failed += 1
        print(f"  FAIL  {description}")


def refuses(db, description, sql, params=()):
    """EN: The database must raise an error for this statement.
    PT: O banco precisa dar erro neste comando.
    """
    try:
        db.execute(sql, params)
    except sqlite3.IntegrityError:
        check(description, True)
        return
    check(description + "  (was accepted!)", False)


def accepts(db, description, sql, params=()):
    """EN: The database must accept this statement.
    PT: O banco precisa aceitar este comando.
    """
    try:
        db.execute(sql, params)
        check(description, True)
    except sqlite3.IntegrityError as error:
        check(f"{description}  ({error})", False)


def main():
    # EN: Foreign keys are off by default in SQLite; the cs50 library turns them on, so we do too
    # PT: No SQLite as chaves estrangeiras vêm desligadas; a biblioteca cs50 liga, então ligamos também
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys = ON")
    with open(SCHEMA, encoding="utf-8") as f:
        db.executescript(f.read())

    print("Seed")
    check("4 plans seeded", db.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 4)
    check("Escala allows 2 owners",
          db.execute("SELECT max_owners FROM plans WHERE code = 'escala'").fetchone()[0] == 2)

    # EN: Two workspaces (A = 1, B = 2) with one user each, plus customers, pipelines and products
    # PT: Duas distribuidoras (A = 1, B = 2) com um usuário cada, além de clientes, funis e produtos
    db.executescript("""
        INSERT INTO users (id, email, name, hash) VALUES (1, 'ana@a.com', 'Ana', 'x'), (2, 'bia@b.com', 'Bia', 'x');
        INSERT INTO workspaces (id, name, plan_id) VALUES (1, 'Distribuidora A', 1), (2, 'Distribuidora B', 1);
        INSERT INTO memberships (workspace_id, user_id, role) VALUES (1, 1, 'owner'), (2, 2, 'owner');
        INSERT INTO companies (id, workspace_id, name) VALUES (10, 1, 'Restaurante A'), (20, 2, 'Mercado B');
        INSERT INTO pipelines (id, workspace_id, name) VALUES (1, 1, 'Vendas A'), (2, 2, 'Vendas B'), (3, 1, 'Outro A');
        INSERT INTO stages (id, workspace_id, pipeline_id, name, kind) VALUES
            (1, 1, 1, 'Novo', 'open'), (2, 1, 1, 'Fechado', 'won'), (3, 2, 2, 'Novo', 'open'), (4, 1, 3, 'Novo', 'open');
        INSERT INTO products (id, workspace_id, sku, name, price_cents) VALUES (1, 1, 'ARZ', 'Arroz', 10000), (2, 2, 'OLE', 'Oleo', 5000);
        INSERT INTO contacts (id, workspace_id, company_id, name) VALUES (1, 1, 10, 'Ze');
    """)

    print("Users")
    refuses(db, "duplicate email", "INSERT INTO users (email, name, hash) VALUES ('ana@a.com', 'X', 'x')")
    refuses(db, "uppercase email", "INSERT INTO users (email, name, hash) VALUES ('Joao@x.com', 'X', 'x')")
    refuses(db, "invalid language", "INSERT INTO users (email, name, hash, lang) VALUES ('c@c.com', 'X', 'x', 'fr')")

    print("Workspaces and roles")
    refuses(db, "seller ceiling above manager ceiling",
            "UPDATE workspaces SET member_discount_limit_bps = 2000, admin_discount_limit_bps = 1000 WHERE id = 1")
    refuses(db, "ceiling above 100%", "UPDATE workspaces SET admin_discount_limit_bps = 10001 WHERE id = 1")
    refuses(db, "invalid role", "INSERT INTO memberships (workspace_id, user_id, role) VALUES (1, 2, 'viewer')")
    refuses(db, "same user twice in a workspace", "INSERT INTO memberships (workspace_id, user_id, role) VALUES (1, 1, 'admin')")

    print("Tenant isolation (composite foreign keys)")
    refuses(db, "contact in A pointing to company of B",
            "INSERT INTO contacts (workspace_id, company_id, name) VALUES (1, 20, 'Intruso')")
    refuses(db, "opportunity in A for company of B",
            "INSERT INTO opportunities (workspace_id, pipeline_id, stage_id, company_id, title) VALUES (1, 1, 1, 20, 'X')")
    refuses(db, "opportunity with stage from another pipeline",
            "INSERT INTO opportunities (workspace_id, pipeline_id, stage_id, company_id, title) VALUES (1, 1, 4, 10, 'X')")
    refuses(db, "buyer link to company of another workspace",
            "INSERT INTO customer_users (workspace_id, company_id, user_id) VALUES (1, 20, 2)")

    accepts(db, "valid opportunity",
            "INSERT INTO opportunities (id, workspace_id, pipeline_id, stage_id, company_id, contact_id, title) "
            "VALUES (1, 1, 1, 1, 10, 1, 'Pedido semanal')")
    accepts(db, "valid quote",
            "INSERT INTO quotes (id, workspace_id, number, opportunity_id, company_id, created_by, valid_until) "
            "VALUES (1, 1, 1, 1, 10, 1, '2026-12-31')")
    refuses(db, "quote item using product of another workspace",
            "INSERT INTO quote_items (workspace_id, quote_id, product_id, product_name, unit, quantity, list_price_cents) "
            "VALUES (1, 1, 2, 'Oleo', 'un', 1, 5000)")

    print("Quotes")
    refuses(db, "duplicate quote number in the same workspace",
            "INSERT INTO quotes (workspace_id, number, opportunity_id, company_id, created_by, valid_until) "
            "VALUES (1, 1, 1, 10, 1, '2026-12-31')")
    refuses(db, "invalid status", "UPDATE quotes SET status = 'approved' WHERE id = 1")
    refuses(db, "header discount above 100%", "UPDATE quotes SET header_discount_bps = 10001 WHERE id = 1")
    refuses(db, "quantity zero",
            "INSERT INTO quote_items (workspace_id, quote_id, product_id, product_name, unit, quantity, list_price_cents) "
            "VALUES (1, 1, 1, 'Arroz', 'un', 0, 10000)")
    refuses(db, "negative item discount",
            "INSERT INTO quote_items (workspace_id, quote_id, product_id, product_name, unit, quantity, list_price_cents, discount_bps) "
            "VALUES (1, 1, 1, 'Arroz', 'un', 1, 10000, -1)")
    accepts(db, "valid quote item",
            "INSERT INTO quote_items (workspace_id, quote_id, product_id, product_name, unit, quantity, list_price_cents, discount_bps) "
            "VALUES (1, 1, 1, 'Arroz', 'un', 10, 10000, 500)")
    refuses(db, "negative product price", "INSERT INTO products (workspace_id, sku, name, price_cents) VALUES (1, 'N', 'N', -5)")
    refuses(db, "duplicate SKU in the same workspace",
            "INSERT INTO products (workspace_id, sku, name, price_cents) VALUES (1, 'ARZ', 'Arroz 2', 100)")

    print("Discount approval")
    refuses(db, "user approving their own request",
            "INSERT INTO discount_requests (workspace_id, quote_id, requested_by, requested_discount_bps, required_role, reason, decided_by) "
            "VALUES (1, 1, 1, 2000, 'admin', 'cliente grande', 1)")

    print("Invites")
    refuses(db, "staff invite without role",
            "INSERT INTO invites (workspace_id, kind, email, token_hash, created_by, expires_at) "
            "VALUES (1, 'staff', 'x@x.com', 'h1', 1, '2026-12-31')")
    refuses(db, "buyer invite without company",
            "INSERT INTO invites (workspace_id, kind, email, token_hash, created_by, expires_at) "
            "VALUES (1, 'customer', 'x@x.com', 'h2', 1, '2026-12-31')")

    print("Tasks and activities")
    refuses(db, "task linked to nothing",
            "INSERT INTO tasks (workspace_id, created_by, title) VALUES (1, 1, 'Ligar')")
    refuses(db, "invalid activity type",
            "INSERT INTO activities (workspace_id, user_id, type, body, company_id) VALUES (1, 1, 'hack', 'x', 10)")
    accepts(db, "valid task", "INSERT INTO tasks (workspace_id, created_by, title, opportunity_id) VALUES (1, 1, 'Ligar', 1)")

    print("Delete rules")
    refuses(db, "delete stage in use", "DELETE FROM stages WHERE id = 1")
    refuses(db, "delete company that has quotes", "DELETE FROM companies WHERE id = 10")
    refuses(db, "delete product used in a quote", "DELETE FROM products WHERE id = 1")
    accepts(db, "delete contact", "DELETE FROM contacts WHERE id = 1")
    check("opportunity kept, contact_id set to NULL",
          db.execute("SELECT contact_id FROM opportunities WHERE id = 1").fetchone() == (None,))

    # EN: An opportunity without quotes can be deleted, and its tasks go with it
    # PT: Uma oportunidade sem orçamentos pode ser apagada, e as tarefas dela vão junto
    db.executescript("""
        INSERT INTO opportunities (id, workspace_id, pipeline_id, stage_id, company_id, title) VALUES (2, 1, 1, 1, 10, 'Sem orcamento');
        INSERT INTO tasks (workspace_id, created_by, title, opportunity_id) VALUES (1, 1, 'Visitar', 2);
        DELETE FROM opportunities WHERE id = 2;
    """)
    check("deleting opportunity without quotes deletes its tasks",
          db.execute("SELECT COUNT(*) FROM tasks WHERE opportunity_id = 2").fetchone()[0] == 0)

    print("Part 15 additions")
    # EN: company data, commission, manual wins and password resets
    # PT: dados da empresa, comissão, ganho manual e redefinição de senha
    accepts(db, "workspace CNPJ with 14 digits", "UPDATE workspaces SET cnpj = '11222333000181' WHERE id = 1")
    refuses(db, "CNPJ with the wrong length", "UPDATE workspaces SET cnpj = '123' WHERE id = 2")
    refuses(db, "two distributors with the same CNPJ", "UPDATE workspaces SET cnpj = '11222333000181' WHERE id = 2")
    accepts(db, "many distributors without CNPJ", "UPDATE workspaces SET cnpj = NULL WHERE id = 2")
    accepts(db, "commission of 2,5%", "UPDATE memberships SET commission_bps = 250 WHERE user_id = 1")
    refuses(db, "negative commission", "UPDATE memberships SET commission_bps = -1 WHERE user_id = 1")
    refuses(db, "commission above 100%", "UPDATE memberships SET commission_bps = 10001 WHERE user_id = 1")
    refuses(db, "closed_manually other than 0/1", "UPDATE opportunities SET closed_manually = 2 WHERE id = 1")
    accepts(db, "password reset link", "INSERT INTO password_resets (user_id, token_hash, expires_at) VALUES (1, 'abc', '2999-01-01 00:00:00')")
    refuses(db, "same reset token twice", "INSERT INTO password_resets (user_id, token_hash, expires_at) VALUES (1, 'abc', '2999-01-01 00:00:00')")
    db.execute("INSERT INTO password_resets (user_id, token_hash, expires_at) VALUES (2, 'xyz', '2999-01-01 00:00:00')")
    db.execute("DELETE FROM memberships WHERE user_id = 2")
    db.execute("DELETE FROM users WHERE id = 2")
    check("deleting a user removes their reset links (cascade)",
          db.execute("SELECT COUNT(*) FROM password_resets WHERE user_id = 2").fetchone()[0] == 0)

    print(f"\n{passed} passed, {failed} failed")
    # EN: exit code 1 when something failed (useful for automation)
    # PT: código de saída 1 quando algo falhou (útil para automação)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
