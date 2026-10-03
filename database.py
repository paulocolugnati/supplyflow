"""EN: Database connection shared by app.py and permissions.py.
    It lives in its own module so both can import it without a circular import.
PT: Conexão com o banco compartilhada pelo app.py e pelo permissions.py.
    Fica num módulo próprio para os dois importarem sem criar import circular.
"""

import atexit
import os

from cs50 import SQL

# EN: CS50's SQL loads SQLAlchemy only on the first query, and SQLAlchemy asks the operating
#     system for the machine type when it loads. On Windows that question (WMI) can take
#     tens of seconds inside a web server thread, which froze the first login after the
#     server started. Importing it here runs that question once, at startup, in the main thread.
# PT: O SQL do CS50 só carrega o SQLAlchemy na primeira consulta, e o SQLAlchemy pergunta ao
#     sistema operacional o tipo da máquina ao carregar. No Windows essa pergunta (WMI) pode
#     levar dezenas de segundos dentro de uma thread do servidor web, o que travava o primeiro
#     login depois de subir o servidor. Importar aqui faz essa pergunta uma vez, ao iniciar,
#     na linha principal.
import sqlalchemy  # noqa: F401,E402

# EN: The database file lives next to this file, whatever folder flask is started from
# PT: O arquivo do banco fica ao lado deste arquivo, de qualquer pasta que o flask seja iniciado
ROOT = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(ROOT, "project.db")
SCHEMA = os.path.join(ROOT, "schema.sql")

# EN: Opened lazily, so 'flask init-db' can run before the file exists
# PT: Aberto só no primeiro uso, para o 'flask init-db' rodar antes do arquivo existir
_db = None


def get_db():
    """EN: Return the cs50 SQL connection, opening it on first use.
    PT: Devolve a conexão SQL do cs50, abrindo-a no primeiro uso.
    """
    global _db
    if _db is None:
        if not os.path.exists(DATABASE):
            raise RuntimeError("project.db not found. Run 'flask init-db' first.")
        _db = SQL("sqlite:///" + DATABASE.replace(os.sep, "/"))
    return _db


@atexit.register
def _close_at_exit():
    """EN: Close the connection while Python is still running. Without this, CS50's library
        closes it during interpreter shutdown, when SQLAlchemy is already half gone, and
        prints a harmless but alarming "Traceback" at the end of every command.
    PT: Fecha a conexão enquanto o Python ainda está rodando. Sem isso, a biblioteca do CS50
        fecha durante o encerramento do interpretador, quando o SQLAlchemy já está pela
        metade, e mostra um "Traceback" inofensivo, mas assustador, no fim de todo comando.
    """
    if _db is not None:
        _db._disconnect()


def use_database(path):
    """EN: Point the app to another database file (used by tests).
    PT: Aponta o app para outro arquivo de banco (usado nos testes).
    """
    global DATABASE, _db
    DATABASE = path
    _db = None
