"""EN: Tasks (follow-ups with a due date) and manual history entries (note, call, WhatsApp).
    Registered in app.py as a Blueprint.
PT: Tarefas (retornos com prazo) e registros manuais no histórico (nota, ligação, WhatsApp).
    Registrado no app.py como um Blueprint.

EN: Rules (docs/ARCHITECTURE.md, sections 5.15, 5.16 and 6.8):
    * a task or entry is linked to a customer, an opportunity and/or a contact of the active
      workspace; every id from the form is checked, and the links must agree with each other
    * "today" and "overdue" use the Sao Paulo date, not UTC
    * completing a task writes a "task_done" line to the history
    * history is insert-only: only manual entries (note, call, whatsapp) can be deleted, by
      their author or an admin; system lines (stage change, quotes...) stay forever
PT: Regras (docs/ARCHITECTURE.md, seções 5.15, 5.16 e 6.8):
    * uma tarefa ou registro fica ligado a um cliente, uma oportunidade e/ou um contato da
      distribuidora ativa; todo id do formulário é conferido, e os vínculos precisam combinar
    * "hoje" e "atrasada" usam a data de São Paulo, não UTC
    * concluir uma tarefa grava uma linha "task_done" no histórico
    * o histórico é só de inserção: só registros manuais (nota, ligação, whatsapp) podem ser
      apagados, pelo autor ou por um admin; linhas do sistema (etapa, orçamentos...) ficam para sempre
"""

from datetime import datetime

from flask import Blueprint, flash, g, redirect, render_template, request

from database import get_db
from helpers import apology, now_utc, safe_redirect_target, today_sp
from permissions import (find_scoped, find_visible_opportunity, get_scoped, has_role, is_workspace_user, require_role,
                         sees_all_sales, workspace_id)
from translations import _

tasks_bp = Blueprint("tasks", __name__)

TITLE_MAX = 160
BODY_MAX = 1000
MANUAL_TYPES = ("note", "call", "whatsapp")


# ---------------------------------------------------------------------------
# EN: Links shared by tasks and history entries
# PT: Vínculos compartilhados por tarefas e registros
# ---------------------------------------------------------------------------

def read_links():
    """EN: Read company / opportunity / contact ids from the form, check each belongs to the
        active workspace, and make them consistent: an opportunity or contact also fills in
        its customer, and a different customer sent alongside is refused.
        Returns (links dict, error key or None).
    PT: Lê os ids de cliente / oportunidade / contato do formulário, confere se cada um é da
        distribuidora ativa e deixa tudo coerente: uma oportunidade ou contato também preenche
        o cliente dela, e um cliente diferente enviado junto é recusado.
        Devolve (dict de vínculos, chave de erro ou None).
    """
    links = {"company_id": None, "opportunity_id": None, "contact_id": None}
    for field, table in (("company_id", "companies"), ("opportunity_id", "opportunities"), ("contact_id", "contacts")):
        raw = request.form.get(field, "")
        if raw:
            # EN: a seller can't link to another seller's opportunity | PT: um vendedor não liga à oportunidade de outro vendedor
            row = find_visible_opportunity(raw) if table == "opportunities" else find_scoped(table, raw)
            if row is None:
                return links, "tasks.error_link"
            links[field] = row

    company = links["company_id"]
    for key in ("opportunity_id", "contact_id"):
        row = links[key]
        if row is None:
            continue
        if company is None:
            company = get_scoped("companies", row["company_id"])
        elif row["company_id"] != company["id"]:
            return links, "tasks.error_link"

    if company is None:
        return links, "tasks.error_link"
    return {
        "company_id": company["id"],
        "opportunity_id": links["opportunity_id"]["id"] if links["opportunity_id"] else None,
        "contact_id": links["contact_id"]["id"] if links["contact_id"] else None,
    }, None


def back(default="/tasks"):
    return redirect(safe_redirect_target(request.form.get("next"), default))


def can_touch_task(task):
    """EN: The assignee, the creator or an admin may complete/reopen/delete a task.
    PT: O responsável, quem criou ou um admin pode concluir/reabrir/apagar uma tarefa.
    """
    return has_role("admin") or g.user["id"] in (task["assignee_id"], task["created_by"])


