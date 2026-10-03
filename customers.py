"""EN: Customers (companies that buy from the distributor) and their contacts.
    Registered in app.py as a Blueprint.
PT: Clientes (empresas que compram da distribuidora) e seus contatos.
    Registrado no app.py como um Blueprint.

EN: Rules (docs/ARCHITECTURE.md, sections 5.6, 5.7, 6.1, 6.9 and 8):
    * every query is limited to the active workspace (get_scoped / workspace_id())
    * any staff member creates and edits customers; only admins and owners choose the
      responsible seller (a member's new customer is always theirs)
    * a member deletes only their own customers; a customer with quotes can't be deleted
      (the database blocks it, we turn that into a friendly message)
    * the plan's customer quota is checked before every insert
PT: Regras (docs/ARCHITECTURE.md, seções 5.6, 5.7, 6.1, 6.9 e 8):
    * toda consulta fica limitada à distribuidora ativa (get_scoped / workspace_id())
    * qualquer pessoa da equipe cria e edita clientes; só admins e owners escolhem o
      vendedor responsável (o cliente novo de um member é sempre dele)
    * um member apaga só os próprios clientes; cliente com orçamento não pode ser apagado
      (o banco bloqueia, e nós transformamos isso numa mensagem amigável)
    * a cota de clientes do plano é conferida antes de todo INSERT
"""

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from database import get_db
from helpers import (apology, escape_like, is_valid_email, new_token, normalize_cnpj, normalize_phone,
                     now_utc, utc_in_days, whatsapp_link)
from permissions import (can_modify, check_quota, get_scoped, has_role, is_workspace_user, own_sales_filter,
                         require_role, workspace_id)
from tasks import tasks_for
from translations import _, customer_text

customers_bp = Blueprint("customers", __name__)

# EN: Size limits, checked on the server | PT: Limites de tamanho, conferidos no servidor
NAME_MAX = 120
SEGMENT_MAX = 60
CITY_MAX = 80
POSITION_MAX = 60


# ---------------------------------------------------------------------------
# EN: Helpers
# PT: Funções auxiliares
# ---------------------------------------------------------------------------

def staff_options():
    """EN: People of the active workspace, for the "responsible seller" select.
    PT: Pessoas da distribuidora ativa, para o select de "vendedor responsável".
    """
    return get_db().execute(
        "SELECT u.id, u.name FROM memberships m JOIN users u ON u.id = m.user_id "
        "WHERE m.workspace_id = ? ORDER BY u.name",
        workspace_id(),
    )


def segment_suggestions():
    """EN: Segments already used in this workspace, offered as suggestions (<datalist>).
    PT: Segmentos já usados nesta distribuidora, oferecidos como sugestões (<datalist>).
    """
    rows = get_db().execute(
        "SELECT DISTINCT segment FROM companies WHERE workspace_id = ? AND segment IS NOT NULL "
        "ORDER BY segment",
        workspace_id(),
    )
    return [row["segment"] for row in rows]


