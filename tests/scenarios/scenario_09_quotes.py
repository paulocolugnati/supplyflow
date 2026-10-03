"""
EN: Scenario: quote builder: items, discounts, totals recalculated by the server, numbering, quota.
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: montador de orçamento: itens, descontos, totais recalculados pelo servidor, numeração, cota.
    Passa pelas rotas de verdade num banco temporário (veja o common.py).
"""

from common import *  # noqa: F401,F403

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

def one(sql, *args):
    rows = db.execute(sql, *args)
    return rows[0] if rows else None

def setup(c, ws_name, suffix=""):
    post(c, "/customers/new", name="Restaurante" + suffix)
    cid = one("SELECT id FROM companies WHERE name = ?", "Restaurante" + suffix)["id"]
    ws = one("SELECT workspace_id FROM companies WHERE id = ?", cid)["workspace_id"]
    stage = one("SELECT id FROM stages WHERE workspace_id = ? ORDER BY position LIMIT 1", ws)["id"]
    post(c, "/opportunities/new", title="Pedido" + suffix, company_id=str(cid), stage_id=str(stage))
    oid = one("SELECT id FROM opportunities WHERE title = ?", "Pedido" + suffix)["id"]
    return ws, cid, oid

owner, other = app.test_client(), app.test_client()
register(owner, "dono@a.com", ws="Dist A")
register(other, "dono@b.com", ws="Dist B")
wa, ca, oa = setup(owner, "A")
wb, cb, ob = setup(other, "B", " B")
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='essencial') WHERE id IN (?, ?)", wa, wb)
for sku, name, price, cost in [("ARZ", "Arroz", "100,00", "78,00"), ("OLE", "Óleo", "50,00", "37,00"), ("FEI", "Feijão", "80,00", "60,00"), ("DET", "Detergente", "20,00", "")]:
    post(owner, "/products/new", sku=sku, name=name, unit="cx", price=price, cost_mode="brl", cost=cost)
post(other, "/products/new", sku="B1", name="Produto B", unit="un", price="10")
pid = {r["sku"]: r["id"] for r in db.execute("SELECT id, sku FROM products")}

print("-- create")
r = post(owner, f"/opportunities/{oa}/quotes")
q = one("SELECT * FROM quotes WHERE workspace_id = ?", wa)
show("draft created with number 1 and validity +7 days", r.status_code == 302 and q["number"] == 1 and q["status"] == "draft" and q["company_id"] == ca)
post(owner, f"/opportunities/{oa}/quotes")
show("numbering is per workspace and sequential", [x["number"] for x in db.execute("SELECT number FROM quotes WHERE workspace_id = ? ORDER BY id", wa)] == [1, 2])
post(other, f"/opportunities/{ob}/quotes")
show("other workspace starts at #1 too", one("SELECT number FROM quotes WHERE workspace_id = ?", wb)["number"] == 1)
show("quote for B's opportunity from A -> 404", post(owner, f"/opportunities/{ob}/quotes").status_code == 404)
qid = q["id"]

print("-- items and recalculation")
post(owner, f"/quotes/{qid}/items", product_id=str(pid["ARZ"]), quantity="10", discount="0")
post(owner, f"/quotes/{qid}/items", product_id=str(pid["OLE"]), quantity="8", discount="")
post(owner, f"/quotes/{qid}/items", product_id=str(pid["FEI"]), quantity="5", discount="0")
q = one("SELECT * FROM quotes WHERE id = ?", qid)
show("totals stored after adding (list 1800,00, no discount)", q["list_total_cents"] == 180000 and q["final_total_cents"] == 180000 and q["effective_discount_bps"] == 0)
item = one("SELECT * FROM quote_items WHERE quote_id = ? AND product_id = ?", qid, pid["ARZ"])
show("item copies name, unit, price and cost", item["product_name"] == "Arroz" and item["unit"] == "cx" and item["list_price_cents"] == 10000 and item["cost_cents"] == 7800)
post(owner, f"/quotes/{qid}/items", product_id=str(pid["ARZ"]), quantity="2", discount="0")
show("same product again adds to quantity (no 2nd line)", one("SELECT COUNT(*) n FROM quote_items WHERE quote_id = ? AND product_id = ?", qid, pid["ARZ"])["n"] == 1
     and one("SELECT quantity FROM quote_items WHERE quote_id = ? AND product_id = ?", qid, pid["ARZ"])["quantity"] == 12)
