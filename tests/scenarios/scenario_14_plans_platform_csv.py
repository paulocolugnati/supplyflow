"""
EN: Scenario: plans page, flask make-admin, platform panel, CSV export with formula guard.
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: página de planos, flask make-admin, painel da plataforma, CSV com proteção contra fórmulas.
    Passa pelas rotas de verdade num banco temporário (veja o common.py).
"""

from common import *  # noqa: F401,F403

import csv, io, html as htmlmod
from urllib.parse import unquote
from click.testing import CliRunner
os.environ["SUPPORT_WHATSAPP"] = "(11) 91234-5678"
def n(sql, *args): return one(sql, *args)["n"]
def text(r): return htmlmod.unescape(r.text)
def post_op(url, **data):
    data["_csrf"] = tok(op, "/platform")
    return op.post(url, data=data)

owner = app.test_client(); register(owner, "dono@a.com", ws="Dist A")
wa = one("SELECT id FROM workspaces")["id"]
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='profissional'), onboarding_done = 1 WHERE id = ?", wa)
manager = join(owner, "gerente@a.com", "admin")
seller = join(owner, "vend@a.com", "member")
seller2 = join(owner, "vend2@a.com", "member")
other = app.test_client(); register(other, "dono@b.com", ws="Dist B")
wb = one("SELECT id FROM workspaces WHERE id <> ?", wa)["id"]
db.execute("UPDATE workspaces SET onboarding_done = 1 WHERE id = ?", wb)

print("-- plans page")
page = text(owner.get("/plans"))
show("shows current plan, price and 'Seu plano' on Profissional", "Plano atual: <b>Profissional</b>" in page and "R$ 249,90" in page and page.count("Seu plano") == 1)
show("owner gets 'Pedir este plano' for the 3 other plans, to support's WhatsApp", page.count("Pedir este plano") == 3 and "wa.me/5511912345678?text=" in owner.get("/plans").text)
link = re.search(r'href="(https://wa.me/5511912345678\?text=[^"]+)"[^>]*>Pedir este plano', owner.get("/plans").text)
msg = unquote(htmlmod.unescape(link.group(1))) if link else ""
show("change message names workspace, current and target plan", "Dist A" in msg and "plano Profissional" in msg and "plano Grátis" in msg)
show("downgrade warning: Grátis has 1 user max, workspace has 4", "Passaria do limite" in page and "Equipe: 4 / 1" in page)
page = text(seller.get("/plans"))
show("seller sees plans but no 'ask' buttons", "Pedir este plano" not in page and "Só o dono" in page)
show("buyer / logged out can't open /plans", app.test_client().get("/plans").status_code == 302)
db.execute("UPDATE workspaces SET custom_price_cents = 14990 WHERE id = ?", wa)
show("negotiated price shown instead of list price", "R$ 149,90" in text(owner.get("/plans")) and "preço negociado" in text(owner.get("/plans")))
db.execute("UPDATE workspaces SET custom_price_cents = NULL WHERE id = ?", wa)
os.environ.pop("SUPPORT_WHATSAPP")
show("without SUPPORT_WHATSAPP: no broken link, a note instead", "wa.me" not in owner.get("/plans").text and "SUPPORT_WHATSAPP" in owner.get("/plans").text)
os.environ["SUPPORT_WHATSAPP"] = "(11) 91234-5678"

print("-- flask make-admin")
runner = app.test_cli_runner()
r = runner.invoke(args=["make-admin", "naoexiste@x.com"])
show("unknown email -> error, nothing changes", r.exit_code != 0 and n("SELECT COUNT(*) n FROM users WHERE is_platform_admin = 1") == 0)
show("non-admin gets 404 on /platform (owner of a workspace)", owner.get("/platform").status_code == 404)
show("logged out gets 404 (panel not revealed)", app.test_client().get("/platform").status_code == 404)
op = app.test_client(); register(op, "ops@supplyflow.com", kind="buyer")
r = runner.invoke(args=["make-admin", "  OPS@SupplyFlow.com "])
show("make-admin turns the flag on (email normalized)", r.exit_code == 0 and one("SELECT is_platform_admin f FROM users WHERE email='ops@supplyflow.com'")["f"] == 1)
r = op.get("/login")
show("operator without workspace lands on /platform", op.get("/").headers.get("Location") == "/platform")

print("-- platform panel")
post(owner, "/customers/new", name="Cliente Secreto =HYPERLINK(1)")
page = text(op.get("/platform"))
show("lists both workspaces with owner contact and plan", "Dist A" in page and "Dist B" in page and "dono@a.com" in page and "Profissional" in page)
show("never shows business data (customer names)", "Cliente Secreto" not in page)
show("nav shows 'Plataforma' only to the operator", "Plataforma" in page and "/platform" not in owner.get("/dashboard").text)
show("search by name", "Dist B" not in text(op.get("/platform?q=Dist A")) and "Dist A" in text(op.get("/platform?q=dist a")))
show("search with quotes/; is harmless", op.get("/platform?q=%27%3B DROP TABLE workspaces;--").status_code == 200 and n("SELECT COUNT(*) n FROM workspaces") == 2)

