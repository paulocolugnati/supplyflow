"""
EN: Scenario: team invites (hash, expiry, single use), roles, owners, transfer, leave.
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: convites da equipe (hash, validade, uso único), cargos, donos, transferência, sair.
    Passa pelas rotas de verdade num banco temporário (veja o common.py).
"""

from common import *  # noqa: F401,F403

def tok(c, url="/login"):
    m = re.search(r'name="_csrf" type="hidden" value="([^"]+)"', c.get(url).text)
    # EN/PT: pages without forms (e.g. wrong-email invite) -> take the token from the portal
    return m.group(1) if m else re.search(r'name="_csrf" type="hidden" value="([^"]+)"', c.get("/portal").text).group(1)

def register(c, email, kind="distributor", ws="Dist A", invite=None):
    t = tok(c, "/register" + (f"?invite={invite}" if invite else ""))
    data = dict(_csrf=t, account_type=kind, name="Nome " + email, email=email, phone="",
                workspace_name=ws, password="12345678", confirmation="12345678")
    if invite: data["invite"] = invite
    return c.post("/register", data=data)

def login(c, email):
    return c.post("/login", data=dict(_csrf=tok(c), email=email, password="12345678"))

def post(c, url, **data):
    data["_csrf"] = tok(c, "/dashboard" if "/invite/" not in url else url.rsplit("/accept", 1)[0])
    return c.post(url, data=data)

def invite(c, email, role):
    post(c, "/team/invite", email=email, role=role)
    html = c.get("/team").text
    m = re.search(r'id="invite-link" readonly type="text" value="[^"]*/invite/([^"]+)"', html)
    return (m.group(1) if m else None), html

def uid(email):
    return db.execute("SELECT id FROM users WHERE email = ?", email)[0]["id"]

owner = app.test_client()
register(owner, "dono@a.com")
wa = db.execute("SELECT id FROM workspaces")[0]["id"]

print("-- invites and quotas")
token, html = invite(owner, "x@a.com", "admin")
show("free plan: invite blocked by quota", token is None and "limite do seu plano" in html)
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='essencial') WHERE id = ?", wa)
t_admin, html = invite(owner, "x@a.com", "admin")
show("essencial: admin invite created, link shown once", t_admin is not None)
show("link not shown again", "invite-link" not in owner.get("/team").text)
show("only hash stored", db.execute("SELECT token_hash FROM invites")[0]["token_hash"] != t_admin)
_, html = invite(owner, "x@a.com", "admin")
show("second invite same email -> pending error", "convite pendente" in html)
_, html = invite(owner, "y@a.com", "admin")
show("second admin -> quota (admins 1/1 incl. pending)", "limite do seu plano" in html)
_, html = invite(owner, "bad-email", "member")
show("invalid email rejected", "e-mail válido" in html)
_, html = invite(owner, "y@a.com", "owner")
show("role 'owner' can't be invited", "permissão" in html)
t_member, _ = invite(owner, "m@a.com", "member")
show("member invite created", t_member is not None)

print("-- accepting")
anon = app.test_client()
r = anon.get(f"/invite/{t_admin}")
show("invite page for logged-out user", r.status_code == 200 and "Dist A" in r.text and "Criar minha conta" in r.text)
show("tampered token -> 404", anon.get(f"/invite/{t_admin}x").status_code == 404)
r = register(anon, "attacker@evil.com", invite=t_admin)   # EN/PT: email in form is ignored
show("register via invite -> dashboard", r.status_code == 302 and r.headers["Location"] == "/dashboard")
row = db.execute("SELECT u.email, m.role, u.signup_source FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.role='admin'")[0]
show("email forced from invite, role admin, source invite",
     row["email"] == "x@a.com" and row["role"] == "admin" and row["signup_source"] == "invite")
show("used link -> 404", app.test_client().get(f"/invite/{t_admin}").status_code == 404)
show("navbar shows Equipe for admin", "Equipe" in anon.get("/dashboard").text)
admin = anon

buyer = app.test_client()
register(buyer, "z@b.com", kind="buyer")
r = buyer.get(f"/invite/{t_member}")
show("other logged account sees wrong-email warning", "outro e-mail" in r.text)
r = post(buyer, f"/invite/{t_member}/accept")
show("accept with wrong email -> 403", r.status_code == 403)

