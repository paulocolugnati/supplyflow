"""
EN: Scenario: period report: sales, ticket, conversion, ranking, commission, losses.
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: relatório do período: vendas, ticket, conversão, ranking, comissão, perdas.
    Passa pelas rotas de verdade num banco temporário (veja o common.py).
"""

from common import *  # noqa: F401,F403

import html as htmlmod
from datetime import datetime, timedelta, timezone
def n(sql, *args): return one(sql, *args)["n"]
def text(r): return htmlmod.unescape(r.text)

owner = app.test_client(); register(owner, "dono@a.com", ws="Dist A")
wa = one("SELECT id FROM workspaces")["id"]
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='profissional'), onboarding_done = 1, cnpj = '11222333000181' WHERE id = ?", wa)
manager = join(owner, "gerente@a.com", "admin")
diego = join(owner, "diego@a.com", "member")
fer = join(owner, "fer@a.com", "member")
uid = {e: one("SELECT id FROM users WHERE email = ?", e)["id"] for e in ("dono@a.com", "gerente@a.com", "diego@a.com", "fer@a.com")}
db.execute("UPDATE users SET name = 'Diego Lima' WHERE email = 'diego@a.com'")
db.execute("UPDATE users SET name = 'Fernanda Rocha' WHERE email = 'fer@a.com'")

print("-- commission on the team page")
def set_commission(c, user, value):
    return post(c, f"/team/members/{user}/commission", commission=value)
set_commission(owner, uid["diego@a.com"], "2,5")
set_commission(owner, uid["fer@a.com"], "3")
show("owner sets 2,5% and 3%", one("SELECT commission_bps c FROM memberships WHERE user_id = ?", uid["diego@a.com"])["c"] == 250
     and one("SELECT commission_bps c FROM memberships WHERE user_id = ?", uid["fer@a.com"])["c"] == 300)
for label, value in [("text", "abc"), ("negative", "-1"), ("above 100", "150"), ("SQL", "1; DROP TABLE memberships")]:
    set_commission(owner, uid["diego@a.com"], value)
    show("refused: " + label, one("SELECT commission_bps c FROM memberships WHERE user_id = ?", uid["diego@a.com"])["c"] == 250)
show("manager can't set commission (403)", set_commission(manager, uid["diego@a.com"], "50").status_code == 403)
show("seller can't set commission (403)", set_commission(diego, uid["diego@a.com"], "50").status_code == 403)
other = app.test_client(); register(other, "dono@b.com", ws="Dist B")
show("other distributor's owner -> 404 for our people", set_commission(other, uid["diego@a.com"], "9").status_code == 404)
show("owner sees inputs; manager reads; seller has no team page", 'name="commission"' in owner.get("/team").text
     and "2,5%" in manager.get("/team").text and 'name="commission"' not in manager.get("/team").text and diego.get("/team").status_code == 403)

