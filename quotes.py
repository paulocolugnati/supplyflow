"""EN: Quotes: create a quote from an opportunity, add catalog products, set item and
    quote-wide discounts, and keep every total recalculated by pricing.py.
    Also the quote's life after the draft: approval, sending, cancelling, duplicating and
    expiring, all through approval.transition(). Registered in app.py as a Blueprint.
PT: Orçamentos: cria um orçamento a partir de uma oportunidade, adiciona produtos do
    catálogo, define descontos por item e geral, e mantém todos os totais recalculados
    pelo pricing.py. E também a vida do orçamento depois do rascunho: aprovação, envio,
    cancelamento, duplicação e vencimento, tudo pelo approval.transition(). Registrado no
    app.py como um Blueprint.

EN: Rules (docs/ARCHITECTURE.md, sections 5.12, 5.13, 6.3, 6.4 and 7):
    * quotes are numbered per workspace (#0001...) inside a transaction
    * the monthly quota counts every quote created this month, cancelled ones included
    * only drafts can be edited; members edit only the quotes they created
    * an item copies name, unit, list price and cost from the catalog when added, so later
      catalog changes never rewrite the quote; inactive products can't be added
    * totals are never typed or trusted from the browser: the server recalculates them
PT: Regras (docs/ARCHITECTURE.md, seções 5.12, 5.13, 6.3, 6.4 e 7):
    * orçamentos são numerados por distribuidora (#0001...) dentro de uma transação
    * a cota mensal conta todo orçamento criado no mês, inclusive os cancelados
    * só rascunhos podem ser editados; members editam só os orçamentos que criaram
    * o item copia nome, unidade, preço de tabela e custo do catálogo ao ser adicionado, então
      mudanças no catálogo nunca reescrevem o orçamento; produto inativo não pode ser adicionado
    * os totais nunca são digitados nem confiados ao navegador: o servidor recalcula
"""

from datetime import datetime

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from database import get_db
from documents import quote_document
from approval import TransitionError, approval_reasons, can_decide, can_send, required_role, transition
from helpers import apology, brl, date_sp_in_days, now_utc, parse_percent, today_sp, whatsapp_link
from permissions import (can_modify, check_quota, find_scoped, get_scoped, get_visible_opportunity, get_visible_quote,
                         has_feature, has_role, own_sales_filter, require_role, workspace_id)
from pricing import calculate
from translations import _, customer_text

quotes_bp = Blueprint("quotes", __name__)

QUANTITY_MAX = 100_000
NOTES_MAX = 1000
DEFAULT_VALIDITY_DAYS = 7


# ---------------------------------------------------------------------------
# EN: Helpers
# PT: Funções auxiliares
# ---------------------------------------------------------------------------

def quote_items(quote_id):
    return get_db().execute(
        "SELECT * FROM quote_items WHERE quote_id = ? AND workspace_id = ? ORDER BY id", quote_id, workspace_id()
    )


def recalculate(quote_id):
    """EN: Recompute every line and total of a quote with pricing.calculate and store them.
        Called after any change, so the database always holds consistent numbers.
    PT: Recalcula cada linha e total de um orçamento com pricing.calculate e grava.
        Chamado depois de qualquer mudança, para o banco sempre ter números coerentes.
    """
    quote = get_scoped("quotes", quote_id)
    items = quote_items(quote_id)
    result = calculate(items, quote["header_discount_bps"])
    db = get_db()
    for item, line in zip(items, result["lines"]):
        db.execute("UPDATE quote_items SET line_total_cents = ? WHERE id = ?", line, item["id"])
    db.execute(
        "UPDATE quotes SET list_total_cents = ?, final_total_cents = ?, effective_discount_bps = ?, "
        "margin_bps = ?, updated_at = ? WHERE id = ? AND workspace_id = ?",
        result["list_total_cents"], result["final_total_cents"], result["effective_discount_bps"],
        result["margin_bps"], now_utc(), quote_id, workspace_id(),
    )
    return result


