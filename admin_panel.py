"""
EN: Platform panel (/platform), only for the SupplyFlow operator (users.is_platform_admin = 1).
    It lists every workspace with its plan, price and usage, and lets the operator change the
    plan and the negotiated price after talking to the customer on WhatsApp.
    Rules (ARCHITECTURE.md §3 and §9):
    * the flag is turned on only from the terminal (`flask make-admin <email>` in app.py)
    * the panel never opens business data (customers, quotes, prices of products...): it only
      shows counts, the owners' contact and the plan
    * anyone else gets a 404, so the panel doesn't even reveal that it exists
    * changing to a smaller plan deletes nothing; the panel just warns what is over the limit
PT: Painel da plataforma (/platform), só para quem opera o SupplyFlow (users.is_platform_admin = 1).
    Lista todas as distribuidoras com plano, preço e uso, e permite trocar o plano e o preço
    negociado depois de conversar com o cliente no WhatsApp.
    Regras (ARCHITECTURE.md §3 e §9):
    * a flag só é ligada pelo terminal (`flask make-admin <email>` no app.py)
    * o painel nunca abre dados de negócio (clientes, orçamentos, preços de produtos...): só
      mostra contagens, o contato dos donos e o plano
    * qualquer outra pessoa recebe 404, então o painel nem revela que existe
    * trocar para um plano menor não apaga nada; o painel só avisa o que passou do limite
"""

from functools import wraps

from flask import Blueprint, abort, flash, g, redirect, render_template, request

from database import get_db
from helpers import escape_like, money_input, normalize_cnpj, now_utc, parse_money
from permissions import quota_usage
from translations import _

admin_bp = Blueprint("platform", __name__)

# EN: Quotas shown per workspace | PT: Cotas mostradas por distribuidora
QUOTAS = ("users", "customers", "products", "quotes_month")


