"""
EN: Scenario: company data, logo upload, settings, support-only identity, password reset, mailer.
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: dados da empresa, upload da logo, configurações, identidade só pelo suporte, recuperar senha, e-mail.
    Passa pelas rotas de verdade num banco temporário (veja o common.py).
"""

from common import *  # noqa: F401,F403

import html as htmlmod, io, struct, zlib
import password_reset, mailer
def n(sql, *args): return one(sql, *args)["n"]
def text(r): return htmlmod.unescape(r.text)
created_files = []

def png_bytes():
    raw = b"\x00\xff\xff\xff"
    def chunk(kind, data): return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")

def upload(c, url, fields, filename=None, content=None):
    data = dict(fields); data["_csrf"] = tok(c, "/dashboard") if c is not None else ""
    if filename is not None:
        data["logo"] = (io.BytesIO(content), filename)
    return c.post(url, data=data, content_type="multipart/form-data")

owner = app.test_client(); register(owner, "dono@a.com", ws="Dist A")
wa = one("SELECT id FROM workspaces")["id"]
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='profissional') WHERE id = ?", wa)
GOOD = dict(name="Distribuidora Sabor", cnpj="11.222.333/0001-81", email="Contato@Sabor.com", phone="(11) 98765-4321", city="Campinas")

print("-- onboarding step 1: company data")
show("new owner lands on step 1", owner.get("/").headers["Location"] == "/onboarding" and "Passo 1 de 2" in text(owner.get("/onboarding")))
for label, change in [("empty name", dict(name="")), ("invalid CNPJ", dict(cnpj="11.222.333/0001-82")), ("CNPJ as text", dict(cnpj="abc'; --")),
                      ("bad e-mail", dict(email="nao-e-email")), ("bad WhatsApp", dict(phone="123")), ("empty city", dict(city=""))]:
    r = upload(owner, "/onboarding", {**GOOD, **change})
    show("refused: " + label, r.status_code == 400 and one("SELECT cnpj FROM workspaces WHERE id = ?", wa)["cnpj"] is None)
