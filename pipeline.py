"""EN: Sales pipeline: board of opportunities by stage, opportunity CRUD, stage changes with
    history, and pipeline/stage settings. Registered in app.py as a Blueprint.
PT: Funil de vendas: quadro de oportunidades por etapa, cadastro de oportunidades, mudança
    de etapa com histórico, e configuração de funis e etapas. Registrado no app.py como Blueprint.

EN: Rules (docs/ARCHITECTURE.md, sections 5.9, 5.10, 6.8, 6.9 and 8):
    * the stage must belong to the opportunity's pipeline (the database also checks it)
    * entering a won/lost stage sets closed_at; going back to an open stage clears it
    * every stage change writes an insert-only activity ("Novo -> Contatado")
    * a seller (member) sees, edits and moves only their own opportunities (others answer 404);
      admins and owners see all; members delete only their own; an opportunity with quotes
      can't be deleted
    * moving to a won stage without an accepted quote is a manual win: it needs a value and is
      marked closed_manually (reported apart on the dashboard)
    * only admins and owners configure stages; a pipeline always keeps at least one won and
      one lost stage; a stage in use can't be deleted; extra pipelines need the plan feature
PT: Regras (docs/ARCHITECTURE.md, seções 5.9, 5.10, 6.8, 6.9 e 8):
    * a etapa precisa ser do funil da oportunidade (o banco também confere)
    * entrar numa etapa won/lost preenche closed_at; voltar para uma etapa open limpa
    * toda mudança de etapa grava uma atividade só de inserção ("Novo -> Contatado")
    * um vendedor (member) vê, edita e move só as próprias oportunidades (as outras dão 404);
      admins e owners veem todas; members apagam só as próprias; oportunidade com orçamento
      não pode ser apagada
    * mover para uma etapa ganha sem orçamento aceito é um ganho manual: exige valor e fica
      marcado closed_manually (contado à parte no painel)
    * só admins e owners configuram etapas; um funil sempre mantém pelo menos uma etapa won
      e uma lost; etapa em uso não pode ser apagada; funis extras dependem do recurso do plano
"""

from datetime import datetime

from flask import Blueprint, flash, g, redirect, render_template, request

from database import get_db
from helpers import apology, money_input, now_utc, parse_money, safe_redirect_target
from permissions import (can_modify, check_quota, find_scoped, get_scoped, get_visible_opportunity, has_feature,
                         has_role, is_workspace_user, require_role, sees_all_sales, workspace_id)
from tasks import tasks_for
from translations import _

pipeline_bp = Blueprint("pipeline", __name__)

TITLE_MAX = 120
STAGE_NAME_MAX = 40
REASON_MAX = 200
KINDS = ("open", "won", "lost")


# ---------------------------------------------------------------------------
# EN: Queries
# PT: Consultas
# ---------------------------------------------------------------------------

def pipelines():
    """EN: All pipelines of the active workspace, default first.
    PT: Todos os funis da distribuidora ativa, o padrão primeiro.
    """
    return get_db().execute(
        "SELECT * FROM pipelines WHERE workspace_id = ? ORDER BY is_default DESC, position, id", workspace_id()
    )


def stages_of(pipeline_id):
    """EN: Stages of a pipeline in board order. | PT: Etapas de um funil na ordem do quadro."""
    return get_db().execute(
        "SELECT * FROM stages WHERE pipeline_id = ? AND workspace_id = ? ORDER BY position, id",
        pipeline_id, workspace_id(),
    )


def current_pipeline():
    """EN: Pipeline chosen in ?p= (only if it is ours), otherwise the default one.
    PT: Funil escolhido em ?p= (só se for nosso), senão o padrão.
    """
    chosen = find_scoped("pipelines", request.args.get("p"))
    return chosen or pipelines()[0]


