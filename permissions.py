"""EN: Multi-tenant security: who is in which workspace, with which role, and what the
    workspace's plan allows. Every business route depends on the functions below.
PT: Segurança multi-tenant: quem está em qual distribuidora, com qual cargo, e o que o
    plano da distribuidora permite. Toda rota de negócio depende das funções abaixo.

EN: The four rules of this file:
    1. The active workspace comes from the session, but membership and role are
       re-read from the database on every request.
    2. Records are always fetched with "AND workspace_id = ?" (get_scoped).
    3. A record from another workspace answers 404, never 403, so nobody can even
       confirm that it exists.
    4. Plan limits are enforced here, on the server, before anything is created.
PT: As quatro regras deste arquivo:
    1. A distribuidora ativa vem da sessão, mas o vínculo e o cargo são relidos do
       banco a cada requisição.
    2. Registros são sempre buscados com "AND workspace_id = ?" (get_scoped).
    3. Registro de outra distribuidora responde 404, nunca 403, para ninguém sequer
       confirmar que ele existe.
    4. Os limites do plano são aplicados aqui, no servidor, antes de criar qualquer coisa.
"""

from functools import wraps

from flask import abort, g, redirect, request, session, url_for

from database import get_db
from helpers import month_start_utc, now_utc

# EN: Higher number = more power | PT: Número maior = mais poder
ROLE_RANK = {"member": 1, "admin": 2, "owner": 3}

# EN: Tables that get_scoped() may read. A table name can't be a "?" parameter in SQL,
#     so only names from this fixed list are ever put into a query (never user input).
# PT: Tabelas que o get_scoped() pode ler. Nome de tabela não pode ser parâmetro "?" no SQL,
#     então só nomes desta lista fixa entram numa consulta (nunca entrada do usuário).
SCOPED_TABLES = {
    "activities", "companies", "contacts", "customer_users", "discount_requests", "invites",
    "opportunities", "pipelines", "products", "quotes", "stages", "tasks",
}

# EN: Plan features that has_feature() understands (column = "feat_" + name)
# PT: Recursos do plano que o has_feature() entende (coluna = "feat_" + nome)
FEATURES = {"discount_approval", "min_margin", "repurchase_alert", "csv_export", "multi_pipeline", "portal_full"}


# ---------------------------------------------------------------------------
# EN: Loading the membership
# PT: Carregando o vínculo
# ---------------------------------------------------------------------------

def load_membership(user_id):
    """EN: Fill g.membership with the user's role, workspace and plan (or None for buyers).
        If the workspace in the session is no longer valid (the user was removed),
        fall back to another workspace of the same user.
    PT: Preenche g.membership com cargo, distribuidora e plano do usuário (ou None para
        compradores). Se a distribuidora da sessão não vale mais (o usuário foi removido),
        cai para outra distribuidora do mesmo usuário.
    """
    db = get_db()
    query = """
        SELECT m.role, m.commission_bps, w.id AS workspace_id, w.name AS workspace_name, w.onboarding_done,
               w.member_discount_limit_bps, w.admin_discount_limit_bps, w.min_margin_bps,
               w.custom_price_cents, w.cnpj AS workspace_cnpj, w.logo_path AS workspace_logo,
               p.*, p.id AS plan_id, p.name AS plan_name
          FROM memberships m
          JOIN workspaces w ON w.id = m.workspace_id
          JOIN plans p ON p.id = w.plan_id
         WHERE m.user_id = ?
    """
    rows = []
    if session.get("workspace_id"):
        rows = db.execute(query + " AND m.workspace_id = ?", user_id, session["workspace_id"])
    if not rows:
        rows = db.execute(query + " ORDER BY m.created_at, m.id LIMIT 1", user_id)

    g.membership = rows[0] if rows else None
    if g.membership:
        session["workspace_id"] = g.membership["workspace_id"]
    else:
        session.pop("workspace_id", None)


def user_workspaces(user_id):
    """EN: All workspaces of a user, for the workspace switcher.
    PT: Todas as distribuidoras de um usuário, para o seletor de distribuidora.
    """
    return get_db().execute(
        """
        SELECT w.id, w.name, m.role
          FROM memberships m JOIN workspaces w ON w.id = m.workspace_id
         WHERE m.user_id = ?
         ORDER BY w.name
        """,
        user_id,
    )


def workspace_id():
    """EN: Id of the active workspace. Only call inside routes protected by require_role.
    PT: Id da distribuidora ativa. Só chame dentro de rotas protegidas por require_role.
    """
    return g.membership["workspace_id"]


# ---------------------------------------------------------------------------
# EN: Roles
# PT: Cargos
# ---------------------------------------------------------------------------

def has_role(minimum):
    """EN: True when the user's role in the active workspace is at least `minimum`.
    PT: Verdadeiro quando o cargo do usuário na distribuidora ativa é pelo menos `minimum`.
    """
    membership = g.get("membership")
    return membership is not None and ROLE_RANK[membership["role"]] >= ROLE_RANK[minimum]


