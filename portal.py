"""EN: Buyer portal: one account sees the quotes of every distributor that invited it, and
    accepts or declines them. Registered in app.py as a Blueprint.
PT: Portal do comprador: uma conta vê os orçamentos de todas as distribuidoras que a
    convidaram, e aceita ou recusa. Registrado no app.py como um Blueprint.

EN: Security model (docs/ARCHITECTURE.md, section 6.6). The portal does NOT use the staff
    "active workspace". Every query starts from customer_users (this user's links), so a
    buyer can only ever reach quotes of customers they were invited to. Buyers see:
    product, quantity, list price, discount and totals. Never: cost, margin, internal notes,
    discount requests, drafts, or other customers.
PT: Modelo de segurança (docs/ARCHITECTURE.md, seção 6.6). O portal NÃO usa a "distribuidora
    ativa" da equipe. Toda consulta parte de customer_users (os vínculos deste usuário), então
    um comprador só alcança orçamentos de clientes para os quais foi convidado. O comprador vê:
    produto, quantidade, preço de tabela, desconto e totais. Nunca: custo, margem, notas
    internas, pedidos de desconto, rascunhos ou outros clientes.
"""

from datetime import date

from flask import Blueprint, abort, flash, g, redirect, render_template, request

from approval import TransitionError, transition
from database import get_db
from documents import quote_document
from helpers import login_required, now_utc, today_sp, whatsapp_link
from translations import _, customer_text

portal_bp = Blueprint("portal", __name__)

# EN: Statuses a buyer may ever see (drafts and internal steps stay inside the distributor)
# PT: Status que um comprador pode ver (rascunhos e etapas internas ficam dentro da distribuidora)
OPEN_STATUSES = ("sent",)
HISTORY_STATUSES = ("accepted", "declined", "expired")
REASON_MAX = 300


def my_links():
    """EN: Customers this account is linked to, with their distributor and plan feature.
    PT: Clientes aos quais esta conta está ligada, com a distribuidora e o recurso do plano.
    """
    return get_db().execute(
        "SELECT cu.company_id, cu.workspace_id, c.name AS company_name, w.name AS workspace_name, "
        "w.logo_path AS workspace_logo, w.phone AS workspace_phone, "
        "p.feat_portal_full FROM customer_users cu JOIN companies c ON c.id = cu.company_id "
        "JOIN workspaces w ON w.id = cu.workspace_id JOIN plans p ON p.id = w.plan_id "
        "WHERE cu.user_id = ? ORDER BY w.name, c.name",
        g.user["id"],
    )


def expire_for(company_ids):
    """EN: Lazy expiry, same rule as quotes.expire_overdue, for the buyer's customers.
    PT: Vencimento sob demanda, mesma regra do quotes.expire_overdue, para os clientes do comprador.
    """
    for company_id in company_ids:
        get_db().execute(
            "UPDATE quotes SET status = 'expired', updated_at = ? WHERE company_id = ? AND status = 'sent' AND valid_until < ?",
            now_utc(), company_id, today_sp(),
        )


def visible_statuses(full):
    return OPEN_STATUSES + (HISTORY_STATUSES if full else ())


def days_left(valid_until):
    """EN: Whole days from today (Sao Paulo) until the quote's last valid day (0 = today).
    PT: Dias inteiros de hoje (São Paulo) até o último dia de validade (0 = hoje).
    """
    return (date.fromisoformat(valid_until) - date.fromisoformat(today_sp())).days


def items_summary(quote_id):
    """EN: The first product names of a quote and how many items it has, for the quote card.
        Only the product name, never cost or margin.
    PT: Os primeiros nomes de produto de um orçamento e quantos itens ele tem, para o cartão.
        Só o nome do produto, nunca custo ou margem.
    """
    rows = get_db().execute("SELECT product_name FROM quote_items WHERE quote_id = ? ORDER BY id", quote_id)
    return {"names": [r["product_name"] for r in rows[:2]], "more": max(len(rows) - 2, 0), "count": len(rows)}


def distributor_whatsapp(phone, customer_name, number=None):
    """EN: WhatsApp link from the buyer to the distributor (always Portuguese), or None.
    PT: Link de WhatsApp do comprador para a distribuidora (sempre em português), ou None.
    """
    if not phone:
        return None
    key = "portal.whatsapp_about_quote" if number else "portal.whatsapp_hello"
    message = (customer_text(key).replace("{name}", g.user["name"].split()[0])
               .replace("{customer}", customer_name).replace("{number}", f"#{number:04d}" if number else ""))
    return whatsapp_link(phone, message)


