"""
EN: Scenario: product catalog: money parsing, cost in R$ or %, margin, toggle, quota.
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: catálogo de produtos: leitura de dinheiro, custo em R$ ou %, margem, ativar/desativar, cota.
    Passa pelas rotas de verdade num banco temporário (veja o common.py).
"""

from common import *  # noqa: F401,F403

from helpers import parse_money, money_input
from products import margin_bps

def tok(c, url="/login"):
    m = re.search(r'name="_csrf" type="hidden" value="([^"]+)"', c.get(url).text)
    return m.group(1) if m else re.search(r'name="_csrf" type="hidden" value="([^"]+)"', c.get("/dashboard").text).group(1)

def register(c, email, kind="distributor", ws="Dist A", invite=None):
    t = tok(c, "/register" + (f"?invite={invite}" if invite else ""))
    data = dict(_csrf=t, account_type=kind, name="Nome " + email, email=email, phone="",
                workspace_name=ws, password="12345678", confirmation="12345678")
    if invite: data["invite"] = invite
    return c.post("/register", data=data)

def post(c, url, **data):
    data["_csrf"] = tok(c, "/dashboard")
    return c.post(url, data=data)

def rows(r):
    import html
    return [html.unescape(x) for x in re.findall(r'<strong class="produto-nome">([^<]+)</strong>', r.text)]

def product(sku):
    found = db.execute("SELECT * FROM products WHERE sku = ?", sku)
    return found[0] if found else None

print("-- helpers")
show("parse_money formats", [parse_money(x) for x in ["12,34", "1.234,56", "1,234.56", "R$ 9,9", "1.234"]] == [1234, 123456, 123456, 990, 123400])
show("parse_money rejects", [parse_money(x) for x in ["-5", "abc", "0,001", "", "1e5"]] == [None] * 5)
show("money_input", money_input(123456) == "1234,56" and money_input(5) == "0,05")
show("margin math", margin_bps(10000, 7000) == 3000 and margin_bps(10000, 12000) == -2000 and margin_bps(10000, None) is None)

owner, other = app.test_client(), app.test_client()
register(owner, "dono@a.com", ws="Dist A")
register(other, "dono@b.com", ws="Dist B")
wa = db.execute("SELECT id FROM workspaces WHERE name='Dist A'")[0]["id"]

print("-- create and validate")
show("empty catalog state", "Monte o seu catálogo" in owner.get("/products").text)
r = post(owner, "/products/new", sku="bad sku!", name="", unit="tonelada", price="-1", cost_mode="pct", cost="150")
show("invalid fields -> 400", r.status_code == 400 and "SKU inválido" in r.text and "unidade da lista" in r.text
     and "maior que zero" in r.text and "Porcentagem de custo inválida" in r.text)
r = post(owner, "/products/new", sku="arz-5", name="Arroz 5 kg", unit="cx", price="100,00", cost_mode="brl", cost="78,00")
p = product("ARZ-5")
show("created: SKU uppercased, cents stored", r.status_code == 302 and p and p["price_cents"] == 10000 and p["cost_cents"] == 7800)
post(owner, "/products/new", sku="OLE-900", name="Óleo 900 ml", unit="cx", price="R$ 50", cost_mode="pct", cost="74")
show("cost typed as % converted to cents (74% of 50,00 = 37,00)", product("OLE-900")["cost_cents"] == 3700)
post(owner, "/products/new", sku="FEI-1", name="Feijão 1 kg", unit="fd", price="80", cost_mode="brl", cost="")
show("cost optional -> NULL", product("FEI-1")["cost_cents"] is None)
r = post(owner, "/products/new", sku="ARZ-5", name="Outro", unit="un", price="1")
show("duplicate SKU refused", r.status_code == 400 and "Já existe um produto com este SKU" in r.text)
r = post(other, "/products/new", sku="ARZ-5", name="Arroz da B", unit="cx", price="99")
show("same SKU allowed in another workspace", r.status_code == 302)
post(owner, "/products/new", sku="PROMO_50", name="Kit 50% off'; DROP TABLE products;--", unit="un", price="1,00", cost="2,00")
show("SQL text stored literally; negative margin kept", product("PROMO_50") and margin_bps(100, product("PROMO_50")["cost_cents"]) < 0)

print("-- list, search, margin")
r = owner.get("/products")
show("list shows margin 22,00% for arroz", "22%" in r.text or "22,00%" in r.text)
show("negative margin flagged", "margem-negativa" in r.text)
show("other workspace product not listed", "Arroz da B" not in r.text)
show("search by SKU", rows(owner.get("/products?q=ole")) == ["Óleo 900 ml"])
show("search '50%' is literal", rows(owner.get("/products?q=50%25")) == ["Kit 50% off'; DROP TABLE products;--"])
show("injection search returns nothing", rows(owner.get("/products?q=' OR 'a'='a")) == [])

