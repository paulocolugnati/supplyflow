"""
EN: Scenario: customers and contacts: validation, CNPJ, search, filters, quota, permissions.
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: clientes e contatos: validação, CNPJ, busca, filtros, cota, permissões.
    Passa pelas rotas de verdade num banco temporário (veja o common.py).
"""

from common import *  # noqa: F401,F403

from helpers import normalize_cnpj, format_cnpj, escape_like

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
    # EN/PT: customer names listed in the table only
    return re.findall(r'class="link-linha" href="/customers/\d+"><strong>([^<]+)</strong>', r.text)

def uid(email):
    return db.execute("SELECT id FROM users WHERE email = ?", email)[0]["id"]

print("-- helpers")
show("valid CNPJ normalized", normalize_cnpj("11.222.333/0001-81") == "11222333000181")
show("wrong check digit rejected", normalize_cnpj("11.222.333/0001-82") is None)
show("repeated digits rejected", normalize_cnpj("00000000000000") is None)
show("short CNPJ rejected", normalize_cnpj("123") is None)
show("CNPJ formatted", format_cnpj("11222333000181") == "11.222.333/0001-81")
show("LIKE wildcards escaped", escape_like("50%_x!") == "50!%!_x!!")

owner, other = app.test_client(), app.test_client()
register(owner, "dono@a.com", ws="Dist A")
register(other, "dono@b.com", ws="Dist B")
wa = db.execute("SELECT id FROM workspaces WHERE name='Dist A'")[0]["id"]
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='essencial') WHERE id = ?", wa)

print("-- create and validate")
r = owner.get("/customers")
show("empty state shown", "Cadastre seu primeiro cliente" in r.text)
r = post(owner, "/customers/new", name="", cnpj="123", phone="abc", segment="x" * 61, city="")
show("invalid fields -> 400 with errors", r.status_code == 400 and "CNPJ inválido" in r.text and "WhatsApp inválido" in r.text and "60 caracteres" in r.text)
r = post(owner, "/customers/new", name="Restaurante do Zé", cnpj="11.222.333/0001-81", phone="(11) 98765-4321", segment="Restaurante", city="São Paulo", owner_id=str(uid("dono@a.com")))
show("valid customer created -> redirect to page", r.status_code == 302 and "/customers/" in r.headers["Location"])
cz = db.execute("SELECT * FROM companies WHERE name = 'Restaurante do Zé'")[0]
show("stored normalized (cnpj digits, phone 55)", cz["cnpj"] == "11222333000181" and cz["phone"] == "5511987654321" and cz["workspace_id"] == wa)
r = post(owner, "/customers/new", name="Outro", cnpj="11222333000181")
show("duplicate CNPJ in same workspace refused", r.status_code == 400 and "Já existe um cliente com este CNPJ" in r.text)
r = post(other, "/customers/new", name="Zé na B", cnpj="11222333000181")
show("same CNPJ allowed in another workspace", r.status_code == 302)
post(owner, "/customers/new", name="Mercado 50% Off", segment="Mercado", city="Campinas")
post(owner, "/customers/new", name="Padaria Pão_Quente'; DROP TABLE companies;--", segment="Padaria")
show("SQL text stored literally", db.execute("SELECT COUNT(*) n FROM companies WHERE name LIKE 'Padaria%'")[0]["n"] == 1)

print("-- search and filters")
r = owner.get("/customers?q=50%25")
show("search '50%' finds only the literal match", "Mercado 50% Off" in r.text and "Restaurante do Zé" not in r.text)
r = owner.get("/customers?q=_")
show("search '_' is literal", "Pão_Quente" in r.text and "Restaurante do Zé" not in r.text)
r = owner.get("/customers?q=11.222")
show("search by formatted CNPJ finds digits", "Restaurante do Zé" in r.text)
r = owner.get("/customers?q=campinas")
show("search by city (case-insensitive)", rows(r) == ["Mercado 50% Off"])
r = owner.get("/customers?segment=Padaria")
show("segment filter", "Pão_Quente" in r.text and "Mercado 50" not in r.text)
r = owner.get("/customers?q=' OR 'a'='a' --")
show("injection in search returns nothing", rows(r) == [])
r = owner.get("/customers")
show("other workspace's customer never listed", "Zé na B" not in r.text)

print("-- isolation")
cb = db.execute("SELECT id FROM companies WHERE name = 'Zé na B'")[0]["id"]
show("view B's customer from A -> 404", owner.get(f"/customers/{cb}").status_code == 404)
show("edit B's customer from A -> 404", post(owner, f"/customers/{cb}/edit", name="Hack").status_code == 404)
show("delete B's customer from A -> 404", post(owner, f"/customers/{cb}/delete").status_code == 404)
show("add contact to B's customer from A -> 404", post(owner, f"/customers/{cb}/contacts", name="Intruso").status_code == 404)
r = post(owner, f"/customers/{cz['id']}/edit", name="Restaurante do Zé", owner_id=str(uid("dono@b.com")))
show("owner_id from another workspace refused", r.status_code == 400 and "Escolha um vendedor da sua equipe" in r.text)

