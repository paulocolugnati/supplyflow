"""
EN: Scenario: tasks and history entries: links, Sao Paulo dates, permissions, insert-only history.
    Runs through the real routes on a temporary database (see common.py).
PT: Cenário: tarefas e registros: vínculos, datas de São Paulo, permissões, histórico só de inserção.
    Passa pelas rotas de verdade num banco temporário (veja o common.py).
"""

from common import *  # noqa: F401,F403

from helpers import today_sp, date_sp_in_days
def n(sql, *args): return one(sql, *args)["n"]

owner = app.test_client(); register(owner, "dono@a.com", ws="Dist A")
wa = one("SELECT id FROM workspaces")["id"]
db.execute("UPDATE workspaces SET plan_id = (SELECT id FROM plans WHERE code='profissional'), onboarding_done = 1 WHERE id = ?", wa)
manager = join(owner, "gerente@a.com", "admin")
seller = join(owner, "vend@a.com", "member")
seller2 = join(owner, "vend2@a.com", "member")
uid = {e: one("SELECT id FROM users WHERE email = ?", e)["id"] for e in ("dono@a.com", "gerente@a.com", "vend@a.com", "vend2@a.com")}
post(owner, "/customers/new", name="Restaurante")
post(owner, "/customers/new", name="Padaria")
c1 = one("SELECT id FROM companies WHERE name='Restaurante'")["id"]; c2 = one("SELECT id FROM companies WHERE name='Padaria'")["id"]
stage = one("SELECT id FROM stages ORDER BY position LIMIT 1")["id"]
post(owner, "/opportunities/new", title="Pedido R", company_id=str(c1), stage_id=str(stage), owner_id=str(uid["vend@a.com"]))
o1 = one("SELECT id FROM opportunities")["id"]
post(owner, f"/customers/{c1}/contacts", name="Maria Compras")
k1 = one("SELECT id FROM contacts")["id"]

other = app.test_client(); register(other, "dono@b.com", ws="Dist B")
post(other, "/customers/new", name="Cliente B")
cb = one("SELECT id FROM companies WHERE name='Cliente B'")["id"]
post(other, "/opportunities/new", title="Pedido B", company_id=str(cb), stage_id=str(one("SELECT id FROM stages WHERE workspace_id <> ? ORDER BY position LIMIT 1", wa)["id"]))
ob = one("SELECT id FROM opportunities WHERE title='Pedido B'")["id"]
show("setup ok", all([c1, c2, o1, k1, cb, ob]))

print("-- create tasks: validation")
base = n("SELECT COUNT(*) n FROM tasks")
for label, data in [
    ("empty title", dict(title="", company_id=str(c1))),
    ("1-char title", dict(title="x", company_id=str(c1))),
    ("161-char title", dict(title="x" * 161, company_id=str(c1))),
    ("no link at all", dict(title="Ligar")),
    ("text as company id", dict(title="Ligar", company_id="abc")),
    ("negative company id", dict(title="Ligar", company_id="-1")),
    ("SQL in company id", dict(title="Ligar", company_id="1; DROP TABLE tasks")),
    ("other tenant's company", dict(title="Ligar", company_id=str(cb))),
    ("other tenant's opportunity", dict(title="Ligar", opportunity_id=str(ob))),
    ("opportunity of a different customer", dict(title="Ligar", company_id=str(c2), opportunity_id=str(o1))),
    ("contact of a different customer", dict(title="Ligar", company_id=str(c2), contact_id=str(k1))),
    ("bad date", dict(title="Ligar", company_id=str(c1), due_date="31/12/2026")),
    ("impossible date", dict(title="Ligar", company_id=str(c1), due_date="2026-02-30")),
    ("assignee from another tenant", dict(title="Ligar", company_id=str(c1), assignee_id=str(one("SELECT id FROM users WHERE email='dono@b.com'")["id"]))),
    ("assignee as text", dict(title="Ligar", company_id=str(c1), assignee_id="'; --")),
]:
    post(seller, "/tasks", **data)
    show("refused: " + label, n("SELECT COUNT(*) n FROM tasks") == base)

today = today_sp()
post(seller, "/tasks", title="Levar amostra 'aspas'; \"teste\"", opportunity_id=str(o1), due_date=date_sp_in_days(-2), next=f"/opportunities/{o1}")
t_over = one("SELECT * FROM tasks ORDER BY id DESC LIMIT 1")
show("opportunity fills its customer, defaults to me, quotes kept", t_over["company_id"] == c1 and t_over["assignee_id"] == uid["vend@a.com"] and "'aspas'" in t_over["title"])
post(seller, "/tasks", title="Ligar hoje", company_id=str(c1), contact_id=str(k1), due_date=today)
post(seller, "/tasks", title="Visitar semana que vem", company_id=str(c2), due_date=date_sp_in_days(5))
post(seller, "/tasks", title="Sem prazo definido", company_id=str(c2))
post(owner, "/tasks", title="Tarefa do gerente", company_id=str(c1), assignee_id=str(uid["gerente@a.com"]), due_date=date_sp_in_days(-1))
show("contact's customer must match (ok when same)", one("SELECT contact_id FROM tasks WHERE title='Ligar hoje'")["contact_id"] == k1)