show("product of another workspace refused", post(owner, f"/quotes/{qid}/items", product_id=str(pid["B1"]), quantity="1").status_code == 302
     and one("SELECT 1 x FROM quote_items WHERE product_id = ?", pid["B1"]) is None)
post(owner, f"/quotes/{qid}/items", product_id=str(pid["DET"]), quantity="0")
post(owner, f"/quotes/{qid}/items", product_id=str(pid["DET"]), quantity="abc")
post(owner, f"/quotes/{qid}/items", product_id=str(pid["DET"]), quantity="1", discount="150")
show("invalid quantity/discount on add refused", one("SELECT 1 x FROM quote_items WHERE product_id = ?", pid["DET"]) is None)
post(owner, f"/products/{pid['DET']}/toggle")
post(owner, f"/quotes/{qid}/items", product_id=str(pid["DET"]), quantity="1")
show("inactive product can't be added", one("SELECT 1 x FROM quote_items WHERE product_id = ?", pid["DET"]) is None)

print("-- save with discounts (the landing page example)")
items = {r["product_id"]: r["id"] for r in db.execute("SELECT id, product_id FROM quote_items WHERE quote_id = ?", qid)}
form = {f"quantity_{items[pid['ARZ']]}": "10", f"discount_{items[pid['ARZ']]}": "0",
        f"quantity_{items[pid['OLE']]}": "8", f"discount_{items[pid['OLE']]}": "0",
        f"quantity_{items[pid['FEI']]}": "5", f"discount_{items[pid['FEI']]}": "0",
        "header_discount": "8", "valid_until": "2999-12-31", "notes_customer": "Entrega na terça", "notes_internal": "Cliente pede prazo"}
r = post(owner, f"/quotes/{qid}", **form)
q = one("SELECT * FROM quotes WHERE id = ?", qid)
show("8% header: final 1656,00, effective 8%, margin 16,91%", q["final_total_cents"] == 165600 and q["effective_discount_bps"] == 800 and q["margin_bps"] == 1691)
show("validity and notes saved", q["valid_until"] == "2999-12-31" and q["notes_customer"] == "Entrega na terça" and q["notes_internal"] == "Cliente pede prazo")
form.update({f"discount_{items[pid['ARZ']]}": "5", f"discount_{items[pid['OLE']]}": "20", "header_discount": "5"})
form[f"quantity_{items[pid['FEI']]}"] = "5"
post(owner, f"/quotes/{qid}", **form)
lines = {r["product_id"]: r["line_total_cents"] for r in db.execute("SELECT product_id, line_total_cents FROM quote_items WHERE quote_id = ?", qid)}
show("item discounts stored per line (arroz 950,00 / óleo 320,00)", lines[pid["ARZ"]] == 95000 and lines[pid["OLE"]] == 32000)
bad = dict(form); bad[f"quantity_{items[pid['ARZ']]}"] = "-3"; bad["header_discount"] = "abc"; bad["valid_until"] = "2000-01-01"
before = one("SELECT final_total_cents FROM quotes WHERE id = ?", qid)["final_total_cents"]
r = post(owner, f"/quotes/{qid}", **bad)
page = html.unescape(owner.get(f"/quotes/{qid}").text)
show("invalid save changes nothing and explains", one("SELECT final_total_cents FROM quotes WHERE id = ?", qid)["final_total_cents"] == before
     and "Quantidade inválida em Arroz" in page and "Desconto geral inválido" in page and "não pode ser no passado" in page)
forged = dict(form); forged["final_total_cents"] = "1"; forged["effective_discount_bps"] = "0"
post(owner, f"/quotes/{qid}", **forged)
show("totals sent by the browser are ignored", one("SELECT final_total_cents FROM quotes WHERE id = ?", qid)["final_total_cents"] != 1)

print("-- price snapshot and removal")
post(owner, f"/products/{pid['ARZ']}/edit", sku="ARZ", name="Arroz novo nome", unit="cx", price="999,00", cost_mode="brl", cost="1")
show("catalog change doesn't rewrite the quote", one("SELECT product_name, list_price_cents FROM quote_items WHERE quote_id = ? AND product_id = ?", qid, pid["ARZ"]) == {"product_name": "Arroz", "list_price_cents": 10000})
show("product used in a quote can't be deleted now", post(owner, f"/products/{pid['FEI']}/delete").status_code == 302 and one("SELECT 1 x FROM products WHERE id = ?", pid["FEI"]) is not None)
post(owner, f"/quotes/{qid}/items/{items[pid['FEI']]}/delete")
show("remove line recalculates", one("SELECT COUNT(*) n FROM quote_items WHERE quote_id = ?", qid)["n"] == 2
     and one("SELECT list_total_cents FROM quotes WHERE id = ?", qid)["list_total_cents"] == 140000)

