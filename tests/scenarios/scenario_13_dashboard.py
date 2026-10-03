"""
EN: Scenario: dashboard numbers and repurchase alerts (Sao Paulo days, plan feature).
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: números do painel e alertas de recompra (dias de São Paulo, recurso do plano).
    Passa pelas rotas de verdade num banco temporário (veja o common.py).
"""

from common import *  # noqa: F401,F403

import html as htmlmod
from datetime import datetime, timedelta, timezone
from helpers import today_sp
def n(sql, *args): return one(sql, *args)["n"]

owner = app.test_client(); register(owner, "dono@a.com", ws="Dist A")
wa = one("SELECT id FROM workspaces")["id"]
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='profissional'), onboarding_done = 1 WHERE id = ?", wa)
manager = join(owner, "gerente@a.com", "admin")
seller = join(owner, "vend@a.com", "member")
seller2 = join(owner, "vend2@a.com", "member")
uid = {e: one("SELECT id FROM users WHERE email = ?", e)["id"] for e in ("dono@a.com", "gerente@a.com", "vend@a.com", "vend2@a.com")}

def stage_of(ws, kind):
    return one("SELECT id FROM stages WHERE workspace_id = ? AND kind = ? ORDER BY position LIMIT 1", ws, kind)["id"]

def customer(c, name, phone=""):
    post(c, "/customers/new", name=name, phone=phone)
    return one("SELECT id FROM companies WHERE name = ?", name)["id"]

def opportunity(c, cid, title, value, ws=None):
    post(c, "/opportunities/new", title=title, company_id=str(cid), stage_id=str(stage_of(ws or wa, "open")), value=value)
    return one("SELECT id FROM opportunities WHERE title = ?", title)["id"]

c_seller = customer(seller, "Bar do Seller", phone="(11) 98888-7777")
c_seller2 = customer(seller2, "Mercado Seller2", phone="(11) 97777-6666")
c_owner = customer(owner, "Hotel Dono")
o1 = opportunity(seller, c_seller, "Opp seller aberta", "1.000,00")
o2 = opportunity(seller2, c_seller2, "Opp seller2 aberta", "500,00")
o3 = opportunity(owner, c_owner, "Opp dono ganha", "2.000,00")
o4 = opportunity(seller, c_seller, "Opp seller ganha", "300,00")
o5 = opportunity(owner, c_owner, "Opp ganha mes passado", "9.999,00")
for o in (o3, o4, o5):
    post(owner, f"/opportunities/{o}/stage", stage_id=str(stage_of(wa, "won")))
db.execute("UPDATE opportunities SET closed_at = '2020-01-15 12:00:00' WHERE id = ?", o5)

print("-- numbers")
page = htmlmod.unescape(owner.get("/dashboard").text)
show("owner: open = 1.500,00 (2 opportunities)", "R$ 1.500,00" in page and "2 oportunidades abertas" in page)
# EN/PT: these wins had no accepted quote, so they are manual wins, shown apart (rule of 15.1)
#        essas vendas não tiveram orçamento aceito: são ganhos manuais, mostrados à parte (regra da 15.1)
show("owner: no quote accepted -> 0 won through the system", "0 negócios ganhos" in page)
show("owner: manual wins shown apart (2.300,00, 2 deals), old win left out", "+ R$ 2.300,00 fora do sistema (2)" in page and "9.999" not in page)
show("manual wins are flagged in the database", one("SELECT COUNT(*) n FROM opportunities WHERE closed_manually = 1")["n"] == 3)
page = htmlmod.unescape(seller.get("/dashboard").text)
show("seller: only own open (1.000,00) and won (300,00)", "R$ 1.000,00" in page and "R$ 300,00" in page and "1.500,00" not in page and "2.300,00" not in page)
show("seller: no plan usage block, ceilings visible", 'id="uso-titulo"' not in page and 'id="tetos-titulo"' in page)
show("owner: plan usage visible", 'id="uso-titulo"' in owner.get("/dashboard").text)

print("-- month boundary in Sao Paulo")
sp_midnight = datetime.now(timezone(timedelta(hours=-3))).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
just_before = (sp_midnight - timedelta(minutes=1)).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
just_after = (sp_midnight + timedelta(minutes=1)).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
db.execute("UPDATE opportunities SET closed_at = ? WHERE id = ?", just_before, o4)
show("won 1 minute before the month (SP) is out", "R$ 300,00" not in htmlmod.unescape(seller.get("/dashboard").text))
db.execute("UPDATE opportunities SET closed_at = ? WHERE id = ?", just_after, o4)
show("won 1 minute after the month starts (SP) is in", "R$ 300,00" in htmlmod.unescape(seller.get("/dashboard").text))

print("-- quotes waiting")
def quote_for(c, oid, status, valid=None):
    before = {r["id"] for r in db.execute("SELECT id FROM quotes")}
    post(c, f"/opportunities/{oid}/quotes")
    qid = [r["id"] for r in db.execute("SELECT id FROM quotes") if r["id"] not in before][0]
    db.execute("UPDATE quotes SET status = ?, valid_until = COALESCE(?, valid_until) WHERE id = ?", status, valid, qid)
    return qid
quote_for(seller, o1, "sent"); quote_for(seller, o1, "sent", valid="2020-01-01"); quote_for(seller2, o2, "sent")
q_pending = quote_for(seller, o1, "pending_approval")
db.execute("INSERT INTO discount_requests (workspace_id, quote_id, requested_by, requested_discount_bps, required_role, reason, status) VALUES (?, ?, ?, 1200, 'admin', 'Cliente grande', 'pending')", wa, q_pending, uid["vend@a.com"])
def number_after(page, label):
    i = page.find(label)
    m = re.search(r'data-contador-rolar>([^<]+)<', page[i:])
    return m.group(1).strip() if i >= 0 and m else None
