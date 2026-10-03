"""
EN: Scenario: sign-up (distributor, buyer, invites), login, logout, open redirects, onboarding, language.
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: cadastro (distribuidora, comprador, convites), login, logout, redirecionamentos abertos, onboarding, idioma.
    Passa pelas rotas de verdade num banco temporário (veja o common.py).
"""

from common import *  # noqa: F401,F403

def token(c, url):
    html = c.get(url).text
    m = re.search(r'name="_csrf" type="hidden" value="([^"]+)"', html)
    return m.group(1)

c = app.test_client()
t = token(c, "/register")

def reg(**kw):
    data = dict(_csrf=t, account_type="distributor", name="Ana", email="ana@x.com", phone="",
                workspace_name="Distribuidora Ana", password="12345678", confirmation="12345678")
    data.update(kw)
    return c.post("/register", data=data)

r = reg(name="", email="ruim", password="123", confirmation="123")
show("empty/invalid fields -> 400 with errors", r.status_code == 400 and "e-mail válido" in r.text and "8 a 128" in r.text)
r = reg(confirmation="diferente")
show("different passwords -> 400", r.status_code == 400 and "não são iguais" in r.text)
r = reg(workspace_name="")
show("distributor without workspace -> 400", r.status_code == 400)
r = reg(phone="123")
show("invalid phone -> 400", r.status_code == 400 and "WhatsApp inválido" in r.text)
r = reg(account_type="hacker")
show("invalid account type -> 400", r.status_code == 400)
r = reg(name="Ana'; DROP TABLE users;--", email="ANA@X.com ", phone="(11) 98765-4321")
show("valid distributor -> redirect to onboarding", r.status_code == 302 and r.headers["Location"] == "/onboarding")

db = appmod.get_db()
u = db.execute("SELECT * FROM users")[0]
show("email lowercased + phone normalized + SQL text stored literally",
     u["email"] == "ana@x.com" and u["phone"] == "5511987654321" and u["name"].startswith("Ana'; DROP"))
show("password hashed", u["hash"] != "12345678" and len(u["hash"]) > 30)
show("workspace + owner + pipeline + 5 stages",
     db.execute("SELECT COUNT(*) n FROM memberships WHERE role='owner'")[0]["n"] == 1
     and db.execute("SELECT COUNT(*) n FROM stages")[0]["n"] == 5
     and db.execute("SELECT kind FROM stages ORDER BY position")[3]["kind"] == "won")

# EN: onboarding step 1 (Part 15.3): company data first; the ceilings page waits for it
# PT: passo 1 do onboarding (parte 15.3): dados da empresa primeiro; a página de tetos espera
t = token(c, "/onboarding")
show("ceilings page sends back to step 1 while company data is missing", c.get("/onboarding/limits").headers.get("Location") == "/onboarding")
r = c.post("/onboarding", data=dict(_csrf=t, name="Distribuidora Ana", cnpj="11.222.333/0001-81", email="contato@dista.com", phone="(11) 98765-4321", city="São Paulo"))
show("company data saved -> step 2", r.status_code == 302 and r.headers["Location"] == "/onboarding/limits")
# EN: onboarding step 2: ceilings | PT: passo 2 do onboarding: tetos
r = c.post("/onboarding/limits", data=dict(_csrf=t, action="save", member_limit="20", admin_limit="10", min_margin="15"))
show("seller > manager -> 400", r.status_code == 400 and "não pode ser maior" in r.text)
r = c.post("/onboarding/limits", data=dict(_csrf=t, action="save", member_limit="abc", admin_limit="-5", min_margin="150"))
show("invalid percents -> 400", r.status_code == 400)
r = c.post("/onboarding/limits", data=dict(_csrf=t, action="save", member_limit="7,5", admin_limit="12.25", min_margin="18"))
w = db.execute("SELECT * FROM workspaces")[0]
show("valid onboarding saved in bps", r.status_code == 302 and w["member_discount_limit_bps"] == 750
     and w["admin_discount_limit_bps"] == 1225 and w["min_margin_bps"] == 1800 and w["onboarding_done"] == 1)
r = c.get("/"); show("logged home -> dashboard", r.headers["Location"] == "/dashboard")
r = c.get("/dashboard"); show("dashboard shows workspace", "Distribuidora Ana" in r.text and "Grátis" in r.text)

# EN: duplicate e-mail | PT: e-mail repetido
c.post("/logout", data=dict(_csrf=token(c, "/dashboard")))
r = c.get("/dashboard"); show("after logout, dashboard -> login", r.status_code == 302 and "/login" in r.headers["Location"])
t = token(c, "/register")
r = reg(email="ana@x.com")
show("duplicate email -> 400 friendly", r.status_code == 400 and "já tem uma conta" in r.text)
show("no orphan rows after duplicate", db.execute("SELECT COUNT(*) n FROM workspaces")[0]["n"] == 1)

# EN: buyer | PT: comprador
r = reg(account_type="buyer", email="ze@rest.com", name="Zé", workspace_name="")
show("buyer -> portal", r.status_code == 302 and r.headers["Location"] == "/portal")
r = c.get("/portal"); show("portal says no links", "ainda não está vinculado" in r.text)
r = c.get("/onboarding"); show("buyer cannot open onboarding -> portal", r.status_code == 302 and r.headers["Location"] == "/portal")
r = c.get("/dashboard"); show("buyer dashboard -> portal", r.headers["Location"] == "/portal")
show("buyer created no workspace", db.execute("SELECT COUNT(*) n FROM workspaces")[0]["n"] == 1)

# EN: login | PT: entrar
c.post("/logout", data=dict(_csrf=token(c, "/portal")))
t = token(c, "/login")
r = c.post("/login", data=dict(_csrf=t, email="ana@x.com", password="errada"))
r2 = c.post("/login", data=dict(_csrf=t, email="naoexiste@x.com", password="12345678"))
show("wrong password and unknown email -> same message", r.status_code == 400 and r2.status_code == 400
     and "E-mail ou senha inválidos" in r.text and "E-mail ou senha inválidos" in r2.text)
r = c.post("/login", data=dict(_csrf=t, email=" ANA@x.com", password="12345678", next="https://evil.com"))
show("login ok, evil next blocked", r.status_code == 302 and r.headers["Location"] == "/dashboard")
r = c.post("/logout")
show("logout without csrf -> 400", r.status_code == 400)

# EN: language saved on the user | PT: idioma salvo no usuário
c.get("/lang/en?next=/dashboard")
show("lang saved on user", db.execute("SELECT lang FROM users WHERE email='ana@x.com'")[0]["lang"] == "en")
r = c.get("/dashboard"); show("dashboard in english", "Plan" in r.text and "Owner" in r.text)

# EN: an English distributor gets English stages | PT: distribuidora em inglês ganha etapas em inglês
c.post("/logout", data=dict(_csrf=token(c, "/dashboard")))
t = token(c, "/register")
r = reg(email="bob@x.com", name="Bob")
show("english signup -> english stages", db.execute(
    "SELECT s.name FROM stages s JOIN pipelines p ON p.id = s.pipeline_id JOIN memberships m ON m.workspace_id = p.workspace_id "
    "JOIN users u ON u.id = m.user_id WHERE u.email='bob@x.com' ORDER BY s.position")[0]["name"] == "New")
r = c.get("/onboarding"); show("onboarding (step 1) renders in english", "Distributor data" in r.text and "Step 1 of 2" in r.text)
