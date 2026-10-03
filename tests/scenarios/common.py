"""
EN: Shared setup for the route scenarios (tests/scenarios/scenario_*.py).
    Each scenario runs in its own Python process (started by tests/test_scenarios.py), so it
    gets a brand-new SQLite database built from schema.sql and a fresh copy of the app.
    The real project.db is never touched.
    A scenario reads like a story: it uses the app through the same routes a person uses
    (forms with CSRF tokens, redirects, permissions) and checks each step with show().
    Run one alone from project/:   python tests/scenarios/scenario_06_customers.py
PT: Preparação compartilhada dos cenários de rota (tests/scenarios/scenario_*.py).
    Cada cenário roda no próprio processo Python (iniciado pelo tests/test_scenarios.py),
    então recebe um banco SQLite novinho, criado a partir do schema.sql, e uma cópia nova do
    app. O project.db de verdade nunca é tocado.
    Um cenário se lê como uma história: usa o app pelas mesmas rotas que uma pessoa usa
    (formulários com token CSRF, redirecionamentos, permissões) e confere cada passo com show().
    Rodar um sozinho, dentro de project/:   python tests/scenarios/scenario_06_customers.py
"""

import atexit
import html
import logging
import os
import re
import shutil
import sqlite3
import sys
import tempfile

# EN: project/ on the import path, so "import app" works from any folder
# PT: project/ no caminho de import, para o "import app" funcionar de qualquer pasta
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# EN: the app logs warnings (e.g. e-mail printed to the terminal); keep the output clean
# PT: o app registra avisos (ex.: e-mail mostrado no terminal); mantém a saída limpa
logging.disable(logging.CRITICAL)

import database  # noqa: E402

# EN: a temporary database, created from schema.sql and removed when the process ends
# PT: um banco temporário, criado a partir do schema.sql e apagado quando o processo termina
_folder = tempfile.mkdtemp(prefix="supplyflow-test-")
_path = os.path.join(_folder, "test.db")
_connection = sqlite3.connect(_path)
with open(database.SCHEMA, encoding="utf-8") as _schema:
    _connection.executescript(_schema.read())
_connection.close()
database.use_database(_path)
atexit.register(shutil.rmtree, _folder, True)

import app as appmod  # noqa: E402

app = appmod.app
app.config["TESTING"] = True
db = database.get_db()

_results = {"passed": 0, "failed": []}


def show(label, condition):
    """EN: Record and print one check. tests/test_scenarios.py fails on any FAIL line.
    PT: Registra e mostra uma conferência. O tests/test_scenarios.py falha com qualquer linha FAIL.
    """
    if condition:
        _results["passed"] += 1
    else:
        _results["failed"].append(label)
    print(("PASS " if condition else "FAIL ") + label)


@atexit.register
def _summary():
    print(f"== {_results['passed']} passed, {len(_results['failed'])} failed")


def tok(client, url="/login"):
    """EN: The CSRF token of a page (falls back to the dashboard, which every staff user has).
    PT: O token CSRF de uma página (cai para o painel, que todo usuário da equipe tem).
    """
    found = re.search(r'name="_csrf" type="hidden" value="([^"]+)"', client.get(url).text)
    if found:
        return found.group(1)
    return re.search(r'name="_csrf" type="hidden" value="([^"]+)"', client.get("/dashboard").text).group(1)


def register(client, email, kind="distributor", ws="Dist A", invite=None):
    """EN: Sign up through the real form (password 12345678).
    PT: Cadastro pelo formulário de verdade (senha 12345678).
    """
    token = tok(client, "/register" + (f"?invite={invite}" if invite else ""))
    data = dict(_csrf=token, account_type=kind, name="Nome " + email, email=email, phone="",
                workspace_name=ws, password="12345678", confirmation="12345678")
    if invite:
        data["invite"] = invite
    return client.post("/register", data=data)


def post(client, url, **data):
    """EN: POST a form with a valid CSRF token. | PT: Envia um formulário com token CSRF válido."""
    data["_csrf"] = tok(client, "/dashboard")
    return client.post(url, data=data)


def one(sql, *args):
    """EN: First row of a query, or None. | PT: Primeira linha de uma consulta, ou None."""
    rows = db.execute(sql, *args)
    return rows[0] if rows else None


def status(quote_id):
    """EN: Current status of a quote. | PT: Status atual de um orçamento."""
    return one("SELECT status FROM quotes WHERE id = ?", quote_id)["status"]


def join(owner, email, role):
    """EN: The owner invites someone, who signs up through the link. Returns their client.
    PT: O dono convida alguém, que se cadastra pelo link. Devolve o cliente dessa pessoa.
    """
    post(owner, "/team/invite", email=email, role=role)
    link = re.search(r'/invite/([^"]+)"', owner.get("/team").text).group(1)
    client = app.test_client()
    register(client, email, invite=link)
    return client


__all__ = ["app", "appmod", "db", "database", "show", "tok", "register", "post", "one", "status", "join",
           "html", "os", "re", "sys", "sqlite3", "tempfile", "logging"]
