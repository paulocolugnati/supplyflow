"""
EN: The distributor's own data and setup (owner only). Registered in app.py as a Blueprint.
    * /onboarding          step 1 of the first setup: company data + logo (all required but
                           the logo)
    * /onboarding/limits   step 2: discount ceilings and minimum margin; also used later
                           from the dashboard and settings to adjust them
    * /settings            company data after the setup: e-mail, WhatsApp, city and logo
                           change here; name and CNPJ only through support (platform
                           panel), because they identify the company on every quote
    Logo upload: PNG, JPEG or WebP up to 1 MB. The file type is checked by its first bytes
    (not by the name the user gave it), and it is saved with a random name, so an upload can
    never overwrite another file or run as a script. SVG is refused: it can carry scripts.
PT: Os dados e a configuração da própria distribuidora (só o owner). Registrado no app.py
    como um Blueprint.
    * /onboarding          passo 1 da configuração inicial: dados da empresa + logo (tudo
                           obrigatório menos a logo)
    * /onboarding/limits   passo 2: tetos de desconto e margem mínima; usado também depois,
                           pelo painel e pelas configurações, para ajustá-los
    * /settings            dados da empresa depois da configuração: e-mail, WhatsApp, cidade
                           e logo mudam aqui; nome e CNPJ só pelo suporte (painel da
                           plataforma), porque identificam a empresa em todo orçamento
    Upload da logo: PNG, JPEG ou WebP até 1 MB. O tipo é conferido pelos primeiros bytes do
    arquivo (não pelo nome que a pessoa deu), e ele é salvo com um nome aleatório, então um
    upload nunca sobrescreve outro arquivo nem roda como script. SVG é recusado: pode levar scripts.
"""

import os
import secrets

from flask import Blueprint, current_app, flash, g, redirect, render_template, request

from database import get_db
from helpers import (is_valid_email, normalize_cnpj, normalize_phone, parse_percent, support_link)
from permissions import require_role, workspace_id
from translations import _

settings_bp = Blueprint("settings", __name__)

NAME_MAX = 100
CITY_MAX = 80
LOGO_MAX_BYTES = 1024 * 1024
LOGO_DIR = ("uploads", "logos")
# EN: first bytes ("magic numbers") of each accepted image type -> file extension
# PT: primeiros bytes ("números mágicos") de cada tipo de imagem aceito -> extensão
LOGO_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
)


def workspace_row():
    """EN: The active workspace with its company data. | PT: A distribuidora ativa com os dados da empresa."""
    return get_db().execute("SELECT * FROM workspaces WHERE id = ?", workspace_id())[0]


def logo_extension(data):
    """EN: 'png', 'jpg' or 'webp' when the bytes really are that image type, else None.
    PT: 'png', 'jpg' ou 'webp' quando os bytes são mesmo desse tipo de imagem, senão None.
    """
    for signature, extension in LOGO_SIGNATURES:
        if data.startswith(signature):
            return extension
    # EN: WebP = "RIFF" + 4 size bytes + "WEBP" | PT: WebP = "RIFF" + 4 bytes de tamanho + "WEBP"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def read_logo():
    """EN: Validate the uploaded logo. Returns (bytes and extension, error key); (None, None)
        when no file was sent.
    PT: Valida a logo enviada. Devolve (bytes e extensão, chave de erro); (None, None)
        quando nenhum arquivo foi enviado.
    """
    upload = request.files.get("logo")
    if upload is None or not upload.filename:
        return None, None
    data = upload.read(LOGO_MAX_BYTES + 1)
    if len(data) > LOGO_MAX_BYTES:
        return None, "settings.error_logo_size"
    extension = logo_extension(data)
    if extension is None:
        return None, "settings.error_logo_type"
    return (data, extension), None


def store_logo(logo, old_path):
    """EN: Save the logo under a random name and remove the previous one. Returns the URL path.
    PT: Salva a logo com um nome aleatório e apaga a anterior. Devolve o caminho da URL.
    """
    data, extension = logo
    folder = os.path.join(current_app.static_folder, *LOGO_DIR)
    os.makedirs(folder, exist_ok=True)
    name = f"{secrets.token_hex(16)}.{extension}"
    with open(os.path.join(folder, name), "wb") as file:
        file.write(data)
    remove_logo_file(old_path)
    return "/static/" + "/".join(LOGO_DIR) + "/" + name


