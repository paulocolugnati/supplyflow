"""EN: Team management: invites by link, accepting invites, roles, removing members,
    co-owners and ownership transfer. Registered in app.py as a Flask Blueprint
    (a group of routes kept in its own file).
PT: Gestão de equipe: convites por link, aceitar convite, cargos, remover membros,
    sócios (2 owners) e transferência de posse. Registrado no app.py como um Blueprint
    do Flask (um grupo de rotas mantido no próprio arquivo).

EN: Rules (docs/ARCHITECTURE.md, sections 3, 5.4 and 8):
    * owner invites admins and members; admin invites only members
    * only the owner changes roles; nobody changes their own role here
    * owner removes admins and members; admin removes only members
    * nobody removes or demotes an owner (protects one partner from the other)
    * the last owner can't leave; they must transfer ownership first
    * plan limits (users, admins, members, owners) are checked before every change
PT: Regras (docs/ARCHITECTURE.md, seções 3, 5.4 e 8):
    * owner convida admins e members; admin convida só members
    * só o owner muda cargos; ninguém muda o próprio cargo aqui
    * owner remove admins e members; admin remove só members
    * ninguém remove nem rebaixa um owner (protege um sócio do outro)
    * o último owner não pode sair; precisa transferir a posse antes
    * os limites do plano (usuários, admins, members, owners) são conferidos antes de cada mudança
"""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from database import get_db
from helpers import (apology, hash_token, is_valid_email, login_required, new_token, now_utc, parse_percent, utc_in_days,
                     whatsapp_link)
from permissions import check_quota, get_scoped, has_role, require_role, workspace_id, workspace_plan
from translations import _

team_bp = Blueprint("team", __name__)

INVITE_DAYS = 7

# EN: Roles each role may invite | PT: Cargos que cada cargo pode convidar
INVITABLE_ROLES = {"owner": ("admin", "member"), "admin": ("member",), "member": ()}


# ---------------------------------------------------------------------------
# EN: Invite helpers (also used by the sign-up route in app.py)
# PT: Funções de convite (também usadas pela rota de cadastro no app.py)
# ---------------------------------------------------------------------------

def find_valid_invite(token):
    """EN: Find a pending, unexpired invite (staff or buyer) by its raw token (we compare
        hashes). For buyer invites it also brings the customer's name.
    PT: Procura um convite pendente e dentro da validade (equipe ou comprador) pelo token
        puro (compara os hashes). Para convites de comprador também traz o nome do cliente.
    """
    if not token:
        return None
    rows = get_db().execute(
        """
        SELECT i.*, w.name AS workspace_name, c.name AS company_name
          FROM invites i JOIN workspaces w ON w.id = i.workspace_id
          LEFT JOIN companies c ON c.id = i.company_id
         WHERE i.token_hash = ? AND i.accepted_at IS NULL AND i.expires_at > ?
        """,
        hash_token(token), now_utc(),
    )
    return rows[0] if rows else None


def accept_invite_for(invite, user_id):
    """EN: Accept any kind of invite for this user. Returns None or an error key.
        The caller wraps this in a transaction.
    PT: Aceita qualquer tipo de convite para este usuário. Devolve None ou uma chave de erro.
        Quem chama envolve isto numa transação.
    """
    if invite["kind"] == "customer":
        return accept_customer_invite(invite, user_id)
    return accept_staff_invite(invite, user_id)


def accept_customer_invite(invite, user_id):
    """EN: Link a buyer account to the invited customer. Buyers never count in the plan.
    PT: Liga uma conta de comprador ao cliente convidado. Compradores nunca contam no plano.
    """
    db = get_db()
    changed = db.execute("UPDATE invites SET accepted_at = ? WHERE id = ? AND accepted_at IS NULL",
                         now_utc(), invite["id"])
    if changed != 1:
        return "team.invite_invalid"
    already = db.execute("SELECT 1 FROM customer_users WHERE company_id = ? AND user_id = ?",
                         invite["company_id"], user_id)
    if not already:
        db.execute("INSERT INTO customer_users (workspace_id, company_id, user_id) VALUES (?, ?, ?)",
                   invite["workspace_id"], invite["company_id"], user_id)
    return None


