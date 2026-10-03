"""
EN: Repurchase alerts (ARCHITECTURE.md §6.7). A customer with at least 3 accepted orders
    has a normal rhythm (the average interval between them). When the days since the last
    order pass 1.5 times that rhythm, the customer is "late" and shows on the dashboard.
    A new accepted order moves the "last order" date, so the alert goes away by itself.
    `alert_for` is pure (only dates in, numbers out) so it can be unit tested; the query
    lives in `workspace_alerts`.
PT: Alertas de recompra (ARCHITECTURE.md §6.7). Um cliente com pelo menos 3 pedidos aceitos
    tem um ritmo normal (o intervalo médio entre eles). Quando os dias desde o último pedido
    passam de 1,5 vez esse ritmo, o cliente está "atrasado" e aparece no painel.
    Um novo pedido aceito muda a data do "último pedido", então o alerta some sozinho.
    `alert_for` é pura (só datas entram, números saem) para poder ter teste unitário; a
    consulta fica em `workspace_alerts`.
"""

from datetime import date

from database import get_db
from pricing import round_div

# EN: Fewer orders than this = not enough history to know the rhythm
# PT: Menos pedidos que isso = histórico insuficiente para saber o ritmo
MIN_ORDERS = 3


def alert_for(order_dates, today):
    """EN: Decide the alert for one customer.
        order_dates: 'YYYY-MM-DD' strings of accepted orders (any order, repeats allowed);
        today: 'YYYY-MM-DD' in Sao Paulo.
        Returns None (no alert) or a dict with orders, average_days, days_since, late_days, last.
        Integer math only: "days_since > 1.5 x average" is written as
        2 x days_since x (orders - 1) > 3 x span, so nothing is rounded before comparing.
    PT: Decide o alerta de um cliente.
        order_dates: textos 'AAAA-MM-DD' dos pedidos aceitos (qualquer ordem, pode repetir);
        today: 'AAAA-MM-DD' em São Paulo.
        Devolve None (sem alerta) ou um dict com orders, average_days, days_since, late_days, last.
        Só contas inteiras: "dias_sem_comprar > 1,5 x média" vira
        2 x dias_sem_comprar x (pedidos - 1) > 3 x intervalo_total, então nada é arredondado antes de comparar.
    """
    days = sorted(date.fromisoformat(d) for d in order_dates)
    orders = len(days)
    if orders < MIN_ORDERS:
        return None

    # EN: span = first to last order; zero means every order fell on the same day (no rhythm)
    # PT: intervalo_total = do primeiro ao último pedido; zero = todos no mesmo dia (sem ritmo)
    span = (days[-1] - days[0]).days
    if span == 0:
        return None

    days_since = (date.fromisoformat(today) - days[-1]).days
    if 2 * days_since * (orders - 1) <= 3 * span:
        return None

    average = round_div(span, orders - 1)
    return {
        "orders": orders,
        "average_days": average,
        "days_since": days_since,
        "late_days": days_since - average,
        "last": days[-1].isoformat(),
    }


def workspace_alerts(workspace_id, today, owner_id=None):
    """EN: Late customers of one workspace, the most late first.
        owner_id limits it to one seller's customers (members see only theirs).
        Dates are the Sao Paulo day of each acceptance (UTC minus 3 hours).
    PT: Clientes atrasados de uma distribuidora, o mais atrasado primeiro.
        owner_id limita aos clientes de um vendedor (vendedores veem só os deles).
        As datas são o dia de São Paulo de cada aceite (UTC menos 3 horas).
    """
    sql = (
        "SELECT q.company_id, date(q.customer_decided_at, '-3 hours') AS day "
        "FROM quotes q JOIN companies c ON c.id = q.company_id "
        "WHERE q.workspace_id = ? AND q.status = 'accepted' AND q.customer_decided_at IS NOT NULL"
    )
    params = [workspace_id]
    if owner_id is not None:
        sql += " AND c.owner_id = ?"
        params.append(owner_id)

    by_company = {}
    for row in get_db().execute(sql, *params):
        by_company.setdefault(row["company_id"], []).append(row["day"])

    alerts = []
    for company_id, days in by_company.items():
        alert = alert_for(days, today)
        if alert is None:
            continue
        company = get_db().execute(
            "SELECT c.id, c.name, c.phone, c.city, u.name AS owner_name FROM companies c "
            "LEFT JOIN users u ON u.id = c.owner_id WHERE c.id = ? AND c.workspace_id = ?",
            company_id, workspace_id,
        )[0]
        alert.update(company)
        alerts.append(alert)

    alerts.sort(key=lambda a: (-a["late_days"], a["name"].lower()))
    return alerts
