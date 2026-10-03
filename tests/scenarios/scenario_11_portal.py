"""
EN: Scenario: buyer portal: invites, multi-distributor, what a buyer may see, accept and decline.
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: portal do comprador: convites, várias distribuidoras, o que o comprador pode ver, aceitar e recusar.
    Passa pelas rotas de verdade num banco temporário (veja o common.py).
"""

from common import *  # noqa: F401,F403

def tok(c, url="/login"):
    m = re.search(r'name="_csrf" type="hidden" value="([^"]+)"', c.get(url).text)
    return m.group(1) if m else re.search(r'name="_csrf" type="hidden" value="([^"]+)"', c.get("/portal").text).group(1)

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

def setup(c, ws, cust, phone=""):
    post(c, "/customers/new", name=cust, phone=phone)
    cid = one("SELECT id FROM companies WHERE name = ?", cust)["id"]
    w = one("SELECT workspace_id FROM companies WHERE id = ?", cid)["workspace_id"]
    stage = one("SELECT id FROM stages WHERE workspace_id = ? ORDER BY position LIMIT 1", w)["id"]
    post(c, "/opportunities/new", title="Pedido " + cust, company_id=str(cid), stage_id=str(stage))
    oid = one("SELECT id FROM opportunities WHERE company_id = ?", cid)["id"]
    post(c, "/products/new", sku="P" + str(cid), name="Arroz " + ws, unit="cx", price="100,00", cost_mode="brl", cost="70,00")
    pid = one("SELECT id FROM products WHERE sku = ?", "P" + str(cid))["id"]
    return w, cid, oid, pid

def make_quote(c, oid, pid, send=True, header="0"):
    before = {r["id"] for r in db.execute("SELECT id FROM quotes")}
    post(c, f"/opportunities/{oid}/quotes")
    qid = [r["id"] for r in db.execute("SELECT id FROM quotes") if r["id"] not in before][0]
    post(c, f"/quotes/{qid}/items", product_id=str(pid), quantity="10", discount="0")
    item = one("SELECT id FROM quote_items WHERE quote_id = ?", qid)
    post(c, f"/quotes/{qid}", **{f"quantity_{item['id']}": "10", f"discount_{item['id']}": "0", "header_discount": header,
                                 "valid_until": "2999-12-31", "notes_customer": "Entrega terça", "notes_internal": "SEGREDO-INTERNO"})
    post(c, f"/quotes/{qid}/submit")
    if send:
        post(c, f"/quotes/{qid}/send")
    return qid

def invite_link(c, cid, email):
    post(c, f"/customers/{cid}/buyers/invite", email=email)
    page = c.get(f"/customers/{cid}").text
    m = re.search(r'id="buyer-link" readonly type="text" value="[^"]*/invite/([^"]+)"', page)
    return m.group(1) if m else None, page

a, b = app.test_client(), app.test_client()
register(a, "dono@a.com", ws="Dist A")
register(b, "dono@b.com", ws="Dist B")
wa, ca, oa, pa = setup(a, "A", "Restaurante do Zé", phone="(11) 98765-4321")
wb, cb, ob, pb = setup(b, "B", "Restaurante do Zé na B")
post(a, "/customers/new", name="Outro cliente A")
ca2 = one("SELECT id FROM companies WHERE name = 'Outro cliente A'")["id"]

print("-- staff invites a buyer")
token, page = invite_link(a, ca, "ze@rest.com")
show("buyer invite link shown once, WhatsApp to customer's phone", token is not None and "wa.me/5511987654321?text=" in page)
show("only hash stored, kind customer, linked to the customer", one("SELECT kind, company_id, role FROM invites WHERE email='ze@rest.com'") == {"kind": "customer", "company_id": ca, "role": None})
show("link not shown again", 'id="buyer-link"' not in a.get(f"/customers/{ca}").text)
_, page = invite_link(a, ca, "ze@rest.com")
show("duplicate pending invite refused", "convite pendente" in page)
_, page = invite_link(a, ca, "nao-é-email")
show("invalid email refused", "e-mail válido" in page)