def editable_quote(quote_id):
    """EN: The quote if the current user may edit it now, otherwise an error response.
        Returns (quote, None) or (None, response).
    PT: O orçamento se o usuário atual pode editá-lo agora, senão uma resposta de erro.
        Devolve (orçamento, None) ou (None, resposta).
    """
    quote = get_visible_quote(quote_id)
    if quote["status"] != "draft":
        return None, apology(_("quotes.error_not_draft"), 409)
    if not can_modify(quote, "created_by"):
        return None, apology(_("quotes.error_not_yours"), 403)
    return quote, None


def creator_role(quote):
    """EN: Current role of whoever created the quote (their ceiling is the one that counts).
        Someone who left the team counts as a member, the most restrictive role.
    PT: Cargo atual de quem criou o orçamento (o teto dessa pessoa é o que vale).
        Quem saiu da equipe conta como member, o cargo mais restrito.
    """
    rows = get_db().execute("SELECT role FROM memberships WHERE user_id = ? AND workspace_id = ?",
                            quote["created_by"], workspace_id())
    return rows[0]["role"] if rows else "member"


def reasons_for(quote):
    """EN: Why this quote needs approval right now ([] = it doesn't).
    PT: Por que este orçamento precisa de aprovação agora ([] = não precisa).
    """
    return approval_reasons(quote["effective_discount_bps"], quote["margin_bps"], creator_role(quote),
                            g.membership, has_feature("min_margin"))


def log_quote(kind, body, quote):
    """EN: Insert-only history line linked to the quote, its opportunity and customer.
    PT: Linha de histórico, só de inserção, ligada ao orçamento, à oportunidade e ao cliente.
    """
    get_db().execute(
        "INSERT INTO activities (workspace_id, user_id, type, body, company_id, opportunity_id, quote_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        workspace_id(), g.user["id"], kind, body, quote["company_id"], quote["opportunity_id"], quote["id"],
    )


def move_quote(quote, new_status, **fields):
    """EN: Change a quote's status through the state machine, plus optional extra columns.
        Column names come only from this code, never from the browser.
    PT: Muda o status do orçamento pela máquina de estados, mais colunas extras opcionais.
        Os nomes das colunas vêm só deste código, nunca do navegador.
    """
    transition(quote["status"], new_status)
    columns = ["status = ?", "updated_at = ?"] + [f"{name} = ?" for name in fields]
    get_db().execute(
        "UPDATE quotes SET " + ", ".join(columns) + " WHERE id = ? AND workspace_id = ? AND status = ?",
        new_status, now_utc(), *fields.values(), quote["id"], workspace_id(), quote["status"],
    )


def cancel_pending_requests(quote_id):
    get_db().execute(
        "UPDATE discount_requests SET status = 'cancelled' WHERE quote_id = ? AND workspace_id = ? AND status = 'pending'",
        quote_id, workspace_id(),
    )


def expire_overdue():
    """EN: Sent quotes past their validity become "expired". Checked lazily whenever quotes
        are listed or opened, so no background job is needed.
    PT: Orçamentos enviados com a validade vencida viram "expired". Conferido sob demanda
        sempre que orçamentos são listados ou abertos, então não precisa de tarefa agendada.
    """
    get_db().execute(
        "UPDATE quotes SET status = 'expired', updated_at = ? WHERE workspace_id = ? AND status = 'sent' AND valid_until < ?",
        now_utc(), workspace_id(), today_sp(),
    )


def number_label(quote):
    return f"#{quote['number']:04d}"


def owned_quote(quote_id):
    """EN: The quote if the user may act on it (creator, or admin/owner), else (None, error).
    PT: O orçamento se o usuário pode agir nele (quem criou, ou admin/owner), senão (None, erro).
    """
    quote = get_visible_quote(quote_id)
    if not can_modify(quote, "created_by"):
        return None, apology(_("quotes.error_not_yours"), 403)
    return quote, None


def read_quantity(text):
    try:
        quantity = int((text or "").strip())
    except ValueError:
        return None
    return quantity if 1 <= quantity <= QUANTITY_MAX else None