def remove_logo_file(path):
    """EN: Delete a logo file this app created. Only paths inside the logo folder, with a
        plain file name, are touched (never "../" or another folder).
    PT: Apaga um arquivo de logo que o próprio sistema criou. Só caminhos dentro da pasta de
        logos, com um nome de arquivo simples, são mexidos (nunca "../" ou outra pasta).
    """
    prefix = "/static/" + "/".join(LOGO_DIR) + "/"
    if not path or not path.startswith(prefix):
        return
    name = path[len(prefix):]
    if not name or "/" in name or "\\" in name or ".." in name:
        return
    full = os.path.join(current_app.static_folder, *LOGO_DIR, name)
    if os.path.isfile(full):
        os.remove(full)


def read_company_form(identity_editable):
    """EN: Read and validate the company data. Name and CNPJ are read only when they may be
        changed here (first setup, or a CNPJ never filled). Returns (form, values, errors).
    PT: Lê e valida os dados da empresa. Nome e CNPJ só são lidos quando podem mudar aqui
        (configuração inicial, ou CNPJ nunca preenchido). Devolve (form, valores, erros).
    """
    form = {key: request.form.get(key, "").strip() for key in ("name", "cnpj", "email", "phone", "city")}
    values, errors = {}, []

    if identity_editable:
        if not 2 <= len(form["name"]) <= NAME_MAX:
            errors.append("register.error_workspace")
        values["name"] = form["name"]
        cnpj = normalize_cnpj(form["cnpj"])
        if cnpj is None:
            errors.append("customers.error_cnpj")
        elif get_db().execute("SELECT 1 FROM workspaces WHERE cnpj = ? AND id <> ?", cnpj, workspace_id()):
            errors.append("settings.error_cnpj_taken")
        values["cnpj"] = cnpj

    email = form["email"].lower()
    if not is_valid_email(email):
        errors.append("register.error_email")
    values["email"] = email

    phone = normalize_phone(form["phone"])
    if phone is None:
        errors.append("register.error_phone")
    values["phone"] = phone

    if not 2 <= len(form["city"]) <= CITY_MAX:
        errors.append("settings.error_city")
    values["city"] = form["city"]
    return form, values, errors


def save_company(values, logo, remove_logo=False):
    """EN: Write the validated values (only the given columns; names come from code).
    PT: Grava os valores validados (só as colunas recebidas; os nomes vêm do código).
    """
    current = workspace_row()
    columns = dict(values)
    if logo:
        columns["logo_path"] = store_logo(logo, current["logo_path"])
    elif remove_logo:
        remove_logo_file(current["logo_path"])
        columns["logo_path"] = None
    allowed = ("name", "cnpj", "email", "phone", "city", "logo_path")
    assignments = ", ".join(f"{column} = ?" for column in columns if column in allowed)
    get_db().execute(f"UPDATE workspaces SET {assignments} WHERE id = ?",
                     *[columns[c] for c in columns if c in allowed], workspace_id())


# ---------------------------------------------------------------------------
# EN: First setup | PT: Configuração inicial
# ---------------------------------------------------------------------------

@settings_bp.route("/onboarding", methods=["GET", "POST"])
@require_role("owner")
def onboarding():
    """EN: Step 1: company data. Once the CNPJ is saved it moves on to the ceilings.
    PT: Passo 1: dados da empresa. Com o CNPJ salvo, segue para os tetos.
    """
    ws = workspace_row()
    if ws["cnpj"]:
        return redirect("/onboarding/limits") if not ws["onboarding_done"] else redirect("/settings")

    if request.method == "GET":
        form = {"name": ws["name"], "email": g.user["email"]}
        return render_template("onboarding_company.html", form=form, errors=[], ws=ws)

    form, values, errors = read_company_form(identity_editable=True)
    logo, logo_error = read_logo()
    if logo_error:
        errors.append(logo_error)
    if errors:
        return render_template("onboarding_company.html", form=form, errors=errors, ws=ws), 400

    save_company(values, logo)
    return redirect("/onboarding/limits")


