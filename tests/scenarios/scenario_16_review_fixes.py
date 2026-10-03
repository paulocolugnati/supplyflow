"""
EN: Scenario: manual wins, sellers see only their deals, items without cost, plans, headers.
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: ganho manual, vendedor vê só os próprios negócios, itens sem custo, planos, cabeçalhos.
    Passa pelas rotas de verdade num banco temporário (veja o common.py).
"""

from common import *  # noqa: F401,F403

import html as htmlmod
from urllib.parse import unquote
def n(sql, *args): return one(sql, *args)["n"]
def text(r): return htmlmod.unescape(r.text)

owner = app.test_client(); register(owner, "dono@a.com", ws="Dist A")
wa = one("SELECT id FROM workspaces")["id"]
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='profissional'), onboarding_done = 1 WHERE id = ?", wa)
manager = join(owner, "gerente@a.com", "admin")
seller = join(owner, "vend@a.com", "member")
seller2 = join(owner, "vend2@a.com", "member")
uid = {e: one("SELECT id FROM users WHERE email = ?", e)["id"] for e in ("dono@a.com", "gerente@a.com", "vend@a.com", "vend2@a.com")}
db.execute("UPDATE users SET name = 'Diego Lima' WHERE email = 'vend@a.com'")
post(owner, "/customers/new", name="Restaurante do Zé", phone="(11) 98765-4321")
cid = one("SELECT id FROM companies")["id"]
stages = {r["kind"]: r["id"] for r in db.execute("SELECT id, kind FROM stages WHERE workspace_id = ? ORDER BY position DESC", wa)}
first = one("SELECT id FROM stages WHERE workspace_id = ? ORDER BY position LIMIT 1", wa)["id"]
post(owner, "/products/new", sku="ARZ", name="Arroz", unit="cx", price="100,00", cost_mode="brl", cost="60,00")
post(owner, "/products/new", sku="DET", name="Detergente", unit="un", price="10,00", cost_mode="brl", cost="")
p_arroz = one("SELECT id FROM products WHERE sku='ARZ'")["id"]; p_det = one("SELECT id FROM products WHERE sku='DET'")["id"]

print("-- (A) manual win")
r = post(seller, "/opportunities/new", title="Venda por telefone", company_id=str(cid), stage_id=str(stages["won"]), value="")
show("born as won without value -> refused", r.status_code == 400 and n("SELECT COUNT(*) n FROM opportunities") == 0)
post(seller, "/opportunities/new", title="Venda por telefone", company_id=str(cid), stage_id=str(stages["won"]), value="800,00")
o_phone = one("SELECT * FROM opportunities WHERE title='Venda por telefone'")
show("born as won with value -> manual win", o_phone["closed_manually"] == 1 and o_phone["closed_at"])
post(seller, "/opportunities/new", title="Sem valor", company_id=str(cid), stage_id=str(first))
o_zero = one("SELECT id FROM opportunities WHERE title='Sem valor'")["id"]
post(seller, f"/opportunities/{o_zero}/stage", stage_id=str(stages["won"]))
show("move to won without quote and without value -> refused", one("SELECT stage_id FROM opportunities WHERE id = ?", o_zero)["stage_id"] == first)
post(seller, "/opportunities/new", title="Com orçamento", company_id=str(cid), stage_id=str(first), value="100,00")
o_quote = one("SELECT id FROM opportunities WHERE title='Com orçamento'")["id"]
post(seller, f"/opportunities/{o_quote}/quotes")
q_acc = one("SELECT id FROM quotes WHERE opportunity_id = ?", o_quote)["id"]
db.execute("UPDATE quotes SET status = 'accepted' WHERE id = ?", q_acc)
post(seller, f"/opportunities/{o_quote}/stage", stage_id=str(stages["won"]))
show("move to won with an accepted quote -> NOT manual", one("SELECT closed_manually m, stage_id s FROM opportunities WHERE id = ?", o_quote) == {"m": 0, "s": stages["won"]})
post(seller, f"/opportunities/{o_phone['id']}/stage", stage_id=str(first))
show("back to open clears the manual flag", one("SELECT closed_manually m FROM opportunities WHERE id = ?", o_phone["id"])["m"] == 0)
post(seller, f"/opportunities/{o_phone['id']}/stage", stage_id=str(stages["won"]))
show("opportunity page and board show 'fechada fora do sistema'", "fechada fora do sistema" in seller.get(f"/opportunities/{o_phone['id']}").text and "fechada fora do sistema" in seller.get("/pipeline").text)
page = text(owner.get("/dashboard"))
show("dashboard: system wins and manual wins apart", "R$ 100,00" in page and "1 negócio ganho" in page and "+ R$ 800,00 fora do sistema (1)" in page)