def read_discount(text):
    """EN: Empty means 0%; otherwise parse_percent (0 to 100%, up to 2 decimals).
    PT: Vazio vale 0%; senão parse_percent (0 a 100%, até 2 casas decimais).
    """
    return 0 if not (text or "").strip() else parse_percent(text)


# ---------------------------------------------------------------------------
# EN: Routes
# PT: Rotas
# ---------------------------------------------------------------------------

@quotes_bp.route("/quotes")
@require_role("member")
def index():
    """EN: All quotes of the workspace, newest first, with an optional status filter.
    PT: Todos os orçamentos da distribuidora, mais novos primeiro, com filtro opcional de status.
    """
    expire_overdue()
    status = request.args.get("status", "")
    # EN: sellers list only quotes of their own opportunities | PT: vendedores listam só orçamentos das próprias oportunidades
    extra, params = own_sales_filter()
    params = [workspace_id()] + params
    if status in ("draft", "pending_approval", "ready", "sent", "accepted", "declined", "expired", "cancelled"):
        extra = " AND q.status = ?"
        params.append(status)
    quotes = get_db().execute(
        "SELECT q.*, c.name AS company_name, o.title AS opportunity_title, u.name AS creator_name, "
        "(SELECT COUNT(*) FROM quote_items i WHERE i.quote_id = q.id) AS item_count "
        "FROM quotes q JOIN companies c ON c.id = q.company_id JOIN opportunities o ON o.id = q.opportunity_id "
        "LEFT JOIN users u ON u.id = q.created_by WHERE q.workspace_id = ?" + extra + " ORDER BY q.number DESC",
        *params,
    )
    return render_template("quotes.html", quotes=quotes, status=status, can_add=check_quota("quotes_month"))


