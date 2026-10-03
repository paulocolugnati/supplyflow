"""
EN: Scenario: clearer portal, landing questions, terms and privacy.
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: portal mais claro, dúvidas da landing, termos e privacidade.
    Passa pelas rotas de verdade num banco temporário (veja o common.py).
"""

from common import *  # noqa: F401,F403

import html as htmlmod
from urllib.parse import unquote
from helpers import date_sp_in_days
def n(sql, *args): return one(sql, *args)["n"]
def text(r): return htmlmod.unescape(r.text)

owner = app.test_client(); register(owner, "dono@a.com", ws="Dist A")
wa = one("SELECT id FROM workspaces")["id"]
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='profissional'), onboarding_done = 1, cnpj = '11222333000181', "
           "phone = '5511912345678', logo_path = '/static/brand/simbolo.svg' WHERE id = ?", wa)
db.execute("UPDATE users SET name = 'Diego Lima' WHERE email = 'dono@a.com'")
post(owner, "/customers/new", name="Restaurante do Zé")
cid = one("SELECT id FROM companies")["id"]
first = one("SELECT id FROM stages WHERE workspace_id = ? ORDER BY position LIMIT 1", wa)["id"]
post(owner, "/opportunities/new", title="Pedido", company_id=str(cid), stage_id=str(first))
oid = one("SELECT id FROM opportunities")["id"]
for sku, name, cost in [("ARZ", "Arroz tipo 1", "61,23"), ("FEI", "Feijão carioca", "5,00"), ("OLE", "Óleo de soja", "3,00")]:
    post(owner, "/products/new", sku=sku, name=name, unit="cx", price="100,00", cost_mode="brl", cost=cost)

def quote(valid_until, products=("ARZ", "FEI", "OLE"), status="sent"):
    before = {r["id"] for r in db.execute("SELECT id FROM quotes")}
    post(owner, f"/opportunities/{oid}/quotes")
    qid = [r["id"] for r in db.execute("SELECT id FROM quotes") if r["id"] not in before][0]
    for sku in products:
        post(owner, f"/quotes/{qid}/items", product_id=str(one("SELECT id FROM products WHERE sku = ?", sku)["id"]), quantity="2", discount="0")
    db.execute("UPDATE quotes SET status = ?, valid_until = ?, sent_at = '2026-10-01 12:00:00', final_total_cents = 50000, list_total_cents = 60000 WHERE id = ?",
               status, valid_until, qid)
    return qid
q_today = quote(date_sp_in_days(0))
q_tomorrow = quote(date_sp_in_days(1), products=("ARZ",))
q_week = quote(date_sp_in_days(7))
q_done = quote(date_sp_in_days(7), status="accepted")
db.execute("UPDATE quotes SET customer_decided_at = '2026-09-20 15:00:00' WHERE id = ?", q_done)

post(owner, f"/customers/{cid}/buyers/invite", email="ze@rest.com")
token = re.search(r'id="buyer-link" readonly type="text" value="[^"]*/invite/([^"]+)"', owner.get(f"/customers/{cid}").text).group(1)
buyer = app.test_client(); register(buyer, "ze@rest.com", invite=token)
db.execute("UPDATE users SET name = 'José Almeida' WHERE email = 'ze@rest.com'")

print("-- portal home")
page = text(buyer.get("/portal"))
show("greets the buyer by first name and explains the page", "Olá, José" in page and "aceite com um toque" in page)
show("one line says how many quotes wait for an answer", "3 orçamentos esperando sua resposta" in page)
show("distributor shows logo and a WhatsApp button", 'src="/static/brand/simbolo.svg"' in page and "Falar com a distribuidora" in page)
link = re.search(r'href="(https://wa.me/5511912345678\?text=[^"]+)"', buyer.get("/portal").text)
msg = unquote(htmlmod.unescape(link.group(1))).split("?text=", 1)[1] if link else ""
show("WhatsApp message in Portuguese, from José of the customer", msg == "Olá! Aqui é José, do Restaurante do Zé.")
show("cards: items summary with 'e mais 1'", "Arroz tipo 1, Feijão carioca e mais 1" in page)
show("cards: due today / tomorrow / in 7 days", "vence hoje" in page and "vence amanhã" in page and "vence em 7 dias" in page)
show("cards: total and savings, one clear button", "R$ 500,00" in page and "Você economiza R$ 100,00" in page and page.count("Ver e responder") == 3)
show("urgent cards (today/tomorrow) are marked", buyer.get("/portal").text.count("cartao-portal-urgente") == 2)
show("history apart, with the accepted quote", "Histórico" in page and f"/portal/quotes/{q_done}" in buyer.get("/portal").text)
show("never cost on the portal", "61,23" not in page)