mem = app.test_client()
register(mem, "m@a.com", kind="buyer")        # EN/PT: account exists before accepting
r = post(mem, f"/invite/{t_member}/accept")
show("existing account with right email accepts", r.status_code == 302
     and db.execute("SELECT role FROM memberships WHERE user_id = ?", uid("m@a.com"))[0]["role"] == "member")
show("member doesn't see Equipe / gets 403 on /team", mem.get("/team").status_code == 403)

print("-- permissions")
_, html = invite(admin, "w@a.com", "admin")
show("admin can't invite admin", "permissão" in html)
t_w, html = invite(admin, "w@a.com", "member")
show("admin invites a member -> Essencial now holds 4 (users 4/4)", t_w is not None)
_, html = invite(admin, "v@a.com", "member")
show("5th person blocked (users 4/4)", "limite do seu plano" in html)
r = post(admin, f"/team/members/{uid('dono@a.com')}/remove")
show("admin can't remove owner", r.status_code == 403)
r = post(admin, f"/team/members/{uid('m@a.com')}/role", role="admin")
show("admin can't change roles", r.status_code == 403)
r = post(owner, f"/team/members/{uid('m@a.com')}/role", role="admin")
show("owner: member->admin blocked by admins quota", "limite do seu plano" in owner.get("/team").text or r.status_code == 302)
show("...and role unchanged", db.execute("SELECT role FROM memberships WHERE user_id = ?", uid("m@a.com"))[0]["role"] == "member")
r = post(owner, f"/team/members/{uid('m@a.com')}/role", role="owner")
show("role endpoint refuses 'owner'", r.status_code == 403)
r = post(owner, f"/team/members/{uid('dono@a.com')}/role", role="member")
show("owner can't change own role", r.status_code == 403)

other = app.test_client()
register(other, "b@b.com", ws="Dist B")
r = post(other, f"/team/members/{uid('m@a.com')}/remove")
show("owner of B can't remove member of A", r.status_code == 403
     and db.execute("SELECT COUNT(*) n FROM memberships WHERE user_id = ?", uid("m@a.com"))[0]["n"] == 1)

print("-- owners")
r = post(owner, f"/team/members/{uid('x@a.com')}/owner")
show("essencial: co-owner blocked", db.execute("SELECT role FROM memberships WHERE user_id = ?", uid("x@a.com"))[0]["role"] == "admin")
r = post(owner, "/team/leave")
show("last owner can't leave", db.execute("SELECT COUNT(*) n FROM memberships WHERE user_id = ?", uid("dono@a.com"))[0]["n"] == 1)
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='escala') WHERE id = ?", wa)
post(owner, f"/team/members/{uid('x@a.com')}/owner")
show("escala: admin becomes co-owner", db.execute("SELECT role FROM memberships WHERE user_id = ?", uid("x@a.com"))[0]["role"] == "owner")
r = post(admin, f"/team/members/{uid('dono@a.com')}/remove")
show("co-owner can't remove the other owner", r.status_code == 403)
r = post(admin, f"/team/members/{uid('dono@a.com')}/role", role="member")
show("co-owner can't demote the other owner", r.status_code == 403)

r = post(owner, f"/team/members/{uid('m@a.com')}/transfer")
show("transfer: owner->admin, member->owner", db.execute("SELECT role FROM memberships WHERE user_id = ?", uid("dono@a.com"))[0]["role"] == "admin"
     and db.execute("SELECT role FROM memberships WHERE user_id = ?", uid("m@a.com"))[0]["role"] == "owner")
r = post(admin, "/team/leave")
show("with 2 owners, one can leave", db.execute("SELECT COUNT(*) n FROM memberships WHERE user_id = ?", uid("x@a.com"))[0]["n"] == 0)

print("-- revoke and expiry")
t_rev, _ = invite(mem, "r@a.com", "member")
inv_id = db.execute("SELECT id FROM invites WHERE email='r@a.com'")[0]["id"]
post(mem, f"/team/invites/{inv_id}/revoke")
show("revoked invite link -> 404", app.test_client().get(f"/invite/{t_rev}").status_code == 404)
r = post(other, f"/team/invites/{inv_id}/revoke")
show("other workspace can't touch invite -> 404", r.status_code == 404)
t_exp, _ = invite(mem, "e@a.com", "member")
db.execute("UPDATE invites SET expires_at = '2000-01-01 00:00:00' WHERE email='e@a.com'")
show("expired invite -> 404", app.test_client().get(f"/invite/{t_exp}").status_code == 404)
show("invalid invite on register -> 404", app.test_client().get(f"/register?invite={t_exp}").status_code == 404)