def log_activity(kind, body, opportunity):
    """EN: Insert-only history line about an opportunity (and its customer).
    PT: Linha de histórico, só de inserção, sobre uma oportunidade (e o cliente dela).
    """
    get_db().execute(
        "INSERT INTO activities (workspace_id, user_id, type, body, company_id, opportunity_id) VALUES (?, ?, ?, ?, ?, ?)",
        workspace_id(), g.user["id"], kind, body, opportunity["company_id"], opportunity["id"],
    )


# ---------------------------------------------------------------------------
# EN: Board
# PT: Quadro
# ---------------------------------------------------------------------------

@pipeline_bp.route("/pipeline")
@require_role("member")
def board():
    """EN: Board: one column per stage, opportunity cards inside, totals per column.
    PT: Quadro: uma coluna por etapa, cartões de oportunidade dentro, totais por coluna.
    """
    pipeline = current_pipeline()
    # EN: sellers always see only their own cards | PT: vendedores sempre veem só os próprios cartões
    owner = request.args.get("owner", "") if sees_all_sales() else "me"
    params = [pipeline["id"], workspace_id()]
    owner_filter = ""
    if owner == "me":
        owner_filter = " AND o.owner_id = ?"
        params.append(g.user["id"])

    opportunities = get_db().execute(
        "SELECT o.*, c.name AS company_name, u.name AS owner_name "
        "FROM opportunities o JOIN companies c ON c.id = o.company_id "
        "LEFT JOIN users u ON u.id = o.owner_id "
        "WHERE o.pipeline_id = ? AND o.workspace_id = ?" + owner_filter + " ORDER BY o.updated_at DESC",
        *params,
    )

    columns = []
    for stage in stages_of(pipeline["id"]):
        cards = [o for o in opportunities if o["stage_id"] == stage["id"]]
        columns.append({"stage": stage, "cards": cards, "total": sum(o["value_cents"] for o in cards)})

    return render_template(
        "pipeline.html",
        pipeline=pipeline,
        pipelines=pipelines(),
        columns=columns,
        owner=owner,
        stages=stages_of(pipeline["id"]),
    )


# ---------------------------------------------------------------------------
# EN: Opportunities
# PT: Oportunidades
# ---------------------------------------------------------------------------

def form_options():
    db = get_db()
    return {
        "companies": db.execute("SELECT id, name FROM companies WHERE workspace_id = ? ORDER BY name COLLATE NOCASE", workspace_id()),
        "contacts": db.execute("SELECT id, name, company_id FROM contacts WHERE workspace_id = ? ORDER BY name COLLATE NOCASE", workspace_id()),
        "pipelines": pipelines(),
        "stages": db.execute("SELECT * FROM stages WHERE workspace_id = ? ORDER BY pipeline_id, position, id", workspace_id()),
        "staff": db.execute(
            "SELECT u.id, u.name FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.workspace_id = ? ORDER BY u.name",
            workspace_id(),
        ),
    }