print("-- contacts")
r = post(owner, f"/customers/{cz['id']}/contacts", name="Zé", position="Dono", phone="11 91234-5678", email="ze@rest.com")
show("contact added", db.execute("SELECT COUNT(*) n FROM contacts WHERE company_id = ?", cz["id"])[0]["n"] == 1)
post(owner, f"/customers/{cz['id']}/contacts", name="", email="ruim")
show("invalid contact not saved", db.execute("SELECT COUNT(*) n FROM contacts WHERE company_id = ?", cz["id"])[0]["n"] == 1)
kid = db.execute("SELECT id FROM contacts WHERE company_id = ?", cz["id"])[0]["id"]
r = owner.get(f"/customers/{cz['id']}")
show("page shows contact + wa.me link with message", "Zé" in r.text and "wa.me/5511912345678?text=" in r.text)
other_cust = db.execute("SELECT id FROM companies WHERE name = 'Mercado 50% Off'")[0]["id"]
show("contact under the wrong customer -> 404", owner.get(f"/customers/{other_cust}/contacts/{kid}/edit").status_code == 404)
r = post(owner, f"/customers/{cz['id']}/contacts/{kid}/edit", name="José", position="Sócio", phone="", email="")
show("contact edited", db.execute("SELECT name FROM contacts WHERE id = ?", kid)[0]["name"] == "José")

print("-- member permissions")
post(owner, "/team/invite", email="vend@a.com", role="member")
link = re.search(r'/invite/([^"]+)"', owner.get("/team").text).group(1)
seller = app.test_client()
register(seller, "vend@a.com", invite=link)
r = post(seller, "/customers/new", name="Lanchonete do Vendedor", owner_id=str(uid("dono@a.com")))
mine = db.execute("SELECT * FROM companies WHERE name = 'Lanchonete do Vendedor'")[0]
show("member's new customer is always theirs (owner_id ignored)", mine["owner_id"] == uid("vend@a.com"))
show("member doesn't see the seller select", 'name="owner_id"' not in seller.get("/customers/new").text)
r = post(seller, f"/customers/{cz['id']}/edit", name="Restaurante do Zé Editado")
show("member can edit someone else's customer", db.execute("SELECT name FROM companies WHERE id = ?", cz["id"])[0]["name"] == "Restaurante do Zé Editado")
show("...and the responsible seller didn't change", db.execute("SELECT owner_id FROM companies WHERE id = ?", cz["id"])[0]["owner_id"] == uid("dono@a.com"))
show("member can't delete someone else's customer -> 403", post(seller, f"/customers/{cz['id']}/delete").status_code == 403)
show("member can't delete contact of someone else's customer -> 403", post(seller, f"/customers/{cz['id']}/contacts/{kid}/delete").status_code == 403)
r = post(seller, f"/customers/{mine['id']}/delete")
show("member deletes own customer", r.status_code == 302 and not db.execute("SELECT 1 FROM companies WHERE id = ?", mine["id"]))
show("filter 'only mine' for member", "Restaurante" not in seller.get("/customers?owner=me").text)

print("-- delete rules and quota")
pid = db.execute("SELECT id FROM pipelines WHERE workspace_id = ?", wa)[0]["id"]
sid = db.execute("SELECT id FROM stages WHERE pipeline_id = ? LIMIT 1", pid)[0]["id"]
oid = db.execute("INSERT INTO opportunities (workspace_id, pipeline_id, stage_id, company_id, title) VALUES (?,?,?,?, 'O')", wa, pid, sid, cz["id"])
db.execute("INSERT INTO quotes (workspace_id, number, opportunity_id, company_id, created_by, valid_until) VALUES (?,1,?,?,?, '2999-01-01')", wa, oid, cz["id"], uid("dono@a.com"))
r = post(owner, f"/customers/{cz['id']}/delete")
show("customer with quotes not deleted, friendly message", db.execute("SELECT 1 FROM companies WHERE id = ?", cz["id"]) and "tem orçamentos" in owner.get(f"/customers/{cz['id']}").text)
r = post(owner, f"/customers/{other_cust}/delete")
show("owner deletes customer without quotes", not db.execute("SELECT 1 FROM companies WHERE id = ?", other_cust))

db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='free') WHERE id = ?", wa)
n = db.execute("SELECT COUNT(*) n FROM companies WHERE workspace_id = ?", wa)[0]["n"]
for i in range(30 - n):
    db.execute("INSERT INTO companies (workspace_id, name) VALUES (?, ?)", wa, f"Cliente {i}")
r = post(owner, "/customers/new", name="Cliente 31")
show("free plan: 31st customer blocked", r.status_code == 302 and not db.execute("SELECT 1 FROM companies WHERE name='Cliente 31'"))
show("list shows limit tag instead of New button", "Limite de clientes do plano atingido" in owner.get("/customers").text)
show("GET /customers/new also blocked", owner.get("/customers/new").status_code == 302)

print("-- shell")
r = owner.get("/dashboard")
show("nav has Clientes + dashboard shortcut", 'href="/customers"' in r.text and "Novo cliente" in r.text)
show("buyer can't open customers -> portal", app.test_client().get("/customers").status_code == 302)