def require_role(minimum="member"):
    """EN: Route decorator: requires login, a workspace and at least this role.
        Not logged in -> login page. Buyer without workspace -> portal. Low role -> 403.
    PT: Decorator de rota: exige login, uma distribuidora e pelo menos este cargo.
        Sem login -> página de login. Comprador sem distribuidora -> portal. Cargo baixo -> 403.

    @app.route("/settings")
    @require_role("owner")
    def settings(): ...
    """
    if minimum not in ROLE_RANK:
        raise ValueError(f"Unknown role: {minimum}")

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if session.get("user_id") is None:
                return redirect(url_for("login", next=request.path))
            if g.get("membership") is None:
                return redirect("/portal")
            if not has_role(minimum):
                abort(403)
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def can_modify(record, owner_field="owner_id"):
    """EN: Owners and admins can change/delete any record of the workspace; members only
        the records they own (record[owner_field] == their user id).
    PT: Owners e admins podem mudar/apagar qualquer registro da distribuidora; members só
        os registros que são deles (record[owner_field] == id do usuário).
    """
    if has_role("admin"):
        return True
    return record.get(owner_field) == session.get("user_id")


# ---------------------------------------------------------------------------
# EN: Tenant isolation
# PT: Isolamento entre distribuidoras
# ---------------------------------------------------------------------------

def _check_table(table):
    if table not in SCOPED_TABLES:
        raise ValueError(f"Table not allowed: {table}")


def get_scoped(table, row_id):
    """EN: Fetch one row of the active workspace, or stop with 404.
        A row of another workspace is treated exactly like a row that doesn't exist.
    PT: Busca uma linha da distribuidora ativa, ou para com 404.
        Uma linha de outra distribuidora é tratada igual a uma linha que não existe.
    """
    row = find_scoped(table, row_id)
    if row is None:
        abort(404)
    return row


def find_scoped(table, row_id):
    """EN: Like get_scoped, but returns None instead of 404. Used to validate ids
        that come from forms (e.g. a company_id chosen in a <select>).
    PT: Igual ao get_scoped, mas devolve None em vez de 404. Usado para validar ids
        que vêm de formulários (ex.: um company_id escolhido num <select>).
    """
    _check_table(table)
    try:
        row_id = int(row_id)
    except (TypeError, ValueError):
        # EN: "abc", "", None or "1 OR 1=1" are simply not found
        # PT: "abc", "", None ou "1 OR 1=1" simplesmente não são encontrados
        return None
    rows = get_db().execute(f"SELECT * FROM {table} WHERE id = ? AND workspace_id = ?", row_id, workspace_id())
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# EN: Sales visibility: a seller (member) sees only their own opportunities and quotes;
#     admins and owners see everything. The customer list stays shared, so nobody
#     registers the same restaurant twice. Hidden rows answer 404, like another tenant's.
# PT: Visibilidade de vendas: um vendedor (member) vê só as oportunidades e orçamentos dele;
#     admins e owners veem tudo. A lista de clientes continua compartilhada, para ninguém
#     cadastrar o mesmo restaurante duas vezes. Linhas escondidas respondem 404, como as de
#     outra distribuidora.
# ---------------------------------------------------------------------------

def sees_all_sales():
    """EN: True for admins and owners. | PT: Verdadeiro para admins e owners."""
    return has_role("admin")


def can_see_opportunity(opportunity):
    """EN: May the current user see this opportunity (and its quotes)?
    PT: O usuário atual pode ver esta oportunidade (e os orçamentos dela)?
    """
    return sees_all_sales() or opportunity["owner_id"] == g.user["id"]


def get_visible_opportunity(opportunity_id):
    """EN: get_scoped + visibility: 404 for another seller's opportunity.
    PT: get_scoped + visibilidade: 404 para a oportunidade de outro vendedor.
    """
    opportunity = get_scoped("opportunities", opportunity_id)
    if not can_see_opportunity(opportunity):
        abort(404)
    return opportunity


def find_visible_opportunity(opportunity_id):
    """EN: Like get_visible_opportunity, but None instead of 404 (for ids sent in forms).
    PT: Igual ao get_visible_opportunity, mas None em vez de 404 (para ids vindos de formulários).
    """
    opportunity = find_scoped("opportunities", opportunity_id)
    return opportunity if opportunity and can_see_opportunity(opportunity) else None


def get_visible_quote(quote_id):
    """EN: get_scoped + visibility through the quote's opportunity.
    PT: get_scoped + visibilidade pela oportunidade do orçamento.
    """
    quote = get_scoped("quotes", quote_id)
    if not sees_all_sales():
        owner = get_db().execute("SELECT owner_id FROM opportunities WHERE id = ? AND workspace_id = ?",
                                 quote["opportunity_id"], workspace_id())
        if not owner or owner[0]["owner_id"] != g.user["id"]:
            abort(404)
    return quote


def own_sales_filter(column="o.owner_id"):
    """EN: SQL piece + params that limit a query to the seller's own opportunities
        ("" and [] for admins). The column name comes from code, never from the user.
    PT: Pedaço de SQL + parâmetros que limitam uma consulta às oportunidades do vendedor
        ("" e [] para admins). O nome da coluna vem do código, nunca do usuário.
    """
    if sees_all_sales():
        return "", []
    return f" AND {column} = ?", [g.user["id"]]