def read_customer_form(existing=None):
    """EN: Read and validate the customer form. Returns (values, errors).
    PT: Lê e valida o formulário de cliente. Devolve (valores, erros).
    """
    form = {
        "name": request.form.get("name", "").strip(),
        "cnpj": request.form.get("cnpj", "").strip(),
        "segment": request.form.get("segment", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "city": request.form.get("city", "").strip(),
        "owner_id": request.form.get("owner_id", ""),
    }
    errors = []

    if not 2 <= len(form["name"]) <= NAME_MAX:
        errors.append("customers.error_name")
    if len(form["segment"]) > SEGMENT_MAX:
        errors.append("customers.error_segment")
    if len(form["city"]) > CITY_MAX:
        errors.append("customers.error_city")

    cnpj = None
    if form["cnpj"]:
        cnpj = normalize_cnpj(form["cnpj"])
        if cnpj is None:
            errors.append("customers.error_cnpj")
        else:
            # EN: same CNPJ twice in one workspace is almost always a duplicate customer
            # PT: o mesmo CNPJ duas vezes numa distribuidora quase sempre é cliente repetido
            duplicate = get_db().execute(
                "SELECT id FROM companies WHERE workspace_id = ? AND cnpj = ? AND id != ?",
                workspace_id(), cnpj, existing["id"] if existing else 0,
            )
            if duplicate:
                errors.append("customers.error_cnpj_taken")

    phone = None
    if form["phone"]:
        phone = normalize_phone(form["phone"])
        if phone is None:
            errors.append("register.error_phone")

    # EN: Only admins and owners choose the responsible seller, and it must be someone of
    #     this workspace (the id comes from the browser, so it is checked)
    # PT: Só admins e owners escolhem o vendedor responsável, e precisa ser alguém desta
    #     distribuidora (o id vem do navegador, então é conferido)
    if has_role("admin"):
        if form["owner_id"] and not is_workspace_user(form["owner_id"]):
            errors.append("customers.error_owner")
        owner_id = int(form["owner_id"]) if form["owner_id"] and not errors else None
    else:
        owner_id = existing["owner_id"] if existing else g.user["id"]

    values = {
        "name": form["name"],
        "cnpj": cnpj,
        "segment": form["segment"] or None,
        "phone": phone,
        "city": form["city"] or None,
        "owner_id": owner_id,
    }
    return form, values, errors


def read_contact_form():
    """EN: Read and validate the contact form. Returns (form, values, errors).
    PT: Lê e valida o formulário de contato. Devolve (form, valores, erros).
    """
    form = {
        "name": request.form.get("name", "").strip(),
        "position": request.form.get("position", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "email": request.form.get("email", "").strip().lower(),
    }
    errors = []
    if not 2 <= len(form["name"]) <= NAME_MAX:
        errors.append("customers.error_contact_name")
    if len(form["position"]) > POSITION_MAX:
        errors.append("customers.error_position")
    phone = normalize_phone(form["phone"]) if form["phone"] else None
    if form["phone"] and phone is None:
        errors.append("register.error_phone")
    if form["email"] and not is_valid_email(form["email"]):
        errors.append("register.error_email")
    values = {
        "name": form["name"],
        "position": form["position"] or None,
        "phone": phone,
        "email": form["email"] or None,
    }
    return form, values, errors


def main_contact_name(company):
    """EN: Name of the customer's first contact (the person who reads the WhatsApp), or the
        company name when there is no contact.
    PT: Nome do primeiro contato do cliente (a pessoa que lê o WhatsApp), ou o nome da
        empresa quando não há contato.
    """
    rows = get_db().execute("SELECT name FROM contacts WHERE company_id = ? AND workspace_id = ? ORDER BY id LIMIT 1",
                            company["id"], workspace_id())
    return rows[0]["name"] if rows else company["name"]


def greeting(name):
    """EN: Pre-filled WhatsApp message to a customer, always in Portuguese, greeting the
        person by first name.
    PT: Mensagem pronta de WhatsApp para um cliente, sempre em português, cumprimentando a
        pessoa pelo primeiro nome.
    """
    return (customer_text("customers.whatsapp_message")
            .replace("{name}", name.split()[0])
            .replace("{user}", g.user["name"].split()[0])
            .replace("{workspace}", g.membership["workspace_name"]))


# ---------------------------------------------------------------------------
# EN: Customers
# PT: Clientes
# ---------------------------------------------------------------------------

@customers_bp.route("/customers")
@require_role("member")
def index():
    """EN: Customer list with search (name, CNPJ, city) and filters (segment, seller).
        The WHERE clause is built from fixed pieces; user input only goes in "?" params.
    PT: Lista de clientes com busca (nome, CNPJ, cidade) e filtros (segmento, vendedor).
        O WHERE é montado com pedaços fixos; a entrada do usuário só entra nos parâmetros "?".
    """
    q = request.args.get("q", "").strip()[:100]
    segment = request.args.get("segment", "").strip()[:SEGMENT_MAX]
    owner = request.args.get("owner", "").strip()

    conditions = ["c.workspace_id = ?"]
    params = [workspace_id()]

    if q:
        like = "%" + escape_like(q) + "%"
        digits = "".join(ch for ch in q if ch.isdigit())
        part = "(c.name LIKE ? ESCAPE '!' OR c.city LIKE ? ESCAPE '!'"
        params += [like, like]
        if digits:
            # EN: "11.222" also finds the CNPJ stored as digits | PT: "11.222" também acha o CNPJ guardado em dígitos
            part += " OR c.cnpj LIKE ? ESCAPE '!'"
            params.append("%" + digits + "%")
        conditions.append(part + ")")
    if segment:
        conditions.append("c.segment = ?")
        params.append(segment)
    if owner == "me":
        conditions.append("c.owner_id = ?")
        params.append(g.user["id"])
    elif owner.isdigit():
        conditions.append("c.owner_id = ?")
        params.append(int(owner))

    # EN: No f-string with user input: only the fixed condition strings above are joined,
    #     every value goes through a "?" parameter
    # PT: Nada de f-string com entrada do usuário: só os pedaços fixos acima são juntados,
    #     todo valor passa por um parâmetro "?"
    sql = (
        "SELECT c.*, u.name AS owner_name, "
        "(SELECT COUNT(*) FROM contacts k WHERE k.company_id = c.id) AS contact_count, "
        "(SELECT COUNT(*) FROM customer_users cu JOIN users b ON b.id = cu.user_id "
        " WHERE cu.company_id = c.id AND b.referred_by_workspace_id = c.workspace_id) AS brought_count "
        "FROM companies c LEFT JOIN users u ON u.id = c.owner_id "
        "WHERE " + " AND ".join(conditions) + " ORDER BY c.name COLLATE NOCASE"
    )
    customers = get_db().execute(sql, *params)
    for customer in customers:
        customer["whatsapp"] = whatsapp_link(customer["phone"], greeting(main_contact_name(customer))) if customer["phone"] else None

    total = get_db().execute("SELECT COUNT(*) AS n FROM companies WHERE workspace_id = ?", workspace_id())[0]["n"]
    return render_template(
        "customers.html",
        customers=customers,
        total=total,
        filters={"q": q, "segment": segment, "owner": owner},
        segments=segment_suggestions(),
        staff=staff_options(),
        can_add=check_quota("customers"),
    )


@customers_bp.route("/customers/new", methods=["GET", "POST"])
@require_role("member")
def create():
    """EN: Create a customer (checks the plan quota first).
    PT: Cria um cliente (confere a cota do plano antes).
    """
    if not check_quota("customers"):
        flash(_("customers.quota"), "warning")
        return redirect("/customers")

    if request.method == "GET":
        return render_template("customer_form.html", form={"owner_id": str(g.user["id"])}, errors=[],
                               customer=None, segments=segment_suggestions(), staff=staff_options())

    form, values, errors = read_customer_form()
    if errors:
        return render_template("customer_form.html", form=form, errors=errors, customer=None,
                               segments=segment_suggestions(), staff=staff_options()), 400

    customer_id = get_db().execute(
        "INSERT INTO companies (workspace_id, name, cnpj, segment, phone, city, owner_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        workspace_id(), values["name"], values["cnpj"], values["segment"], values["phone"],
        values["city"], values["owner_id"],
    )
    flash(_("customers.created"), "success")
    return redirect(f"/customers/{customer_id}")


@customers_bp.route("/customers/<int:customer_id>")
@require_role("member")
def show(customer_id):
    """EN: Customer page: data, contacts and WhatsApp buttons.
    PT: Página do cliente: dados, contatos e botões de WhatsApp.
    """
    customer = get_scoped("companies", customer_id)
    owner = get_db().execute("SELECT name FROM users WHERE id = ?", customer["owner_id"]) if customer["owner_id"] else []
    contacts = get_db().execute(
        "SELECT * FROM contacts WHERE company_id = ? AND workspace_id = ? ORDER BY name COLLATE NOCASE",
        customer_id, workspace_id(),
    )
    for contact in contacts:
        contact["whatsapp"] = whatsapp_link(contact["phone"], greeting(contact["name"])) if contact["phone"] else None

    # EN: the customer is shared, but a seller sees only their own deals and values
    # PT: o cliente é compartilhado, mas um vendedor vê só os próprios negócios e valores
    mine_sql, mine_params = own_sales_filter()
    opportunities = get_db().execute(
        "SELECT o.id, o.title, o.value_cents, s.name AS stage_name, s.kind AS stage_kind "
        "FROM opportunities o JOIN stages s ON s.id = o.stage_id "
        "WHERE o.company_id = ? AND o.workspace_id = ?" + mine_sql + " ORDER BY o.updated_at DESC",
        customer_id, workspace_id(), *mine_params,
    )
    # EN: Buyers linked to this customer; "brought by you" = account created through OUR invite
    # PT: Compradores ligados a este cliente; "trazido por você" = conta criada pelo NOSSO convite
    buyers = get_db().execute(
        "SELECT u.id, u.name, u.email, (u.referred_by_workspace_id = ?) AS brought "
        "FROM customer_users cu JOIN users u ON u.id = cu.user_id WHERE cu.company_id = ? ORDER BY u.name",
        workspace_id(), customer_id,
    )
    buyer_invites = get_db().execute(
        "SELECT id, email, expires_at FROM invites WHERE workspace_id = ? AND kind = 'customer' AND company_id = ? "
        "AND accepted_at IS NULL AND expires_at > ? ORDER BY created_at DESC",
        workspace_id(), customer_id, now_utc(),
    )
    # EN: everything that happened with this customer, newest first (opportunities, quotes,
    #     notes, tasks...): every history line carries the customer's id
    # PT: tudo o que aconteceu com este cliente, mais novo primeiro (oportunidades, orçamentos,
    #     notas, tarefas...): toda linha de histórico leva o id do cliente
    # EN: lines about another seller's deal are hidden from sellers
    # PT: linhas sobre o negócio de outro vendedor ficam escondidas dos vendedores
    hide_sql = " AND (a.opportunity_id IS NULL OR o.owner_id = ?)" if mine_params else ""
    history = get_db().execute(
        "SELECT a.*, u.name AS user_name, o.title AS opportunity_title FROM activities a "
        "LEFT JOIN users u ON u.id = a.user_id LEFT JOIN opportunities o ON o.id = a.opportunity_id "
        "WHERE a.company_id = ? AND a.workspace_id = ?" + hide_sql + " ORDER BY a.created_at DESC, a.id DESC LIMIT 60",
        customer_id, workspace_id(), *mine_params,
    )
    return render_template(
        "customer.html",
        customer=customer,
        opportunities=opportunities,
        tasks=tasks_for("company_id", customer_id),
        history=history,
        staff=staff_options(),
        buyers=buyers,
        buyer_invites=buyer_invites,
        new_buyer_invite=session.pop("new_buyer_invite", None),
        owner_name=owner[0]["name"] if owner else None,
        contacts=contacts,
        whatsapp=whatsapp_link(customer["phone"], greeting(main_contact_name(customer))) if customer["phone"] else None,
        can_delete=can_modify(customer),
        contact_form={},
        contact_errors=[],
    )


@customers_bp.route("/customers/<int:customer_id>/edit", methods=["GET", "POST"])
@require_role("member")
def edit(customer_id):
    """EN: Edit a customer. Any staff member can edit; only admins change the seller.
    PT: Edita um cliente. Qualquer pessoa da equipe edita; só admins trocam o vendedor.
    """
    customer = get_scoped("companies", customer_id)

    if request.method == "GET":
        form = dict(customer)
        form["owner_id"] = str(customer["owner_id"] or "")
        return render_template("customer_form.html", form=form, errors=[], customer=customer,
                               segments=segment_suggestions(), staff=staff_options())

    form, values, errors = read_customer_form(existing=customer)
    if errors:
        return render_template("customer_form.html", form=form, errors=errors, customer=customer,
                               segments=segment_suggestions(), staff=staff_options()), 400

    get_db().execute(
        "UPDATE companies SET name = ?, cnpj = ?, segment = ?, phone = ?, city = ?, owner_id = ? "
        "WHERE id = ? AND workspace_id = ?",
        values["name"], values["cnpj"], values["segment"], values["phone"], values["city"],
        values["owner_id"], customer_id, workspace_id(),
    )
    flash(_("customers.saved"), "success")
    return redirect(f"/customers/{customer_id}")


@customers_bp.route("/customers/<int:customer_id>/delete", methods=["POST"])
@require_role("member")
def delete(customer_id):
    """EN: Delete a customer. Members only their own; blocked when there are quotes.
    PT: Apaga um cliente. Members só os próprios; bloqueado quando há orçamentos.
    """
    customer = get_scoped("companies", customer_id)
    if not can_modify(customer):
        return apology(_("customers.error_not_yours"), 403)
    try:
        get_db().execute("DELETE FROM companies WHERE id = ? AND workspace_id = ?", customer_id, workspace_id())
    except ValueError:
        # EN: the foreign key from quotes refused the delete | PT: a chave estrangeira dos orçamentos recusou
        flash(_("customers.error_has_quotes"), "danger")
        return redirect(f"/customers/{customer_id}")
    flash(_("customers.deleted"), "success")
    return redirect("/customers")


# ---------------------------------------------------------------------------
# EN: Contacts (always inside a customer of the active workspace)
# PT: Contatos (sempre dentro de um cliente da distribuidora ativa)
# ---------------------------------------------------------------------------

def get_contact(customer_id, contact_id):
    """EN: The contact must belong to this customer AND to this workspace, or 404.
    PT: O contato precisa ser deste cliente E desta distribuidora, ou 404.
    """
    customer = get_scoped("companies", customer_id)
    contact = get_scoped("contacts", contact_id)
    if contact["company_id"] != customer["id"]:
        return customer, None
    return customer, contact


@customers_bp.route("/customers/<int:customer_id>/contacts", methods=["POST"])
@require_role("member")
def add_contact(customer_id):
    """EN: Add a contact to a customer.
    PT: Adiciona um contato a um cliente.
    """
    customer = get_scoped("companies", customer_id)
    form, values, errors = read_contact_form()
    if errors:
        for error in errors:
            flash(_(error), "danger")
        return redirect(f"/customers/{customer_id}#contatos")

    get_db().execute(
        "INSERT INTO contacts (workspace_id, company_id, name, position, phone, email) VALUES (?, ?, ?, ?, ?, ?)",
        workspace_id(), customer["id"], values["name"], values["position"], values["phone"], values["email"],
    )
    flash(_("customers.contact_added"), "success")
    return redirect(f"/customers/{customer_id}#contatos")


@customers_bp.route("/customers/<int:customer_id>/contacts/<int:contact_id>/edit", methods=["GET", "POST"])
@require_role("member")
def edit_contact(customer_id, contact_id):
    """EN: Edit a contact on its own page.
    PT: Edita um contato numa página própria.
    """
    customer, contact = get_contact(customer_id, contact_id)
    if contact is None:
        return apology(_("error.not_found"), 404)

    if request.method == "GET":
        return render_template("contact_form.html", customer=customer, contact=contact, form=dict(contact), errors=[])

    form, values, errors = read_contact_form()
    if errors:
        return render_template("contact_form.html", customer=customer, contact=contact, form=form, errors=errors), 400

    get_db().execute(
        "UPDATE contacts SET name = ?, position = ?, phone = ?, email = ? WHERE id = ? AND workspace_id = ?",
        values["name"], values["position"], values["phone"], values["email"], contact_id, workspace_id(),
    )
    flash(_("customers.contact_saved"), "success")
    return redirect(f"/customers/{customer_id}#contatos")


@customers_bp.route("/customers/<int:customer_id>/contacts/<int:contact_id>/delete", methods=["POST"])
@require_role("member")
def delete_contact(customer_id, contact_id):
    """EN: Delete a contact. Same rule as the customer: members only on their own customers.
    PT: Apaga um contato. Mesma regra do cliente: members só nos próprios clientes.
    """
    customer, contact = get_contact(customer_id, contact_id)
    if contact is None:
        return apology(_("error.not_found"), 404)
    if not can_modify(customer):
        return apology(_("customers.error_not_yours"), 403)
    get_db().execute("DELETE FROM contacts WHERE id = ? AND workspace_id = ?", contact_id, workspace_id())
    flash(_("customers.contact_deleted"), "success")
    return redirect(f"/customers/{customer_id}#contatos")


# ---------------------------------------------------------------------------
# EN: Buyers (portal access for people of a customer)
# PT: Compradores (acesso ao portal para pessoas de um cliente)
# ---------------------------------------------------------------------------

BUYER_INVITE_DAYS = 7


@customers_bp.route("/customers/<int:customer_id>/buyers/invite", methods=["POST"])
@require_role("member")
def invite_buyer(customer_id):
    """EN: Invite a buyer to this customer's portal. The link is shown once (only its hash
        is stored) and can go straight to the customer's WhatsApp. Buyers are free and never
        count against the plan.
    PT: Convida um comprador para o portal deste cliente. O link aparece uma vez (só o hash
        fica guardado) e pode ir direto para o WhatsApp do cliente. Compradores são grátis e
        nunca contam no plano.
    """
    customer = get_scoped("companies", customer_id)
    email = request.form.get("email", "").strip().lower()
    if not is_valid_email(email):
        flash(_("register.error_email"), "danger")
        return redirect(f"/customers/{customer_id}#compradores")

    db = get_db()
    linked = db.execute(
        "SELECT 1 FROM customer_users cu JOIN users u ON u.id = cu.user_id WHERE cu.company_id = ? AND u.email = ?",
        customer_id, email,
    )
    pending = db.execute(
        "SELECT 1 FROM invites WHERE workspace_id = ? AND kind = 'customer' AND company_id = ? AND email = ? "
        "AND accepted_at IS NULL AND expires_at > ?",
        workspace_id(), customer_id, email, now_utc(),
    )
    if linked:
        flash(_("buyers.error_linked"), "danger")
        return redirect(f"/customers/{customer_id}#compradores")
    if pending:
        flash(_("team.error_pending"), "danger")
        return redirect(f"/customers/{customer_id}#compradores")

    token, token_hash = new_token()
    db.execute(
        "INSERT INTO invites (workspace_id, kind, email, company_id, token_hash, created_by, expires_at) "
        "VALUES (?, 'customer', ?, ?, ?, ?, ?)",
        workspace_id(), email, customer_id, token_hash, g.user["id"], utc_in_days(BUYER_INVITE_DAYS),
    )
    link = url_for("team.show_invite", token=token, _external=True)
    message = (customer_text("buyers.whatsapp_message").replace("{workspace}", g.membership["workspace_name"])
               .replace("{company}", customer["name"]) + " " + link)
    session["new_buyer_invite"] = {
        "email": email, "link": link,
        "share": whatsapp_link(customer["phone"] or "", message),
    }
    return redirect(f"/customers/{customer_id}#compradores")


@customers_bp.route("/customers/<int:customer_id>/buyers/invites/<int:invite_id>/revoke", methods=["POST"])
@require_role("member")
def revoke_buyer_invite(customer_id, invite_id):
    get_scoped("companies", customer_id)
    invite = get_scoped("invites", invite_id)
    if invite["kind"] != "customer" or invite["company_id"] != customer_id or invite["accepted_at"]:
        return apology(_("error.not_found"), 404)
    get_db().execute("UPDATE invites SET expires_at = ? WHERE id = ?", now_utc(), invite_id)
    flash(_("team.invite_revoked"), "success")
    return redirect(f"/customers/{customer_id}#compradores")


@customers_bp.route("/customers/<int:customer_id>/buyers/<int:user_id>/remove", methods=["POST"])
@require_role("member")
def remove_buyer(customer_id, user_id):
    """EN: Unlink a buyer (they keep their account and other distributors). Same rule as
        deleting the customer: members only on their own customers.
    PT: Desliga um comprador (ele mantém a conta e as outras distribuidoras). Mesma regra de
        apagar o cliente: members só nos próprios clientes.
    """
    customer = get_scoped("companies", customer_id)
    if not can_modify(customer):
        return apology(_("customers.error_not_yours"), 403)
    get_db().execute("DELETE FROM customer_users WHERE company_id = ? AND user_id = ? AND workspace_id = ?",
                     customer_id, user_id, workspace_id())
    flash(_("buyers.removed"), "success")
    return redirect(f"/customers/{customer_id}#compradores")