def read_opportunity_form(existing=None):
    """EN: Read and validate the opportunity form. Every id from the browser is checked
        against the active workspace. Returns (form, values, errors).
    PT: Lê e valida o formulário de oportunidade. Todo id vindo do navegador é conferido
        contra a distribuidora ativa. Devolve (form, valores, erros).
    """
    form = {key: request.form.get(key, "").strip() for key in
            ("title", "company_id", "contact_id", "pipeline_id", "stage_id", "value", "expected_close", "owner_id")}
    errors = []

    if not 2 <= len(form["title"]) <= TITLE_MAX:
        errors.append("pipeline.error_title")

    company = find_scoped("companies", form["company_id"])
    if company is None:
        errors.append("pipeline.error_company")

    # EN: The contact is optional, but if sent it must be a contact of THAT customer
    # PT: O contato é opcional, mas se vier precisa ser contato DAQUELE cliente
    contact_id = None
    if form["contact_id"]:
        contact = find_scoped("contacts", form["contact_id"])
        if contact is None or company is None or contact["company_id"] != company["id"]:
            errors.append("pipeline.error_contact")
        else:
            contact_id = contact["id"]

    # EN: Stage only on creation (afterwards it moves through /stage). The pipeline is the
    #     stage's own pipeline, so the two can never disagree.
    # PT: Etapa só na criação (depois ela muda pela rota /stage). O funil é o da própria
    #     etapa, então os dois nunca discordam.
    pipeline_id = stage_id = None
    if existing is None:
        stage = find_scoped("stages", form["stage_id"])
        if stage is None:
            errors.append("pipeline.error_stage")
        else:
            pipeline_id, stage_id = stage["pipeline_id"], stage["id"]

    value = 0
    if form["value"]:
        value = parse_money(form["value"])
        if value is None:
            errors.append("pipeline.error_value")
            value = 0

    expected_close = None
    if form["expected_close"]:
        try:
            expected_close = datetime.strptime(form["expected_close"], "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            errors.append("pipeline.error_date")

    # EN: Same rule as customers: only admins choose the responsible seller
    # PT: Mesma regra dos clientes: só admins escolhem o vendedor responsável
    if has_role("admin"):
        if form["owner_id"] and not is_workspace_user(form["owner_id"]):
            errors.append("customers.error_owner")
        owner_id = int(form["owner_id"]) if form["owner_id"].isdigit() else None
    else:
        owner_id = existing["owner_id"] if existing else g.user["id"]

    values = {
        "title": form["title"], "company_id": company["id"] if company else None, "contact_id": contact_id,
        "pipeline_id": pipeline_id, "stage_id": stage_id, "value_cents": value,
        "expected_close": expected_close, "owner_id": owner_id,
    }
    return form, values, errors


def opportunity_form_page(form, errors, opportunity, status=200):
    return render_template("opportunity_form.html", form=form, errors=errors, opportunity=opportunity, **form_options()), status


@pipeline_bp.route("/opportunities/new", methods=["GET", "POST"])
@require_role("member")
def create():
    """EN: New opportunity. ?company=<id> pre-selects the customer (from the customer page).
    PT: Nova oportunidade. ?company=<id> já escolhe o cliente (vindo da página do cliente).
    """
    if request.method == "GET":
        pipeline = current_pipeline()
        first_stage = stages_of(pipeline["id"])[0]
        company = find_scoped("companies", request.args.get("company"))
        form = {
            "company_id": str(company["id"]) if company else "",
            "pipeline_id": str(pipeline["id"]), "stage_id": str(first_stage["id"]),
            "owner_id": str(g.user["id"]),
        }
        return opportunity_form_page(form, [], None)

    form, values, errors = read_opportunity_form()
    if errors:
        return opportunity_form_page(form, errors, None, 400)

    stage = get_scoped("stages", values["stage_id"])
    # EN: born as won = a sale closed outside the system: it needs a value and is marked as manual
    # PT: nascer como ganha = venda fechada fora do sistema: precisa de valor e fica marcada como manual
    if stage["kind"] == "won" and values["value_cents"] <= 0:
        return opportunity_form_page(form, ["pipeline.error_won_value"], None, 400)
    closed_at = now_utc() if stage["kind"] in ("won", "lost") else None
    opportunity_id = get_db().execute(
        "INSERT INTO opportunities (workspace_id, pipeline_id, stage_id, company_id, contact_id, owner_id, "
        "title, value_cents, expected_close, closed_at, closed_manually) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        workspace_id(), values["pipeline_id"], values["stage_id"], values["company_id"], values["contact_id"],
        values["owner_id"], values["title"], values["value_cents"], values["expected_close"], closed_at,
        1 if stage["kind"] == "won" else 0,
    )
    flash(_("pipeline.created"), "success")
    return redirect(f"/opportunities/{opportunity_id}")


def load_opportunity(opportunity_id):
    """EN: Opportunity of the active workspace with names for display, or 404.
    PT: Oportunidade da distribuidora ativa com os nomes para exibir, ou 404.
    """
    get_visible_opportunity(opportunity_id)
    return get_db().execute(
        "SELECT o.*, c.name AS company_name, k.name AS contact_name, u.name AS owner_name, "
        "s.name AS stage_name, s.kind AS stage_kind, p.name AS pipeline_name "
        "FROM opportunities o JOIN companies c ON c.id = o.company_id "
        "JOIN stages s ON s.id = o.stage_id JOIN pipelines p ON p.id = o.pipeline_id "
        "LEFT JOIN contacts k ON k.id = o.contact_id LEFT JOIN users u ON u.id = o.owner_id "
        "WHERE o.id = ? AND o.workspace_id = ?",
        opportunity_id, workspace_id(),
    )[0]


@pipeline_bp.route("/opportunities/<int:opportunity_id>")
@require_role("member")
def show(opportunity_id):
    """EN: Opportunity page: data, stage track with move buttons, history.
    PT: Página da oportunidade: dados, trilho de etapas com botões de mover, histórico.
    """
    opportunity = load_opportunity(opportunity_id)
    history = get_db().execute(
        "SELECT a.*, u.name AS user_name FROM activities a LEFT JOIN users u ON u.id = a.user_id "
        "WHERE a.opportunity_id = ? AND a.workspace_id = ? ORDER BY a.created_at DESC, a.id DESC",
        opportunity_id, workspace_id(),
    )
    quotes = get_db().execute(
        "SELECT id, number, status, final_total_cents, created_at FROM quotes "
        "WHERE opportunity_id = ? AND workspace_id = ? ORDER BY number DESC",
        opportunity_id, workspace_id(),
    )
    return render_template(
        "opportunity.html",
        opportunity=opportunity,
        quotes=quotes,
        can_quote=check_quota("quotes_month"),
        tasks=tasks_for("opportunity_id", opportunity_id),
        staff=get_db().execute(
            "SELECT u.id, u.name FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.workspace_id = ? ORDER BY u.name",
            workspace_id(),
        ),
        stages=stages_of(opportunity["pipeline_id"]),
        history=history,
        can_delete=can_modify(opportunity),
    )


@pipeline_bp.route("/opportunities/<int:opportunity_id>/edit", methods=["GET", "POST"])
@require_role("member")
def edit(opportunity_id):
    """EN: Edit title, customer, contact, value, expected close and (admins) seller.
    PT: Edita título, cliente, contato, valor, previsão e (admins) vendedor.
    """
    opportunity = get_visible_opportunity(opportunity_id)

    if request.method == "GET":
        form = {
            "title": opportunity["title"], "company_id": str(opportunity["company_id"]),
            "contact_id": str(opportunity["contact_id"] or ""), "value": money_input(opportunity["value_cents"]),
            "expected_close": opportunity["expected_close"] or "", "owner_id": str(opportunity["owner_id"] or ""),
        }
        return opportunity_form_page(form, [], opportunity)

    form, values, errors = read_opportunity_form(existing=opportunity)
    if errors:
        return opportunity_form_page(form, errors, opportunity, 400)

    get_db().execute(
        "UPDATE opportunities SET title = ?, company_id = ?, contact_id = ?, value_cents = ?, expected_close = ?, "
        "owner_id = ?, updated_at = ? WHERE id = ? AND workspace_id = ?",
        values["title"], values["company_id"], values["contact_id"], values["value_cents"], values["expected_close"],
        values["owner_id"], now_utc(), opportunity_id, workspace_id(),
    )
    flash(_("pipeline.saved"), "success")
    return redirect(f"/opportunities/{opportunity_id}")


@pipeline_bp.route("/opportunities/<int:opportunity_id>/stage", methods=["POST"])
@require_role("member")
def move(opportunity_id):
    """EN: Move to another stage of the SAME pipeline. Sets or clears closed_at, keeps the
        lost reason, and writes the history line, all in one transaction.
    PT: Move para outra etapa do MESMO funil. Preenche ou limpa closed_at, guarda o motivo
        de perda e grava a linha de histórico, tudo numa transação.
    """
    opportunity = load_opportunity(opportunity_id)
    stage = find_scoped("stages", request.form.get("stage_id"))
    back = safe_redirect_target(request.form.get("next"), f"/opportunities/{opportunity_id}")

    if stage is None or stage["pipeline_id"] != opportunity["pipeline_id"]:
        return apology(_("pipeline.error_stage"), 400)
    if stage["id"] == opportunity["stage_id"]:
        return redirect(back)

    # EN: won without an accepted quote = manual win: only with a value, and marked apart
    # PT: ganha sem orçamento aceito = ganho manual: só com valor, e marcado à parte
    manual = 0
    if stage["kind"] == "won":
        accepted = get_db().execute(
            "SELECT 1 FROM quotes WHERE opportunity_id = ? AND workspace_id = ? AND status = 'accepted' LIMIT 1",
            opportunity_id, workspace_id())
        if not accepted:
            if opportunity["value_cents"] <= 0:
                flash(_("pipeline.error_won_value"), "danger")
                return redirect(back)
            manual = 1

    reason = request.form.get("lost_reason", "").strip()[:REASON_MAX] or None
    if stage["kind"] in ("won", "lost"):
        closed_at = now_utc()
    else:
        closed_at = None
        reason = None
    if stage["kind"] != "lost":
        reason = None

    body = (f"{opportunity['stage_name']} → {stage['name']}" + (f" · {reason}" if reason else "")
            + (" · " + _("pipeline.closed_manually") if manual else ""))

    db = get_db()
    db.execute("BEGIN TRANSACTION")
    try:
        db.execute(
            "UPDATE opportunities SET stage_id = ?, closed_at = ?, lost_reason = ?, closed_manually = ?, updated_at = ? "
            "WHERE id = ? AND workspace_id = ?",
            stage["id"], closed_at, reason, manual, now_utc(), opportunity_id, workspace_id(),
        )
        log_activity("stage_change", body, opportunity)
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    flash(_("pipeline.moved").replace("{stage}", stage["name"]), "success")
    return redirect(back)


@pipeline_bp.route("/opportunities/<int:opportunity_id>/delete", methods=["POST"])
@require_role("member")
def delete(opportunity_id):
    """EN: Delete an opportunity (members only their own; blocked when it has quotes).
        Its tasks and history go with it (ON DELETE CASCADE).
    PT: Apaga uma oportunidade (members só as próprias; bloqueado quando há orçamentos).
        As tarefas e o histórico dela vão junto (ON DELETE CASCADE).
    """
    opportunity = get_visible_opportunity(opportunity_id)
    if not can_modify(opportunity):
        return apology(_("pipeline.error_not_yours"), 403)
    try:
        get_db().execute("DELETE FROM opportunities WHERE id = ? AND workspace_id = ?", opportunity_id, workspace_id())
    except ValueError:
        flash(_("pipeline.error_has_quotes"), "danger")
        return redirect(f"/opportunities/{opportunity_id}")
    flash(_("pipeline.deleted"), "success")
    return redirect(f"/pipeline?p={opportunity['pipeline_id']}")


# ---------------------------------------------------------------------------
# EN: Settings (admins and owners)
# PT: Configuração (admins e owners)
# ---------------------------------------------------------------------------

def kind_count(pipeline_id, kind):
    return get_db().execute(
        "SELECT COUNT(*) AS n FROM stages WHERE pipeline_id = ? AND workspace_id = ? AND kind = ?",
        pipeline_id, workspace_id(), kind,
    )[0]["n"]


@pipeline_bp.route("/pipeline/settings")
@require_role("admin")
def settings():
    """EN: Pipelines and their stages, with the number of opportunities in each stage.
    PT: Funis e suas etapas, com o número de oportunidades em cada etapa.
    """
    data = []
    for pipeline in pipelines():
        stages = get_db().execute(
            "SELECT s.*, (SELECT COUNT(*) FROM opportunities o WHERE o.stage_id = s.id) AS in_use "
            "FROM stages s WHERE s.pipeline_id = ? AND s.workspace_id = ? ORDER BY s.position, s.id",
            pipeline["id"], workspace_id(),
        )
        data.append({"pipeline": pipeline, "stages": stages})
    return render_template("pipeline_settings.html", data=data, can_add_pipeline=has_feature("multi_pipeline"))


def back_to_settings():
    return redirect("/pipeline/settings")


@pipeline_bp.route("/pipeline/<int:pipeline_id>/stages", methods=["POST"])
@require_role("admin")
def add_stage(pipeline_id):
    """EN: Add a stage at the end of the open stages (before won/lost).
    PT: Adiciona uma etapa no fim das etapas abertas (antes de won/lost).
    """
    pipeline = get_scoped("pipelines", pipeline_id)
    name = request.form.get("name", "").strip()
    kind = request.form.get("kind", "open")
    if not 1 <= len(name) <= STAGE_NAME_MAX or kind not in KINDS:
        flash(_("pipeline.error_stage_name"), "danger")
        return back_to_settings()

    db = get_db()
    # EN: open stages go right after the last open one; won/lost go to the end
    # PT: etapas abertas entram logo depois da última aberta; won/lost vão para o fim
    if kind == "open":
        last_open = db.execute("SELECT MAX(position) AS m FROM stages WHERE pipeline_id = ? AND kind = 'open'", pipeline["id"])[0]["m"]
        position = (last_open if last_open is not None else -1) + 1
        db.execute("UPDATE stages SET position = position + 1 WHERE pipeline_id = ? AND position >= ?", pipeline["id"], position)
    else:
        position = db.execute("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM stages WHERE pipeline_id = ?", pipeline["id"])[0]["p"]
    db.execute(
        "INSERT INTO stages (workspace_id, pipeline_id, name, position, kind) VALUES (?, ?, ?, ?, ?)",
        workspace_id(), pipeline["id"], name, position, kind,
    )
    flash(_("pipeline.stage_added"), "success")
    return back_to_settings()


@pipeline_bp.route("/stages/<int:stage_id>/rename", methods=["POST"])
@require_role("admin")
def rename_stage(stage_id):
    stage = get_scoped("stages", stage_id)
    name = request.form.get("name", "").strip()
    if not 1 <= len(name) <= STAGE_NAME_MAX:
        flash(_("pipeline.error_stage_name"), "danger")
        return back_to_settings()
    get_db().execute("UPDATE stages SET name = ? WHERE id = ? AND workspace_id = ?", name, stage["id"], workspace_id())
    flash(_("pipeline.stage_saved"), "success")
    return back_to_settings()


@pipeline_bp.route("/stages/<int:stage_id>/move", methods=["POST"])
@require_role("admin")
def reorder_stage(stage_id):
    """EN: Swap a stage with its neighbor (up or down) inside the same pipeline.
    PT: Troca uma etapa de lugar com a vizinha (para cima ou para baixo) no mesmo funil.
    """
    stage = get_scoped("stages", stage_id)
    siblings = stages_of(stage["pipeline_id"])
    index = next(i for i, s in enumerate(siblings) if s["id"] == stage["id"])
    target = index - 1 if request.form.get("direction") == "up" else index + 1
    if 0 <= target < len(siblings):
        db = get_db()
        # EN: renumber the whole list so positions stay 0..n-1 | PT: renumera a lista para as posições ficarem 0..n-1
        siblings[index], siblings[target] = siblings[target], siblings[index]
        for position, s in enumerate(siblings):
            db.execute("UPDATE stages SET position = ? WHERE id = ? AND workspace_id = ?", position, s["id"], workspace_id())
    return back_to_settings()


@pipeline_bp.route("/stages/<int:stage_id>/delete", methods=["POST"])
@require_role("admin")
def delete_stage(stage_id):
    """EN: Delete a stage: refused when in use, or when it is the last won/lost stage.
    PT: Apaga uma etapa: recusado quando está em uso, ou quando é a última won/lost.
    """
    stage = get_scoped("stages", stage_id)
    if stage["kind"] in ("won", "lost") and kind_count(stage["pipeline_id"], stage["kind"]) <= 1:
        flash(_("pipeline.error_last_kind"), "danger")
        return back_to_settings()
    if kind_count(stage["pipeline_id"], "open") <= 1 and stage["kind"] == "open":
        flash(_("pipeline.error_last_open"), "danger")
        return back_to_settings()
    try:
        get_db().execute("DELETE FROM stages WHERE id = ? AND workspace_id = ?", stage["id"], workspace_id())
    except ValueError:
        flash(_("pipeline.error_stage_in_use"), "danger")
        return back_to_settings()
    flash(_("pipeline.stage_deleted"), "success")
    return back_to_settings()


@pipeline_bp.route("/pipelines", methods=["POST"])
@require_role("admin")
def add_pipeline():
    """EN: Create another pipeline (plan feature), with the same 5 starting stages.
    PT: Cria outro funil (recurso do plano), com as mesmas 5 etapas iniciais.
    """
    if not has_feature("multi_pipeline"):
        flash(_("feature.unavailable"), "warning")
        return back_to_settings()
    name = request.form.get("name", "").strip()
    if not 2 <= len(name) <= STAGE_NAME_MAX:
        flash(_("pipeline.error_pipeline_name"), "danger")
        return back_to_settings()

    from app import DEFAULT_PIPELINE   # EN: local import avoids a circular import | PT: import local evita import circular
    from translations import current_lang
    _unused, stages = DEFAULT_PIPELINE[current_lang()]
    db = get_db()
    db.execute("BEGIN TRANSACTION")
    try:
        position = db.execute("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM pipelines WHERE workspace_id = ?", workspace_id())[0]["p"]
        pipeline_id = db.execute("INSERT INTO pipelines (workspace_id, name, position) VALUES (?, ?, ?)", workspace_id(), name, position)
        for index, (stage_name, kind) in enumerate(stages):
            db.execute("INSERT INTO stages (workspace_id, pipeline_id, name, position, kind) VALUES (?, ?, ?, ?, ?)",
                       workspace_id(), pipeline_id, stage_name, index, kind)
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    flash(_("pipeline.pipeline_added"), "success")
    return back_to_settings()


@pipeline_bp.route("/pipelines/<int:pipeline_id>/rename", methods=["POST"])
@require_role("admin")
def rename_pipeline(pipeline_id):
    pipeline = get_scoped("pipelines", pipeline_id)
    name = request.form.get("name", "").strip()
    if not 2 <= len(name) <= STAGE_NAME_MAX:
        flash(_("pipeline.error_pipeline_name"), "danger")
        return back_to_settings()
    get_db().execute("UPDATE pipelines SET name = ? WHERE id = ? AND workspace_id = ?", name, pipeline["id"], workspace_id())
    flash(_("pipeline.pipeline_saved"), "success")
    return back_to_settings()


@pipeline_bp.route("/pipelines/<int:pipeline_id>/delete", methods=["POST"])
@require_role("admin")
def delete_pipeline(pipeline_id):
    """EN: Delete an extra pipeline. The default one stays; a pipeline with opportunities stays.
    PT: Apaga um funil extra. O padrão fica; funil com oportunidades fica.
    """
    pipeline = get_scoped("pipelines", pipeline_id)
    if pipeline["is_default"]:
        flash(_("pipeline.error_default"), "danger")
        return back_to_settings()
    try:
        get_db().execute("DELETE FROM pipelines WHERE id = ? AND workspace_id = ?", pipeline["id"], workspace_id())
    except ValueError:
        flash(_("pipeline.error_pipeline_in_use"), "danger")
        return back_to_settings()
    flash(_("pipeline.pipeline_deleted"), "success")
    return back_to_settings()