def accept_staff_invite(invite, user_id):
    """EN: Add the user to the invite's workspace. Returns None on success or an error key.
        The caller wraps this in a transaction.
    PT: Adiciona o usuário à distribuidora do convite. Devolve None se deu certo ou uma
        chave de erro. Quem chama envolve isto numa transação.
    """
    db = get_db()

    already = db.execute("SELECT 1 FROM memberships WHERE workspace_id = ? AND user_id = ?",
                         invite["workspace_id"], user_id)
    if already:
        return "team.error_already_member"

    # EN: The pending invite is already counted in the usage, so adding=0: we only check
    #     that the plan wasn't downgraded after the invite was sent.
    # PT: O convite pendente já está contado no uso, então adding=0: só conferimos se o
    #     plano não foi rebaixado depois que o convite foi enviado.
    plan = workspace_plan(invite["workspace_id"])
    if not check_quota("users", 0, plan) or not check_quota(invite["role"] + "s", 0, plan):
        return "quota.exceeded"

    # EN: "WHERE accepted_at IS NULL" makes the invite single-use even if two requests
    #     arrive at the same time: only one UPDATE changes a row.
    # PT: "WHERE accepted_at IS NULL" deixa o convite de uso único mesmo se duas requisições
    #     chegarem ao mesmo tempo: só um UPDATE altera a linha.
    changed = db.execute("UPDATE invites SET accepted_at = ? WHERE id = ? AND accepted_at IS NULL",
                         now_utc(), invite["id"])
    if changed != 1:
        return "team.invite_invalid"

    db.execute("INSERT INTO memberships (workspace_id, user_id, role) VALUES (?, ?, ?)",
               invite["workspace_id"], user_id, invite["role"])
    return None


def load_member(user_id):
    """EN: A member of the active workspace, or None.
    PT: Um membro da distribuidora ativa, ou None.
    """
    rows = get_db().execute(
        """
        SELECT m.user_id, m.role, u.name, u.email
          FROM memberships m JOIN users u ON u.id = m.user_id
         WHERE m.workspace_id = ? AND m.user_id = ?
        """,
        workspace_id(), user_id,
    )
    if not rows:
        return None
    return rows[0]


# ---------------------------------------------------------------------------
# EN: Team page
# PT: Página da equipe
# ---------------------------------------------------------------------------

@team_bp.route("/team")
@require_role("admin")
def team():
    """EN: Members, pending invites and the invite form.
    PT: Membros, convites pendentes e o formulário de convite.
    """
    db = get_db()
    members = db.execute(
        """
        SELECT m.user_id, m.role, m.created_at, m.commission_bps, u.name, u.email
          FROM memberships m JOIN users u ON u.id = m.user_id
         WHERE m.workspace_id = ?
         ORDER BY CASE m.role WHEN 'owner' THEN 1 WHEN 'admin' THEN 2 ELSE 3 END, u.name
        """,
        workspace_id(),
    )
    invites = db.execute(
        """
        SELECT id, email, role, expires_at, created_at
          FROM invites
         WHERE workspace_id = ? AND kind = 'staff' AND accepted_at IS NULL AND expires_at > ?
         ORDER BY created_at DESC
        """,
        workspace_id(), now_utc(),
    )

    # EN: The raw link exists only right after creation (the database keeps only the hash),
    #     so it is shown once and removed from the session.
    # PT: O link puro só existe logo depois de criado (o banco guarda só o hash), então ele
    #     aparece uma vez e é removido da sessão.
    new_invite = session.pop("new_invite", None)

    return render_template(
        "team.html",
        members=members,
        invites=invites,
        new_invite=new_invite,
        invitable_roles=INVITABLE_ROLES[g.membership["role"]],
        can_add_owner=check_quota("owners"),
        my_id=g.user["id"],
    )


@team_bp.route("/team/invite", methods=["POST"])
@require_role("admin")
def invite():
    """EN: Create a staff invite and show its link once.
    PT: Cria um convite de equipe e mostra o link uma vez.
    """
    db = get_db()
    email = request.form.get("email", "").strip().lower()
    role = request.form.get("role", "")

    if not is_valid_email(email):
        flash(_("register.error_email"), "danger")
        return redirect("/team")

    # EN: The role must be one that the current user is allowed to invite
    # PT: O cargo precisa ser um que o usuário atual tem permissão de convidar
    if role not in INVITABLE_ROLES[g.membership["role"]]:
        flash(_("error.forbidden"), "danger")
        return redirect("/team")

    member = db.execute(
        "SELECT 1 FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.workspace_id = ? AND u.email = ?",
        workspace_id(), email,
    )
    if member:
        flash(_("team.error_already_member"), "danger")
        return redirect("/team")

    pending = db.execute(
        "SELECT 1 FROM invites WHERE workspace_id = ? AND kind = 'staff' AND email = ? "
        "AND accepted_at IS NULL AND expires_at > ?",
        workspace_id(), email, now_utc(),
    )
    if pending:
        flash(_("team.error_pending"), "danger")
        return redirect("/team")

    if not check_quota("users") or not check_quota(role + "s"):
        flash(_("quota.exceeded"), "warning")
        return redirect("/team")

    token, token_hash = new_token()
    db.execute(
        "INSERT INTO invites (workspace_id, kind, email, role, token_hash, created_by, expires_at) "
        "VALUES (?, 'staff', ?, ?, ?, ?, ?)",
        workspace_id(), email, role, token_hash, g.user["id"], utc_in_days(INVITE_DAYS),
    )

    # EN: There is no email server, so the link is shared by WhatsApp or copied.
    #     "https://wa.me/?text=..." (no number) lets the user pick the contact.
    # PT: Não há servidor de e-mail, então o link é compartilhado por WhatsApp ou copiado.
    #     "https://wa.me/?text=..." (sem número) deixa o usuário escolher o contato.
    link = url_for("team.show_invite", token=token, _external=True)
    message = _("team.whatsapp_message").replace("{workspace}", g.membership["workspace_name"]) + " " + link
    session["new_invite"] = {"email": email, "link": link, "share": whatsapp_link("", message)}
    return redirect("/team")


