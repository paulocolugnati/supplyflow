"""
EN: Sales report of a period, for the dashboard: totals, ticket, conversion, average discount,
    seller ranking with commission, top customers, loss reasons and the team's overdue tasks.
    Definitions (also in docs/ARCHITECTURE.md §6.12):
    * a sale = a quote accepted by the buyer in the period (customer_decided_at), plus the
      manual wins closed in the period (closed_manually = 1, value of the opportunity)
    * a sale belongs to the seller responsible for the opportunity (opportunities.owner_id)
    * ticket = sold / number of sales
    * conversion = quotes sent in the period that were accepted / quotes sent in the period
    * average discount = (list total - final total) / list total of the accepted quotes,
      weighted by value (a big order counts more than a small one)
    * commission = sales of the seller x their commission % (memberships.commission_bps)
    Integer math only (cents and basis points), rounding like pricing.py.
    Periods use the Sao Paulo calendar: "this month", "last month", "last 90 days".
PT: Relatório de vendas de um período, para o painel: totais, ticket, conversão, desconto
    médio, ranking de vendedores com comissão, clientes que mais compraram, motivos de perda e
    as tarefas atrasadas da equipe.
    Definições (também em docs/ARCHITECTURE.md §6.12):
    * uma venda = um orçamento aceito pelo comprador no período (customer_decided_at), mais
      os ganhos manuais fechados no período (closed_manually = 1, valor da oportunidade)
    * a venda é do vendedor responsável pela oportunidade (opportunities.owner_id)
    * ticket = vendido / número de vendas
    * conversão = orçamentos enviados no período que foram aceitos / enviados no período
    * desconto médio = (total de tabela - total final) / total de tabela dos orçamentos
      aceitos, ponderado pelo valor (um pedido grande pesa mais que um pequeno)
    * comissão = vendas do vendedor x o % de comissão dele (memberships.commission_bps)
    Só contas com inteiros (centavos e basis points), arredondando como o pricing.py.
    Os períodos usam o calendário de São Paulo: "este mês", "mês passado", "últimos 90 dias".
"""

from datetime import datetime, timedelta, timezone

from database import get_db
from helpers import SAO_PAULO
from pricing import round_div

PERIODS = ("month", "last_month", "90d")
TOP_CUSTOMERS = 8