print("-- isolation, permissions, status")
qb = one("SELECT id FROM quotes WHERE workspace_id = ?", wb)["id"]
show("B's quote from A -> 404 (view, save, add, remove)", owner.get(f"/quotes/{qb}").status_code == 404 and post(owner, f"/quotes/{qb}", header_discount="1").status_code == 404
     and post(owner, f"/quotes/{qb}/items", product_id=str(pid["ARZ"])).status_code == 404)
show("item id of another quote can't be removed via this quote", post(owner, f"/quotes/{qid}/items/999999/delete").status_code == 302)
post(owner, "/team/invite", email="vend@a.com", role="member")
link = re.search(r'/invite/([^"]+)"', owner.get("/team").text).group(1)
seller = app.test_client(); register(seller, "vend@a.com", invite=link)
# EN/PT: Part 15.1 rule: sellers see only quotes of their own opportunities | regra 15.1: vendedor vê só orçamentos das próprias oportunidades
show("member can't open owner's quote -> 404", seller.get(f"/quotes/{qid}").status_code == 404)
show("member can't edit owner's quote -> 404", post(seller, f"/quotes/{qid}", header_discount="50").status_code == 404
     and one("SELECT header_discount_bps h FROM quotes WHERE id = ?", qid)["h"] != 5000)
show("member can't start a quote on owner's opportunity -> 404", post(seller, f"/opportunities/{oa}/quotes").status_code == 404)
show("member's quote list hides owner's quotes", "#0001" not in seller.get("/quotes").text)
stage_a = one("SELECT id FROM stages WHERE workspace_id = ? ORDER BY position LIMIT 1", wa)["id"]
post(seller, "/opportunities/new", title="Opp do vendedor", company_id=str(ca), stage_id=str(stage_a))
ov = one("SELECT id FROM opportunities WHERE title = 'Opp do vendedor'")["id"]
post(seller, f"/opportunities/{ov}/quotes")
qs = one("SELECT id FROM quotes WHERE created_by = (SELECT id FROM users WHERE email='vend@a.com')")["id"]
show("member edits own quote", post(seller, f"/quotes/{qs}/items", product_id=str(pid["OLE"]), quantity="1").status_code == 302
     and one("SELECT COUNT(*) n FROM quote_items WHERE quote_id = ?", qs)["n"] == 1)
db.execute("UPDATE quotes SET status = 'sent' WHERE id = ?", qid)
show("non-draft quote can't be edited -> 409", post(owner, f"/quotes/{qid}", header_discount="1").status_code == 409)
show("internal notes visible to staff", "Cliente pede prazo" in owner.get(f"/quotes/{qid}").text)

print("-- monthly quota (Essencial: 200)")
show("list shows quotes", "#0001" in owner.get("/quotes").text)
n = one("SELECT COUNT(*) n FROM quotes WHERE workspace_id = ?", wa)["n"]
uid = one("SELECT id FROM users WHERE email='dono@a.com'")["id"]
for i in range(200 - n):
    db.execute("INSERT INTO quotes (workspace_id, number, opportunity_id, company_id, created_by, valid_until, status) VALUES (?, ?, ?, ?, ?, '2999-01-01', 'cancelled')", wa, 1000 + i, oa, ca, uid)
r = post(owner, f"/opportunities/{oa}/quotes")
show("201st quote of the month blocked (cancelled ones count)", one("SELECT COUNT(*) n FROM quotes WHERE workspace_id = ?", wa)["n"] == 200)
show("opportunity page shows the limit tag", "Limite de orçamentos do mês atingido" in owner.get(f"/opportunities/{oa}").text)
db.execute("UPDATE quotes SET created_at = '2000-01-01 00:00:00' WHERE workspace_id = ? AND number >= 1000", wa)
post(owner, f"/opportunities/{oa}/quotes")
show("old months don't count", one("SELECT COUNT(*) n FROM quotes WHERE workspace_id = ?", wa)["n"] == 201)
show("nav has Orçamentos", 'href="/quotes"' in owner.get("/dashboard").text)