@settings_bp.route("/onboarding/limits", methods=["GET", "POST"])
@require_role("owner")
def limits():
    """EN: Step 2 (and later adjustments): discount ceilings per role and minimum margin.
    PT: Passo 2 (e ajustes depois): tetos de desconto por cargo e margem mínima.
    """
    ws = workspace_row()
    if not ws["cnpj"] and not ws["onboarding_done"]:
        return redirect("/onboarding")
    membership = g.membership
    done = bool(ws["onboarding_done"])

    if request.method == "GET":
        return render_template("onboarding.html", ws=membership, errors=[], done=done)

    db = get_db()
    # EN: "Skip" keeps the defaults (5% seller, 15% manager, 15% margin); only in the first setup
    # PT: "Pular" mantém os padrões (5% vendedor, 15% gerente, 15% margem); só na configuração inicial
    if request.form.get("action") == "skip" and not done:
        db.execute("UPDATE workspaces SET onboarding_done = 1 WHERE id = ?", workspace_id())
        return redirect("/dashboard")

    member_limit = parse_percent(request.form.get("member_limit"))
    admin_limit = parse_percent(request.form.get("admin_limit"))
    min_margin = parse_percent(request.form.get("min_margin"))

    errors = []
    if member_limit is None or admin_limit is None or min_margin is None:
        errors.append("onboarding.error_invalid")
    elif member_limit > admin_limit:
        # EN: same rule as the CHECK in schema.sql, with a friendly message
        # PT: mesma regra do CHECK do schema.sql, com uma mensagem amigável
        errors.append("onboarding.error_order")
    if errors:
        return render_template("onboarding.html", ws=membership, errors=errors, form=request.form, done=done), 400

    db.execute(
        "UPDATE workspaces SET member_discount_limit_bps = ?, admin_discount_limit_bps = ?, min_margin_bps = ?, "
        "onboarding_done = 1 WHERE id = ?",
        member_limit, admin_limit, min_margin, workspace_id(),
    )
    flash(_("onboarding.saved"), "success")
    return redirect("/settings" if done else "/dashboard")


# ---------------------------------------------------------------------------
# EN: Settings | PT: Configurações
# ---------------------------------------------------------------------------

@settings_bp.route("/settings", methods=["GET", "POST"])
@require_role("owner")
def settings():
    """EN: Company data after the setup. Name and CNPJ are locked (support changes them),
        except a CNPJ that was never filled (accounts created before this screen existed).
    PT: Dados da empresa depois da configuração. Nome e CNPJ ficam travados (o suporte muda),
        exceto um CNPJ nunca preenchido (contas criadas antes desta tela existir).
    """
    ws = workspace_row()
    cnpj_missing = not ws["cnpj"]
    support = support_link(_("settings.support_message").replace("{workspace}", ws["name"]))

    if request.method == "GET":
        form = {key: ws[key] or "" for key in ("name", "email", "city")}
        form["phone"] = ws["phone"] or ""
        form["cnpj"] = ""
        return render_template("settings.html", ws=ws, form=form, errors=[], cnpj_missing=cnpj_missing, support=support)

    # EN: a CNPJ never filled may be set once here; the name stays locked
    # PT: um CNPJ nunca preenchido pode ser definido uma vez aqui; o nome continua travado
    form, values, errors = read_company_form(identity_editable=False)
    if cnpj_missing:
        cnpj = normalize_cnpj(form["cnpj"])
        if cnpj is None:
            errors.append("customers.error_cnpj")
        elif get_db().execute("SELECT 1 FROM workspaces WHERE cnpj = ? AND id <> ?", cnpj, workspace_id()):
            errors.append("settings.error_cnpj_taken")
        values["cnpj"] = cnpj
    logo, logo_error = read_logo()
    if logo_error:
        errors.append(logo_error)
    if errors:
        return render_template("settings.html", ws=ws, form=form, errors=errors, cnpj_missing=cnpj_missing, support=support), 400

    save_company(values, logo, remove_logo=request.form.get("remove_logo") == "1")
    flash(_("settings.saved"), "success")
    return redirect("/settings")
