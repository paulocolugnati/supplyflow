"""
EN: Plans page for the staff: the current plan (and the price negotiated with support, if
    any), usage of each quota and the four plans side by side. Changing plans in v1 is
    manual: the owner talks to support on WhatsApp and the platform admin switches the plan
    in the platform panel (admin_panel.py). No payment here (Stripe is v2).
    Registered in app.py as a Blueprint.
    For every other plan the page also warns what would go over the limit after a downgrade
    (nothing is deleted; creating new items is what gets blocked, ARCHITECTURE.md §7).
PT: Página de planos da equipe: o plano atual (e o preço negociado com o suporte, se houver),
    o uso de cada cota e os quatro planos lado a lado. Trocar de plano na v1 é manual: o dono
    fala com o suporte no WhatsApp e o admin da plataforma troca o plano no painel da
    plataforma (admin_panel.py). Sem pagamento aqui (Stripe fica para a v2).
    Registrado no app.py como um Blueprint.
    Para cada outro plano a página também avisa o que passaria do limite num downgrade
    (nada é apagado; o que fica bloqueado é criar itens novos, ARCHITECTURE.md §7).
"""

from flask import Blueprint, g, render_template

from database import get_db
from helpers import support_link
from permissions import plan_usage, quota_usage, require_role
from translations import _

plans_bp = Blueprint("plans", __name__)

# EN: Quotas compared when checking a plan change | PT: Cotas comparadas ao avaliar uma troca de plano
QUOTAS = ("users", "owners", "admins", "members", "customers", "products", "quotes_month")


def over_limits(plan):
    """EN: Quotas the active workspace would go over on this plan (empty list = fits).
    PT: Cotas que a distribuidora ativa passaria neste plano (lista vazia = cabe).
    """
    # EN: quota_usage needs the workspace id next to the plan columns
    # PT: o quota_usage precisa do id da distribuidora junto das colunas do plano
    candidate = dict(plan)
    candidate["workspace_id"] = g.membership["workspace_id"]
    over = []
    for resource in QUOTAS:
        used, limit = quota_usage(resource, candidate)
        if limit is not None and used > limit:
            over.append({"resource": resource, "used": used, "limit": limit})
    return over


def change_message(plan_name):
    """EN: Pre-filled WhatsApp message to support asking for a plan change.
    PT: Mensagem pronta de WhatsApp para o suporte pedindo troca de plano.
    """
    return (_("plans.change_message")
            .replace("{user}", g.user["name"])
            .replace("{workspace}", g.membership["workspace_name"])
            .replace("{current}", g.membership["plan_name"])
            .replace("{target}", plan_name))


@plans_bp.route("/plans")
@require_role("member")
def index():
    """EN: Current plan, usage and every plan. Only the owner gets "ask for this plan" links.
    PT: Plano atual, uso e todos os planos. Só o dono recebe os links "pedir este plano".
    """
    workspace = get_db().execute(
        "SELECT custom_price_cents, plan_started_at FROM workspaces WHERE id = ?", g.membership["workspace_id"]
    )[0]
    plans = get_db().execute("SELECT * FROM plans ORDER BY position")
    owner = g.membership["role"] == "owner"
    for plan in plans:
        plan["current"] = plan["code"] == g.membership["code"]
        plan["over"] = [] if plan["current"] else over_limits(plan)
        plan["ask"] = support_link(change_message(plan["name"])) if owner and not plan["current"] else None

    return render_template(
        "plans.html",
        ws=g.membership,
        workspace=workspace,
        plans=plans,
        usage=plan_usage(),
        support=support_link(_("plans.support_message")
                             .replace("{workspace}", g.membership["workspace_name"])
                             .replace("{current}", g.membership["plan_name"])),
    )