print("-- edit, toggle, delete")
pid = product("ARZ-5")["id"]
r = post(owner, f"/products/{pid}/edit", sku="ARZ-5", name="Arroz tipo 1, 5 kg", unit="cx", price="105,50", cost_mode="brl", cost="78")
show("edit saved", product("ARZ-5")["name"] == "Arroz tipo 1, 5 kg" and product("ARZ-5")["price_cents"] == 10550)
form = owner.get(f"/products/{pid}/edit").text
show("edit form shows money in BR format", 'value="105,50"' in form and 'value="78,00"' in form)
r = post(owner, f"/products/{pid}/edit", sku="OLE-900", name="X", unit="cx", price="1")
show("renaming SKU onto another's SKU refused", r.status_code == 400)
r = post(owner, f"/products/{pid}/toggle", next="/products?status=all")
show("deactivate + safe redirect back", product("ARZ-5")["active"] == 0 and r.headers["Location"].endswith("/products?status=all"))
r = post(owner, f"/products/{pid}/toggle", next="https://evil.com")
show("reactivate + external redirect blocked", product("ARZ-5")["active"] == 1 and r.headers["Location"] == "/products")
post(owner, f"/products/{pid}/toggle")
show("inactive hidden from default list", "Arroz tipo 1" not in owner.get("/products").text)
show("inactive shown in 'inactive' filter", rows(owner.get("/products?status=inactive")) == ["Arroz tipo 1, 5 kg"])

pipe = db.execute("SELECT id FROM pipelines WHERE workspace_id = ?", wa)[0]["id"]
stage = db.execute("SELECT id FROM stages WHERE pipeline_id = ? LIMIT 1", pipe)[0]["id"]
co = db.execute("INSERT INTO companies (workspace_id, name) VALUES (?, 'C')", wa)
op = db.execute("INSERT INTO opportunities (workspace_id, pipeline_id, stage_id, company_id, title) VALUES (?,?,?,?, 'O')", wa, pipe, stage, co)
uid = db.execute("SELECT id FROM users WHERE email='dono@a.com'")[0]["id"]
q = db.execute("INSERT INTO quotes (workspace_id, number, opportunity_id, company_id, created_by, valid_until) VALUES (?,1,?,?,?, '2999-01-01')", wa, op, co, uid)
db.execute("INSERT INTO quote_items (workspace_id, quote_id, product_id, product_name, unit, quantity, list_price_cents) VALUES (?,?,?,?,?,1,100)", wa, q, pid, "Arroz", "cx")
r = post(owner, f"/products/{pid}/delete")
show("product in a quote not deleted, message suggests deactivating", product("ARZ-5") is not None and "Desative-o" in owner.get("/products").text)
fid = product("FEI-1")["id"]
post(owner, f"/products/{fid}/delete")
show("unused product deleted", product("FEI-1") is None)

print("-- isolation and permissions")
bid = db.execute("SELECT id FROM products WHERE name = 'Arroz da B'")[0]["id"]
show("edit B's product from A -> 404", owner.get(f"/products/{bid}/edit").status_code == 404)
show("toggle B's product from A -> 404", post(owner, f"/products/{bid}/toggle").status_code == 404)
show("delete B's product from A -> 404", post(owner, f"/products/{bid}/delete").status_code == 404)

post(owner, "/team/invite", email="vend@a.com", role="member")
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='essencial') WHERE id = ?", wa)
post(owner, "/team/invite", email="vend@a.com", role="member")
link = re.search(r'/invite/([^"]+)"', owner.get("/team").text).group(1)
seller = app.test_client()
register(seller, "vend@a.com", invite=link)
r = seller.get("/products")
show("member sees the catalog", r.status_code == 200 and "Óleo 900 ml" in r.text)
show("member sees no edit actions", "/products/new" not in r.text and "/toggle" not in r.text)
show("member blocked from new/edit/toggle/delete -> 403",
     seller.get("/products/new").status_code == 403 and post(seller, f"/products/{pid}/edit", sku="X").status_code == 403
     and post(seller, f"/products/{pid}/toggle").status_code == 403 and post(seller, f"/products/{pid}/delete").status_code == 403)

print("-- quota (Essencial: 100 products)")
n = db.execute("SELECT COUNT(*) n FROM products WHERE workspace_id = ?", wa)[0]["n"]
for i in range(100 - n):
    db.execute("INSERT INTO products (workspace_id, sku, name, price_cents) VALUES (?, ?, ?, 100)", wa, f"Q{i}", f"P{i}")
r = post(owner, "/products/new", sku="EXTRA", name="Extra", unit="un", price="1")
show("101st product blocked", r.status_code == 302 and product("EXTRA") is None)
show("limit tag shown", "Limite de produtos do plano atingido" in owner.get("/products").text)
show("nav has Produtos", 'href="/products"' in owner.get("/dashboard").text)