def task_query(where, *params):
    """EN: Tasks with the names of what they are linked to, ordered by due date.
    PT: Tarefas com os nomes do que estão ligadas, ordenadas pelo prazo.
    """
    return get_db().execute(
        "SELECT t.*, c.name AS company_name, o.title AS opportunity_title, k.name AS contact_name, "
        "u.name AS assignee_name FROM tasks t "
        "LEFT JOIN companies c ON c.id = t.company_id LEFT JOIN opportunities o ON o.id = t.opportunity_id "
        "LEFT JOIN contacts k ON k.id = t.contact_id LEFT JOIN users u ON u.id = t.assignee_id "
        "WHERE t.workspace_id = ? AND " + where +
        " ORDER BY t.due_date IS NULL, t.due_date, t.id",
        workspace_id(), *params,
    )


def bucket(task, today):
    """EN: overdue / today / upcoming / undated, by the Sao Paulo date.
    PT: atrasada / hoje / próxima / sem prazo, pela data de São Paulo.
    """
    if task["due_date"] is None:
        return "undated"
    if task["due_date"] < today:
        return "overdue"
    return "today" if task["due_date"] == today else "upcoming"


def open_count_for(user_id):
    """EN: Overdue + today tasks of a user (menu badge). | PT: Tarefas atrasadas + de hoje (contador do menu)."""
    return get_db().execute(
        "SELECT COUNT(*) AS n FROM tasks WHERE workspace_id = ? AND assignee_id = ? AND done_at IS NULL "
        "AND due_date IS NOT NULL AND due_date <= ?",
        workspace_id(), user_id, today_sp(),
    )[0]["n"]


def tasks_for(field, value):
    """EN: Open and recently done tasks of a customer or opportunity (for their pages).
    PT: Tarefas abertas e concluídas recentes de um cliente ou oportunidade (para as páginas deles).
    """
    if field not in ("company_id", "opportunity_id"):
        raise ValueError(field)
    today = today_sp()
    where = "t." + field + " = ? AND (t.done_at IS NULL OR t.done_at >= datetime('now', '-14 days'))"
    params = [value]
    if not sees_all_sales():
        # EN: sellers see only tasks they own or created | PT: vendedores veem só tarefas deles ou criadas por eles
        where += " AND (t.assignee_id = ? OR t.created_by = ?)"
        params += [g.user["id"], g.user["id"]]
    rows = task_query(where, *params)
    for row in rows:
        row["bucket"] = "done" if row["done_at"] else bucket(row, today)
    return rows


# ---------------------------------------------------------------------------
# EN: Tasks
# PT: Tarefas
# ---------------------------------------------------------------------------

@tasks_bp.route("/tasks")
@require_role("member")
def index():
    """EN: My tasks by default (admins can see the whole team), grouped by urgency.
    PT: Minhas tarefas por padrão (admins podem ver a equipe toda), agrupadas por urgência.
    """
    scope = request.args.get("scope", "mine")
    if scope == "team" and has_role("admin"):
        rows = task_query("t.done_at IS NULL")
    else:
        scope = "mine"
        rows = task_query("t.done_at IS NULL AND t.assignee_id = ?", g.user["id"])

    today = today_sp()
    groups = {"overdue": [], "today": [], "upcoming": [], "undated": []}
    for row in rows:
        row["bucket"] = bucket(row, today)
        groups[row["bucket"]].append(row)

    # EN: the last few completed tasks, so a mistake can be reopened
    # PT: as últimas tarefas concluídas, para um engano poder ser reaberto
    done = get_db().execute(
        "SELECT t.*, c.name AS company_name, u.name AS assignee_name FROM tasks t "
        "LEFT JOIN companies c ON c.id = t.company_id LEFT JOIN users u ON u.id = t.assignee_id "
        "WHERE t.workspace_id = ? AND t.done_at IS NOT NULL AND (t.assignee_id = ? OR ? = 'team') "
        "ORDER BY t.done_at DESC LIMIT 8",
        workspace_id(), g.user["id"], scope,
    )
    companies = get_db().execute("SELECT id, name FROM companies WHERE workspace_id = ? ORDER BY name COLLATE NOCASE", workspace_id())
    staff = get_db().execute(
        "SELECT u.id, u.name FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.workspace_id = ? ORDER BY u.name",
        workspace_id(),
    )
    return render_template("tasks.html", groups=groups, done=done, scope=scope, today=today,
                           companies=companies, staff=staff)


