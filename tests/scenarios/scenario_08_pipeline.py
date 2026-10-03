"""
EN: Scenario: pipeline board, opportunities, stage moves, stage and pipeline settings.
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: quadro do funil, oportunidades, mudança de etapa, configuração de etapas e funis.
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

owner, other = app.test_client(), app.test_client()
register(owner, "dono@a.com", ws="Dist A")
register(other, "dono@b.com", ws="Dist B")
wa = one("SELECT id FROM workspaces WHERE name='Dist A'")["id"]
wb = one("SELECT id FROM workspaces WHERE name='Dist B'")["id"]
pa = one("SELECT id FROM pipelines WHERE workspace_id = ?", wa)["id"]
stages = {s["name"]: s for s in db.execute("SELECT * FROM stages WHERE pipeline_id = ?", pa)}
sb = one("SELECT id FROM stages WHERE workspace_id = ? LIMIT 1", wb)["id"]

print("-- board and creation")
r = owner.get("/pipeline")
show("board shows the 5 default columns", all(name in r.text for name in ["Novo", "Contatado", "Orçamento enviado", "Fechado", "Perdido"]))
show("no customer -> form asks to create one", "Cadastre um cliente antes" in owner.get("/opportunities/new").text)
post(owner, "/customers/new", name="Restaurante do Zé")
post(owner, "/customers/new", name="Mercado Bom")
cz = one("SELECT id FROM companies WHERE name='Restaurante do Zé'")["id"]
cm = one("SELECT id FROM companies WHERE name='Mercado Bom'")["id"]
post(owner, f"/customers/{cz}/contacts", name="Zé")
post(owner, f"/customers/{cm}/contacts", name="Bia do Mercado")
kz = one("SELECT id FROM contacts WHERE name='Zé'")["id"]
km = one("SELECT id FROM contacts WHERE name='Bia do Mercado'")["id"]
post(other, "/customers/new", name="Cliente B")
cb = one("SELECT id FROM companies WHERE name='Cliente B'")["id"]

r = owner.get(f"/opportunities/new?company={cz}")
show("?company= preselects customer", f'selected value="{cz}"' in r.text)
r = post(owner, "/opportunities/new", title="", company_id=str(cb), contact_id=str(km), stage_id=str(sb), value="abc", expected_close="31/12/2026")
show("invalid -> 400 (title, foreign customer, stage, value, date)", r.status_code == 400 and all(x in html.unescape(r.text) for x in
     ["Informe o título", "Escolha um cliente da sua distribuidora", "etapa válida", "Valor inválido", "Data inválida"]))
r = post(owner, "/opportunities/new", title="Pedido semanal", company_id=str(cz), contact_id=str(km), stage_id=str(stages["Novo"]["id"]))
show("contact of another customer refused", r.status_code == 400 and "O contato precisa ser deste cliente" in r.text)
r = post(owner, "/opportunities/new", title="Pedido semanal", company_id=str(cz), contact_id=str(kz),
         stage_id=str(stages["Novo"]["id"]), value="1.250,00", expected_close="2026-12-31")
op = one("SELECT * FROM opportunities WHERE title='Pedido semanal'")
show("created with value in cents, date, contact", r.status_code == 302 and op["value_cents"] == 125000 and op["expected_close"] == "2026-12-31" and op["contact_id"] == kz)
show("card on the board with column total", "Pedido semanal" in owner.get("/pipeline").text and "R$ 1.250,00" in owner.get("/pipeline").text)
show("customer page lists the opportunity", "Pedido semanal" in owner.get(f"/customers/{cz}").text)

print("-- moving stages")
r = post(owner, f"/opportunities/{op['id']}/stage", stage_id=str(stages["Contatado"]["id"]), next="/pipeline")
op2 = one("SELECT * FROM opportunities WHERE id = ?", op["id"])
show("moved, safe redirect back to board", op2["stage_id"] == stages["Contatado"]["id"] and r.headers["Location"].endswith("/pipeline") and op2["closed_at"] is None)
act = one("SELECT * FROM activities WHERE opportunity_id = ? ORDER BY id DESC", op["id"])
show("history line written", act and act["type"] == "stage_change" and act["body"] == "Novo → Contatado" and act["company_id"] == cz)
post(owner, f"/opportunities/{op['id']}/stage", stage_id=str(stages["Perdido"]["id"]), lost_reason="Preço alto")
op3 = one("SELECT * FROM opportunities WHERE id = ?", op["id"])
show("lost: closed_at + reason", op3["closed_at"] is not None and op3["lost_reason"] == "Preço alto")
show("history mentions the reason", "Contatado → Perdido · Preço alto" in html.unescape(owner.get(f"/opportunities/{op['id']}").text))
post(owner, f"/opportunities/{op['id']}/stage", stage_id=str(stages["Novo"]["id"]))
op4 = one("SELECT * FROM opportunities WHERE id = ?", op["id"])
show("back to open clears closed_at and reason", op4["closed_at"] is None and op4["lost_reason"] is None)
post(owner, f"/opportunities/{op['id']}/stage", stage_id=str(stages["Fechado"]["id"]), lost_reason="ignorado")
op5 = one("SELECT * FROM opportunities WHERE id = ?", op["id"])
show("won: closed_at set, reason ignored", op5["closed_at"] is not None and op5["lost_reason"] is None)
r = post(owner, f"/opportunities/{op['id']}/stage", stage_id=str(sb))
show("stage of another workspace -> 400", r.status_code == 400)
r = post(owner, f"/opportunities/{op['id']}/stage", stage_id="1 OR 1=1")
show("garbage stage id -> 400", r.status_code == 400)
r = post(owner, f"/opportunities/{op['id']}/stage", stage_id=str(stages["Novo"]["id"]), next="https://evil.com")
show("evil next ignored", r.headers["Location"].endswith(f"/opportunities/{op['id']}"))
show("history count = 5", one("SELECT COUNT(*) n FROM activities WHERE opportunity_id = ?", op["id"])["n"] == 5)

print("-- isolation")
post(other, "/opportunities/new", title="Opp da B", company_id=str(cb), stage_id=str(sb))
ob = one("SELECT id FROM opportunities WHERE title='Opp da B'")["id"]
show("view B's opportunity -> 404", owner.get(f"/opportunities/{ob}").status_code == 404)
show("move B's opportunity -> 404", post(owner, f"/opportunities/{ob}/stage", stage_id=str(stages["Novo"]["id"])).status_code == 404)
show("edit/delete B's opportunity -> 404", post(owner, f"/opportunities/{ob}/edit", title="x").status_code == 404 and post(owner, f"/opportunities/{ob}/delete").status_code == 404)
show("B's card not on A's board", "Opp da B" not in owner.get("/pipeline").text)
show("?p= with B's pipeline falls back to A's", "Opp da B" not in owner.get(f"/pipeline?p={one('SELECT id FROM pipelines WHERE workspace_id=?', wb)['id']}").text)

print("-- edit and member rules")
r = post(owner, f"/opportunities/{op['id']}/edit", title="Pedido semanal grande", company_id=str(cm), contact_id=str(km), value="2000", expected_close="")
e = one("SELECT * FROM opportunities WHERE id = ?", op["id"])
show("edit: customer + contact + value changed", e["title"] == "Pedido semanal grande" and e["company_id"] == cm and e["contact_id"] == km and e["value_cents"] == 200000)
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='essencial') WHERE id = ?", wa)
post(owner, "/team/invite", email="vend@a.com", role="member")
link = re.search(r'/invite/([^"]+)"', owner.get("/team").text).group(1)
seller = app.test_client(); register(seller, "vend@a.com", invite=link)
vid = one("SELECT id FROM users WHERE email='vend@a.com'")["id"]
post(seller, "/opportunities/new", title="Opp do vendedor", company_id=str(cz), stage_id=str(stages["Novo"]["id"]), owner_id=str(e["owner_id"] or 1))
ov = one("SELECT * FROM opportunities WHERE title='Opp do vendedor'")
show("member's opportunity is theirs", ov["owner_id"] == vid)
# EN/PT: Part 15.1 rule: a seller sees and touches only their own opportunities | regra da parte 15.1: vendedor vê e mexe só nas próprias
r = post(seller, f"/opportunities/{op['id']}/stage", stage_id=str(stages["Contatado"]["id"]))
show("member can't move owner's opportunity -> 404, stage unchanged", r.status_code == 404 and one("SELECT stage_id FROM opportunities WHERE id = ?", op["id"])["stage_id"] != stages["Contatado"]["id"])
show("member can't delete owner's opportunity -> 404", post(seller, f"/opportunities/{op['id']}/delete").status_code == 404 and one("SELECT 1 x FROM opportunities WHERE id = ?", op["id"]))
show("member can't open or edit owner's opportunity -> 404", seller.get(f"/opportunities/{op['id']}").status_code == 404 and seller.get(f"/opportunities/{op['id']}/edit").status_code == 404)
board = seller.get("/pipeline?owner=").text
show("member's board shows only their cards, even asking for everyone", "Opp do vendedor" in board and op["title"] not in board)
show("owner's board shows both", "Opp do vendedor" in owner.get("/pipeline").text and op["title"] in owner.get("/pipeline").text)
show("owner moves it to Contatado", post(owner, f"/opportunities/{op['id']}/stage", stage_id=str(stages["Contatado"]["id"])).status_code == 302)
show("'only mine' filter", "Opp do vendedor" in seller.get("/pipeline?owner=me").text and "Pedido semanal" not in seller.get("/pipeline?owner=me").text)
show("member can't open settings -> 403", seller.get("/pipeline/settings").status_code == 403)

print("-- delete rules")
uid = one("SELECT id FROM users WHERE email='dono@a.com'")["id"]
db.execute("INSERT INTO quotes (workspace_id, number, opportunity_id, company_id, created_by, valid_until) VALUES (?,1,?,?,?, '2999-01-01')", wa, op["id"], cm, uid)
post(owner, f"/opportunities/{op['id']}/delete")
show("opportunity with quote not deleted", one("SELECT 1 x FROM opportunities WHERE id = ?", op["id"]) is not None)
r = post(seller, f"/opportunities/{ov['id']}/delete")
show("member deletes own opportunity; history cascades", one("SELECT 1 x FROM opportunities WHERE id = ?", ov["id"]) is None)

print("-- settings")
r = post(owner, f"/pipeline/{pa}/stages", name="Negociação", kind="open")
order = [s["name"] for s in db.execute("SELECT name FROM stages WHERE pipeline_id = ? ORDER BY position", pa)]
show("new open stage goes before won/lost", order == ["Novo", "Contatado", "Orçamento enviado", "Negociação", "Fechado", "Perdido"])
neg = one("SELECT id FROM stages WHERE name='Negociação'")["id"]
post(owner, f"/stages/{neg}/move", direction="up")
order = [s["name"] for s in db.execute("SELECT name FROM stages WHERE pipeline_id = ? ORDER BY position", pa)]
show("move up swaps neighbors", order[2] == "Negociação" and order[3] == "Orçamento enviado")
post(owner, f"/stages/{neg}/rename", name="Negociando")
show("rename stage", one("SELECT name FROM stages WHERE id = ?", neg)["name"] == "Negociando")
post(owner, f"/stages/{stages['Contatado']['id']}/delete")
show("stage in use not deleted", one("SELECT 1 x FROM stages WHERE id = ?", stages["Contatado"]["id"]) is not None)
post(owner, f"/stages/{stages['Perdido']['id']}/delete")
show("last lost stage not deleted", one("SELECT 1 x FROM stages WHERE id = ?", stages["Perdido"]["id"]) is not None)
post(owner, f"/stages/{neg}/delete")
show("unused stage deleted", one("SELECT 1 x FROM stages WHERE id = ?", neg) is None)
show("stage of B from A -> 404", post(owner, f"/stages/{sb}/rename", name="x").status_code == 404)
post(owner, "/pipelines", name="Grandes contas")
show("Essencial: extra pipeline blocked", one("SELECT 1 x FROM pipelines WHERE name='Grandes contas'") is None)
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='profissional') WHERE id = ?", wa)
post(owner, "/pipelines", name="Grandes contas")
gp = one("SELECT id FROM pipelines WHERE name='Grandes contas'")
show("Profissional: extra pipeline with 5 stages", gp and one("SELECT COUNT(*) n FROM stages WHERE pipeline_id = ?", gp["id"])["n"] == 5)
show("board offers the pipeline switcher", "Grandes contas" in owner.get("/pipeline").text)
post(owner, f"/pipelines/{pa}/delete")
show("default pipeline not deleted", one("SELECT 1 x FROM pipelines WHERE id = ?", pa) is not None)
post(owner, f"/pipelines/{gp['id']}/delete")
show("extra empty pipeline deleted (stages cascade)", one("SELECT 1 x FROM pipelines WHERE id = ?", gp["id"]) is None and one("SELECT COUNT(*) n FROM stages WHERE pipeline_id = ?", gp["id"])["n"] == 0)
show("nav has Funil", 'href="/pipeline"' in owner.get("/dashboard").text)