@quotes_bp.route("/opportunities/<int:opportunity_id>/quotes", methods=["POST"])
@require_role("member")
def create(opportunity_id):
    """EN: Start a draft quote for an opportunity. Numbering and the quota check happen in
        one transaction, so two quotes created at once never get the same number.
    PT: Começa um orçamento rascunho para uma oportunidade. A numeração e a conferência da
        cota acontecem numa transação, então dois orçamentos criados ao mesmo tempo nunca
        recebem o mesmo número.
    """
    opportunity = get_visible_opportunity(opportunity_id)
    if not check_quota("quotes_month"):
        flash(_("quotes.quota"), "warning")
        return redirect(f"/opportunities/{opportunity_id}")

    db = get_db()
    db.execute("BEGIN TRANSACTION")
    try:
        number = db.execute("SELECT next_quote_number FROM workspaces WHERE id = ?", workspace_id())[0]["next_quote_number"]
        db.execute("UPDATE workspaces SET next_quote_number = next_quote_number + 1 WHERE id = ?", workspace_id())
        quote_id = db.execute(
            "INSERT INTO quotes (workspace_id, number, opportunity_id, company_id, created_by, valid_until) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            workspace_id(), number, opportunity["id"], opportunity["company_id"], g.user["id"],
            date_sp_in_days(DEFAULT_VALIDITY_DAYS),
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    flash(_("quotes.created"), "success")
    return redirect(f"/quotes/{quote_id}")


@quotes_bp.route("/quotes/<int:quote_id>/document")
@require_role("member")
def document(quote_id):
    """EN: The quote as an A4 document to send to the customer (documents.py).
    PT: O orçamento como documento A4 para enviar ao cliente (documents.py).
    """
    expire_overdue()
    return quote_document(get_visible_quote(quote_id), f"/quotes/{quote_id}")


@quotes_bp.route("/quotes/<int:quote_id>")
@require_role("member")
def show(quote_id):
    """EN: Quote builder (draft and allowed to edit) or read-only view.
    PT: Montador do orçamento (rascunho e com permissão) ou visualização somente leitura.
    """
    expire_overdue()
    quote = get_visible_quote(quote_id)
    db = get_db()
    context = db.execute(
        "SELECT o.title AS opportunity_title, c.name AS company_name, u.name AS creator_name "
        "FROM opportunities o JOIN companies c ON c.id = o.company_id LEFT JOIN users u ON u.id = ? "
        "WHERE o.id = ? AND o.workspace_id = ?",
        quote["created_by"], quote["opportunity_id"], workspace_id(),
    )[0]
    products = db.execute(
        "SELECT id, sku, name, unit, price_cents FROM products WHERE workspace_id = ? AND active = 1 ORDER BY name COLLATE NOCASE",
        workspace_id(),
    )
    items = quote_items(quote_id)
    reasons = reasons_for(quote)
    pending = db.execute(
        "SELECT r.*, u.name AS requester_name FROM discount_requests r LEFT JOIN users u ON u.id = r.requested_by "
        "WHERE r.quote_id = ? AND r.workspace_id = ? ORDER BY r.id DESC LIMIT 1",
        quote_id, workspace_id(),
    )
    history = db.execute(
        "SELECT a.*, u.name AS user_name FROM activities a LEFT JOIN users u ON u.id = a.user_id "
        "WHERE a.quote_id = ? AND a.workspace_id = ? ORDER BY a.id DESC",
        quote_id, workspace_id(),
    )
    # EN: the message carries the portal link and goes to the customer's WhatsApp when known
    # PT: a mensagem leva o link do portal e vai para o WhatsApp do cliente quando conhecido
    phone = db.execute("SELECT phone FROM companies WHERE id = ?", quote["company_id"])[0]["phone"]
    message = (customer_text("quotes.whatsapp_sent").replace("{number}", number_label(quote))
               .replace("{total}", brl(quote["final_total_cents"]))
               .replace("{date}", quote["valid_until"][8:10] + "/" + quote["valid_until"][5:7])
               .replace("{link}", url_for("portal.show", quote_id=quote["id"], _external=True)))
    return render_template(
        "quote.html",
        quote=quote,
        info=context,
        items=items,
        products=products,
        reasons=reasons,
        needed_role=required_role(quote["effective_discount_bps"], g.membership) if reasons else None,
        last_request=pending[0] if pending else None,
        history=history,
        can_act=can_modify(quote, "created_by"),
        share=whatsapp_link(phone or "", message),
        editable=quote["status"] == "draft" and can_modify(quote, "created_by"),
        result=calculate(items, quote["header_discount_bps"]),
        # EN: "your ceiling" only when the viewer created the quote; otherwise name whose ceiling it is
        # PT: "seu teto" só quando quem vê criou o orçamento; senão diz de quem é o teto
        creator_is_me=quote["created_by"] == g.user["id"],
        creator_role=creator_role(quote),
        # EN: items without cost + any discount: the seller gets two warnings (screen + confirm)
        # PT: itens sem custo + algum desconto: o vendedor recebe dois avisos (tela + confirmação)
        unpriced=[i["product_name"] for i in items if i["cost_cents"] is None] if quote["effective_discount_bps"] > 0 else [],
        today=today_sp(),
    )


@quotes_bp.route("/quotes/<int:quote_id>/items", methods=["POST"])
@require_role("member")
def add_item(quote_id):
    """EN: Add a catalog product. Adding a product that is already in the quote adds to its
        quantity instead of creating a second line.
    PT: Adiciona um produto do catálogo. Adicionar um produto que já está no orçamento soma
        na quantidade dele em vez de criar uma segunda linha.
    """
    quote, error = editable_quote(quote_id)
    if error:
        return error

    product = find_scoped("products", request.form.get("product_id"))
    quantity = read_quantity(request.form.get("quantity", "1"))
    discount = read_discount(request.form.get("discount"))
    if product is None or not product["active"]:
        flash(_("quotes.error_product"), "danger")
    elif quantity is None:
        flash(_("quotes.error_quantity"), "danger")
    elif discount is None:
        flash(_("quotes.error_discount"), "danger")
    else:
        db = get_db()
        existing = db.execute("SELECT id, quantity FROM quote_items WHERE quote_id = ? AND product_id = ?", quote_id, product["id"])
        if existing:
            new_quantity = min(existing[0]["quantity"] + quantity, QUANTITY_MAX)
            db.execute("UPDATE quote_items SET quantity = ? WHERE id = ?", new_quantity, existing[0]["id"])
        else:
            # EN: copies of name, unit, price and cost "freeze" the catalog at this moment
            # PT: cópias de nome, unidade, preço e custo "congelam" o catálogo neste momento
            db.execute(
                "INSERT INTO quote_items (workspace_id, quote_id, product_id, product_name, unit, quantity, "
                "list_price_cents, cost_cents, discount_bps) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                workspace_id(), quote_id, product["id"], product["name"], product["unit"], quantity,
                product["price_cents"], product["cost_cents"], discount,
            )
        recalculate(quote_id)
        flash(_("quotes.item_added"), "success")
    return redirect(f"/quotes/{quote_id}#itens")


@quotes_bp.route("/quotes/<int:quote_id>", methods=["POST"])
@require_role("member")
def save(quote_id):
    """EN: Save quantities and discounts of every line plus the quote-wide fields. All lines
        are validated first; nothing is saved if any value is invalid.
    PT: Salva quantidades e descontos de cada linha e os campos gerais do orçamento. Todas as
        linhas são validadas antes; nada é salvo se algum valor for inválido.
    """
    quote, error = editable_quote(quote_id)
    if error:
        return error

    errors = []
    updates = []
    for item in quote_items(quote_id):
        quantity = read_quantity(request.form.get(f"quantity_{item['id']}"))
        discount = read_discount(request.form.get(f"discount_{item['id']}"))
        if quantity is None:
            errors.append(_("quotes.error_quantity_line").replace("{item}", item["product_name"]))
        if discount is None:
            errors.append(_("quotes.error_discount_line").replace("{item}", item["product_name"]))
        updates.append((quantity, discount, item["id"]))

    header = read_discount(request.form.get("header_discount"))
    if header is None:
        errors.append(_("quotes.error_header_discount"))

    valid_until = request.form.get("valid_until", "").strip()
    try:
        valid_until = datetime.strptime(valid_until, "%Y-%m-%d").strftime("%Y-%m-%d")
        if valid_until < today_sp():
            errors.append(_("quotes.error_valid_past"))
    except ValueError:
        errors.append(_("quotes.error_valid_until"))

    notes_customer = request.form.get("notes_customer", "").strip()
    notes_internal = request.form.get("notes_internal", "").strip()
    if len(notes_customer) > NOTES_MAX or len(notes_internal) > NOTES_MAX:
        errors.append(_("quotes.error_notes"))

    if errors:
        for message in errors:
            flash(message, "danger")
        return redirect(f"/quotes/{quote_id}")

    db = get_db()
    db.execute("BEGIN TRANSACTION")
    try:
        for quantity, discount, item_id in updates:
            db.execute("UPDATE quote_items SET quantity = ?, discount_bps = ? WHERE id = ? AND quote_id = ?",
                       quantity, discount, item_id, quote_id)
        db.execute(
            "UPDATE quotes SET header_discount_bps = ?, valid_until = ?, notes_customer = ?, notes_internal = ? "
            "WHERE id = ? AND workspace_id = ?",
            header, valid_until, notes_customer or None, notes_internal or None, quote_id, workspace_id(),
        )
        recalculate(quote_id)
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    flash(_("quotes.saved"), "success")
    return redirect(f"/quotes/{quote_id}")


@quotes_bp.route("/quotes/<int:quote_id>/items/<int:item_id>/delete", methods=["POST"])
@require_role("member")
def remove_item(quote_id, item_id):
    """EN: Remove a line from a draft. | PT: Remove uma linha de um rascunho."""
    quote, error = editable_quote(quote_id)
    if error:
        return error
    get_db().execute("DELETE FROM quote_items WHERE id = ? AND quote_id = ? AND workspace_id = ?", item_id, quote_id, workspace_id())
    recalculate(quote_id)
    flash(_("quotes.item_removed"), "success")
    return redirect(f"/quotes/{quote_id}#itens")


# ---------------------------------------------------------------------------
# EN: The quote's life after the draft (state machine in approval.py)
# PT: A vida do orçamento depois do rascunho (máquina de estados no approval.py)
# ---------------------------------------------------------------------------

@quotes_bp.route("/quotes/<int:quote_id>/submit", methods=["POST"])
@require_role("member")
def submit(quote_id):
    """EN: Finish a draft. Within the creator's ceiling (and margin) it becomes "ready";
        above it, a discount request is created and the quote waits for approval.
    PT: Conclui um rascunho. Dentro do teto (e da margem) de quem criou, vira "ready";
        acima, um pedido de desconto é criado e o orçamento espera a aprovação.
    """
    quote, error = owned_quote(quote_id)
    if error:
        return error
    if quote["status"] != "draft":
        return apology(_("quotes.error_not_draft"), 409)
    if not quote_items(quote_id):
        flash(_("quotes.error_empty"), "danger")
        return redirect(f"/quotes/{quote_id}")
    if quote["valid_until"] < today_sp():
        flash(_("quotes.error_valid_past"), "danger")
        return redirect(f"/quotes/{quote_id}")

    db = get_db()
    db.execute("BEGIN TRANSACTION")
    try:
        recalculate(quote_id)
        quote = get_scoped("quotes", quote_id)
        reasons = reasons_for(quote)
        if not reasons:
            move_quote(quote, "ready")
            log_quote("note", _("quotes.log_ready"), quote)
            db.execute("COMMIT")
            flash(_("quotes.ready_ok"), "success")
            return redirect(f"/quotes/{quote_id}")

        reason = request.form.get("reason", "").strip()
        if not 3 <= len(reason) <= 300:
            db.execute("ROLLBACK")
            flash(_("quotes.error_reason"), "danger")
            return redirect(f"/quotes/{quote_id}#concluir")

        needed = required_role(quote["effective_discount_bps"], g.membership)
        db.execute(
            "INSERT INTO discount_requests (workspace_id, quote_id, requested_by, requested_discount_bps, "
            "requested_margin_bps, required_role, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
            workspace_id(), quote_id, g.user["id"], quote["effective_discount_bps"], quote["margin_bps"], needed, reason,
        )
        move_quote(quote, "pending_approval")
        log_quote("discount_requested", reason, quote)
        db.execute("COMMIT")
    except TransitionError:
        db.execute("ROLLBACK")
        return apology(_("quotes.error_transition"), 409)
    except Exception:
        db.execute("ROLLBACK")
        raise

    flash(_("quotes.sent_for_approval").replace("{role}", _("role." + needed)), "success")
    return redirect(f"/quotes/{quote_id}")


@quotes_bp.route("/quotes/<int:quote_id>/reopen", methods=["POST"])
@require_role("member")
def reopen(quote_id):
    """EN: Back to draft to edit. Any approval is dropped and pending requests are cancelled:
        this is what makes "approve 10%, then raise to 25%" impossible.
    PT: Volta para rascunho para editar. Qualquer aprovação cai e pedidos pendentes são
        cancelados: é isso que torna "aprovar 10% e depois subir para 25%" impossível.
    """
    quote, error = owned_quote(quote_id)
    if error:
        return error
    db = get_db()
    db.execute("BEGIN TRANSACTION")
    try:
        move_quote(quote, "draft", approved_by=None, approved_at=None, approved_discount_bps=None)
        cancel_pending_requests(quote_id)
        log_quote("note", _("quotes.log_reopened"), quote)
        db.execute("COMMIT")
    except TransitionError:
        db.execute("ROLLBACK")
        return apology(_("quotes.error_transition"), 409)
    except Exception:
        db.execute("ROLLBACK")
        raise
    flash(_("quotes.reopened"), "success")
    return redirect(f"/quotes/{quote_id}")


@quotes_bp.route("/quotes/<int:quote_id>/send", methods=["POST"])
@require_role("member")
def send(quote_id):
    """EN: Send a ready quote to the customer. The send check (approval.can_send) runs again
        here, on the server, right before the quote leaves.
    PT: Envia um orçamento pronto ao cliente. A conferência de envio (approval.can_send) roda
        de novo aqui, no servidor, logo antes de o orçamento sair.
    """
    quote, error = owned_quote(quote_id)
    if error:
        return error
    if quote["valid_until"] < today_sp():
        flash(_("quotes.error_valid_past"), "danger")
        return redirect(f"/quotes/{quote_id}")
    if not can_send(quote, reasons_for(quote)):
        return apology(_("quotes.error_not_approved"), 409)

    db = get_db()
    db.execute("BEGIN TRANSACTION")
    try:
        move_quote(quote, "sent", sent_at=now_utc())
        log_quote("quote_sent", number_label(quote), quote)
        db.execute("COMMIT")
    except TransitionError:
        db.execute("ROLLBACK")
        return apology(_("quotes.error_transition"), 409)
    except Exception:
        db.execute("ROLLBACK")
        raise
    flash(_("quotes.sent_ok"), "success")
    return redirect(f"/quotes/{quote_id}")


@quotes_bp.route("/quotes/<int:quote_id>/cancel", methods=["POST"])
@require_role("member")
def cancel(quote_id):
    """EN: Cancel a quote that is not final. It stays in the history and in the monthly count.
    PT: Cancela um orçamento que não está finalizado. Ele fica no histórico e na contagem do mês.
    """
    quote, error = owned_quote(quote_id)
    if error:
        return error
    db = get_db()
    db.execute("BEGIN TRANSACTION")
    try:
        move_quote(quote, "cancelled")
        cancel_pending_requests(quote_id)
        log_quote("note", _("quotes.log_cancelled"), quote)
        db.execute("COMMIT")
    except TransitionError:
        db.execute("ROLLBACK")
        return apology(_("quotes.error_transition"), 409)
    except Exception:
        db.execute("ROLLBACK")
        raise
    flash(_("quotes.cancelled_ok"), "success")
    return redirect(f"/quotes/{quote_id}")


@quotes_bp.route("/quotes/<int:quote_id>/duplicate", methods=["POST"])
@require_role("member")
def duplicate(quote_id):
    """EN: Copy a quote (any status) into a new draft of the current user, with the same
        item snapshots and discounts. This is how a sent quote gets "changed".
    PT: Copia um orçamento (qualquer status) num rascunho novo do usuário atual, com as mesmas
        cópias de itens e descontos. É assim que um orçamento enviado é "alterado".
    """
    original = get_visible_quote(quote_id)
    if not check_quota("quotes_month"):
        flash(_("quotes.quota"), "warning")
        return redirect(f"/quotes/{quote_id}")

    db = get_db()
    db.execute("BEGIN TRANSACTION")
    try:
        number = db.execute("SELECT next_quote_number FROM workspaces WHERE id = ?", workspace_id())[0]["next_quote_number"]
        db.execute("UPDATE workspaces SET next_quote_number = next_quote_number + 1 WHERE id = ?", workspace_id())
        new_id = db.execute(
            "INSERT INTO quotes (workspace_id, number, opportunity_id, company_id, created_by, valid_until, "
            "header_discount_bps, notes_customer, notes_internal) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            workspace_id(), number, original["opportunity_id"], original["company_id"], g.user["id"],
            date_sp_in_days(DEFAULT_VALIDITY_DAYS), original["header_discount_bps"],
            original["notes_customer"], original["notes_internal"],
        )
        for item in quote_items(quote_id):
            db.execute(
                "INSERT INTO quote_items (workspace_id, quote_id, product_id, product_name, unit, quantity, "
                "list_price_cents, cost_cents, discount_bps) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                workspace_id(), new_id, item["product_id"], item["product_name"], item["unit"], item["quantity"],
                item["list_price_cents"], item["cost_cents"], item["discount_bps"],
            )
        recalculate(new_id)
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    flash(_("quotes.duplicated").replace("{number}", number_label(original)), "success")
    return redirect(f"/quotes/{new_id}")


# ---------------------------------------------------------------------------
# EN: Approval queue (admins and owners)
# PT: Fila de aprovação (admins e owners)
# ---------------------------------------------------------------------------

def pending_for_me():
    """EN: Pending requests the current user may decide (never their own).
    PT: Pedidos pendentes que o usuário atual pode decidir (nunca os dele).
    """
    rows = get_db().execute(
        "SELECT r.*, q.number, q.final_total_cents, q.list_total_cents, q.effective_discount_bps, q.margin_bps, "
        "q.id AS quote_id, q.company_id, c.name AS company_name, u.name AS requester_name "
        "FROM discount_requests r JOIN quotes q ON q.id = r.quote_id JOIN companies c ON c.id = q.company_id "
        "LEFT JOIN users u ON u.id = r.requested_by "
        "WHERE r.workspace_id = ? AND r.status = 'pending' AND q.status = 'pending_approval' ORDER BY r.created_at",
        workspace_id(),
    )
    return [r for r in rows if can_decide(g.user["id"], g.membership["role"], r)]


@quotes_bp.route("/approvals")
@require_role("admin")
def approvals():
    """EN: The queue, with everything needed to decide without opening the quote: items,
        discount in R$ and the customer's buying history.
    PT: A fila, com tudo o que é preciso para decidir sem abrir o orçamento: itens,
        desconto em R$ e o histórico de compras do cliente.
    """
    requests = pending_for_me()
    for r in requests:
        r["items"] = quote_items(r["quote_id"])
        r["discount_cents"] = r["list_total_cents"] - r["final_total_cents"]
        r["history"] = get_db().execute(
            "SELECT COUNT(*) AS orders, COALESCE(SUM(final_total_cents), 0) AS total, MAX(customer_decided_at) AS last "
            "FROM quotes WHERE company_id = ? AND workspace_id = ? AND status = 'accepted'",
            r["company_id"], workspace_id(),
        )[0]
    return render_template("approvals.html", requests=requests)


def decide(request_id, approve):
    """EN: Approve or reject one request, re-checking everything on the server.
    PT: Aprova ou recusa um pedido, conferindo tudo de novo no servidor.
    """
    req = get_scoped("discount_requests", request_id)
    if req["status"] != "pending":
        return apology(_("approvals.error_decided"), 409)
    if not can_decide(g.user["id"], g.membership["role"], req):
        return apology(_("approvals.error_cannot"), 403)
    quote = get_scoped("quotes", req["quote_id"])
    note = request.form.get("note", "").strip()[:300]
    if not approve and len(note) < 3:
        flash(_("approvals.error_note"), "danger")
        return redirect("/approvals")

    db = get_db()
    db.execute("BEGIN TRANSACTION")
    try:
        # EN: the quote can't have changed while pending (it isn't editable), but we check anyway
        # PT: o orçamento não pode ter mudado enquanto pendente (não é editável), mas conferimos mesmo assim
        if quote["effective_discount_bps"] != req["requested_discount_bps"]:
            raise TransitionError("discount changed")
        changed = db.execute(
            "UPDATE discount_requests SET status = ?, decided_by = ?, decided_at = ?, decision_note = ? "
            "WHERE id = ? AND status = 'pending'",
            "approved" if approve else "rejected", g.user["id"], now_utc(), note or None, request_id,
        )
        if changed != 1:
            raise TransitionError("already decided")
        if approve:
            move_quote(quote, "ready", approved_by=g.user["id"], approved_at=now_utc(),
                       approved_discount_bps=req["requested_discount_bps"])
            log_quote("discount_approved", note or number_label(quote), quote)
        else:
            move_quote(quote, "draft")
            log_quote("discount_rejected", note, quote)
        db.execute("COMMIT")
    except TransitionError:
        db.execute("ROLLBACK")
        return apology(_("quotes.error_transition"), 409)
    except Exception:
        db.execute("ROLLBACK")
        raise

    flash(_("approvals.approved" if approve else "approvals.rejected").replace("{number}", number_label(quote)), "success")
    return redirect("/approvals")


@quotes_bp.route("/approvals/<int:request_id>/approve", methods=["POST"])
@require_role("admin")
def approve(request_id):
    return decide(request_id, True)


@quotes_bp.route("/approvals/<int:request_id>/reject", methods=["POST"])
@require_role("admin")
def reject(request_id):
    return decide(request_id, False)