r = upload(owner, "/onboarding", GOOD, "logo.png", b"isto nao e uma imagem")
show("refused: text file named .png", r.status_code == 400 and "PNG, JPG ou WebP" in text(r))
r = upload(owner, "/onboarding", GOOD, "logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
show("refused: SVG (can carry scripts)", r.status_code == 400)
r = upload(owner, "/onboarding", GOOD, "grande.png", b"\x89PNG\r\n\x1a\n" + b"0" * (1024 * 1024 + 10))
show("refused: logo above 1 MB", r.status_code == 400 and "1 MB" in text(r))
r = upload(owner, "/onboarding", GOOD, "../../../app.py", png_bytes())
w = one("SELECT * FROM workspaces WHERE id = ?", wa)
show("valid data + PNG saved, goes to step 2", r.status_code == 302 and r.headers["Location"] == "/onboarding/limits"
     and w["cnpj"] == "11222333000181" and w["email"] == "contato@sabor.com" and w["phone"] == "5511987654321" and w["city"] == "Campinas")
show("logo stored with a random name in the logo folder (user's file name ignored)", re.fullmatch(r"/static/uploads/logos/[0-9a-f]{32}\.png", w["logo_path"] or "") is not None)
logo_file = os.path.join(app.static_folder, "uploads", "logos", w["logo_path"].rsplit("/", 1)[1]); created_files.append(logo_file)
show("the file exists and is the PNG sent", os.path.isfile(logo_file) and open(logo_file, "rb").read() == png_bytes())
show("step 1 again -> moves on (CNPJ already saved)", owner.get("/onboarding").headers["Location"] == "/onboarding/limits")
post(owner, "/onboarding/limits", action="skip")
show("skip in step 2 finishes the setup", one("SELECT onboarding_done d FROM workspaces WHERE id = ?", wa)["d"] == 1 and owner.get("/").headers["Location"] == "/dashboard")
show("after the setup, /onboarding goes to settings", owner.get("/onboarding").headers["Location"] == "/settings")

other = app.test_client(); register(other, "dono@b.com", ws="Dist B")
r = upload(other, "/onboarding", {**GOOD, "name": "Dist B"})
show("same CNPJ in another distributor -> refused", r.status_code == 400 and "outra distribuidora" in text(r))

print("-- settings")
manager = join(owner, "gerente@a.com", "admin")
show("manager can't open settings or onboarding (owner only)", manager.get("/settings").status_code == 403 and manager.get("/onboarding").status_code == 403)
page = text(owner.get("/settings"))
show("settings shows name and CNPJ locked, with the support path", "Distribuidora Sabor" in page and "11.222.333/0001-81" in page and "travado" in page and 'name="cnpj"' not in page)
r = upload(owner, "/settings", dict(name="Nome Hackeado", cnpj="45.723.174/0001-10", email="novo@sabor.com", phone="(19) 99999-0000", city="Valinhos"))
w = one("SELECT * FROM workspaces WHERE id = ?", wa)
show("owner changes e-mail, WhatsApp and city; name and CNPJ ignored", r.status_code == 302 and w["email"] == "novo@sabor.com" and w["phone"] == "5519999990000"
     and w["city"] == "Valinhos" and w["name"] == "Distribuidora Sabor" and w["cnpj"] == "11222333000181")
old_logo = logo_file
r = upload(owner, "/settings", dict(email="novo@sabor.com", phone="(19) 99999-0000", city="Valinhos"), "nova.png", png_bytes())
w = one("SELECT * FROM workspaces WHERE id = ?", wa)
new_logo = os.path.join(app.static_folder, "uploads", "logos", w["logo_path"].rsplit("/", 1)[1]); created_files.append(new_logo)
show("new logo replaces and deletes the old file", os.path.isfile(new_logo) and not os.path.exists(old_logo))
upload(owner, "/settings", dict(email="novo@sabor.com", phone="(19) 99999-0000", city="Valinhos", remove_logo="1"))
show("remove logo deletes the file and clears the path", one("SELECT logo_path p FROM workspaces WHERE id = ?", wa)["p"] is None and not os.path.exists(new_logo))
db.execute("UPDATE workspaces SET logo_path = '/static/uploads/logos/../../../app.py' WHERE id = ?", wa)
upload(owner, "/settings", dict(email="novo@sabor.com", phone="(19) 99999-0000", city="Valinhos", remove_logo="1"))
show("a tampered logo path never deletes files outside the folder", os.path.isfile(os.path.join(os.getcwd(), "app.py")))
r = upload(owner, "/settings", dict(email="x", phone="(19) 99999-0000", city="Valinhos"))
show("settings validates too (bad e-mail -> 400)", r.status_code == 400)
db.execute("UPDATE workspaces SET cnpj = NULL WHERE id = ?", wa)
show("legacy account without CNPJ: dashboard banner + CNPJ field once", "Complete os dados" in text(owner.get("/dashboard")) and 'name="cnpj"' in owner.get("/settings").text)
upload(owner, "/settings", dict(cnpj="11.222.333/0001-81", email="novo@sabor.com", phone="(19) 99999-0000", city="Valinhos"))
show("CNPJ set once, then locked again", one("SELECT cnpj FROM workspaces WHERE id = ?", wa)["cnpj"] == "11222333000181" and 'name="cnpj"' not in owner.get("/settings").text)
show("owner's menu has Settings; manager's doesn't", 'href="/settings"' in owner.get("/dashboard").text and 'href="/settings"' not in manager.get("/dashboard").text)

print("-- document and portal show the company data")
db.execute("UPDATE workspaces SET logo_path = '/static/brand/simbolo.svg' WHERE id = ?", wa)
post(owner, "/customers/new", name="Restaurante")
cid = one("SELECT id FROM companies WHERE workspace_id = ?", wa)["id"]
post(owner, "/opportunities/new", title="Pedido", company_id=str(cid), stage_id=str(one("SELECT id FROM stages WHERE workspace_id = ? ORDER BY position LIMIT 1", wa)["id"]))
oid = one("SELECT id FROM opportunities WHERE workspace_id = ?", wa)["id"]
post(owner, f"/opportunities/{oid}/quotes")
qid = one("SELECT id FROM quotes WHERE workspace_id = ?", wa)["id"]
page = text(owner.get(f"/quotes/{qid}/document"))
show("PDF header: logo, CNPJ, WhatsApp, e-mail and city", 'src="/static/brand/simbolo.svg"' in page and "11.222.333/0001-81" in page and "(19) 99999-0000" in page and "novo@sabor.com" in page and "Valinhos" in page)
db.execute("UPDATE workspaces SET logo_path = NULL WHERE id = ?", wa)

print("-- platform panel: name and CNPJ")
op = app.test_client(); register(op, "ops@x.com", kind="buyer")
app.test_cli_runner().invoke(args=["make-admin", "ops@x.com"])
def post_op(url, **data):
    data["_csrf"] = tok(op, "/platform"); return op.post(url, data=data)
post_op(f"/platform/workspaces/{wa}/identity", name="Sabor do Campo LTDA", cnpj="45.723.174/0001-10")
show("support changes name and CNPJ", one("SELECT name, cnpj FROM workspaces WHERE id = ?", wa) == {"name": "Sabor do Campo LTDA", "cnpj": "45723174000110"})
wb = one("SELECT id FROM workspaces WHERE id <> ? ORDER BY id LIMIT 1", wa)["id"]
post_op(f"/platform/workspaces/{wb}/identity", name="Dist B", cnpj="45.723.174/0001-10")
show("support can't give B the CNPJ of A", one("SELECT cnpj FROM workspaces WHERE id = ?", wb)["cnpj"] is None)
post_op(f"/platform/workspaces/{wa}/identity", name="X", cnpj="")
show("too-short name refused", one("SELECT name FROM workspaces WHERE id = ?", wa)["name"] == "Sabor do Campo LTDA")
show("owner can't use the support route (404)", post(owner, f"/platform/workspaces/{wa}/identity", name="Hack", cnpj="").status_code == 404)

print("-- forgot password")
sent = []
password_reset.send_email = lambda to, subject, body: sent.append((to, subject, body)) or True
anon = app.test_client()
show("login page links to 'Esqueci minha senha'", 'href="/forgot"' in anon.get("/login").text)
def forgot(c, email):
    return c.post("/forgot", data=dict(_csrf=tok(c, "/forgot"), email=email))
r = forgot(anon, "ninguem@x.com")
show("unknown e-mail: same answer, nothing stored or sent", "Se existir uma conta com ninguem@x.com" in text(r) and n("SELECT COUNT(*) n FROM password_resets") == 0 and not sent)
r = forgot(anon, "  DONO@A.com ")
show("known e-mail: same answer, one link stored (hash only) and one e-mail", "Se existir uma conta com dono@a.com" in text(r) and n("SELECT COUNT(*) n FROM password_resets") == 1 and len(sent) == 1)
link = re.search(r"http://localhost/reset/(\S+)", sent[0][2])
token = link.group(1) if link else ""
show("the e-mail has the link, in Portuguese; the raw token is not in the database", "Olá, Nome!" in sent[0][2] and token and not db.execute("SELECT 1 FROM password_resets WHERE token_hash = ?", token))
show("bad e-mail format -> 400", forgot(anon, "x").status_code == 400)
show("POST without CSRF refused", anon.post("/forgot", data=dict(email="dono@a.com")).status_code == 400)
show("link page opens", anon.get(f"/reset/{token}").status_code == 200)
r = anon.post(f"/reset/{token}", data=dict(_csrf=tok(anon, f"/reset/{token}"), password="123", confirmation="123"))
show("short password refused", r.status_code == 400)
r = anon.post(f"/reset/{token}", data=dict(_csrf=tok(anon, f"/reset/{token}"), password="novasenha1", confirmation="outra-senha"))
show("different confirmation refused", r.status_code == 400)
forgot(anon, "dono@a.com")
token2 = re.search(r"/reset/(\S+)", sent[-1][2]).group(1)
logged = app.test_client(); logged.post("/login", data=dict(_csrf=tok(logged, "/login"), email="dono@a.com", password="12345678"))
r = logged.post(f"/reset/{token}", data=dict(_csrf=tok(logged, f"/reset/{token}"), password="novasenha1", confirmation="novasenha1"))
show("valid -> password changed, redirect to login, session cleared", r.status_code == 302 and r.headers["Location"] == "/login" and logged.get("/dashboard").status_code == 302)
c = app.test_client(); r = c.post("/login", data=dict(_csrf=tok(c, "/login"), email="dono@a.com", password="novasenha1"))
show("new password works", r.status_code == 302 and r.headers["Location"] == "/dashboard")
c = app.test_client(); r = c.post("/login", data=dict(_csrf=tok(c, "/login"), email="dono@a.com", password="12345678"))
show("old password doesn't", r.status_code == 400)
show("link works once", anon.get(f"/reset/{token}").status_code == 404)
show("the other open link of the account was cancelled", anon.get(f"/reset/{token2}").status_code == 404)
show("random token -> 404", anon.get("/reset/abc123").status_code == 404)
forgot(anon, "dono@a.com"); token3 = re.search(r"/reset/(\S+)", sent[-1][2]).group(1)
db.execute("UPDATE password_resets SET expires_at = '2000-01-01 00:00:00' WHERE token_hash = ?", __import__("helpers").hash_token(token3))
show("expired link -> 404", anon.get(f"/reset/{token3}").status_code == 404)
before = n("SELECT COUNT(*) n FROM password_resets")
for _ in range(3): forgot(anon, "dono@a.com")
show("at most 3 links per hour per account", n("SELECT COUNT(*) n FROM password_resets") - before <= 1)

print("-- mailer (SMTP stubbed, no network)")
import smtplib
calls = {}
class FakeSMTP:
    def __init__(self, host, port, context=None, timeout=None): calls["host"] = (host, port)
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def login(self, user, password): calls["login"] = (user, password)
    def send_message(self, message): calls["message"] = message
smtplib.SMTP_SSL = FakeSMTP
os.environ["MAIL_USERNAME"] = "supplyflow.app@gmail.com"; os.environ["MAIL_PASSWORD"] = "abcd efgh ijkl mnop"
with app.app_context():
    ok = mailer.send_email("ze@rest.com", "Assunto", "Corpo")
show("configured: logs in to Gmail SSL with env credentials and sends", ok and calls["host"] == ("smtp.gmail.com", 465) and calls["login"][0] == "supplyflow.app@gmail.com"
     and calls["message"]["To"] == "ze@rest.com" and calls["message"]["Subject"] == "Assunto")
class BrokenSMTP(FakeSMTP):
    def login(self, user, password): raise smtplib.SMTPAuthenticationError(535, b"bad")
smtplib.SMTP_SSL = BrokenSMTP
with app.app_context():
    show("wrong app password -> False, no crash", mailer.send_email("ze@rest.com", "A", "B") is False)
for k in ("MAIL_USERNAME", "MAIL_PASSWORD"): os.environ.pop(k)

for f in created_files:
    if os.path.exists(f): os.remove(f)