print("-- My tasks page (Sao Paulo buckets)")
page = seller.get("/tasks").text
pos = [page.find(s) for s in ('id="grupo-overdue"', 'id="grupo-today"', 'id="grupo-upcoming"', 'id="grupo-undated"')]
show("groups in order overdue, today, upcoming, undated", all(p > 0 for p in pos) and pos == sorted(pos))
show("quotes escaped in HTML", "&#39;aspas&#39;" in page and "'aspas'" not in page)
show("seller doesn't see the manager's task", "Tarefa do gerente" not in page)
show("badge counts overdue + today = 2", re.search(r'class="contagem-nav"[^>]*>2<', page) is not None)
show("member can't see team view (falls back to mine)", "Tarefa do gerente" not in seller.get("/tasks?scope=team").text)
team = manager.get("/tasks?scope=team").text
show("admin sees team view", "Tarefa do gerente" in team and "Ligar hoje" in team)
show("other tenant sees nothing of A", "Ligar hoje" not in other.get("/tasks?scope=team").text)

print("-- complete / reopen / delete")
r = post(seller, f"/tasks/{t_over['id']}/done", next=f"/opportunities/{o1}")
act = one("SELECT * FROM activities WHERE type='task_done' ORDER BY id DESC LIMIT 1")
show("done sets done_at and writes task_done on the opportunity", bool(one("SELECT done_at FROM tasks WHERE id=?", t_over["id"])["done_at"]) and act is not None and act["opportunity_id"] == o1 and act["company_id"] == c1 and act["user_id"] == uid["vend@a.com"])
show("redirects back to the safe next", r.headers["Location"] == f"/opportunities/{o1}")
post(seller, f"/tasks/{t_over['id']}/done")
show("done twice doesn't duplicate the history line", n("SELECT COUNT(*) n FROM activities WHERE type='task_done'") == 1)
r = post(seller, f"/tasks/{t_over['id']}/reopen", next="https://evil.com")
show("reopen works; external next blocked", one("SELECT done_at FROM tasks WHERE id=?", t_over["id"])["done_at"] is None and "evil.com" not in r.headers["Location"])
t_mgr = one("SELECT id FROM tasks WHERE title='Tarefa do gerente'")["id"]
show("seller can't complete someone else's task (403)", post(seller, f"/tasks/{t_mgr}/done").status_code == 403 and post(seller2, f"/tasks/{t_over['id']}/done").status_code == 403)
show("other tenant -> 404 on done/reopen/delete", all(post(other, f"/tasks/{t_mgr}/{a}").status_code == 404 for a in ("done", "reopen", "delete")))
show("seller can't delete manager's task", post(seller, f"/tasks/{t_mgr}/delete").status_code == 403)
show("admin can delete a seller's task", post(manager, f"/tasks/{t_over['id']}/delete").status_code == 302 and n("SELECT COUNT(*) n FROM tasks WHERE id=?", t_over["id"]) == 0)
show("history line survives the task deletion", n("SELECT COUNT(*) n FROM activities WHERE type='task_done'") == 1)
show("nonexistent task -> 404", post(owner, "/tasks/99999/done").status_code == 404)

print("-- history entries")
base = n("SELECT COUNT(*) n FROM activities")
for label, data in [
    ("empty body", dict(type="note", body="   ", company_id=str(c1))),
    ("1001-char body", dict(type="note", body="x" * 1001, company_id=str(c1))),
    ("system type forged", dict(type="stage_change", body="falso", company_id=str(c1))),
    ("unknown type", dict(type="email", body="oi", company_id=str(c1))),
    ("other tenant's customer", dict(type="note", body="oi", company_id=str(cb))),
    ("mismatched opportunity", dict(type="note", body="oi", company_id=str(c2), opportunity_id=str(o1))),
]:
    post(seller, "/activities", **data)
    show("refused: " + label, n("SELECT COUNT(*) n FROM activities") == base)
post(seller, "/activities", type="call", body="Ligou; pediu retorno <b>sexta</b>", company_id=str(c1), opportunity_id=str(o1))
post(manager, "/activities", type="whatsapp", body="Mandei catálogo", company_id=str(c1))
e_seller = one("SELECT id FROM activities WHERE type='call'")["id"]; e_mgr = one("SELECT id FROM activities WHERE type='whatsapp'")["id"]
cust_page = owner.get(f"/customers/{c1}").text
show("customer timeline joins opportunity + customer entries", "Ligou; pediu retorno" in cust_page and "Mandei catálogo" in cust_page and "Tarefa concluída" in cust_page)
show("entry body escaped", "&lt;b&gt;sexta&lt;/b&gt;" in cust_page)
show("customer page lists its open tasks", "Ligar hoje" in cust_page and "Tarefa do gerente" in cust_page)
opp_page = seller.get(f"/opportunities/{o1}").text
show("opportunity timeline has the call, not the customer-only WhatsApp", "Ligou; pediu retorno" in opp_page and "Mandei catálogo" not in opp_page)
show("other tenant's customer page -> 404", other.get(f"/customers/{c1}").status_code == 404)
show("seller can't delete manager's entry", post(seller, f"/activities/{e_mgr}/delete").status_code == 403)
show("system line can't be deleted even by owner", post(owner, f"/activities/{act['id']}/delete").status_code == 403)
show("other tenant -> 404", post(other, f"/activities/{e_seller}/delete").status_code == 404)
post(seller, f"/activities/{e_seller}/delete"); post(owner, f"/activities/{e_mgr}/delete")
show("author and admin can delete manual entries", n("SELECT COUNT(*) n FROM activities WHERE id IN (?, ?)", e_seller, e_mgr) == 0)

print("-- CSRF + login")
r = seller.post("/tasks", data=dict(title="Sem token", company_id=str(c1)))
show("POST without CSRF refused", r.status_code in (400, 403) and n("SELECT COUNT(*) n FROM tasks WHERE title='Sem token'") == 0)
show("logged out -> login", app.test_client().get("/tasks").status_code == 302)