def load_quote(quote_id):
    """EN: A quote this buyer may see, with its distributor and plan feature, or 404.
        A quote of another customer and a quote in a hidden status look exactly the same.
    PT: Um orçamento que este comprador pode ver, com a distribuidora e o recurso do plano,
        ou 404. Orçamento de outro cliente e orçamento num status escondido parecem iguais.
    """
    rows = get_db().execute(
        "SELECT q.*, c.name AS company_name, w.name AS workspace_name, w.logo_path AS workspace_logo, p.feat_portal_full "
        "FROM quotes q JOIN customer_users cu ON cu.company_id = q.company_id AND cu.workspace_id = q.workspace_id "
        "JOIN companies c ON c.id = q.company_id JOIN workspaces w ON w.id = q.workspace_id "
        "JOIN plans p ON p.id = w.plan_id WHERE q.id = ? AND cu.user_id = ?",
        quote_id, g.user["id"],
    )
    if not rows:
        abort(404)
    quote = rows[0]
    expire_for([quote["company_id"]])
    quote["status"] = get_db().execute("SELECT status FROM quotes WHERE id = ?", quote_id)[0]["status"]
    if quote["status"] not in visible_statuses(quote["feat_portal_full"]):
        abort(404)
    return quote


def log_buyer(kind, body, quote):
    """EN: History line written by the buyer, inside the distributor's workspace.
    PT: Linha de histórico escrita pelo comprador, dentro da distribuidora.
    """
    get_db().execute(
        "INSERT INTO activities (workspace_id, user_id, type, body, company_id, opportunity_id, quote_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        quote["workspace_id"], g.user["id"], kind, body, quote["company_id"], quote["opportunity_id"], quote["id"],
    )


# ---------------------------------------------------------------------------
# EN: Pages
# PT: Páginas
# ---------------------------------------------------------------------------

@portal_bp.route("/portal")
@login_required
def home():
    """EN: Quotes grouped by distributor: open ones first, history only on full portals.
    PT: Orçamentos agrupados por distribuidora: os abertos primeiro, histórico só no portal completo.
    """
    links = my_links()
    expire_for([link["company_id"] for link in links])

    groups = {}
    for link in links:
        statuses = visible_statuses(link["feat_portal_full"])
        quotes = get_db().execute(
            "SELECT id, number, status, final_total_cents, list_total_cents, valid_until, sent_at, customer_decided_at FROM quotes "
            "WHERE company_id = ? AND workspace_id = ? AND status IN (" + ", ".join("?" * len(statuses)) + ") "
            "ORDER BY CASE status WHEN 'sent' THEN 0 ELSE 1 END, number DESC",
            link["company_id"], link["workspace_id"], *statuses,
        )
        # EN: open quotes to answer first, with items and days left; the rest is history
        # PT: orçamentos a responder primeiro, com itens e dias restantes; o resto é histórico
        for quote in quotes:
            quote["items"] = items_summary(quote["id"])
            quote["days_left"] = days_left(quote["valid_until"]) if quote["status"] == "sent" else None
        group = groups.setdefault(link["workspace_id"], {
            "name": link["workspace_name"], "logo": link["workspace_logo"], "full": link["feat_portal_full"],
            "whatsapp": distributor_whatsapp(link["workspace_phone"], link["company_name"]), "customers": [],
        })
        group["customers"].append({
            "name": link["company_name"],
            "open": [q for q in quotes if q["status"] == "sent"],
            "history": [q for q in quotes if q["status"] != "sent"],
        })

    waiting = sum(len(c["open"]) for group in groups.values() for c in group["customers"])
    return render_template("portal.html", groups=list(groups.values()), link_count=len(links), waiting=waiting)


@portal_bp.route("/portal/quotes/<int:quote_id>/document")
@login_required
def document(quote_id):
    """EN: The same A4 document the distributor sends, for the buyer to save or print.
        load_quote already checked that this buyer may see this quote.
    PT: O mesmo documento A4 que a distribuidora envia, para o comprador salvar ou imprimir.
        O load_quote já conferiu que este comprador pode ver este orçamento.
    """
    quote = load_quote(quote_id)
    return quote_document(quote, f"/portal/quotes/{quote_id}")


@portal_bp.route("/portal/quotes/<int:quote_id>")
@login_required
def show(quote_id):
    quote = load_quote(quote_id)
    # EN: only the columns a buyer may see | PT: só as colunas que o comprador pode ver
    items = get_db().execute(
        "SELECT product_name, unit, quantity, list_price_cents, discount_bps, line_total_cents "
        "FROM quote_items WHERE quote_id = ? ORDER BY id",
        quote_id,
    )
    can_decide = quote["status"] == "sent" and quote["valid_until"] >= today_sp()
    # EN: who to talk to: the seller who made the quote and the distributor's WhatsApp
    # PT: com quem falar: o vendedor que fez o orçamento e o WhatsApp da distribuidora
    seller = get_db().execute("SELECT name FROM users WHERE id = ?", quote["created_by"])
    phone = get_db().execute("SELECT phone FROM workspaces WHERE id = ?", quote["workspace_id"])[0]["phone"]
    return render_template(
        "portal_quote.html", quote=quote, items=items, can_decide=can_decide,
        days=days_left(quote["valid_until"]) if quote["status"] == "sent" else None,
        seller=seller[0]["name"] if seller else None,
        whatsapp=distributor_whatsapp(phone, quote["company_name"], quote["number"]),
    )