print("-- portal quote page")
page = text(buyer.get(f"/portal/quotes/{q_tomorrow}"))
show("decision comes before the items", page.index('id="decidir"') < page.index('id="itens-titulo"'))
show("total and deadline in the decision block", "R$ 500,00" in page.split('id="decidir"')[0][-600:] or "vence amanhã" in page)
show("who to talk to: the seller and a WhatsApp about this quote", "Seu vendedor" in page and "Diego Lima" in page)
link = re.search(r'href="(https://wa.me/5511912345678\?text=[^"]+)"', buyer.get(f"/portal/quotes/{q_tomorrow}").text)
msg = unquote(htmlmod.unescape(link.group(1))).split("?text=", 1)[1] if link else ""
show("the WhatsApp message names the quote number", f"#{one('SELECT number FROM quotes WHERE id = ?', q_tomorrow)['number']:04d}" in msg)
show("never cost or internal data", "61,23" not in page and "Margem" not in page)
def post_buyer(url, page):
    token = re.search(r'name="_csrf" type="hidden" value="([^"]+)"', buyer.get(page).text).group(1)
    return buyer.post(url, data={"_csrf": token})
show("accept still works from the new layout", post_buyer(f"/portal/quotes/{q_tomorrow}/accept", f"/portal/quotes/{q_tomorrow}").status_code == 302 and one("SELECT status FROM quotes WHERE id = ?", q_tomorrow)["status"] == "accepted")
show("after accepting: 'a distribuidora já foi avisada'", "A distribuidora já foi avisada" in text(buyer.get(f"/portal/quotes/{q_tomorrow}")))
show("accepting cancels the other open quotes of the same deal, so nothing waits now",
     "Nenhum orçamento esperando sua resposta" in text(buyer.get("/portal")) and one("SELECT status FROM quotes WHERE id = ?", q_week)["status"] == "cancelled")
stranger = app.test_client(); register(stranger, "x@y.com", kind="buyer")
show("another buyer -> 404", stranger.get(f"/portal/quotes/{q_week}").status_code == 404)

print("-- landing questions")
anon = app.test_client()
page = text(anon.get("/"))
show("rail has D07 Dúvidas and D08 Saída", "D07" in page and "Dúvidas" in page and "D08" in page)
show("comparison table: spreadsheet + WhatsApp vs SupplyFlow, 3 rows", "Planilha + WhatsApp" in page and "teto por cargo; passou, trava" in page and "alerta de recompra" in page)
show("7 questions, honest ones included", anon.get("/").text.count('class="faq-item"') == 7 and "E a LGPD?" in page and "Posso sair levando meus dados?" in page and "ainda não há pagamento online" in page)
show("LGPD answer links to the privacy page; footer links to both", anon.get("/").text.count('href="/privacy"') >= 2 and 'href="/terms"' in anon.get("/").text)

print("-- terms and privacy")
r = anon.get("/terms"); page = text(r)
show("terms: public, says it is a student CS50x project, 6 sections", r.status_code == 200 and "projeto de estudante" in page and "CS50x" in page and page.count("<h2>") == 6)
r = anon.get("/privacy"); page = text(r)
show("privacy: LGPD, cookies, rights, 7 sections", r.status_code == 200 and "LGPD" in page and "Cookies" in page and "Seus direitos" in page and page.count("<h2>") == 7)
anon.get("/lang/en")
show("both in English too", "student project" in text(anon.get("/terms")) and "Privacy policy" in text(anon.get("/privacy")))
anon.get("/lang/pt")
show("sign-up says the account accepts terms and privacy (links)", 'href="/terms"' in anon.get("/register").text and 'href="/privacy"' in anon.get("/register").text)
show("logged-in users can open them too", owner.get("/terms").status_code == 200)
raw = [k for path in ("/terms", "/privacy", "/", "/register") for k in re.findall(r"\b(?:terms|privacy|legal|landing|portal)\.[a-z0-9_]+\b", re.sub(r"<[^>]+>", " ", anon.get(path).text))]
show("no raw translation keys on the new pages", not raw)
if raw: print(raw[:5])