page = owner.get("/dashboard").text
show("owner: 2 sent (expired one not counted, and marked expired)", number_after(page, "Esperando o cliente") == "2" and n("SELECT COUNT(*) n FROM quotes WHERE status='expired'") == 1)
show("owner: 1 waiting for approval", number_after(page, "Esperando sua aprova") == "1")
page = seller.get("/dashboard").text
show("seller: own sent = 1, own approval requests = 1", number_after(page, "Esperando o cliente") == "1" and number_after(page, "Seus pedidos de aprova") == "1")
show("seller2: no approval requests of their own", number_after(seller2.get("/dashboard").text, "Seus pedidos de aprova") == "0")

print("-- repurchase alerts")
def accepted(cid, oid, c, utc_stamp):
    qid = quote_for(c, oid, "accepted")
    db.execute("UPDATE quotes SET customer_decided_at = ? WHERE id = ?", utc_stamp, qid)
    return qid
today = datetime.strptime(today_sp(), "%Y-%m-%d")
def days_ago(d, hour="15:00:00"):
    return (today - timedelta(days=d)).strftime("%Y-%m-%d") + " " + hour
# EN: seller's customer: every 10 days, last 20 days ago -> late 10 days
# PT: cliente do seller: a cada 10 dias, último há 20 dias -> 10 dias de atraso
for d in (40, 30, 20):
    accepted(c_seller, o1, seller, days_ago(d))
# EN: seller2's customer: only 2 orders -> no alert | PT: cliente do seller2: só 2 pedidos -> sem alerta
for d in (90, 60):
    accepted(c_seller2, o2, seller2, days_ago(d))
# EN: owner's customer on rhythm (every 10 days, last 10 days ago) | PT: cliente do dono no ritmo
for d in (30, 20, 10):
    accepted(c_owner, o3, owner, days_ago(d))
page = htmlmod.unescape(owner.get("/dashboard").text)
show("owner sees the late customer with 10 days late", "Bar do Seller" in page and "10 dias de atraso" in page and "compra a cada 10 dias" in page)
show("customers with < 3 orders or on rhythm don't show", "Mercado Seller2" not in page and "Hotel Dono" not in page.split('id="recompra-titulo"')[1].split('id="hoje-titulo"')[0])
show("WhatsApp link with a pre-filled message to the customer's phone", "wa.me/5511988887777?text=" in owner.get("/dashboard").text)
show("seller sees their own late customer", "Bar do Seller" in seller.get("/dashboard").text)
show("seller2 doesn't see someone else's customer", "Bar do Seller" not in seller2.get("/dashboard").text)
other = app.test_client(); register(other, "dono@b.com", ws="Dist B")
wb = one("SELECT id FROM workspaces WHERE id <> ? ORDER BY id DESC LIMIT 1", wa)["id"]
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='profissional'), onboarding_done = 1 WHERE id = ?", wb)
show("other tenant sees nothing of A", "Bar do Seller" not in other.get("/dashboard").text)

# EN: Sao Paulo day: 02:00 UTC is still the previous day in SP (23:00)
# PT: dia de São Paulo: 02:00 UTC ainda é o dia anterior em SP (23:00)
c_tz = customer(owner, "Cliente Fuso")
o_tz = opportunity(owner, c_tz, "Opp fuso", "10,00")
for d in (40, 30, 20):
    accepted(c_tz, o_tz, owner, days_ago(d - 1, "02:00:00"))
# EN: SP days 40, 30, 20 ago (UTC would say 39, 29, 19) -> last order shown = SP date of 20 days ago
# PT: dias SP 40, 30, 20 atrás (UTC diria 39, 29, 19) -> último pedido mostrado = data SP de 20 dias atrás
sp_last = (today - timedelta(days=20)).strftime("%d/%m")
box = htmlmod.unescape(owner.get("/dashboard").text).split('Cliente Fuso')[1][:400]
show("02:00 UTC counted as the previous Sao Paulo day", f"último pedido em {sp_last}" in box)

print("-- a new order clears the alert")
accepted(c_seller, o1, seller, days_ago(0))
show("alert gone after a new accepted order", "Bar do Seller" not in owner.get("/dashboard").text.split('id="recompra-titulo"')[1].split('id="hoje-titulo"')[0])

print("-- plan without the feature")
db.execute("DELETE FROM quotes WHERE customer_decided_at = ?", days_ago(0))
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='essencial') WHERE id = ?", wa)
page = htmlmod.unescape(owner.get("/dashboard").text)
show("Essencial: locked message, no alert list even with late customers", "planos Profissional e Escala" in page and "Bar do Seller" not in page.split('id="recompra-titulo"')[1].split('id="hoje-titulo"')[0])

print("-- tasks for today + access")
post(seller, "/tasks", title="Ligar urgente", company_id=str(c_seller), due_date=today_sp())
post(seller, "/tasks", title="Tarefa futura", company_id=str(c_seller), due_date="2999-01-01")
page = seller.get("/dashboard").text
show("today task on the dashboard, future task not", "Ligar urgente" in page and "Tarefa futura" not in page)
buyer = app.test_client(); register(buyer, "comprador@x.com", kind="buyer")
r = buyer.get("/dashboard")
show("buyer can't open the staff dashboard", r.status_code in (302, 403, 404) and "Em aberto no funil" not in r.text)
show("logged out -> login", app.test_client().get("/dashboard").status_code == 302)
show("English toggle works", "Open in the funnel" in (owner.get("/lang/en") and owner.get("/dashboard").text))