def is_workspace_user(user_id):
    """EN: True when user_id is staff of the active workspace (for "responsible seller" fields).
    PT: Verdadeiro quando user_id é da equipe da distribuidora ativa (para campos "vendedor responsável").
    """
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return False
    rows = get_db().execute(
        "SELECT 1 FROM memberships WHERE user_id = ? AND workspace_id = ?", user_id, workspace_id()
    )
    return bool(rows)


# ---------------------------------------------------------------------------
# EN: Plan features and quotas
# PT: Recursos e cotas do plano
# ---------------------------------------------------------------------------

def has_feature(name):
    """EN: True when the active workspace's plan includes this feature.
    PT: Verdadeiro quando o plano da distribuidora ativa inclui este recurso.
    """
    if name not in FEATURES:
        raise ValueError(f"Unknown feature: {name}")
    membership = g.get("membership")
    return membership is not None and membership["feat_" + name] == 1


def _count(sql, *params):
    return get_db().execute(sql, *params)[0]["n"]


def workspace_plan(ws_id):
    """EN: A workspace joined with its plan, for quota checks outside the active workspace
        (e.g. accepting an invite to another distributor).
    PT: Uma distribuidora junto com o plano dela, para checar cotas fora da distribuidora
        ativa (ex.: aceitar convite de outra distribuidora).
    """
    rows = get_db().execute(
        "SELECT p.*, w.id AS workspace_id, w.name AS workspace_name "
        "FROM workspaces w JOIN plans p ON p.id = w.plan_id WHERE w.id = ?",
        ws_id,
    )
    return rows[0] if rows else None


def quota_usage(resource, plan=None):
    """EN: Return (used, limit) for a resource. limit None = unlimited.
        `plan` is a row with workspace_id and the plan columns; default = active workspace.
        Pending staff invites count as users, so nobody can invite past the limit.
    PT: Devolve (usado, limite) de um recurso. limite None = ilimitado.
        `plan` é uma linha com workspace_id e as colunas do plano; padrão = distribuidora ativa.
        Convites de equipe pendentes contam como usuários, para ninguém convidar além do limite.
    """
    plan = plan or g.membership
    ws = plan["workspace_id"]
    now = now_utc()

    # EN: Pending (not accepted, not expired) staff invites, optionally for one role
    # PT: Convites de equipe pendentes (não aceitos, não vencidos), opcionalmente de um cargo
    pending = ("SELECT COUNT(*) AS n FROM invites WHERE workspace_id = ? AND kind = 'staff' "
               "AND accepted_at IS NULL AND expires_at > ?")

    if resource == "customers":
        used = _count("SELECT COUNT(*) AS n FROM companies WHERE workspace_id = ?", ws)
        return used, plan["max_customers"]
    if resource == "products":
        used = _count("SELECT COUNT(*) AS n FROM products WHERE workspace_id = ?", ws)
        return used, plan["max_products"]
    if resource == "quotes_month":
        # EN: cancelled quotes count too: quotes are never deleted, so the quota can't be "freed"
        # PT: orçamentos cancelados também contam: não se apaga orçamento, então não dá para "liberar" cota
        used = _count("SELECT COUNT(*) AS n FROM quotes WHERE workspace_id = ? AND created_at >= ?",
                      ws, month_start_utc())
        return used, plan["max_quotes_month"]
    if resource == "users":
        used = (_count("SELECT COUNT(*) AS n FROM memberships WHERE workspace_id = ?", ws)
                + _count(pending, ws, now))
        return used, plan["max_users"]
    if resource in ("admins", "members"):
        role = resource[:-1]
        used = (_count("SELECT COUNT(*) AS n FROM memberships WHERE workspace_id = ? AND role = ?", ws, role)
                + _count(pending + " AND role = ?", ws, now, role))
        return used, plan["max_" + resource]
    if resource == "owners":
        used = _count("SELECT COUNT(*) AS n FROM memberships WHERE workspace_id = ? AND role = 'owner'", ws)
        return used, plan["max_owners"]
    raise ValueError(f"Unknown quota: {resource}")


def check_quota(resource, adding=1, plan=None):
    """EN: True when the workspace can create `adding` more items of this resource.
        Call it right before every INSERT that the plan limits.
        adding=0 checks that the current usage is still within the limit.
    PT: Verdadeiro quando a distribuidora pode criar mais `adding` itens deste recurso.
        Chame logo antes de todo INSERT que o plano limita.
        adding=0 confere se o uso atual ainda está dentro do limite.
    """
    used, limit = quota_usage(resource, plan)
    return limit is None or used + adding <= limit


def plan_usage():
    """EN: Usage of the main quotas, for the dashboard card and the plans page.
    PT: Uso das cotas principais, para o cartão do dashboard e a página de planos.
    """
    usage = []
    for resource in ("users", "customers", "products", "quotes_month"):
        used, limit = quota_usage(resource)
        percent = None if limit in (None, 0) else min(100, used * 100 // limit)
        usage.append({"resource": resource, "used": used, "limit": limit, "percent": percent})
    return usage
