"""
EN: Staff dashboard (the "Painel"): what is open in the funnel, what was won this month,
    quotes waiting for approval or for the customer, my tasks for today, repurchase alerts,
    plan usage and the discount ceilings.
    Registered in app.py as a Blueprint.
    Rules:
    * owner/admin see the whole workspace; a member sees only their own opportunities,
      quotes and customers
    * the period report (reports.py): sales, ticket, conversion, average discount, seller
      ranking with commission, top customers, loss reasons; filter by ?period=
    * "this month" starts at midnight in Sao Paulo (month_start_utc)
    * repurchase alerts only on plans with the feature (Profissional and Escala)
PT: Painel da equipe: o que está aberto no funil, o que foi fechado no mês, orçamentos
    esperando aprovação ou o cliente, minhas tarefas de hoje, alertas de recompra, uso do
    plano e os tetos de desconto.
    Registrado no app.py como um Blueprint.
    Regras:
    * dono/gerente veem a distribuidora toda; um vendedor vê só as oportunidades,
      orçamentos e clientes dele
    * o relatório do período (reports.py): vendas, ticket, conversão, desconto médio,
      ranking de vendedores com comissão, clientes que mais compraram, motivos de perda;
      filtro por ?period=
    * "este mês" começa à meia-noite de São Paulo (month_start_utc)
    * alertas de recompra só nos planos com o recurso (Profissional e Escala)
"""

from flask import Blueprint, g, render_template, request

from database import get_db
from helpers import month_start_utc, today_sp, whatsapp_link
from permissions import has_feature, has_role, plan_usage, require_role, workspace_id
from quotes import expire_overdue, pending_for_me
from reports import PERIODS, report, team_overdue
from repurchase import workspace_alerts
from tasks import task_query
from customers import main_contact_name
from translations import customer_text

dashboard_bp = Blueprint("dashboard", __name__)


def funnel_numbers(kind, owner_id, since=None, manual=None):
    """EN: Count and total value of opportunities in stages of one kind (open/won).
        owner_id=None means the whole workspace; since limits by closed_at (UTC text).
    PT: Quantidade e valor total das oportunidades em etapas de um tipo (open/won).
        owner_id=None = distribuidora toda; since limita pelo closed_at (texto UTC).
    """
    sql = (
        "SELECT COUNT(*) AS n, COALESCE(SUM(o.value_cents), 0) AS total FROM opportunities o "
        "JOIN stages s ON s.id = o.stage_id WHERE o.workspace_id = ? AND s.kind = ?"
    )
    params = [workspace_id(), kind]
    if owner_id is not None:
        sql += " AND o.owner_id = ?"
        params.append(owner_id)
    if since is not None:
        sql += " AND o.closed_at >= ?"
        params.append(since)
    if manual is not None:
        # EN: 0 = won through an accepted quote, 1 = marked as won by hand
        # PT: 0 = ganha por orçamento aceito, 1 = marcada como ganha à mão
        sql += " AND o.closed_manually = ?"
        params.append(manual)
    return get_db().execute(sql, *params)[0]


def quotes_in(status, created_by):
    """EN: Number of quotes in one status (only mine when created_by is given).
    PT: Número de orçamentos num estado (só os meus quando created_by vem preenchido).
    """
    sql = "SELECT COUNT(*) AS n FROM quotes WHERE workspace_id = ? AND status = ?"
    params = [workspace_id(), status]
    if created_by is not None:
        sql += " AND created_by = ?"
        params.append(created_by)
    return get_db().execute(sql, *params)[0]["n"]


def repurchase_message(name):
    """EN: Pre-filled WhatsApp message for a late customer (always Portuguese, to the contact).
    PT: Mensagem pronta de WhatsApp para um cliente atrasado (sempre em português, para o contato).
    """
    return (customer_text("dashboard.repurchase_message")
            .replace("{name}", name.split()[0])
            .replace("{user}", g.user["name"].split()[0])
            .replace("{workspace}", g.membership["workspace_name"]))


@dashboard_bp.route("/dashboard")
@require_role("member")
def index():
    """EN: Staff home with the numbers that matter today.
    PT: Início da equipe com os números que importam hoje.
    """
    # EN: overdue "sent" quotes become "expired" first, so the counts are right
    # PT: orçamentos "enviados" vencidos viram "expirados" antes, para as contagens ficarem certas
    expire_overdue()
    manager = has_role("admin")
    # EN: None = no filter (whole workspace) | PT: None = sem filtro (distribuidora toda)
    mine = None if manager else g.user["id"]
    today = today_sp()

    open_deals = funnel_numbers("open", mine)
    won_month = funnel_numbers("won", mine, since=month_start_utc(), manual=0)
    won_manual = funnel_numbers("won", mine, since=month_start_utc(), manual=1)
    waiting_approval = len(pending_for_me()) if manager else quotes_in("pending_approval", mine)
    waiting_customer = quotes_in("sent", mine)

    # EN: my overdue + today tasks, most urgent first (same rule as the menu badge)
    # PT: minhas tarefas atrasadas + de hoje, a mais urgente primeiro (mesma regra do contador do menu)
    tasks = task_query("t.done_at IS NULL AND t.assignee_id = ? AND t.due_date IS NOT NULL AND t.due_date <= ?",
                       g.user["id"], today)
    for task in tasks:
        task["bucket"] = "overdue" if task["due_date"] < today else "today"

    # EN: the period report (?period=month|last_month|90d); anything else falls back to this month
    # PT: o relatório do período (?period=month|last_month|90d); qualquer outra coisa vira este mês
    period = request.args.get("period", "month")
    if period not in PERIODS:
        period = "month"
    sales_report = report(workspace_id(), period, owner_id=mine)
    my_commission = g.membership["commission_bps"]

    alerts = None
    if has_feature("repurchase_alert"):
        alerts = workspace_alerts(workspace_id(), today, owner_id=mine)
        for alert in alerts:
            alert["whatsapp"] = whatsapp_link(alert["phone"], repurchase_message(main_contact_name(alert))) if alert["phone"] else None

    return render_template(
        "dashboard.html",
        ws=g.membership,
        manager=manager,
        today=today,
        open_deals=open_deals,
        won_month=won_month,
        won_manual=won_manual,
        waiting_approval=waiting_approval,
        waiting_customer=waiting_customer,
        tasks=tasks,
        alerts=alerts,
        usage=plan_usage() if manager else None,
        report=sales_report,
        periods=PERIODS,
        my_commission=my_commission,
        overdue=team_overdue(workspace_id(), today) if manager else None,
    )