@tasks_bp.route("/tasks", methods=["POST"])
@require_role("member")
def create():
    """EN: Create a task linked to a customer / opportunity / contact.
    PT: Cria uma tarefa ligada a um cliente / oportunidade / contato.
    """
    title = request.form.get("title", "").strip()
    if not 2 <= len(title) <= TITLE_MAX:
        flash(_("tasks.error_title"), "danger")
        return back()

    due = request.form.get("due_date", "").strip() or None
    if due:
        try:
            due = datetime.strptime(due, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            flash(_("pipeline.error_date"), "danger")
            return back()

    assignee = request.form.get("assignee_id", "") or str(g.user["id"])
    if not is_workspace_user(assignee):
        flash(_("customers.error_owner"), "danger")
        return back()

    links, error = read_links()
    if error:
        flash(_(error), "danger")
        return back()

    get_db().execute(
        "INSERT INTO tasks (workspace_id, assignee_id, created_by, title, due_date, company_id, contact_id, opportunity_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        workspace_id(), int(assignee), g.user["id"], title, due, links["company_id"], links["contact_id"], links["opportunity_id"],
    )
    flash(_("tasks.created"), "success")
    return back()


@tasks_bp.route("/tasks/<int:task_id>/done", methods=["POST"])
@require_role("member")
def complete(task_id):
    """EN: Complete a task and write it to the history (one transaction).
    PT: Conclui uma tarefa e grava no histórico (uma transação).
    """
    task = get_scoped("tasks", task_id)
    if not can_touch_task(task):
        return apology(_("tasks.error_not_yours"), 403)
    if task["done_at"]:
        return back()

    db = get_db()
    db.execute("BEGIN TRANSACTION")
    try:
        db.execute("UPDATE tasks SET done_at = ? WHERE id = ? AND workspace_id = ?", now_utc(), task_id, workspace_id())
        db.execute(
            "INSERT INTO activities (workspace_id, user_id, type, body, company_id, contact_id, opportunity_id) "
            "VALUES (?, ?, 'task_done', ?, ?, ?, ?)",
            workspace_id(), g.user["id"], task["title"], task["company_id"], task["contact_id"], task["opportunity_id"],
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    flash(_("tasks.done"), "success")
    return back()


@tasks_bp.route("/tasks/<int:task_id>/reopen", methods=["POST"])
@require_role("member")
def reopen(task_id):
    task = get_scoped("tasks", task_id)
    if not can_touch_task(task):
        return apology(_("tasks.error_not_yours"), 403)
    get_db().execute("UPDATE tasks SET done_at = NULL WHERE id = ? AND workspace_id = ?", task_id, workspace_id())
    return back()


@tasks_bp.route("/tasks/<int:task_id>/delete", methods=["POST"])
@require_role("member")
def delete(task_id):
    task = get_scoped("tasks", task_id)
    if not (has_role("admin") or task["created_by"] == g.user["id"]):
        return apology(_("tasks.error_not_yours"), 403)
    get_db().execute("DELETE FROM tasks WHERE id = ? AND workspace_id = ?", task_id, workspace_id())
    flash(_("tasks.deleted"), "success")
    return back()


# ---------------------------------------------------------------------------
# EN: Manual history entries
# PT: Registros manuais no histórico
# ---------------------------------------------------------------------------

@tasks_bp.route("/activities", methods=["POST"])
@require_role("member")
def add_entry():
    """EN: Add a note, a call or a WhatsApp conversation to the history.
    PT: Adiciona uma nota, uma ligação ou uma conversa de WhatsApp ao histórico.
    """
    kind = request.form.get("type", "note")
    body = request.form.get("body", "").strip()
    if kind not in MANUAL_TYPES:
        flash(_("tasks.error_type"), "danger")
        return back("/customers")
    if not 1 <= len(body) <= BODY_MAX:
        flash(_("tasks.error_body"), "danger")
        return back("/customers")
    links, error = read_links()
    if error:
        flash(_(error), "danger")
        return back("/customers")

    get_db().execute(
        "INSERT INTO activities (workspace_id, user_id, type, body, company_id, contact_id, opportunity_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        workspace_id(), g.user["id"], kind, body, links["company_id"], links["contact_id"], links["opportunity_id"],
    )
    flash(_("tasks.entry_added"), "success")
    return back("/customers")


@tasks_bp.route("/activities/<int:activity_id>/delete", methods=["POST"])
@require_role("member")
def delete_entry(activity_id):
    """EN: Delete a manual entry (author or admin). System lines can never be deleted.
    PT: Apaga um registro manual (autor ou admin). Linhas do sistema nunca podem ser apagadas.
    """
    entry = get_scoped("activities", activity_id)
    if entry["type"] not in MANUAL_TYPES:
        return apology(_("tasks.error_system_line"), 403)
    if not (has_role("admin") or entry["user_id"] == g.user["id"]):
        return apology(_("tasks.error_not_yours"), 403)
    get_db().execute("DELETE FROM activities WHERE id = ? AND workspace_id = ?", activity_id, workspace_id())
    flash(_("tasks.entry_deleted"), "success")
    return back("/customers")