def platform_admin_required(f):
    """EN: Only platform admins get through; everyone else (even logged out) sees a 404.
        The flag is re-read from the database on every request (g.user), so turning it off
        in the terminal works right away.
    PT: Só admins da plataforma passam; qualquer outro (mesmo deslogado) vê um 404.
        A flag é relida do banco a cada requisição (g.user), então desligar pelo terminal
        vale na hora.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if g.get("user") is None or g.user["is_platform_admin"] != 1:
            abort(404)
        return f(*args, **kwargs)
    return decorated_function


def workspace_rows(search=""):
    """EN: Every workspace with plan, owners' contact and usage, newest first.
    PT: Todas as distribuidoras com plano, contato dos donos e uso, mais novas primeiro.
    """
    sql = (
        "SELECT w.id AS workspace_id, w.name AS workspace_name, w.custom_price_cents, w.plan_started_at, w.cnpj AS workspace_cnpj, "
        "w.created_at, p.*, p.name AS plan_name, "
        "(SELECT group_concat(u.name || ' <' || u.email || '>', ', ') FROM memberships m "
        " JOIN users u ON u.id = m.user_id WHERE m.workspace_id = w.id AND m.role = 'owner') AS owners, "
        "(SELECT COUNT(*) FROM customer_users cu WHERE cu.workspace_id = w.id) AS buyers, "
        "(SELECT COUNT(*) FROM users r WHERE r.referred_by_workspace_id = w.id) AS referred "
        "FROM workspaces w JOIN plans p ON p.id = w.plan_id"
    )
    params = []
    if search:
        sql += " WHERE w.name LIKE ? ESCAPE '!'"
        params.append("%" + escape_like(search) + "%")
    rows = get_db().execute(sql + " ORDER BY w.created_at DESC, w.id DESC", *params)

    for row in rows:
        row["usage"] = []
        for resource in QUOTAS:
            used, limit = quota_usage(resource, row)
            row["usage"].append({"resource": resource, "used": used, "limit": limit,
                                 "over": limit is not None and used > limit})
        row["price_cents"] = row["custom_price_cents"] if row["custom_price_cents"] is not None else row["price_cents"]
    return rows


@admin_bp.route("/platform")
@platform_admin_required
def index():
    """EN: Totals, workspaces per plan and the list of workspaces (with a name search).
    PT: Totais, distribuidoras por plano e a lista de distribuidoras (com busca por nome).
    """
    db = get_db()
    search = request.args.get("q", "").strip()[:80]
    totals = {
        "workspaces": db.execute("SELECT COUNT(*) AS n FROM workspaces")[0]["n"],
        "staff": db.execute("SELECT COUNT(DISTINCT user_id) AS n FROM memberships")[0]["n"],
        "buyers": db.execute("SELECT COUNT(DISTINCT user_id) AS n FROM customer_users")[0]["n"],
    }
    per_plan = db.execute(
        "SELECT p.code, p.name, p.price_cents, COUNT(w.id) AS n FROM plans p "
        "LEFT JOIN workspaces w ON w.plan_id = p.id GROUP BY p.id ORDER BY p.position"
    )
    plans = db.execute("SELECT id, code, name, price_cents FROM plans ORDER BY position")
    return render_template("platform.html", totals=totals, per_plan=per_plan, plans=plans,
                           workspaces=workspace_rows(search), search=search, money_input=money_input)


@admin_bp.route("/platform/workspaces/<int:ws_id>", methods=["POST"])
@platform_admin_required
def update(ws_id):
    """EN: Change a workspace's plan and/or negotiated price (blank price = list price).
        plan_started_at only moves when the plan really changes.
    PT: Troca o plano e/ou o preço negociado de uma distribuidora (preço vazio = preço de tabela).
        plan_started_at só muda quando o plano muda de verdade.
    """
    db = get_db()
    rows = db.execute("SELECT id, name, plan_id FROM workspaces WHERE id = ?", ws_id)
    if not rows:
        abort(404)
    workspace = rows[0]

    plan = db.execute("SELECT id, name FROM plans WHERE code = ?", request.form.get("plan", ""))
    if not plan:
        flash(_("platform.error_plan"), "danger")
        return redirect("/platform")
    plan = plan[0]

    raw_price = request.form.get("custom_price", "").strip()
    price = None
    if raw_price:
        price = parse_money(raw_price)
        if price is None:
            flash(_("platform.error_price"), "danger")
            return redirect("/platform")

    if plan["id"] != workspace["plan_id"]:
        db.execute("UPDATE workspaces SET plan_id = ?, custom_price_cents = ?, plan_started_at = ? WHERE id = ?",
                   plan["id"], price, now_utc(), ws_id)
    else:
        db.execute("UPDATE workspaces SET custom_price_cents = ? WHERE id = ?", price, ws_id)
    flash(_("platform.saved").replace("{workspace}", workspace["name"]).replace("{plan}", plan["name"]), "success")
    return redirect("/platform")


@admin_bp.route("/platform/workspaces/<int:ws_id>/identity", methods=["POST"])
@platform_admin_required
def identity(ws_id):
    """EN: Change a distributor's name and CNPJ. Only support does this (the owner can't),
        because both identify the company on every quote sent to customers.
        A blank CNPJ clears it; a filled one must be valid and not used by another distributor.
    PT: Troca o nome e o CNPJ de uma distribuidora. Só o suporte faz isso (o dono não),
        porque os dois identificam a empresa em todo orçamento enviado aos clientes.
        CNPJ vazio limpa; preenchido precisa ser válido e não usado por outra distribuidora.
    """
    db = get_db()
    if not db.execute("SELECT 1 FROM workspaces WHERE id = ?", ws_id):
        abort(404)
    name = request.form.get("name", "").strip()
    raw_cnpj = request.form.get("cnpj", "").strip()
    if not 2 <= len(name) <= 100:
        flash(_("register.error_workspace"), "danger")
        return redirect("/platform")
    cnpj = None
    if raw_cnpj:
        cnpj = normalize_cnpj(raw_cnpj)
        if cnpj is None:
            flash(_("customers.error_cnpj"), "danger")
            return redirect("/platform")
        if db.execute("SELECT 1 FROM workspaces WHERE cnpj = ? AND id <> ?", cnpj, ws_id):
            flash(_("settings.error_cnpj_taken"), "danger")
            return redirect("/platform")
    db.execute("UPDATE workspaces SET name = ?, cnpj = ? WHERE id = ?", name, cnpj, ws_id)
    flash(_("platform.identity_saved").replace("{workspace}", name), "success")
    return redirect("/platform")
