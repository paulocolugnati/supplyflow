"""
EN: Scenario: roles, isolation between distributors (404), plan quotas and features.
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: cargos, isolamento entre distribuidoras (404), cotas e recursos do plano.
    Passa pelas rotas de verdade num banco temporário (veja o common.py).
"""

from common import *  # noqa: F401,F403

import permissions as P
from flask import jsonify, g

# EN/PT: test-only routes, registered before the first request
@app.route("/t/scoped/<table>/<row_id>")
@P.require_role("member")
def t_scoped(table, row_id):
    return str(P.get_scoped(table, row_id)["id"])

@app.route("/t/admin")
@P.require_role("admin")
def t_admin():
    return "admin ok"

@app.route("/t/owner")
@P.require_role("owner")
def t_owner():
    return "owner ok"

@app.route("/t/quota/<res>")
@P.require_role("member")
def t_quota(res):
    used, limit = P.quota_usage(res)
    return jsonify(used=used, limit=limit, ok=P.check_quota(res))

@app.route("/t/feature/<name>")
@P.require_role("member")
def t_feature(name):
    return jsonify(on=P.has_feature(name))

@app.route("/t/can_modify/<int:owner>")
@P.require_role("member")
def t_can_modify(owner):
    return jsonify(ok=P.can_modify({"owner_id": owner}))

def token(c, url="/login"):
    return re.search(r'name="_csrf" type="hidden" value="([^"]+)"', c.get(url).text).group(1)

def register(c, email, kind="distributor", ws="Dist"):
    t = token(c, "/register")
    return c.post("/register", data=dict(_csrf=t, account_type=kind, name="Nome", email=email, phone="",
                                         workspace_name=ws, password="12345678", confirmation="12345678"))

a, b, buyer, anon = app.test_client(), app.test_client(), app.test_client(), app.test_client()
register(a, "a@x.com", ws="Dist A")
register(b, "b@x.com", ws="Dist B")
register(buyer, "z@x.com", kind="buyer")
ua = db.execute("SELECT id FROM users WHERE email='a@x.com'")[0]["id"]
ub = db.execute("SELECT id FROM users WHERE email='b@x.com'")[0]["id"]
wa = db.execute("SELECT id FROM workspaces WHERE name='Dist A'")[0]["id"]
wb = db.execute("SELECT id FROM workspaces WHERE name='Dist B'")[0]["id"]
ca = db.execute("INSERT INTO companies (workspace_id, name) VALUES (?, 'Cliente A')", wa)
cb = db.execute("INSERT INTO companies (workspace_id, name) VALUES (?, 'Cliente B')", wb)

print("-- tenant isolation")
show("A reads own company", a.get(f"/t/scoped/companies/{ca}").status_code == 200)
show("A reads B's company -> 404", a.get(f"/t/scoped/companies/{cb}").status_code == 404)
show("B reads A's company -> 404", b.get(f"/t/scoped/companies/{ca}").status_code == 404)
show("id '1 OR 1=1' -> 404", a.get("/t/scoped/companies/1%20OR%201=1").status_code == 404)
show("id 'abc' -> 404", a.get("/t/scoped/companies/abc").status_code == 404)
try:
    with app.test_request_context():
        g.membership = {"workspace_id": wa}
        P.get_scoped("users", 1)
    show("table outside whitelist refused", False)
except ValueError:
    show("table outside whitelist refused", True)

print("-- roles")
show("anonymous -> login", anon.get("/t/admin").status_code == 302 and "/login" in anon.get("/t/admin").headers["Location"])
show("buyer -> portal", buyer.get("/t/admin").headers["Location"] == "/portal")
show("owner passes admin and owner routes", a.get("/t/admin").text == "admin ok" and a.get("/t/owner").text == "owner ok")