print("-- (C) a seller sees only their own deals")
post(seller2, "/opportunities/new", title="Negócio da Fernanda", company_id=str(cid), stage_id=str(first), value="5.555,00")
o_other = one("SELECT id FROM opportunities WHERE title='Negócio da Fernanda'")["id"]
post(seller2, "/activities", type="call", body="Ligação secreta da Fernanda", company_id=str(cid), opportunity_id=str(o_other))
post(seller2, "/activities", type="note", body="Nota geral do cliente", company_id=str(cid))
page = text(seller.get(f"/customers/{cid}"))
show("customer page: seller doesn't see the colleague's deal or its history", "Negócio da Fernanda" not in page and "Ligação secreta" not in page and "5.555" not in page)
show("customer page: notes about the customer itself stay visible", "Nota geral do cliente" in page)
show("manager sees everything on the customer page", "Negócio da Fernanda" in text(manager.get(f"/customers/{cid}")) and "Ligação secreta" in text(manager.get(f"/customers/{cid}")))
show("seller can't open the colleague's opportunity -> 404", seller.get(f"/opportunities/{o_other}").status_code == 404)
before = n("SELECT COUNT(*) n FROM tasks")
post(seller, "/tasks", title="Espiar negócio", opportunity_id=str(o_other))
show("seller can't link a task to the colleague's opportunity", n("SELECT COUNT(*) n FROM tasks") == before)
before = n("SELECT COUNT(*) n FROM activities")
post(seller, "/activities", type="note", body="intrometido", company_id=str(cid), opportunity_id=str(o_other))
show("seller can't log history on the colleague's opportunity", n("SELECT COUNT(*) n FROM activities") == before)
post(seller2, "/tasks", title="Tarefa da Fernanda", company_id=str(cid))
show("customer page: seller doesn't see the colleague's tasks", "Tarefa da Fernanda" not in text(seller.get(f"/customers/{cid}")))
show("customer list stays shared", "Restaurante do Zé" in text(seller2.get("/customers")))
show("seller has no 'whole team' filter on the board", 'name="owner"' not in seller.get("/pipeline").text and 'name="owner"' in owner.get("/pipeline").text)

print("-- (B) items without cost: two warnings, no extra approval")
post(seller, "/opportunities/new", title="Pedido Zé", company_id=str(cid), stage_id=str(first))
o_ze = one("SELECT id FROM opportunities WHERE title='Pedido Zé'")["id"]
post(seller, f"/opportunities/{o_ze}/quotes")
q = one("SELECT id FROM quotes WHERE opportunity_id = ? ORDER BY id DESC", o_ze)["id"]
page = text(seller.get(f"/quotes/{q}"))
show("empty quote: 'add items' and no finish button", "Adicione itens para concluir" in page and "/submit" not in page)
post(seller, f"/quotes/{q}/items", product_id=str(p_det), quantity="10", discount="0")
page = text(seller.get(f"/quotes/{q}"))
show("no discount: no warning", "itens sem custo" not in page)
item = one("SELECT id FROM quote_items WHERE quote_id = ?", q)["id"]
post(seller, f"/quotes/{q}", **{f"quantity_{item}": "10", f"discount_{item}": "3", "header_discount": "0", "valid_until": "2999-12-31"})
page = text(seller.get(f"/quotes/{q}"))
show("discount within ceiling + no-cost item: warning 1 on screen (names the item)", "Atenção: itens sem custo cadastrado" in page and "Detergente" in page.split("Atenção: itens sem custo")[1][:300])
show("warning 2: confirm on the finish form", 'data-confirm="Este orçamento dá desconto em itens sem custo' in page)
show("still within ceiling -> no approval needed", "Dentro do seu teto" in page)
post(seller, f"/quotes/{q}/submit")
show("finishing works (status ready, no request)", one("SELECT status FROM quotes WHERE id = ?", q)["status"] == "ready" and n("SELECT COUNT(*) n FROM discount_requests WHERE quote_id = ?", q) == 0)