r = post_op(f"/platform/workspaces/{wb}", plan="essencial", custom_price="59,90")
w = one("SELECT w.*, p.code FROM workspaces w JOIN plans p ON p.id = w.plan_id WHERE w.id = ?", wb)
show("operator changes B to Essencial at R$ 59,90", w["code"] == "essencial" and w["custom_price_cents"] == 5990)
started = w["plan_started_at"]
post_op(f"/platform/workspaces/{wb}", plan="essencial", custom_price="")
w = one("SELECT * FROM workspaces WHERE id = ?", wb)
show("blank price = list price; same plan keeps plan_started_at", w["custom_price_cents"] is None and w["plan_started_at"] == started)
for label, data in [("unknown plan", dict(plan="ouro", custom_price="")), ("SQL in plan", dict(plan="free' OR 1=1 --", custom_price="")),
                    ("negative price", dict(plan="escala", custom_price="-10")), ("text price", dict(plan="escala", custom_price="abc")),
                    ("huge price", dict(plan="escala", custom_price="99999999999"))]:
    post_op(f"/platform/workspaces/{wb}", **data)
    show("refused: " + label, one("SELECT p.code FROM workspaces w JOIN plans p ON p.id = w.plan_id WHERE w.id = ?", wb)["code"] == "essencial")
show("nonexistent workspace -> 404", post_op("/platform/workspaces/9999", plan="free").status_code == 404)
show("owner can't change plans (404)", post(owner, f"/platform/workspaces/{wa}", plan="escala").status_code == 404
     and one("SELECT p.code FROM workspaces w JOIN plans p ON p.id = w.plan_id WHERE w.id = ?", wa)["code"] == "profissional")
r = op.post(f"/platform/workspaces/{wb}", data=dict(plan="escala"))
show("POST without CSRF refused", r.status_code == 400 and one("SELECT p.code FROM workspaces w JOIN plans p ON p.id = w.plan_id WHERE w.id = ?", wb)["code"] == "essencial")

post_op(f"/platform/workspaces/{wa}", plan="free")
page = text(op.get("/platform?q=Dist A"))
show("downgrade keeps everything and flags over-limit usage", n("SELECT COUNT(*) n FROM memberships WHERE workspace_id = ?", wa) == 4 and "uso-acima" in op.get("/platform?q=Dist A").text)
show("downgrade takes effect at once for the workspace (Grátis on plans page)", "Plano atual: <b>Grátis</b>" in text(owner.get("/plans")))
post_op(f"/platform/workspaces/{wa}", plan="profissional")

r = runner.invoke(args=["make-admin", "ops@supplyflow.com", "--remove"])
show("--remove turns it off and the panel is gone at once", r.exit_code == 0 and op.get("/platform").status_code == 404)

print("-- CSV export")
post(owner, "/products/new", sku="ARZ", name="+Arroz 5kg", unit="cx", price="1.234,50", cost_mode="brl", cost="1.000,00")
stage = one("SELECT id FROM stages WHERE workspace_id = ? ORDER BY position LIMIT 1", wa)["id"]
cid = one("SELECT id FROM companies WHERE name LIKE 'Cliente Secreto%'")["id"]
post(owner, "/opportunities/new", title="@SUM(A1)", company_id=str(cid), stage_id=str(stage), value="2.500,00")
post(other, "/customers/new", name="Cliente da B")
def rows_of(r, delim):
    body = r.data.decode("utf-8")
    return body, list(csv.reader(io.StringIO(body.lstrip("﻿")), delimiter=delim))
post(owner, "/customers/new", name='=HYPERLINK("http://x")')
r = owner.get("/export/customers.csv")
body, rows = rows_of(r, ";")
show("owner downloads customers.csv (attachment, text/csv, BOM)", r.status_code == 200 and r.mimetype == "text/csv" and "attachment" in r.headers["Content-Disposition"] and body.startswith("﻿"))
show("PT header and ';' separator", rows[0][0] == "Cliente" and rows[0][1] == "CNPJ")
names = [r_[0] for r_ in rows[1:]]
show("formula neutralized with an apostrophe, normal name untouched", "'=HYPERLINK(\"http://x\")" in names and "Cliente Secreto =HYPERLINK(1)" in names)
show("only this workspace's customers", "Cliente da B" not in body)
body, rows = rows_of(owner.get("/export/opportunities.csv"), ";")
show("opportunities: '@' title neutralized, value 2500,00, stage kind translated", any(r_[0] == "'@SUM(A1)" and "2500,00" in r_ and "Aberta" in r_ for r_ in rows))
body, rows = rows_of(owner.get("/export/products.csv"), ";")
show("products: '+' name neutralized, price 1234,50 and cost 1000,00", any(r_[1] == "'+Arroz 5kg" and r_[3] == "1234,50" and r_[4] == "1000,00" for r_ in rows))
show("quotes export works (header only is fine)", owner.get("/export/quotes.csv").status_code == 200)
owner.get("/lang/en")
body, rows = rows_of(owner.get("/export/products.csv"), ",")
show("EN: ',' separator and decimal point", len(rows[0]) == 7 and rows[0][4] == "Cost (R$)" and any(r_[3] == "1234.50" and r_[4] == "1000.00" for r_ in rows))
owner.get("/lang/pt")
show("admin can export", manager.get("/export/customers.csv").status_code == 200)
show("member can't export (403)", seller.get("/export/customers.csv").status_code == 403)
show("unknown kind -> 404", owner.get("/export/users.csv").status_code == 404 and owner.get("/export/..%2Fapp.csv").status_code == 404)
show("button shown to owner, hidden from member", "/export/customers.csv" in owner.get("/customers").text and "/export/customers.csv" not in seller.get("/customers").text)
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='essencial') WHERE id = ?", wa)
show("plan without CSV: route 403 and button hidden", owner.get("/export/customers.csv").status_code == 403 and "/export/customers.csv" not in owner.get("/customers").text)
show("logged out -> login", app.test_client().get("/export/customers.csv").status_code == 302)
