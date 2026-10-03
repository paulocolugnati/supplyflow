"""
EN: Scenario: quote PDF document, draft autosave hooks, drag and drop hooks.
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: documento PDF do orçamento, ganchos do rascunho salvo, ganchos do arrastar.
    Passa pelas rotas de verdade num banco temporário (veja o common.py).
"""

from common import *  # noqa: F401,F403

import html as htmlmod
def n(sql, *args): return one(sql, *args)["n"]
def text(r): return htmlmod.unescape(r.text)

owner = app.test_client(); register(owner, "dono@a.com", ws="Dist A")
wa = one("SELECT id FROM workspaces")["id"]
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='profissional'), onboarding_done = 1 WHERE id = ?", wa)
seller = join(owner, "vend@a.com", "member")
seller2 = join(owner, "vend2@a.com", "member")
db.execute("UPDATE users SET name = 'Diego Lima' WHERE email = 'vend@a.com'")
post(owner, "/customers/new", name="Restaurante do Zé", cnpj="11.222.333/0001-81", city="São Paulo")
cid = one("SELECT id FROM companies")["id"]
post(owner, f"/customers/{cid}/contacts", name="José Almeida")
first = one("SELECT id FROM stages WHERE workspace_id = ? ORDER BY position LIMIT 1", wa)["id"]
post(owner, "/products/new", sku="ARZ", name="Arroz tipo 1", unit="cx", price="100,00", cost_mode="brl", cost="61,23")
pid = one("SELECT id FROM products")["id"]
post(seller, "/opportunities/new", title="Pedido Zé", company_id=str(cid), stage_id=str(first),
     contact_id=str(one("SELECT id FROM contacts")["id"]))
oid = one("SELECT id FROM opportunities")["id"]
post(seller, f"/opportunities/{oid}/quotes")
qid = one("SELECT id FROM quotes")["id"]
post(seller, f"/quotes/{qid}/items", product_id=str(pid), quantity="1500", discount="0")
item = one("SELECT id FROM quote_items")["id"]
post(seller, f"/quotes/{qid}", **{f"quantity_{item}": "1500", f"discount_{item}": "2", "header_discount": "1", "valid_until": "2999-12-31",
                                  "notes_customer": "Entrega na terça", "notes_internal": "SEGREDO-INTERNO"})

print("-- quote document for the staff")
r = seller.get(f"/quotes/{qid}/document")
page = text(r)
show("seller opens the A4 document of their quote", r.status_code == 200 and "Orçamento" in page and "nº 0001" in page)
show("customer data, contact, seller, items and totals", all(x in page for x in ("Restaurante do Zé", "11.222.333/0001-81", "A/C José Almeida", "Diego Lima", "Arroz tipo 1", "1.500 cx", "Entrega na terça")))
show("never cost, margin or internal notes", "61,23" not in page and "SEGREDO-INTERNO" not in page and "Margem" not in page)
show("draft carries the 'not final' banner", "Rascunho: este orçamento ainda não foi enviado" in page)
show("page title = PDF file name", "<title>Orcamento-0001-Restaurante-do-Z" in r.text)
show("'Baixar PDF' uses a button handled by sf.js (no inline script, CSP ok)", "data-imprimir" in r.text and "onclick" not in r.text and "<script defer src=\"/static/sf.js\">" in r.text)
seller.get("/lang/en")
show("document stays in Portuguese even with the screen in English", "Válido até" in text(seller.get(f"/quotes/{qid}/document")))
seller.get("/lang/pt")
show("quote page links to the document", f"/quotes/{qid}/document" in seller.get(f"/quotes/{qid}").text)
show("another seller -> 404", seller2.get(f"/quotes/{qid}/document").status_code == 404)
show("owner can open it", owner.get(f"/quotes/{qid}/document").status_code == 200)
other = app.test_client(); register(other, "dono@b.com", ws="Dist B")
show("another distributor -> 404", other.get(f"/quotes/{qid}/document").status_code == 404)
show("logged out -> login", app.test_client().get(f"/quotes/{qid}/document").status_code == 302)
show("unknown quote -> 404", owner.get("/quotes/9999/document").status_code == 404)

print("-- quote document for the buyer")
post(owner, f"/customers/{cid}/buyers/invite", email="ze@rest.com")
token = re.search(r'id="buyer-link" readonly type="text" value="[^"]*/invite/([^"]+)"', owner.get(f"/customers/{cid}").text).group(1)
buyer = app.test_client(); register(buyer, "ze@rest.com", invite=token)
show("draft quote: buyer gets 404 (not visible yet)", buyer.get(f"/portal/quotes/{qid}/document").status_code == 404)
post(seller, f"/quotes/{qid}/submit")
post(seller, f"/quotes/{qid}/send")
r = buyer.get(f"/portal/quotes/{qid}/document")
page = text(r)
show("sent quote: buyer opens the same document, no banner", r.status_code == 200 and "Arroz tipo 1" in page and "Rascunho" not in page and "61,23" not in page)
show("buyer's back link goes to the portal", f'href="/portal/quotes/{qid}"' in r.text)
show("portal quote page links to the document", f"/portal/quotes/{qid}/document" in buyer.get(f"/portal/quotes/{qid}").text)
stranger = app.test_client(); register(stranger, "x@y.com", kind="buyer")
show("another buyer -> 404", stranger.get(f"/portal/quotes/{qid}/document").status_code == 404)
db.execute("UPDATE quotes SET status = 'cancelled' WHERE id = ?", qid)
show("cancelled quote in the staff document says so", "Este orçamento foi cancelado" in text(owner.get(f"/quotes/{qid}/document")))

print("-- draft autosave and drag and drop hooks")
post(seller, f"/opportunities/{oid}/quotes")
q2 = one("SELECT id FROM quotes ORDER BY id DESC")["id"]
page = seller.get(f"/quotes/{q2}").text
show("editable quote has the draft key and the restore notice (hidden)", f'data-rascunho="sf-orcamento-{q2}"' in page and "data-rascunho-aviso hidden" in page)
show("read-only quote has no draft key", "data-rascunho=" not in owner.get(f"/quotes/{qid}").text)
page = seller.get("/pipeline").text
show("board: hidden move form with CSRF, draggable cards, columns with stage id and kind",
     "data-mover-form hidden" in page and 'name="_csrf"' in page and f'data-cartao="{oid}" draggable="true"' in page and f'data-etapa="{first}" data-tipo="open"' in page)