@portal_bp.route("/portal/quotes/<int:quote_id>/accept", methods=["POST"])
@login_required
def accept(quote_id):
    """EN: Accept: the quote becomes "accepted", the opportunity moves to the won stage of its
        pipeline with the quote's total, and other open quotes of that opportunity are
        cancelled. One transaction: all of it happens, or none.
    PT: Aceitar: o orçamento vira "aceito", a oportunidade vai para a etapa ganha do funil
        com o total do orçamento, e os outros orçamentos abertos dela são cancelados.
        Uma transação: acontece tudo, ou nada.
    """
    quote = load_quote(quote_id)
    if quote["valid_until"] < today_sp():
        return redirect(f"/portal/quotes/{quote_id}")

    db = get_db()
    db.execute("BEGIN TRANSACTION")
    try:
        transition(quote["status"], "accepted")
        changed = db.execute(
            "UPDATE quotes SET status = 'accepted', customer_user_id = ?, customer_decided_at = ?, updated_at = ? "
            "WHERE id = ? AND status = 'sent'",
            g.user["id"], now_utc(), now_utc(), quote_id,
        )
        if changed != 1:
            raise TransitionError("already decided")

        opportunity = db.execute("SELECT * FROM opportunities WHERE id = ?", quote["opportunity_id"])[0]
        won = db.execute(
            "SELECT id, name FROM stages WHERE pipeline_id = ? AND kind = 'won' ORDER BY position LIMIT 1",
            opportunity["pipeline_id"],
        )[0]
        old_stage = db.execute("SELECT name FROM stages WHERE id = ?", opportunity["stage_id"])[0]["name"]
        db.execute(
            "UPDATE opportunities SET stage_id = ?, closed_at = ?, lost_reason = NULL, closed_manually = 0, value_cents = ?, "
            "updated_at = ? WHERE id = ?",
            won["id"], now_utc(), quote["final_total_cents"], now_utc(), opportunity["id"],
        )
        db.execute(
            "UPDATE quotes SET status = 'cancelled', updated_at = ? WHERE opportunity_id = ? AND id != ? AND status IN ('sent', 'ready', 'pending_approval', 'draft')",
            now_utc(), opportunity["id"], quote_id,
        )
        log_buyer("quote_accepted", f"#{quote['number']:04d}", quote)
        log_buyer("stage_change", f"{old_stage} → {won['name']}", quote)
        db.execute("COMMIT")
    except TransitionError:
        db.execute("ROLLBACK")
        flash(_("portal.already_decided"), "warning")
        return redirect(f"/portal/quotes/{quote_id}")
    except Exception:
        db.execute("ROLLBACK")
        raise

    flash(_("portal.accepted"), "success")
    return redirect(f"/portal/quotes/{quote_id}")


@portal_bp.route("/portal/quotes/<int:quote_id>/decline", methods=["POST"])
@login_required
def decline(quote_id):
    """EN: Decline. On the full portal the buyer can say why; the opportunity stays open so
        the seller can try again.
    PT: Recusar. No portal completo o comprador pode dizer o porquê; a oportunidade continua
        aberta para o vendedor tentar de novo.
    """
    quote = load_quote(quote_id)
    reason = request.form.get("reason", "").strip()[:REASON_MAX] if quote["feat_portal_full"] else ""

    db = get_db()
    db.execute("BEGIN TRANSACTION")
    try:
        transition(quote["status"], "declined")
        changed = db.execute(
            "UPDATE quotes SET status = 'declined', customer_user_id = ?, customer_decided_at = ?, decline_reason = ?, updated_at = ? "
            "WHERE id = ? AND status = 'sent'",
            g.user["id"], now_utc(), reason or None, now_utc(), quote_id,
        )
        if changed != 1:
            raise TransitionError("already decided")
        log_buyer("quote_declined", reason or f"#{quote['number']:04d}", quote)
        db.execute("COMMIT")
    except TransitionError:
        db.execute("ROLLBACK")
        flash(_("portal.already_decided"), "warning")
        return redirect(f"/portal/quotes/{quote_id}")
    except Exception:
        db.execute("ROLLBACK")
        raise

    flash(_("portal.declined"), "success")
    return redirect("/portal")