print("-- 'your ceiling' speaks to the viewer")
post(seller, f"/opportunities/{o_ze}/quotes")
q2 = one("SELECT id FROM quotes WHERE opportunity_id = ? ORDER BY id DESC", o_ze)["id"]
post(seller, f"/quotes/{q2}/items", product_id=str(p_arroz), quantity="10", discount="0")
item = one("SELECT id FROM quote_items WHERE quote_id = ?", q2)["id"]
post(seller, f"/quotes/{q2}", **{f"quantity_{item}": "10", f"discount_{item}": "9", "header_discount": "0", "valid_until": "2999-12-31"})
show("seller reads 'Acima do seu teto'", "Acima do seu teto" in text(seller.get(f"/quotes/{q2}")))
page = text(owner.get(f"/quotes/{q2}"))
show("owner reads whose ceiling it is", "Acima do teto de Diego Lima (Vendedor)" in page and "Acima do seu teto" not in page)
post(seller, f"/quotes/{q2}", **{f"quantity_{item}": "10", f"discount_{item}": "0", "header_discount": "0", "valid_until": "2999-12-31"})
db.execute("UPDATE quote_items SET cost_cents = 9500 WHERE id = ?", item)
post(seller, f"/quotes/{q2}", **{f"quantity_{item}": "10", f"discount_{item}": "0", "header_discount": "0", "valid_until": "2999-12-31"})
page = text(seller.get(f"/quotes/{q2}"))
show("margin-only: margin title and margin label (not 'Por que este desconto?')", "Margem abaixo da mínima" in page and "Por que vender com essa margem?" in page and "Por que este desconto?" not in page)

print("-- approval card")
post(seller, f"/quotes/{q2}", **{f"quantity_{item}": "10", f"discount_{item}": "9", "header_discount": "0", "valid_until": "2999-12-31"})
post(seller, f"/quotes/{q2}/submit", reason="Cliente grande")
page = text(manager.get("/approvals"))
show("card shows the items, discount in R$ and customer history", "Arroz" in page and "Desconto em R$" in page and "Histórico do cliente" in page and "1 pedidos" in page)
show("approve and reject have visible, separate labels", '<label for="nota-aprovar-' in manager.get("/approvals").text and '<label for="nota-recusar-' in manager.get("/approvals").text)

print("-- WhatsApp messages to customers")
post(owner, f"/customers/{cid}/contacts", name="José Almeida", phone="(11) 91111-2222")
owner.get("/lang/en")
body = owner.get(f"/customers/{cid}").text
link = re.search(r'href="(https://wa.me/5511987654321\?text=[^"]+)"', body)
msg = unquote(htmlmod.unescape(link.group(1))).split("?text=", 1)[1] if link else ""
show("customer message: Portuguese even with the screen in English, greets the contact", msg.startswith("Olá, José") and "Restaurante" not in msg.split("!")[0])
owner.get("/lang/pt")

print("-- plans, formats, headers")
page = text(owner.get("/plans"))
show("new prices and team sizes", all(x in page for x in ("R$ 99,90", "R$ 249,90", "R$ 449,90")) and "<b>4</b>" in page and "<b>8</b>" in page)
show("thousands separator: 2.000 quotes", "<b>2.000</b>" in page and "<b>2000</b>" not in page)
r = owner.get("/dashboard")
show("security headers", "default-src 'self'" in r.headers.get("Content-Security-Policy", "") and r.headers.get("X-Frame-Options") == "DENY"
     and r.headers.get("X-Content-Type-Options") == "nosniff" and r.headers.get("Referrer-Policy"))
r = app.test_client().get("/favicon.ico")
show("/favicon.ico -> brand symbol", r.status_code == 301 and r.headers["Location"].endswith("/static/brand/simbolo.svg"))
show("landing has headers too", "frame-ancestors 'none'" in app.test_client().get("/").headers.get("Content-Security-Policy", ""))