@team_bp.route("/team/invites/<int:invite_id>/revoke", methods=["POST"])
@require_role("admin")
def revoke_invite(invite_id):
    """EN: Cancel a pending invite by expiring it now (the row stays as history).
    PT: Cancela um convite pendente fazendo ele vencer agora (a linha fica como histórico).
    """
    invite_row = get_scoped("invites", invite_id)
    if invite_row["kind"] != "staff" or invite_row["accepted_at"] is not None:
        return apology(_("error.not_found"), 404)
    # EN: an admin can only revoke the invites they could have created (members)
    # PT: um admin só cancela convites que ele poderia ter criado (members)
    if invite_row["role"] not in INVITABLE_ROLES[g.membership["role"]]:
        return apology(_("error.forbidden"), 403)
    get_db().execute("UPDATE invites SET expires_at = ? WHERE id = ?", now_utc(), invite_id)
    flash(_("team.invite_revoked"), "success")
    return redirect("/team")


# ---------------------------------------------------------------------------
# EN: Managing members
# PT: Gerenciando membros
# ---------------------------------------------------------------------------

@team_bp.route("/team/members/<int:user_id>/role", methods=["POST"])
@require_role("owner")
def change_role(user_id):
    """EN: Switch a member between admin and member (owner only, never on an owner).
    PT: Troca um membro entre admin e member (só owner, nunca num owner).
    """
    member = load_member(user_id)
    new_role = request.form.get("role", "")
    if member is None or member["role"] == "owner" or user_id == g.user["id"]:
        return apology(_("error.forbidden"), 403)
    if new_role not in ("admin", "member"):
        return apology(_("error.forbidden"), 403)
    if new_role == member["role"]:
        return redirect("/team")
    if not check_quota(new_role + "s"):
        flash(_("quota.exceeded"), "warning")
        return redirect("/team")

    get_db().execute("UPDATE memberships SET role = ? WHERE workspace_id = ? AND user_id = ?",
                     new_role, workspace_id(), user_id)
    flash(_("team.role_changed"), "success")
    return redirect("/team")


@team_bp.route("/team/members/<int:user_id>/commission", methods=["POST"])
@require_role("owner")
def set_commission(user_id):
    """EN: Set the commission (%) of one person of the team, owners included. Only the owner
        decides pay. The value is typed as a percentage and stored in basis points.
    PT: Define a comissão (%) de uma pessoa da equipe, inclusive donos. Só o dono decide
        remuneração. O valor é digitado em porcentagem e guardado em basis points.
    """
    if not get_db().execute("SELECT 1 FROM memberships WHERE workspace_id = ? AND user_id = ?", workspace_id(), user_id):
        abort(404)
    raw = request.form.get("commission", "").strip()
    value = parse_percent(raw) if raw else 0
    if value is None:
        flash(_("team.error_commission"), "danger")
        return redirect("/team")
    get_db().execute("UPDATE memberships SET commission_bps = ? WHERE workspace_id = ? AND user_id = ?",
                     value, workspace_id(), user_id)
    flash(_("team.commission_saved"), "success")
    return redirect("/team")


@team_bp.route("/team/members/<int:user_id>/remove", methods=["POST"])
@require_role("admin")
def remove_member(user_id):
    """EN: Remove someone from the team. Their records stay in the workspace.
    PT: Remove alguém da equipe. Os registros da pessoa continuam na distribuidora.
    """
    member = load_member(user_id)
    if member is None or user_id == g.user["id"]:
        return apology(_("error.forbidden"), 403)

    # EN: owner removes admins and members; admin removes only members; nobody removes an owner
    # PT: owner remove admins e members; admin remove só members; ninguém remove um owner
    allowed = ("admin", "member") if has_role("owner") else ("member",)
    if member["role"] not in allowed:
        return apology(_("error.forbidden"), 403)

    get_db().execute("DELETE FROM memberships WHERE workspace_id = ? AND user_id = ?", workspace_id(), user_id)
    flash(_("team.member_removed"), "success")
    return redirect("/team")