def to_utc(moment):
    """EN: A Sao Paulo datetime as the database's UTC text. | PT: Um horário de São Paulo como texto UTC do banco."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def period_range(code, now=None):
    """EN: (start, end) in UTC text for a period code; end None = until now. Unknown codes
        fall back to "month". `now` is a Sao Paulo datetime (only tests pass it).
    PT: (início, fim) em texto UTC para um código de período; fim None = até agora. Códigos
        desconhecidos viram "month". `now` é um horário de São Paulo (só os testes passam).
    """
    now = now or datetime.now(SAO_PAULO)
    this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if code == "last_month":
        previous = (this_month - timedelta(days=1)).replace(day=1)
        return to_utc(previous), to_utc(this_month)
    if code == "90d":
        start = (now - timedelta(days=90)).replace(hour=0, minute=0, second=0, microsecond=0)
        return to_utc(start), None
    return to_utc(this_month), None


def between(column, start, end):
    """EN: SQL piece + params for "column inside the period". The column name comes from code.
    PT: Pedaço de SQL + parâmetros para "coluna dentro do período". O nome da coluna vem do código.
    """
    if end is None:
        return f" AND {column} >= ?", [start]
    return f" AND {column} >= ? AND {column} < ?", [start, end]


def sales(workspace_id, start, end, owner_id=None):
    """EN: Every sale of the period (accepted quotes + manual wins), one dict per sale.
    PT: Todas as vendas do período (orçamentos aceitos + ganhos manuais), um dict por venda.
    """
    db = get_db()
    mine = " AND o.owner_id = ?" if owner_id else ""
    mine_params = [owner_id] if owner_id else []

    period_sql, period_params = between("q.customer_decided_at", start, end)
    accepted = db.execute(
        "SELECT o.owner_id, q.company_id, q.final_total_cents AS total, q.list_total_cents AS list, "
        "q.customer_decided_at AS at, 0 AS manual FROM quotes q JOIN opportunities o ON o.id = q.opportunity_id "
        "WHERE q.workspace_id = ? AND q.status = 'accepted'" + period_sql + mine,
        workspace_id, *period_params, *mine_params,
    )
    period_sql, period_params = between("o.closed_at", start, end)
    manual = db.execute(
        "SELECT o.owner_id, o.company_id, o.value_cents AS total, NULL AS list, o.closed_at AS at, 1 AS manual "
        "FROM opportunities o JOIN stages s ON s.id = o.stage_id "
        "WHERE o.workspace_id = ? AND s.kind = 'won' AND o.closed_manually = 1" + period_sql + mine,
        workspace_id, *period_params, *mine_params,
    )
    return accepted + manual


def list_of(row):
    """EN: List total of a sale (an accepted quote always has one; fall back to the final total).
    PT: Total de tabela de uma venda (orçamento aceito sempre tem; senão usa o total final).
    """
    return row["list"] if row["list"] is not None else row["total"]


def summarize(rows, sent, sent_accepted):
    """EN: Period totals from the sales rows (pure: no database).
        sent / sent_accepted: quotes sent in the period, and how many of those were accepted.
    PT: Totais do período a partir das vendas (pura: sem banco).
        sent / sent_accepted: orçamentos enviados no período, e quantos deles foram aceitos.
    """
    sold = sum(r["total"] for r in rows)
    orders = len(rows)
    quotes = [r for r in rows if not r["manual"]]
    list_total = sum(list_of(r) for r in quotes)
    final_total = sum(r["total"] for r in quotes)
    return {
        "sold": sold,
        "orders": orders,
        "manual": sum(r["total"] for r in rows if r["manual"]),
        "ticket": round_div(sold, orders) if orders else 0,
        "avg_discount_bps": round_div((list_total - final_total) * 10000, list_total) if list_total else None,
        "sent": sent,
        "conversion_bps": round_div(sent_accepted * 10000, sent) if sent else None,
    }


def by_seller(rows, people):
    """EN: Ranking of sellers by value sold, with commission. `people` maps user id ->
        {"name", "commission_bps"}. Sales with no responsible seller are grouped apart.
    PT: Ranking de vendedores pelo valor vendido, com comissão. `people` liga id do usuário ->
        {"name", "commission_bps"}. Vendas sem vendedor responsável ficam num grupo à parte.
    """
    groups = {}
    for r in rows:
        group = groups.setdefault(r["owner_id"], {"user_id": r["owner_id"], "sold": 0, "orders": 0, "list": 0, "final": 0, "manual": 0})
        group["sold"] += r["total"]
        group["orders"] += 1
        if r["manual"]:
            group["manual"] += r["total"]
        else:
            group["list"] += list_of(r)
            group["final"] += r["total"]
    ranking = []
    for group in groups.values():
        person = people.get(group["user_id"], {"name": None, "commission_bps": 0})
        group["name"] = person["name"]
        group["commission_bps"] = person["commission_bps"]
        group["commission"] = round_div(group["sold"] * person["commission_bps"], 10000)
        group["ticket"] = round_div(group["sold"], group["orders"])
        group["avg_discount_bps"] = round_div((group["list"] - group["final"]) * 10000, group["list"]) if group["list"] else None
        ranking.append(group)
    ranking.sort(key=lambda g: (-g["sold"], g["name"] or "~"))
    top = ranking[0]["sold"] if ranking else 0
    for group in ranking:
        # EN: bar length relative to the best seller (0..1, for CSS) | PT: tamanho da barra relativo ao melhor (0..1, para o CSS)
        group["share"] = round(group["sold"] / top, 3) if top else 0
    return ranking


def by_customer(rows, names):
    """EN: Customers that bought the most in the period (value), with orders and last purchase.
    PT: Clientes que mais compraram no período (valor), com pedidos e última compra.
    """
    groups = {}
    for r in rows:
        group = groups.setdefault(r["company_id"], {"company_id": r["company_id"], "total": 0, "orders": 0, "last": ""})
        group["total"] += r["total"]
        group["orders"] += 1
        group["last"] = max(group["last"], r["at"] or "")
    ranking = sorted(groups.values(), key=lambda g: -g["total"])[:TOP_CUSTOMERS]
    top = ranking[0]["total"] if ranking else 0
    for group in ranking:
        group["name"] = names.get(group["company_id"], "—")
        group["share"] = round(group["total"] / top, 3) if top else 0
    return ranking


def report(workspace_id, period, owner_id=None):
    """EN: Everything the dashboard shows for a period. owner_id limits it to one seller.
    PT: Tudo o que o painel mostra de um período. owner_id limita a um vendedor.
    """
    db = get_db()
    start, end = period_range(period)
    rows = sales(workspace_id, start, end, owner_id)

    mine = " AND o.owner_id = ?" if owner_id else ""
    mine_params = [owner_id] if owner_id else []
    period_sql, period_params = between("q.sent_at", start, end)
    sent = db.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(q.status = 'accepted'), 0) AS accepted FROM quotes q "
        "JOIN opportunities o ON o.id = q.opportunity_id WHERE q.workspace_id = ? AND q.sent_at IS NOT NULL"
        + period_sql + mine, workspace_id, *period_params, *mine_params,
    )[0]

    people = {r["id"]: {"name": r["name"], "commission_bps": r["commission_bps"] or 0} for r in db.execute(
        "SELECT u.id, u.name, m.commission_bps FROM users u "
        "LEFT JOIN memberships m ON m.user_id = u.id AND m.workspace_id = ? "
        "WHERE u.id IN (SELECT DISTINCT owner_id FROM opportunities WHERE workspace_id = ? AND owner_id IS NOT NULL)",
        workspace_id, workspace_id)}
    names = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM companies WHERE workspace_id = ?", workspace_id)}

    period_sql, period_params = between("o.closed_at", start, end)
    losses = db.execute(
        "SELECT MIN(TRIM(o.lost_reason)) AS reason, COUNT(*) AS n, COALESCE(SUM(o.value_cents), 0) AS total "
        "FROM opportunities o JOIN stages s ON s.id = o.stage_id WHERE o.workspace_id = ? AND s.kind = 'lost'"
        + period_sql + mine + " GROUP BY LOWER(TRIM(COALESCE(o.lost_reason, ''))) ORDER BY n DESC, total DESC LIMIT 6",
        workspace_id, *period_params, *mine_params,
    )
    lost_most = losses[0]["n"] if losses else 0
    for loss in losses:
        loss["share"] = round(loss["n"] / lost_most, 3) if lost_most else 0

    return {
        "period": period,
        "totals": summarize(rows, sent["n"], sent["accepted"]),
        "sellers": by_seller(rows, people),
        "customers": by_customer(rows, names),
        "losses": losses,
    }


def team_overdue(workspace_id, today):
    """EN: Overdue open tasks per person (for managers), the most behind first.
    PT: Tarefas abertas atrasadas por pessoa (para gerentes), quem está mais atrasado primeiro.
    """
    return get_db().execute(
        "SELECT u.name, COUNT(*) AS n, MIN(t.due_date) AS oldest FROM tasks t JOIN users u ON u.id = t.assignee_id "
        "WHERE t.workspace_id = ? AND t.done_at IS NULL AND t.due_date IS NOT NULL AND t.due_date < ? "
        "GROUP BY t.assignee_id ORDER BY n DESC, oldest",
        workspace_id, today,
    )