print("-- buyer signs up through the invite")
anon = app.test_client()
r = anon.get(f"/invite/{token}")
show("invite page talks about quotes of Dist A", "Orçamentos da Dist A" in r.text and "Restaurante do Zé" in r.text)
r = register(anon, "hacker@x.com", invite=token)
u = one("SELECT * FROM users WHERE email = 'ze@rest.com'")
show("account created with invited email, source invite, referred by A", u and u["signup_source"] == "invite" and u["referred_by_workspace_id"] == wa)
show("no workspace created; lands on portal", one("SELECT COUNT(*) n FROM memberships WHERE user_id = ?", u["id"])["n"] == 0 and r.headers["Location"] == "/portal")
show("linked to the customer", one("SELECT 1 x FROM customer_users WHERE user_id = ? AND company_id = ?", u["id"], ca))
show("buyer counts nothing in the plan (users still 1)", one("SELECT COUNT(*) n FROM memberships WHERE workspace_id = ?", wa)["n"] == 1)
buyer = anon
show("customer page shows 'Trazido por você'", "Trazido por você" in a.get(f"/customers/{ca}").text and "Trazido por você" in a.get("/customers").text)

print("-- the same buyer also buys from B (existing account)")
token_b, _ = invite_link(b, cb, "ze@rest.com")
r = post(buyer, f"/invite/{token_b}/accept")
show("existing account accepts B's invite", r.status_code == 302 and one("SELECT COUNT(*) n FROM customer_users WHERE user_id = ?", u["id"])["n"] == 2)
show("referred_by stays A (first distributor)", one("SELECT referred_by_workspace_id r FROM users WHERE id = ?", u["id"])["r"] == wa)
show("B doesn't get 'Trazido por você'", "Trazido por você" not in b.get(f"/customers/{cb}").text)

print("-- what the buyer sees")
q_draft = make_quote(a, oa, pa, send=False)
q_sent = make_quote(a, oa, pa)
q_b = make_quote(b, ob, pb)
q_other = make_quote(a, one("SELECT id FROM opportunities WHERE company_id = ?", ca2)["id"] if one("SELECT id FROM opportunities WHERE company_id = ?", ca2) else oa, pa)
r = buyer.get("/portal")
show("portal groups both distributors", "Dist A" in r.text and "Dist B" in r.text)
show("sent quotes listed, draft/ready not", f"/portal/quotes/{q_sent}" in r.text and f"/portal/quotes/{q_b}" in r.text and f"/portal/quotes/{q_draft}" not in r.text)
r = buyer.get(f"/portal/quotes/{q_sent}")
show("quote page: items, totals, customer notes", r.status_code == 200 and "Arroz A" in r.text and "R$ 1.000,00" in r.text and "Entrega terça" in r.text)
show("NEVER internal notes, cost or margin", "SEGREDO-INTERNO" not in r.text and "70,00" not in r.text and "Margem" not in r.text)
show("draft/ready quote -> 404", buyer.get(f"/portal/quotes/{q_draft}").status_code == 404)
post(a, "/customers/new", name="Cliente sem comprador")
cx = one("SELECT id FROM companies WHERE name = 'Cliente sem comprador'")["id"]
stage = one("SELECT id FROM stages WHERE workspace_id = ? ORDER BY position LIMIT 1", wa)["id"]
post(a, "/opportunities/new", title="Opp X", company_id=str(cx), stage_id=str(stage))
ox = one("SELECT id FROM opportunities WHERE title = 'Opp X'")["id"]
qx = make_quote(a, ox, pa)
show("quote of a customer the buyer isn't linked to -> 404", buyer.get(f"/portal/quotes/{qx}").status_code == 404)
show("staff of A (not a buyer) gets 404 in the portal quote", a.get(f"/portal/quotes/{q_sent}").status_code == 404)
stranger = app.test_client(); register(stranger, "x@y.com", kind="buyer")
show("random buyer -> 404, and accept blocked", stranger.get(f"/portal/quotes/{q_sent}").status_code == 404 and post(stranger, f"/portal/quotes/{q_sent}/accept").status_code == 404)
show("logged out -> login", app.test_client().get(f"/portal/quotes/{q_sent}").status_code == 302)

print("-- accept")
q_sent2 = make_quote(a, oa, pa)
r = post(buyer, f"/portal/quotes/{q_sent}/accept")
q = one("SELECT * FROM quotes WHERE id = ?", q_sent)
opp = one("SELECT o.*, s.kind FROM opportunities o JOIN stages s ON s.id = o.stage_id WHERE o.id = ?", oa)
show("quote accepted by the buyer", q["status"] == "accepted" and q["customer_user_id"] == u["id"] and q["customer_decided_at"])
show("opportunity moved to won with the quote total", opp["kind"] == "won" and opp["value_cents"] == q["final_total_cents"] and opp["closed_at"])
show("other open quotes of the opportunity cancelled", one("SELECT status FROM quotes WHERE id = ?", q_sent2)["status"] == "cancelled"
     and one("SELECT status FROM quotes WHERE id = ?", q_draft)["status"] == "cancelled")