# EN/PT: put B's user into A as member, then switch
db.execute("INSERT INTO memberships (workspace_id, user_id, role) VALUES (?, ?, 'member')", wa, ub)
r = b.get("/dashboard"); show("switcher visible with 2 workspaces", "Trocar distribuidora" in r.text)
t = token(b, "/dashboard")
r = b.post("/workspace/switch", data=dict(_csrf=t, workspace_id=str(wa)))
show("switch to A ok", r.status_code == 302 and "Dist A" in b.get("/dashboard").text)
show("member blocked from admin route -> 403", b.get("/t/admin").status_code == 403)
show("member blocked from onboarding -> 403", b.get("/onboarding").status_code == 403)
show("member now reads A's company", b.get(f"/t/scoped/companies/{ca}").status_code == 200)
show("member can modify own record", b.get(f"/t/can_modify/{ub}").json["ok"] is True)
show("member can't modify other's record", b.get(f"/t/can_modify/{ua}").json["ok"] is False)
show("owner can modify any record", a.get(f"/t/can_modify/{ub}").json["ok"] is True)
other = db.execute("INSERT INTO workspaces (name, plan_id) VALUES ('Dist C', 1)")
r = b.post("/workspace/switch", data=dict(_csrf=t, workspace_id=str(other)))
show("switch to foreign workspace -> 404", r.status_code == 404)
r = b.post("/workspace/switch", data=dict(_csrf=t, workspace_id="abc"))
show("switch with garbage -> 404", r.status_code == 404)

# EN/PT: remove B from A while logged in: next request falls back to B's own workspace
db.execute("DELETE FROM memberships WHERE workspace_id = ? AND user_id = ?", wa, ub)
r = b.get(f"/t/scoped/companies/{ca}")
show("removed member loses access immediately -> 404", r.status_code == 404)
show("falls back to own workspace", "Dist B" in b.get("/dashboard").text)

print("-- plan quotas (Free: 30 customers, 1 user)")
q = a.get("/t/quota/customers").json
show("customers 1/30 ok", q == {"used": 1, "limit": 30, "ok": True})
for i in range(29):
    db.execute("INSERT INTO companies (workspace_id, name) VALUES (?, ?)", wa, f"C{i}")
q = a.get("/t/quota/customers").json
show("customers 30/30 blocked", q["used"] == 30 and q["ok"] is False)
q = a.get("/t/quota/users").json
show("users 1/1 blocked", q == {"used": 1, "limit": 1, "ok": False})
show("free plan: no approval feature", a.get("/t/feature/discount_approval").json["on"] is False)

db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='essencial') WHERE id = ?", wa)
show("essencial: approval feature on", a.get("/t/feature/discount_approval").json["on"] is True)
show("essencial: customers 30/100 ok", a.get("/t/quota/customers").json["ok"] is True)
db.execute("INSERT INTO invites (workspace_id, kind, email, role, token_hash, created_by, expires_at) "
           "VALUES (?, 'staff', 'n@x.com', 'admin', 'h1', ?, '2999-01-01 00:00:00')", wa, ua)
show("pending admin invite counts: admins 1/1 blocked", a.get("/t/quota/admins").json == {"used": 1, "limit": 1, "ok": False})
db.execute("INSERT INTO invites (workspace_id, kind, email, role, token_hash, created_by, expires_at) "
           "VALUES (?, 'staff', 'old@x.com', 'member', 'h2', ?, '2000-01-01 00:00:00')", wa, ua)
show("expired invite doesn't count: users 2/3", a.get("/t/quota/users").json["used"] == 2)

db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='escala') WHERE id = ?", wa)
q = a.get("/t/quota/customers").json
show("escala: unlimited", q["limit"] is None and q["ok"] is True)
show("escala: 2 owners allowed", a.get("/t/quota/owners").json == {"used": 1, "limit": 2, "ok": True})

pid = db.execute("SELECT id FROM pipelines WHERE workspace_id = ?", wa)[0]["id"]
sid = db.execute("SELECT id FROM stages WHERE pipeline_id = ? LIMIT 1", pid)[0]["id"]
oid = db.execute("INSERT INTO opportunities (workspace_id, pipeline_id, stage_id, company_id, title) VALUES (?,?,?,?, 'O')", wa, pid, sid, ca)
db.execute("INSERT INTO quotes (workspace_id, number, opportunity_id, company_id, created_by, valid_until, created_at) VALUES (?,1,?,?,?, '2999-01-01', '2000-01-01 00:00:00')", wa, oid, ca, ua)
db.execute("INSERT INTO quotes (workspace_id, number, opportunity_id, company_id, created_by, valid_until, status) VALUES (?,2,?,?,?, '2999-01-01', 'cancelled')", wa, oid, ca, ua)
show("quotes_month counts this month incl. cancelled, not old ones", a.get("/t/quota/quotes_month").json["used"] == 1)

r = a.get("/dashboard"); show("dashboard shows usage card", "Uso do plano" in r.text and "ilimitado" in r.text)