print("-- data: sales this month and last month")
post(owner, "/customers/new", name="Restaurante do Zé"); post(owner, "/customers/new", name="Padaria Pão")
c_ze = one("SELECT id FROM companies WHERE name='Restaurante do Zé'")["id"]; c_pao = one("SELECT id FROM companies WHERE name='Padaria Pão'")["id"]
first = one("SELECT id FROM stages WHERE workspace_id = ? ORDER BY position LIMIT 1", wa)["id"]
won = one("SELECT id FROM stages WHERE workspace_id = ? AND kind = 'won'", wa)["id"]
lost = one("SELECT id FROM stages WHERE workspace_id = ? AND kind = 'lost'", wa)["id"]
now = datetime.now(timezone.utc)
this_month = now.strftime("%Y-%m-%d %H:%M:%S")
last_month = (now.replace(day=1) - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
counter = [0]
def deal(seller, company, final, list_total, decided, status="accepted", sent=None):
    counter[0] += 1
    title = f"Negócio {counter[0]}"
    post(seller, "/opportunities/new", title=title, company_id=str(company), stage_id=str(first))
    oid = one("SELECT id FROM opportunities WHERE title = ?", title)["id"]
    post(seller, f"/opportunities/{oid}/quotes")
    qid = one("SELECT id FROM quotes WHERE opportunity_id = ?", oid)["id"]
    db.execute("UPDATE quotes SET status = ?, final_total_cents = ?, list_total_cents = ?, customer_decided_at = ?, sent_at = ? WHERE id = ?",
               status, final, list_total, decided if status == "accepted" else None, sent or decided, qid)
    return oid
deal(diego, c_ze, 90000, 100000, this_month)            # EN/PT: R$ 900 (10% off)
deal(fer, c_ze, 150000, 150000, this_month)             # EN/PT: R$ 1.500
deal(fer, c_pao, 50000, 50000, this_month)              # EN/PT: R$ 500
deal(diego, c_pao, 1, 1, last_month)                    # EN/PT: last month only
deal(diego, c_pao, 0, 0, None, status="declined", sent=this_month)   # EN/PT: sent, not accepted
post(diego, "/opportunities/new", title="Venda por telefone", company_id=str(c_pao), stage_id=str(won), value="200,00")
for reason, value in [("Preço alto", "100,00"), (" preço ALTO ", "50,00"), ("", "10,00")]:
    counter[0] += 1
    post(owner, "/opportunities/new", title=f"Perdida {counter[0]}", company_id=str(c_ze), stage_id=str(first), value=value)
    oid = one("SELECT id FROM opportunities WHERE title = ?", f"Perdida {counter[0]}")["id"]
    post(owner, f"/opportunities/{oid}/stage", stage_id=str(lost), lost_reason=reason)

print("-- owner dashboard: this month")
page = text(owner.get("/dashboard"))
block = page.split('id="relatorio-titulo"')[1]
show("sold = 900 + 1.500 + 500 + 200 manual = 3.100,00", "R$ 3.100,00" in block and "inclui R$ 200,00 fora do sistema" in block)
show("4 sales, ticket 775,00", ">4<" in block.replace(" ", "") and "R$ 775,00" in block)
show("conversion: 3 accepted of 4 sent this month = 75%", "75%" in block and "aceitos de 4 enviados" in block)
show("average discount weighted: 100 off 3.000 = 3,33%", "3,33%" in block)
rank = block.split('id="ranking-titulo"')[1].split('id="clientes-top-titulo"')[0]
show("ranking: Fernanda (2.000) before Diego (1.100)", rank.index("Fernanda Rocha") < rank.index("Diego Lima"))
show("commission: Fernanda 3% of 2.000 = 60,00; Diego 2,5% of 1.100 = 27,50", "R$ 60,00" in rank and "R$ 27,50" in rank)
show("Diego's row shows his 10% discount and the manual sale", "10%" in rank and "inclui R$ 200,00" in rank)
top = block.split('id="clientes-top-titulo"')[1].split('id="perdas-titulo"')[0]
show("top customers: Zé (2.400) before Pão (700)", top.index("Restaurante do Zé") < top.index("Padaria Pão") and "R$ 2.400,00" in top and "R$ 700,00" in top)
loss = block.split('id="perdas-titulo"')[1].split('id="atrasadas-titulo"')[0]
show("loss reasons grouped ignoring case/spaces: 'Preço alto' x2, then no reason", "Preço alto" in loss and ">2<" in loss.replace(" ", "") and "Sem motivo informado" in loss)

print("-- period filter")
page = text(owner.get("/dashboard?period=last_month"))
block = page.split('id="relatorio-titulo"')[1]
show("last month: only the R$ 0,01 sale", "R$ 0,01" in block and "R$ 3.100,00" not in block)
show("90 days includes both months", "R$ 3.100,01" in text(owner.get("/dashboard?period=90d")))
r = owner.get("/dashboard?period=%27%3B%20DROP%20TABLE%20quotes--")
show("weird period falls back to this month", r.status_code == 200 and "R$ 3.100,00" in text(r) and n("SELECT COUNT(*) n FROM quotes") > 0)
show("chosen period marked", 'aria-current="true" class="periodo" href="/dashboard?period=last_month' in owner.get("/dashboard?period=last_month").text)

print("-- seller sees only their own")
page = text(diego.get("/dashboard"))
block = page.split('id="relatorio-titulo"')[1]
show("Diego: 'Seu resultado', his 1.100,00 and his commission 27,50", "Seu resultado" in page and "R$ 1.100,00" in block and "Sua comissão (2,5%)" in block and "R$ 27,50" in block)
show("Diego doesn't see Fernanda's numbers nor the ranking", "Fernanda" not in block and "R$ 3.100,00" not in block and 'id="ranking-titulo"' not in page)
show("Diego's top customers come only from his sales", "R$ 1.100,00" in block and "R$ 2.400,00" not in block)

print("-- team overdue tasks (managers)")
post(diego, "/tasks", title="Atrasada 1", company_id=str(c_ze), due_date="2020-01-01")
post(diego, "/tasks", title="Atrasada 2", company_id=str(c_ze), due_date="2021-01-01")
page = text(manager.get("/dashboard"))
show("manager sees Diego with 2 overdue, oldest 01/01", "Tarefas atrasadas da equipe" in page and "Diego Lima" in page.split('id="atrasadas-titulo"')[1] and "01/01" in page.split('id="atrasadas-titulo"')[1])
show("seller has no team-overdue block", 'id="atrasadas-titulo"' not in diego.get("/dashboard").text)
show("other distributor sees none of it", "Diego" not in text(other.get("/dashboard")))
show("English labels", "Team results" in (owner.get("/lang/en") and owner.get("/dashboard").text))