acts = [x["type"] for x in db.execute("SELECT type FROM activities WHERE quote_id = ? ORDER BY id", q_sent)]
show("history: accepted + stage change, by the buyer, in A's workspace", "quote_accepted" in acts and "stage_change" in acts
     and one("SELECT user_id, workspace_id FROM activities WHERE type='quote_accepted' AND quote_id = ?", q_sent) == {"user_id": u["id"], "workspace_id": wa})
decided_at = one("SELECT customer_decided_at d FROM quotes WHERE id = ?", q_sent)["d"]
show("accept twice refused (basic portal hides decided quotes -> 404) and nothing changes",
     post(buyer, f"/portal/quotes/{q_sent}/accept").status_code == 404 and one("SELECT customer_decided_at d FROM quotes WHERE id = ?", q_sent)["d"] == decided_at)
show("staff sees 'Aceito' on the quote", "Aceito pelo cliente" in a.get(f"/quotes/{q_sent}").text)

print("-- decline, basic vs full portal, expiry")
post(buyer, f"/portal/quotes/{q_b}/decline", reason="Achei caro")
qb = one("SELECT * FROM quotes WHERE id = ?", q_b)
show("Free plan (basic portal): declined without storing a reason", qb["status"] == "declined" and qb["decline_reason"] is None)
show("basic portal hides the history", f"/portal/quotes/{q_b}" not in buyer.get("/portal").text and buyer.get(f"/portal/quotes/{q_b}").status_code == 404)
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='essencial') WHERE id = ?", wa)
show("full portal (Essencial) shows history", f"/portal/quotes/{q_sent}" in buyer.get("/portal").text)
q_full = make_quote(a, oa, pa)
db.execute("UPDATE opportunities SET stage_id = ? WHERE id = ?", stage, oa)
show("full portal offers a decline reason", 'name="reason"' in buyer.get(f"/portal/quotes/{q_full}").text)
post(buyer, f"/portal/quotes/{q_full}/decline", reason="Prazo longo")
show("reason stored and in history", one("SELECT decline_reason FROM quotes WHERE id = ?", q_full)["decline_reason"] == "Prazo longo"
     and one("SELECT body FROM activities WHERE type='quote_declined' AND quote_id = ?", q_full)["body"] == "Prazo longo")
show("decline doesn't move the opportunity", one("SELECT stage_id FROM opportunities WHERE id = ?", oa)["stage_id"] == stage)
q_exp = make_quote(a, oa, pa)
db.execute("UPDATE quotes SET valid_until = '2000-01-01' WHERE id = ?", q_exp)
r = buyer.get(f"/portal/quotes/{q_exp}")
show("expired when the buyer opens it; can't accept", one("SELECT status FROM quotes WHERE id = ?", q_exp)["status"] == "expired"
     and post(buyer, f"/portal/quotes/{q_exp}/accept").status_code == 302 and one("SELECT status FROM quotes WHERE id = ?", q_exp)["status"] == "expired")

print("-- staff side: WhatsApp link, revoke, remove")
q_link = make_quote(a, oa, pa)
show("staff WhatsApp message carries the portal link to the customer's phone", f"/portal/quotes/{q_link}" in html.unescape(a.get(f"/quotes/{q_link}").text) and "wa.me/5511987654321" in a.get(f"/quotes/{q_link}").text)
t2, _ = invite_link(a, ca, "maria@rest.com")
inv = one("SELECT id FROM invites WHERE email = 'maria@rest.com'")["id"]
post(a, f"/customers/{ca}/buyers/invites/{inv}/revoke")
show("revoked buyer invite -> 404", app.test_client().get(f"/invite/{t2}").status_code == 404)
show("B can't revoke A's buyer invite", post(b, f"/customers/{ca}/buyers/invites/{inv}/revoke").status_code == 404)
post(a, f"/customers/{ca}/buyers/{u['id']}/remove")
show("remove access: link gone, account and B link kept", one("SELECT COUNT(*) n FROM customer_users WHERE user_id = ?", u["id"])["n"] == 1
     and buyer.get(f"/portal/quotes/{q_link}").status_code == 404)
