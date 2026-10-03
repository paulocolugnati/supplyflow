"""
EN: Scenario: task delete, error pages, translations (no raw keys on any screen).
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: apagar tarefa, páginas de erro, traduções (nenhuma chave crua em nenhuma tela).
    Passa pelas rotas de verdade num banco temporário (veja o common.py).
"""

from common import *  # noqa: F401,F403

import translations as T
def n(sql, *args): return one(sql, *args)["n"]

owner = app.test_client(); register(owner, "dono@a.com", ws="Dist A")
wa = one("SELECT id FROM workspaces")["id"]
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='profissional'), onboarding_done = 1 WHERE id = ?", wa)
seller = join(owner, "vend@a.com", "member")
seller2 = join(owner, "vend2@a.com", "member")
post(owner, "/customers/new", name="Restaurante")
cid = one("SELECT id FROM companies")["id"]

print("-- task delete button")
post(seller, "/tasks", title="Tarefa do seller", company_id=str(cid))
tid = one("SELECT id FROM tasks")["id"]
show("creator sees the delete button", f"/tasks/{tid}/delete" in seller.get("/tasks").text)
show("owner sees it on the customer page", f"/tasks/{tid}/delete" in owner.get(f"/customers/{cid}").text)
show("other member doesn't see it", f"/tasks/{tid}/delete" not in seller2.get(f"/customers/{cid}").text)
r = post(seller, f"/tasks/{tid}/delete", next=f"/customers/{cid}")
show("delete works and returns to the page", r.status_code == 302 and r.headers["Location"] == f"/customers/{cid}" and n("SELECT COUNT(*) n FROM tasks") == 0)

print("-- error pages")
r = owner.get("/tasks/1/done")
show("GET on a POST-only route -> 405 page, translated", r.status_code == 405 and "não pode ser aberta por um link" in r.text)
r = owner.get("/nao-existe")
show("404 page translated", r.status_code == 404 and "Página não encontrada" in r.text)
with app.test_request_context("/"):
    body, status = appmod.server_error(RuntimeError("SECRET-TRACE"))
show("500 page hides the traceback", status == 500 and "SECRET-TRACE" not in body and "Algo falhou" in body)

print("-- translations")
pt, en = T.TRANSLATIONS["pt"], T.TRANSLATIONS["en"]
show("same keys in PT and EN", set(pt) == set(en))
show("no empty values", all(v.strip() for v in list(pt.values()) + list(en.values())))
placeholders = [k for k in pt if set(re.findall(r"{\w+}", pt[k])) != set(re.findall(r"{\w+}", en[k]))]
show("same {placeholders} in PT and EN", not placeholders)
if placeholders: print(placeholders)
show("the 'Configurações' page mentioned in the texts exists (owner)", owner.get("/settings").status_code == 200)
owner.get("/lang/en")
page = owner.get("/dashboard").text
show("EN dashboard has lang=en and English text", 'lang="en"' in page and "Open in the funnel" in page)

print("-- no raw translation keys on any screen")
owner.get("/lang/pt")
post(owner, "/opportunities/new", title="Pedido X", company_id=str(cid), stage_id=str(one("SELECT id FROM stages WHERE workspace_id = ? ORDER BY position LIMIT 1", wa)["id"]))
oid = one("SELECT id FROM opportunities")["id"]
post(owner, f"/opportunities/{oid}/quotes")
qid = one("SELECT id FROM quotes")["id"]
keys = set(pt)
pattern = re.compile(r"\b(" + "|".join(sorted({k.split(".")[0] for k in keys})) + r")\.[a-z0-9_]+\b")
pages = {"anon": (app.test_client(), ["/", "/login", "/register", "/register?type=buyer", "/invite/x"]),
         "owner": (owner, ["/dashboard", "/pipeline", "/pipeline/settings", f"/opportunities/{oid}", "/opportunities/new", "/quotes",
                            f"/quotes/{qid}", "/approvals", "/tasks", "/customers", f"/customers/{cid}", "/customers/new", "/products",
                            "/products/new", "/team", "/plans", "/onboarding", "/nao-existe"])}
raw = []
for lang in ("pt", "en"):
    for who, (client, paths) in pages.items():
        client.get("/lang/" + lang)
        for path in paths:
            body = client.get(path).text
            body = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", body, flags=re.S)
            for m in pattern.finditer(body):
                if m.group(0) in keys or m.group(0).count(".") == 1 and m.group(0).split(".")[1].islower() and "_" in m.group(0):
                    raw.append(f"{lang} {path}: {m.group(0)}")
show("no raw keys in PT and EN on 23 screens", not raw)
if raw: print(raw[:10])