@team_bp.route("/team/members/<int:user_id>/owner", methods=["POST"])
@require_role("owner")
def add_owner(user_id):
    """EN: Make a member a co-owner (partner). Only possible when the plan allows 2 owners.
    PT: Torna um membro sócio (owner). Só é possível quando o plano permite 2 owners.
    """
    member = load_member(user_id)
    if member is None or member["role"] == "owner":
        return apology(_("error.forbidden"), 403)
    if not check_quota("owners"):
        flash(_("quota.exceeded"), "warning")
        return redirect("/team")

    get_db().execute("UPDATE memberships SET role = 'owner' WHERE workspace_id = ? AND user_id = ?",
                     workspace_id(), user_id)
    flash(_("team.owner_added"), "success")
    return redirect("/team")


@team_bp.route("/team/members/<int:user_id>/transfer", methods=["POST"])
@require_role("owner")
def transfer_ownership(user_id):
    """EN: Hand the workspace over: the target becomes owner and the current owner becomes
        admin, in one transaction (the workspace is never left without an owner).
    PT: Passa a distribuidora adiante: o alvo vira owner e o owner atual vira admin, numa
        transação (a distribuidora nunca fica sem owner).
    """
    member = load_member(user_id)
    if member is None or member["role"] == "owner":
        return apology(_("error.forbidden"), 403)

    db = get_db()
    db.execute("BEGIN TRANSACTION")
    try:
        db.execute("UPDATE memberships SET role = 'owner' WHERE workspace_id = ? AND user_id = ?",
                   workspace_id(), user_id)
        db.execute("UPDATE memberships SET role = 'admin' WHERE workspace_id = ? AND user_id = ?",
                   workspace_id(), g.user["id"])
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    flash(_("team.ownership_transferred"), "success")
    return redirect("/dashboard")


@team_bp.route("/team/leave", methods=["POST"])
@require_role("member")
def leave():
    """EN: Leave the active workspace. The last owner can't leave.
    PT: Sair da distribuidora ativa. O último owner não pode sair.
    """
    db = get_db()
    if g.membership["role"] == "owner":
        owners = db.execute("SELECT COUNT(*) AS n FROM memberships WHERE workspace_id = ? AND role = 'owner'",
                            workspace_id())[0]["n"]
        if owners <= 1:
            flash(_("team.error_last_owner"), "danger")
            return redirect("/team")

    db.execute("DELETE FROM memberships WHERE workspace_id = ? AND user_id = ?", workspace_id(), g.user["id"])
    session.pop("workspace_id", None)
    flash(_("team.left"), "success")
    return redirect("/")


# ---------------------------------------------------------------------------
# EN: Opening and accepting an invite
# PT: Abrindo e aceitando um convite
# ---------------------------------------------------------------------------

@team_bp.route("/invite/<token>")
def show_invite(token):
    """EN: Landing page of an invite link. Works logged in or out.
    PT: Página de chegada do link de convite. Funciona logado ou não.
    """
    invite_row = find_valid_invite(token)
    if invite_row is None:
        return apology(_("team.invite_invalid"), 404)
    email_matches = g.user is not None and g.user["email"] == invite_row["email"]
    return render_template("invite.html", invite=invite_row, token=token, email_matches=email_matches)


@team_bp.route("/invite/<token>/accept", methods=["POST"])
@login_required
def accept_invite(token):
    """EN: Accept an invite. The logged-in account must have the invited email, so a
        leaked link alone is not enough to join.
    PT: Aceita um convite. A conta logada precisa ter o e-mail convidado, então só o link
        vazado não basta para entrar.
    """
    invite_row = find_valid_invite(token)
    if invite_row is None:
        return apology(_("team.invite_invalid"), 404)
    if g.user["email"] != invite_row["email"]:
        return apology(_("team.error_wrong_email"), 403)

    db = get_db()
    db.execute("BEGIN TRANSACTION")
    try:
        error = accept_invite_for(invite_row, g.user["id"])
        db.execute("ROLLBACK" if error else "COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    if error:
        return apology(_(error), 400)

    if invite_row["kind"] == "customer":
        flash(_("portal.linked").replace("{workspace}", invite_row["workspace_name"]), "success")
        return redirect("/portal")
    session["workspace_id"] = invite_row["workspace_id"]
    flash(_("team.joined").replace("{workspace}", invite_row["workspace_name"]), "success")
    return redirect("/dashboard")
