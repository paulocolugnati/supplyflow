"""
EN: Scenario: discount approval: ceilings per role, minimum margin, exact approval, no self-approval.
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: aprovação de desconto: tetos por cargo, margem mínima, aprovação exata, ninguém aprova o próprio pedido.
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

def status(qid):
    return one("SELECT status FROM quotes WHERE id = ?", qid)["status"]

def join(owner, email, role):
    post(owner, "/team/invite", email=email, role=role)
    link = re.search(r'/invite/([^"]+)"', owner.get("/team").text).group(1)
    c = app.test_client(); register(c, email, invite=link)
    return c

# EN/PT: Essencial plan (approval + min margin), seller 5%, manager 15%, margin 15%
owner = app.test_client()
register(owner, "dono@a.com", ws="Dist A")
wa = one("SELECT id FROM workspaces")["id"]
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='essencial'), onboarding_done = 1 WHERE id = ?", wa)
manager = join(owner, "gerente@a.com", "admin")
seller = join(owner, "vend@a.com", "member")
post(owner, "/customers/new", name="Restaurante")
cid = one("SELECT id FROM companies")["id"]
stage = one("SELECT id FROM stages ORDER BY position LIMIT 1")["id"]
# EN/PT: the deal belongs to the seller, so seller, manager and owner can all see it (rule of 15.1)
#        a oportunidade é do vendedor, então vendedor, gerente e dono enxergam (regra da 15.1)
post(owner, "/opportunities/new", title="Pedido", company_id=str(cid), stage_id=str(stage),
     owner_id=str(one("SELECT id FROM users WHERE email='vend@a.com'")["id"]))
oid = one("SELECT id FROM opportunities")["id"]
post(owner, "/products/new", sku="ARZ", name="Arroz", unit="cx", price="100,00", cost_mode="brl", cost="60,00")
pid = one("SELECT id FROM products")["id"]

def new_quote(c, qty="10", item_discount="0", header="0"):
    before = {r["id"] for r in db.execute("SELECT id FROM quotes")}
    post(c, f"/opportunities/{oid}/quotes")
    qid = [r["id"] for r in db.execute("SELECT id FROM quotes") if r["id"] not in before][0]
    post(c, f"/quotes/{qid}/items", product_id=str(pid), quantity=qty, discount=item_discount)
    if header != "0":
        set_header(c, qid, header)
    return qid

def set_header(c, qid, header):
    item = one("SELECT id, quantity, discount_bps FROM quote_items WHERE quote_id = ?", qid)
    post(c, f"/quotes/{qid}", **{f"quantity_{item['id']}": str(item["quantity"]), f"discount_{item['id']}": str(item["discount_bps"] / 100),
                                 "header_discount": header, "valid_until": "2999-12-31"})

print("-- within the ceiling")
q1 = new_quote(seller, header="4")
r = seller.get(f"/quotes/{q1}")
show("page says within ceiling", "Dentro do seu teto" in r.text)
post(seller, f"/quotes/{q1}/submit")
show("4% by seller -> ready (no approval)", status(q1) == "ready")
post(seller, f"/quotes/{q1}/send")
show("ready -> sent, sent_at set", status(q1) == "sent" and one("SELECT sent_at FROM quotes WHERE id = ?", q1)["sent_at"])
show("sent page offers WhatsApp summary", "wa.me/?text=" in seller.get(f"/quotes/{q1}").text)
show("sent quote can't be edited", post(seller, f"/quotes/{q1}", header_discount="1").status_code == 409)
show("history: ready + sent", one("SELECT COUNT(*) n FROM activities WHERE quote_id = ?", q1)["n"] == 2)

print("-- above the seller's ceiling")
q2 = new_quote(seller, header="10")
r = seller.get(f"/quotes/{q2}")
show("page explains approval by manager", "precisa de aprovação do Gerente" in r.text)
r = post(seller, f"/quotes/{q2}/submit", reason="")
show("reason required", status(q2) == "draft")
post(seller, f"/quotes/{q2}/submit", reason="Cliente grande")
req = one("SELECT * FROM discount_requests WHERE quote_id = ?", q2)
show("10% -> pending, request for admin with 1000 bps", status(q2) == "pending_approval" and req["required_role"] == "admin" and req["requested_discount_bps"] == 1000)
show("pending quote can't be sent (state machine)", post(seller, f"/quotes/{q2}/send").status_code == 409)
show("seller has no approvals page", seller.get("/approvals").status_code == 403)
show("seller can't approve by posting directly -> 403", post(seller, f"/approvals/{req['id']}/approve").status_code == 403)
r = manager.get("/approvals")
show("manager sees the request + menu badge", "Cliente grande" in r.text and 'class="contagem-nav"' in r.text)
post(manager, f"/approvals/{req['id']}/approve", note="ok, cliente fiel")
q = one("SELECT * FROM quotes WHERE id = ?", q2)
show("approved: ready, approved exactly 10%, approver recorded", q["status"] == "ready" and q["approved_discount_bps"] == 1000
     and q["approved_by"] == one("SELECT id FROM users WHERE email='gerente@a.com'")["id"])
show("request closed", one("SELECT status FROM discount_requests WHERE id = ?", req["id"])["status"] == "approved")
show("deciding twice refused", post(manager, f"/approvals/{req['id']}/approve").status_code == 409)

print("-- the bypass: approve 10%, then raise to 25%")
show("ready quote not editable directly", post(seller, f"/quotes/{q2}", header_discount="25").status_code == 409)
post(seller, f"/quotes/{q2}/reopen")
q = one("SELECT * FROM quotes WHERE id = ?", q2)
show("reopen -> draft and approval dropped", q["status"] == "draft" and q["approved_discount_bps"] is None and q["approved_by"] is None)
set_header(seller, q2, "25")
db.execute("UPDATE quotes SET status = 'ready', approved_discount_bps = 1000 WHERE id = ?", q2)   # EN/PT: forged state | estado forjado
r = post(seller, f"/quotes/{q2}/send")
show("even with a forged 'ready' + old approval, sending 25% is refused", r.status_code == 409 and status(q2) == "ready")
db.execute("UPDATE quotes SET status = 'draft', approved_discount_bps = NULL WHERE id = ?", q2)
post(seller, f"/quotes/{q2}/submit", reason="Concorrente agressivo")
req2 = one("SELECT * FROM discount_requests WHERE quote_id = ? ORDER BY id DESC", q2)
show("25% -> needs the owner", req2["required_role"] == "owner")
show("manager doesn't see owner-level request", "Concorrente agressivo" not in manager.get("/approvals").text)
show("manager can't approve owner-level request -> 403", post(manager, f"/approvals/{req2['id']}/approve").status_code == 403)
post(owner, f"/approvals/{req2['id']}/reject", note="")
show("reject without note refused", status(q2) == "pending_approval")
post(owner, f"/approvals/{req2['id']}/reject", note="Margem não permite")
show("rejected -> back to draft, history has the note", status(q2) == "draft"
     and one("SELECT body FROM activities WHERE quote_id = ? AND type = 'discount_rejected'", q2)["body"] == "Margem não permite")

print("-- self-approval and margin")
q3 = new_quote(manager, header="20")
post(manager, f"/quotes/{q3}/submit", reason="Volume alto")
req3 = one("SELECT * FROM discount_requests WHERE quote_id = ?", q3)
show("manager above own ceiling -> owner", req3["required_role"] == "owner")
show("manager can't approve own request", post(manager, f"/approvals/{req3['id']}/approve").status_code == 403)
db.execute("UPDATE workspaces SET admin_discount_limit_bps = 3000 WHERE id = ?", wa)
q4 = new_quote(seller, header="7")
post(seller, f"/quotes/{q4}/submit", reason="Teste")
req4 = one("SELECT * FROM discount_requests WHERE quote_id = ?", q4)
db.execute("UPDATE discount_requests SET requested_by = (SELECT id FROM users WHERE email='gerente@a.com') WHERE id = ?", req4["id"])
show("DB also blocks self-decision (CHECK)", post(manager, f"/approvals/{req4['id']}/approve").status_code == 403)
db.execute("UPDATE workspaces SET admin_discount_limit_bps = 1500 WHERE id = ?", wa)
q5 = new_quote(seller, item_discount="0", header="3")
post(owner, f"/products/{pid}/edit", sku="ARZ", name="Arroz", unit="cx", price="100,00", cost_mode="brl", cost="95,00")
q6 = new_quote(seller, header="3")
r = seller.get(f"/quotes/{q6}")
show("margin below minimum triggers approval within ceiling", "margem abaixo da mínima" in html.unescape(r.text))
post(seller, f"/quotes/{q6}/submit", reason="Produto de entrada")
show("margin case -> pending for admin", status(q6) == "pending_approval" and one("SELECT required_role FROM discount_requests WHERE quote_id = ?", q6)["required_role"] == "admin")
q7 = new_quote(owner, header="40")
post(owner, f"/quotes/{q7}/submit")
show("owner never needs approval", status(q7) == "ready")

print("-- cancel, duplicate, expire")
post(seller, f"/quotes/{q6}/cancel")
show("cancel pending -> cancelled, request cancelled", status(q6) == "cancelled" and one("SELECT status FROM discount_requests WHERE quote_id = ?", q6)["status"] == "cancelled")
show("cancelled is final", post(seller, f"/quotes/{q6}/reopen").status_code == 409)
r = post(manager, f"/quotes/{q1}/duplicate")
dup = one("SELECT * FROM quotes ORDER BY id DESC")
show("duplicate -> new draft owned by who duplicated, same items", dup["status"] == "draft" and dup["created_by"] == one("SELECT id FROM users WHERE email='gerente@a.com'")["id"]
     and one("SELECT COUNT(*) n FROM quote_items WHERE quote_id = ?", dup["id"])["n"] == 1 and dup["final_total_cents"] == one("SELECT final_total_cents FROM quotes WHERE id = ?", q1)["final_total_cents"])
db.execute("UPDATE quotes SET valid_until = '2000-01-01' WHERE id = ?", q1)
seller.get("/quotes")
show("sent quote past validity -> expired when listed", status(q1) == "expired")
show("member can't cancel someone else's quote", post(seller, f"/quotes/{q7}/cancel").status_code == 403)

print("-- isolation")
other = app.test_client(); register(other, "b@b.com", ws="Dist B")
show("other workspace: quote and request -> 404", other.get(f"/quotes/{q2}").status_code == 404
     and post(other, f"/approvals/{req2['id']}/approve").status_code == 404 and post(other, f"/quotes/{q2}/submit").status_code == 404)
show("nav has Aprovações for admin, not for member", 'href="/approvals"' in manager.get("/dashboard").text and 'href="/approvals"' not in seller.get("/dashboard").text)
