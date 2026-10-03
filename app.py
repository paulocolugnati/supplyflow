import os
import secrets
import sqlite3

import click
from flask import Flask, flash, g, redirect, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

import database
from database import get_db
from helpers import (apology, brl, csrf_is_valid, csrf_token, format_cnpj, format_phone, is_valid_email,
                     login_required, normalize_phone, num, pct, safe_redirect_target,
                     support_link, to_local)
from permissions import load_membership, require_role, user_workspaces
from admin_panel import admin_bp
from customers import customers_bp
from dashboard import dashboard_bp
from exports import exports_bp
from products import products_bp
from password_reset import reset_bp
from pipeline import pipeline_bp
from plans import plans_bp
from settings import settings_bp
from quotes import pending_for_me, quotes_bp
from portal import portal_bp
from tasks import open_count_for, tasks_bp
from team import accept_invite_for, find_valid_invite, team_bp
from translations import LANGUAGES, _, current_lang, translate

# EN: Configure application
# PT: Configura a aplicação
app = Flask(__name__)


def load_secret_key():
    """EN: Use SECRET_KEY from the environment, or a random key saved once in instance/.
        Saving it keeps users logged in across restarts during development.
    PT: Usa SECRET_KEY do ambiente, ou uma chave aleatória salva uma vez em instance/.
        Salvar a chave mantém os usuários logados quando o servidor reinicia.
    """
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    os.makedirs(app.instance_path, exist_ok=True)
    path = os.path.join(app.instance_path, "secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


# EN: Sessions: signed cookie, unreadable by JavaScript, not sent by cross-site forms
# PT: Sessão: cookie assinado, que o JavaScript não lê e que formulários de outros sites não enviam
app.config["SECRET_KEY"] = load_secret_key()

# EN: Public demo mode (DEMO_MODE=1 on the server): sign-up is closed and the login page
#     lists the demo accounts. The demo data is rebuilt every day by start.sh.
# PT: Modo demonstração pública (DEMO_MODE=1 no servidor): o cadastro fica fechado e a
#     página de login mostra as contas de demonstração. O start.sh recria os dados todo dia.
DEMO_MODE = os.environ.get("DEMO_MODE") == "1"
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# EN: biggest request accepted (the logo upload is limited to 1 MB in settings.py) | PT: maior envio aceito (a logo é limitada a 1 MB no settings.py)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

# EN: Team routes live in team.py, customers in customers.py, products in products.py,
#     pipeline and opportunities in pipeline.py, quotes in quotes.py, buyer portal in portal.py,
#     tasks and history entries in tasks.py, the staff dashboard in dashboard.py,
#     plans in plans.py, CSV in exports.py, the platform panel in admin_panel.py,
#     forgot-password in password_reset.py, onboarding + settings in settings.py
# PT: As rotas de equipe ficam no team.py, as de clientes no customers.py, as de produtos no products.py,
#     as de funil e oportunidades no pipeline.py, as de orçamentos no quotes.py,
#     as do portal do comprador no portal.py, as de tarefas e registros no tasks.py, o painel da equipe no dashboard.py,
#     planos no plans.py, CSV no exports.py, o painel da plataforma no admin_panel.py,
#     esqueci a senha no password_reset.py, onboarding + configurações no settings.py
app.register_blueprint(team_bp)
app.register_blueprint(customers_bp)
app.register_blueprint(products_bp)
app.register_blueprint(pipeline_bp)
app.register_blueprint(quotes_bp)
app.register_blueprint(portal_bp)
app.register_blueprint(tasks_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(plans_bp)
app.register_blueprint(exports_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(reset_bp)
app.register_blueprint(settings_bp)

# EN: Pipeline created for every new distributor, named in the user's language.
#     Each stage has a kind (open / won / lost) used by the dashboard.
# PT: Funil criado para toda distribuidora nova, com nomes no idioma do usuário.
#     Cada etapa tem um tipo (open / won / lost) usado pelo dashboard.
DEFAULT_PIPELINE = {
    "pt": ("Vendas", [("Novo", "open"), ("Contatado", "open"), ("Orçamento enviado", "open"),
                      ("Fechado", "won"), ("Perdido", "lost")]),
    "en": ("Sales", [("New", "open"), ("Contacted", "open"), ("Quote sent", "open"),
                     ("Won", "won"), ("Lost", "lost")]),
}

# EN: Input size limits (checked on the server, not only in HTML)
# PT: Limites de tamanho das entradas (conferidos no servidor, não só no HTML)
NAME_MAX = 100
PASSWORD_MIN = 8
PASSWORD_MAX = 128


# ---------------------------------------------------------------------------
# EN: Request hooks and template helpers
# PT: Ganchos de requisição e funções para os templates
# ---------------------------------------------------------------------------

@app.before_request
def before_request():
    """EN: Runs before every request: CSRF check, then load the user and their workspace.
    PT: Roda antes de toda requisição: confere o CSRF e carrega o usuário e a distribuidora.
    """
    # EN: Static files (CSS/JS) need no user or database
    # PT: Arquivos estáticos (CSS/JS) não precisam de usuário nem de banco
    if request.endpoint == "static":
        return None

    # EN: Every form that changes data must carry the session's CSRF token
    # PT: Todo formulário que muda dados precisa trazer o token CSRF da sessão
    if request.method == "POST" and not csrf_is_valid():
        return apology(_("error.csrf"), 400)

    g.user = None
    g.membership = None
    if session.get("user_id") is None:
        return None

    rows = get_db().execute("SELECT id, name, email, lang, is_platform_admin FROM users WHERE id = ?", session["user_id"])
    if not rows:
        # EN: the account no longer exists: log out, keep the language
        # PT: a conta não existe mais: desloga, mantendo o idioma
        lang = current_lang()
        session.clear()
        session["lang"] = lang
        return None

    g.user = rows[0]
    # EN: Role and plan are re-read from the database on every request (permissions.py)
    # PT: Cargo e plano são relidos do banco a cada requisição (permissions.py)
    load_membership(g.user["id"])
    return None


@app.after_request
def after_request(response):
    """EN: Ensure responses aren't cached (pages show private data).
    PT: Garante que as respostas não fiquem em cache (as páginas mostram dados privados).
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.context_processor
def inject_helpers():
    """EN: Make t(), the language, the CSRF token, the user and the workspace available
        in every template.
    PT: Deixa t(), o idioma, o token CSRF, o usuário e a distribuidora disponíveis em
        todos os templates.
    """
    lang = current_lang()
    user = g.get("user")
    return {
        "t": lambda key: translate(key, lang),
        "lang": lang,
        "languages": LANGUAGES,
        "demo_mode": DEMO_MODE,
        "csrf_token": csrf_token,
        "current_user": user,
        "membership": g.get("membership"),
        # EN: only staff with more than one workspace see the switcher
        # PT: só quem é de mais de uma distribuidora vê o seletor
        "my_workspaces": user_workspaces(user["id"]) if user and g.get("membership") else [],
        # EN: staff who are also buyers see the Portal item in the menu
        # PT: quem é da equipe e também comprador vê o item Portal no menu
        "has_buyer_links": bool(user) and bool(get_db().execute(
            "SELECT 1 FROM customer_users WHERE user_id = ? LIMIT 1", user["id"])),
        "support_link": support_link,
        # EN: "dark" (default) or "light", chosen by the visitor and kept in a cookie
        # PT: "dark" (padrão) ou "light", escolhido pelo visitante e guardado num cookie
        "theme": "light" if request.cookies.get("theme") == "light" else "dark",
        # EN: pending discount requests this admin/owner may decide (badge in the menu)
        # PT: pedidos de desconto pendentes que este admin/owner pode decidir (contador no menu)
        "approvals_count": len(pending_for_me()) if g.get("membership") and g.membership["role"] in ("owner", "admin") else 0,
        # EN: my overdue + today tasks (badge in the menu) | PT: minhas tarefas atrasadas + de hoje (contador no menu)
        "tasks_count": open_count_for(user["id"]) if user and g.get("membership") else 0,
    }


# EN: Money and percentages always use the Brazilian format (R$ 1.234,56 · 12,5%) in both
#     languages: the currency is the real, and sf.js formats the live numbers the same way
# PT: Dinheiro e porcentagens sempre no formato brasileiro (R$ 1.234,56 · 12,5%) nos dois
#     idiomas: a moeda é o real, e o sf.js formata os números ao vivo do mesmo jeito
@app.template_filter("brl")
def brl_filter(cents):
    return brl(cents, "pt")


@app.template_filter("pct")
def pct_filter(bps):
    return pct(bps, "pt")


app.jinja_env.filters["phone"] = format_phone
app.jinja_env.filters["cnpj"] = format_cnpj
app.jinja_env.filters["local_time"] = to_local
app.jinja_env.filters["num"] = num


# EN: Security headers on every response:
#     * CSP: scripts, fonts and images only from this site; no plugins; no framing; forms
#       only post here. Styles allow inline because the templates set CSS variables with
#       style="--x: ..." (no script runs from them)
#     * nosniff: the browser never guesses a file type (e.g. runs a .txt as script)
#     * DENY: no other site can put SupplyFlow inside a frame (clickjacking)
#     * Referrer-Policy: links to wa.me don't leak the full internal URL
# PT: Cabeçalhos de segurança em toda resposta:
#     * CSP: scripts, fontes e imagens só deste site; sem plugins; sem ser colocado em frame;
#       formulários só enviam para cá. Estilos permitem inline porque os templates definem
#       variáveis CSS com style="--x: ..." (nenhum script roda a partir deles)
#     * nosniff: o navegador nunca adivinha o tipo de arquivo (ex.: rodar um .txt como script)
#     * DENY: nenhum outro site coloca o SupplyFlow dentro de um frame (clickjacking)
#     * Referrer-Policy: links para o wa.me não vazam a URL interna completa
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'"
)


@app.after_request
def security_headers(response):
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


@app.route("/favicon.ico")
def favicon():
    # EN: browsers ask for /favicon.ico on their own; send them to the SVG symbol
    # PT: navegadores pedem /favicon.ico sozinhos; manda para o símbolo em SVG
    return redirect("/static/brand/simbolo.svg", code=301)


@app.errorhandler(403)
def forbidden(error):
    return apology(_("error.forbidden"), 403)


@app.errorhandler(404)
def not_found(error):
    return apology(_("error.not_found"), 404)


@app.errorhandler(413)
def too_large(error):
    # EN: an upload above MAX_CONTENT_LENGTH (e.g. a huge logo) | PT: um envio acima do MAX_CONTENT_LENGTH (ex.: logo enorme)
    return apology(_("settings.error_logo_size"), 413)


@app.errorhandler(405)
def method_not_allowed(error):
    # EN: e.g. opening a POST-only address in the browser | PT: ex.: abrir no navegador um endereço que só aceita POST
    return apology(_("error.method"), 405)


@app.errorhandler(500)
def server_error(error):
    # EN: never show the Python traceback to the user (debug mode shows it only to the developer)
    # PT: nunca mostrar o traceback do Python para o usuário (o modo debug mostra só para quem desenvolve)
    return apology(_("error.server"), 500)


# ---------------------------------------------------------------------------
# EN: Session helpers
# PT: Funções de sessão
# ---------------------------------------------------------------------------

def start_session(user_id, lang):
    """EN: Log a user in. The session is cleared first so an old session id can't be
        reused by an attacker (session fixation). The workspace is chosen by
        load_membership on the next request.
    PT: Faz o login. A sessão é limpa antes para que um id de sessão antigo não possa ser
        reaproveitado por um atacante (session fixation). A distribuidora é escolhida
        pelo load_membership na próxima requisição.
    """
    session.clear()
    session["user_id"] = user_id
    session["lang"] = lang
    load_membership(user_id)


def home_url():
    """EN: Where a logged-in user lands: onboarding, staff dashboard or buyer portal.
    PT: Para onde o usuário logado vai: onboarding, painel da equipe ou portal do comprador.
    """
    membership = g.get("membership")
    if membership is None:
        # EN: an operator with no distributor of their own lands on the platform panel
        # PT: quem opera a plataforma sem distribuidora própria cai no painel da plataforma
        # EN: read from the database: right after login g.user is not loaded yet
        # PT: lido do banco: logo depois do login o g.user ainda não foi carregado
        user_id = session.get("user_id")
        operator = get_db().execute(
            "SELECT 1 FROM users WHERE id = ? AND is_platform_admin = 1 "
            "AND NOT EXISTS (SELECT 1 FROM customer_users WHERE user_id = users.id)", user_id)
        if operator:
            return "/platform"
        return "/portal"
    if membership["role"] == "owner" and not membership["onboarding_done"]:
        return "/onboarding"
    return "/dashboard"


# ---------------------------------------------------------------------------
# EN: Public pages
# PT: Páginas públicas
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """EN: Landing page; logged-in users go straight to their home.
    PT: Página inicial; quem está logado vai direto para a sua área.
    """
    if g.user:
        return redirect(home_url())
    # EN: Plans come from the database, so prices and limits on the page are always the real ones
    # PT: Os planos vêm do banco, então preços e limites na página são sempre os reais
    plans = get_db().execute("SELECT * FROM plans ORDER BY position")
    support = support_link(_("landing.support_message"))
    return render_template("landing.html", plans=plans, support=support)


# EN: How many numbered sections each legal page has (texts in translations.py)
# PT: Quantas seções numeradas cada página legal tem (textos no translations.py)
LEGAL_SECTIONS = {"terms": 6, "privacy": 7}


@app.route("/terms")
def terms():
    """EN: Terms of use (public). | PT: Termos de uso (público)."""
    return render_template("legal.html", kind="terms", sections=LEGAL_SECTIONS["terms"],
                           support=support_link(_("landing.support_message")))


@app.route("/privacy")
def privacy():
    """EN: Privacy policy (public), in plain language. | PT: Política de privacidade (pública), em linguagem simples."""
    return render_template("legal.html", kind="privacy", sections=LEGAL_SECTIONS["privacy"],
                           support=support_link(_("landing.support_message")))


@app.route("/lang/<code>")
def set_language(code):
    """EN: Switch the interface language and go back to the page the user was on.
    PT: Troca o idioma da interface e volta para a página em que o usuário estava.
    """
    if code in LANGUAGES:
        session["lang"] = code
        if g.user:
            # EN: remember the choice for the next login | PT: lembra a escolha no próximo login
            get_db().execute("UPDATE users SET lang = ? WHERE id = ?", code, g.user["id"])
    return redirect(safe_redirect_target(request.args.get("next"), "/"))


# ---------------------------------------------------------------------------
# EN: Authentication
# PT: Autenticação
# ---------------------------------------------------------------------------

def validate_registration(form):
    """EN: Check the sign-up form on the server. Returns a list of error keys (empty = ok).
    PT: Confere o formulário de cadastro no servidor. Devolve uma lista de erros (vazia = ok).
    """
    errors = []
    # EN: "staff_invite" is set by the server when the sign-up comes from an invite link
    # PT: "staff_invite" é definido pelo servidor quando o cadastro vem de um link de convite
    if form["account_type"] not in ("distributor", "buyer", "staff_invite", "customer_invite"):
        errors.append("register.error_type")
    if not 2 <= len(form["name"]) <= NAME_MAX:
        errors.append("register.error_name")
    if not is_valid_email(form["email"]):
        errors.append("register.error_email")
    if form["phone"] and normalize_phone(form["phone"]) is None:
        errors.append("register.error_phone")
    if form["account_type"] == "distributor" and not 2 <= len(form["workspace_name"]) <= NAME_MAX:
        errors.append("register.error_workspace")
    if not PASSWORD_MIN <= len(form["password"]) <= PASSWORD_MAX:
        errors.append("register.error_password")
    elif form["password"] != form["confirmation"]:
        errors.append("register.error_confirmation")
    return errors


def create_distributor(user_id, workspace_name, lang):
    """EN: Create the workspace (Free plan), the owner membership and the default pipeline.
        Called inside the registration transaction.
    PT: Cria a distribuidora (plano Grátis), o vínculo de owner e o funil padrão.
        Chamada dentro da transação do cadastro.
    """
    db = get_db()
    plan_id = db.execute("SELECT id FROM plans WHERE code = 'free'")[0]["id"]
    workspace_id = db.execute("INSERT INTO workspaces (name, plan_id) VALUES (?, ?)", workspace_name, plan_id)
    db.execute("INSERT INTO memberships (workspace_id, user_id, role) VALUES (?, ?, 'owner')",
               workspace_id, user_id)

    pipeline_name, stages = DEFAULT_PIPELINE[lang]
    pipeline_id = db.execute(
        "INSERT INTO pipelines (workspace_id, name, is_default) VALUES (?, ?, 1)", workspace_id, pipeline_name
    )
    for position, (stage_name, kind) in enumerate(stages):
        db.execute(
            "INSERT INTO stages (workspace_id, pipeline_id, name, position, kind) VALUES (?, ?, ?, ?, ?)",
            workspace_id, pipeline_id, stage_name, position, kind,
        )


@app.route("/register", methods=["GET", "POST"])
def register():
    """EN: Sign up as a distributor (creates a workspace), as a buyer, or through a
        staff invite link (?invite=token: the account joins that team right away).
    PT: Cadastro como distribuidora (cria um workspace), como comprador, ou por um link
        de convite de equipe (?invite=token: a conta já entra nessa equipe).
    """
    if g.user:
        return redirect(home_url())
    if DEMO_MODE:
        return redirect("/login")

    # EN: An invite token may come in the URL (GET) or in a hidden field (POST)
    # PT: O token do convite pode vir na URL (GET) ou num campo escondido (POST)
    token = request.values.get("invite", "")
    invite = find_valid_invite(token) if token else None
    if token and invite is None:
        return apology(_("team.invite_invalid"), 404)

    invite_type = None
    if invite:
        invite_type = "customer_invite" if invite["kind"] == "customer" else "staff_invite"

    if request.method == "GET":
        if invite:
            form = {"account_type": invite_type, "email": invite["email"]}
        else:
            form = {"account_type": request.args.get("type", "distributor")}
        return render_template("register.html", form=form, errors=[], invite=invite, token=token)

    # EN: Read and clean every field; never trust the browser.
    #     With an invite, the type and the email come from the invite, not from the form.
    # PT: Lê e limpa cada campo; nunca confie no navegador.
    #     Com convite, o tipo e o e-mail vêm do convite, não do formulário.
    form = {
        "account_type": invite_type if invite else request.form.get("account_type", ""),
        "name": request.form.get("name", "").strip(),
        "email": invite["email"] if invite else request.form.get("email", "").strip().lower(),
        "phone": request.form.get("phone", "").strip(),
        "workspace_name": request.form.get("workspace_name", "").strip(),
        "password": request.form.get("password", ""),
        "confirmation": request.form.get("confirmation", ""),
    }

    def form_error(error_keys):
        return render_template("register.html", form=form, errors=error_keys, invite=invite, token=token), 400

    errors = validate_registration(form)
    if errors:
        return form_error(errors)

    lang = current_lang()
    db = get_db()

    # EN: Everything is created in one transaction: either all rows exist or none do
    # PT: Tudo é criado numa transação: ou todas as linhas existem, ou nenhuma
    db.execute("BEGIN TRANSACTION")
    try:
        user_id = db.execute(
            "INSERT INTO users (email, name, hash, phone, lang, signup_source, referred_by_workspace_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            form["email"], form["name"], generate_password_hash(form["password"]),
            normalize_phone(form["phone"]), lang, "invite" if invite else "direct",
            # EN: a buyer who created the account through a distributor's invite was brought
            #     by that distributor (kept forever, used for the "brought by you" tag)
            # PT: um comprador que criou a conta pelo convite de uma distribuidora foi trazido
            #     por ela (guardado para sempre, usado na etiqueta "trazido por você")
            invite["workspace_id"] if invite and invite["kind"] == "customer" else None,
        )
    except ValueError:
        # EN: the UNIQUE index on email rejected a duplicate
        # PT: o índice UNIQUE do e-mail recusou um e-mail repetido
        db.execute("ROLLBACK")
        return form_error(["register.error_taken"])

    try:
        invite_error = None
        if form["account_type"] == "distributor":
            create_distributor(user_id, form["workspace_name"], lang)
        elif invite:
            invite_error = accept_invite_for(invite, user_id)
        # EN: if joining the team fails, the account isn't created either
        # PT: se entrar na equipe falhar, a conta também não é criada
        db.execute("ROLLBACK" if invite_error else "COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    if invite_error:
        return form_error([invite_error])

    start_session(user_id, lang)
    flash(_("register.welcome"), "success")
    return redirect(home_url())


@app.route("/login", methods=["GET", "POST"])
def login():
    """EN: Log in with email and password.
    PT: Entrar com e-mail e senha.
    """
    if g.user:
        return redirect(home_url())

    next_url = request.values.get("next", "")

    if request.method == "GET":
        return render_template("login.html", email="", next_url=next_url, error=None)

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    rows = get_db().execute("SELECT id, hash, lang FROM users WHERE email = ?", email) if email else []

    # EN: Same message for "unknown email" and "wrong password", so nobody can discover
    #     which emails have an account
    # PT: Mesma mensagem para "e-mail não existe" e "senha errada", para ninguém descobrir
    #     quais e-mails têm conta
    if len(rows) != 1 or not check_password_hash(rows[0]["hash"], password):
        return render_template("login.html", email=email, next_url=next_url, error="login.error"), 400

    start_session(rows[0]["id"], rows[0]["lang"])
    return redirect(safe_redirect_target(next_url, home_url()))


@app.route("/logout", methods=["POST"])
def logout():
    """EN: Log out (POST only, so a link on another site can't log the user out).
    PT: Sair (só POST, para um link em outro site não conseguir deslogar o usuário).
    """
    lang = current_lang()
    session.clear()
    session["lang"] = lang
    return redirect("/")


# ---------------------------------------------------------------------------
# EN: Workspace (distributor) area
# PT: Área da distribuidora
# ---------------------------------------------------------------------------

@app.route("/workspace/switch", methods=["POST"])
@require_role("member")
def switch_workspace():
    """EN: Change the active workspace. The id comes from the form, so it is only
        accepted if the user really is a member of that workspace.
    PT: Troca a distribuidora ativa. O id vem do formulário, então só é aceito se o
        usuário for mesmo membro dessa distribuidora.
    """
    target = request.form.get("workspace_id", "")
    allowed = {str(row["id"]) for row in user_workspaces(g.user["id"])}
    if target not in allowed:
        return apology(_("error.not_found"), 404)
    session["workspace_id"] = int(target)
    return redirect("/dashboard")


# ---------------------------------------------------------------------------
# EN: Buyer area
# PT: Área do comprador
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# EN: Command line
# PT: Linha de comando
# ---------------------------------------------------------------------------

@app.cli.command("init-db")
@click.option("--reset", is_flag=True, help="Delete the existing database first.")
def init_db(reset):
    """EN: Create project.db from schema.sql.
    PT: Cria o project.db a partir do schema.sql.
    """
    if os.path.exists(database.DATABASE):
        if not reset:
            raise click.ClickException(
                "project.db already exists. Use 'flask init-db --reset' to recreate it (all data is lost)."
            )
        os.remove(database.DATABASE)

    # EN: sqlite3 runs the whole script at once; the cs50 library runs one statement per call
    # PT: o sqlite3 roda o script inteiro de uma vez; a biblioteca cs50 roda um comando por chamada
    with open(database.SCHEMA, encoding="utf-8") as f:
        connection = sqlite3.connect(database.DATABASE)
        connection.executescript(f.read())
        connection.close()

    click.echo("Database created: project.db")


@app.cli.command("make-admin")
@click.argument("email")
@click.option("--remove", is_flag=True, help="Turn the flag off instead.")
def make_admin(email, remove):
    """EN: Turn the platform admin flag on (or off with --remove) for an existing account.
        This is the only way to get into /platform: there is no screen for it.
    PT: Liga a flag de admin da plataforma (ou desliga com --remove) para uma conta existente.
        É o único jeito de entrar no /platform: não existe tela para isso.
    """
    email = email.strip().lower()
    rows = get_db().execute("SELECT id, name FROM users WHERE email = ?", email)
    if not rows:
        raise click.ClickException(f"No account with the email {email}.")
    get_db().execute("UPDATE users SET is_platform_admin = ? WHERE id = ?", 0 if remove else 1, rows[0]["id"])
    click.echo(f"{rows[0]['name']} <{email}> is {'no longer' if remove else 'now'} a platform admin.")
