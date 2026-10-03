import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import quote, urlparse

from flask import redirect, render_template, request, session, url_for

# EN: Brazil has had no daylight saving time since 2019, so Sao Paulo is always UTC-3.
#     A fixed offset avoids depending on the tzdata package, which Windows lacks.
# PT: O Brasil não tem horário de verão desde 2019, então São Paulo é sempre UTC-3.
#     Um deslocamento fixo evita depender do pacote tzdata, que o Windows não tem.
SAO_PAULO = timezone(timedelta(hours=-3), "America/Sao_Paulo")


def apology(message, code=400):
    """EN: Render an error page with a message and an HTTP status code.
    PT: Mostra uma página de erro com uma mensagem e um código HTTP.
    """
    return render_template("apology.html", message=message, code=code), code


def login_required(f):
    """EN: Redirect to the login page when nobody is logged in.
    PT: Redireciona para o login quando ninguém está logado.

    https://flask.palletsprojects.com/en/latest/patterns/viewdecorators/
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            # EN: remember where the user wanted to go | PT: lembra para onde o usuário queria ir
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)

    return decorated_function


# ---------------------------------------------------------------------------
# EN: Time
# PT: Horário
# ---------------------------------------------------------------------------

def now_utc():
    """EN: Current time as stored in the database: 'YYYY-MM-DD HH:MM:SS' in UTC.
    PT: Horário atual no formato do banco: 'AAAA-MM-DD HH:MM:SS' em UTC.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def utc_in_days(days):
    """EN: UTC timestamp `days` from now, in the database format (used for invite expiry).
    PT: Horário UTC daqui a `days` dias, no formato do banco (usado na validade dos convites).
    """
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def today_sp():
    """EN: Today's date in Sao Paulo, 'YYYY-MM-DD'. Used for due dates and 'today' lists.
    PT: Data de hoje em São Paulo, 'AAAA-MM-DD'. Usada em prazos e listas de "hoje".
    """
    return datetime.now(SAO_PAULO).strftime("%Y-%m-%d")


def month_start_utc():
    """EN: First moment of the current month in Sao Paulo, written in UTC for the database.
        Midnight in Sao Paulo (UTC-3) is 03:00 UTC. Used by the monthly quote quota.
    PT: Primeiro instante do mês atual em São Paulo, escrito em UTC para o banco.
        Meia-noite em São Paulo (UTC-3) é 03:00 UTC. Usado pela cota mensal de orçamentos.
    """
    first_day = datetime.now(SAO_PAULO).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return first_day.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def date_sp_in_days(days):
    """EN: Sao Paulo date `days` from today, 'YYYY-MM-DD' (default quote validity).
    PT: Data de São Paulo daqui a `days` dias, 'AAAA-MM-DD' (validade padrão do orçamento).
    """
    return (datetime.now(SAO_PAULO) + timedelta(days=days)).strftime("%Y-%m-%d")


def to_local(value):
    """EN: Convert a UTC timestamp from the database to Sao Paulo time, 'DD/MM/YYYY HH:MM'.
    PT: Converte um horário UTC do banco para o horário de São Paulo, 'DD/MM/AAAA HH:MM'.
    """
    if not value:
        return ""
    moment = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return moment.astimezone(SAO_PAULO).strftime("%d/%m/%Y %H:%M")


# ---------------------------------------------------------------------------
# EN: Formatting (registered as Jinja filters in app.py)
# PT: Formatação (registrada como filtros do Jinja no app.py)
# ---------------------------------------------------------------------------

def brl(cents, lang="pt"):
    """EN: Format integer cents as Brazilian reais: 123456 -> 'R$ 1.234,56'.
    PT: Formata centavos inteiros como reais: 123456 -> 'R$ 1.234,56'.
    """
    if cents is None:
        return ""
    sign = "-" if cents < 0 else ""
    reais, centavos = divmod(abs(int(cents)), 100)
    text = f"{reais:,}.{centavos:02d}"            # '1,234.56'
    if lang == "pt":
        # EN: swap separators to the Brazilian style | PT: troca os separadores para o padrão brasileiro
        text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{sign}R$ {text}"


def num(value):
    """EN: Whole number with Brazilian thousands separator: 2000 -> '2.000'.
    PT: Número inteiro com separador de milhar brasileiro: 2000 -> '2.000'.
    """
    if value is None:
        return ""
    return f"{int(value):,}".replace(",", ".")


def pct(bps, lang="pt"):
    """EN: Format basis points as a percentage: 1250 -> '12,5%'. Integer math only.
    PT: Formata basis points como porcentagem: 1250 -> '12,5%'. Só conta com inteiros.
    """
    if bps is None:
        return ""
    sign = "-" if bps < 0 else ""
    whole, fraction = divmod(abs(int(bps)), 100)
    text = str(whole) if fraction == 0 else f"{whole}.{fraction:02d}".rstrip("0")
    if lang == "pt":
        text = text.replace(".", ",")
    return f"{sign}{text}%"


# ---------------------------------------------------------------------------
# EN: Input parsing and validation (never trust the browser)
# PT: Leitura e validação de entradas (nunca confie no navegador)
# ---------------------------------------------------------------------------

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PERCENT_PATTERN = re.compile(r"^\d{1,3}([.,]\d{1,2})?$")


def is_valid_email(email):
    """EN: Basic shape check (something@something.something), max 254 chars.
    PT: Checagem básica de formato (algo@algo.algo), no máximo 254 caracteres.
    """
    return bool(email) and len(email) <= 254 and EMAIL_PATTERN.match(email) is not None


def parse_percent(text):
    """EN: Turn '12,5' or '12.5' into basis points (1250). Returns None when invalid
        or outside 0-100%. Uses only integers, so there are no float rounding errors.
    PT: Converte '12,5' ou '12.5' em basis points (1250). Devolve None se for inválido
        ou fora de 0-100%. Usa só inteiros, então não há erro de arredondamento de float.
    """
    text = (text or "").strip().replace("%", "")
    if not PERCENT_PATTERN.match(text):
        return None
    whole, _, fraction = text.replace(",", ".").partition(".")
    bps = int(whole) * 100 + int(fraction.ljust(2, "0") or 0)
    return bps if 0 <= bps <= 10000 else None


MONEY_MAX_CENTS = 99_999_999   # EN: R$ 999.999,99 | PT: R$ 999.999,99


def parse_money(text):
    """EN: Turn what people type as money into integer cents, or None when invalid.
        Accepts "12,34", "12.34", "1.234,56", "1,234.56", "1234" and an optional "R$".
        Integer math only (no float), so R$ 0,10 + R$ 0,20 is always R$ 0,30.
    PT: Converte o que a pessoa digita como dinheiro em centavos inteiros, ou None se for
        inválido. Aceita "12,34", "12.34", "1.234,56", "1,234.56", "1234" e um "R$" opcional.
        Só conta com inteiros (sem float), então R$ 0,10 + R$ 0,20 é sempre R$ 0,30.
    """
    text = (text or "").replace("R$", "").replace(" ", "").strip()
    if not text:
        return None
    if "," in text and "." in text:
        # EN: the last separator is the decimal one | PT: o último separador é o decimal
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", text):
        # EN: "1.234" is one thousand two hundred... | PT: "1.234" é mil duzentos e trinta e quatro
        text = text.replace(".", "")
    if not re.fullmatch(r"\d{1,9}(\.\d{1,2})?", text):
        return None
    whole, _, fraction = text.partition(".")
    cents = int(whole) * 100 + int(fraction.ljust(2, "0") or 0)
    return cents if cents <= MONEY_MAX_CENTS else None


def money_input(cents):
    """EN: Cents back to an editable text in Brazilian style: 1234 -> '12,34'.
    PT: Centavos de volta para texto editável no padrão brasileiro: 1234 -> '12,34'.
    """
    if cents is None:
        return ""
    return f"{cents // 100},{cents % 100:02d}"


def escape_like(text):
    """EN: Escape LIKE wildcards so a search for "50%" finds the text "50%" instead of
        "anything starting with 50". "!" is the escape character (a backslash would confuse
        the cs50 library's placeholder parser). Use with: ... LIKE ? ESCAPE '!'
    PT: Escapa os curingas do LIKE para uma busca por "50%" achar o texto "50%" em vez de
        "qualquer coisa que comece com 50". O "!" é o caractere de escape (uma barra invertida
        confundiria o leitor de "?" da biblioteca cs50). Use com: ... LIKE ? ESCAPE '!'
    """
    return text.replace("!", "!!").replace("%", "!%").replace("_", "!_")


# ---------------------------------------------------------------------------
# EN: CNPJ (Brazilian company registration number)
# PT: CNPJ (cadastro nacional da pessoa jurídica)
# ---------------------------------------------------------------------------

def normalize_cnpj(raw):
    """EN: Return the 14 digits of a valid CNPJ, or None. Checks both verification digits,
        so a typo is caught before it is saved.
    PT: Devolve os 14 dígitos de um CNPJ válido, ou None. Confere os dois dígitos
        verificadores, então um erro de digitação é pego antes de salvar.

    '11.222.333/0001-81' -> '11222333000181'
    """
    digits = re.sub(r"\D", "", raw or "")
    # EN: 14 digits, and not a repeated digit like 00000000000000
    # PT: 14 dígitos, e não um dígito repetido como 00000000000000
    if len(digits) != 14 or len(set(digits)) == 1:
        return None

    def check_digit(base):
        weights = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][-len(base):]
        total = sum(int(d) * w for d, w in zip(base, weights))
        rest = total % 11
        return "0" if rest < 2 else str(11 - rest)

    first = check_digit(digits[:12])
    second = check_digit(digits[:12] + first)
    return digits if digits[12:] == first + second else None


def format_cnpj(digits):
    """EN: '11222333000181' -> '11.222.333/0001-81' for display.
    PT: '11222333000181' -> '11.222.333/0001-81' para exibir.
    """
    if not digits or len(digits) != 14:
        return digits or ""
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


# ---------------------------------------------------------------------------
# EN: Phone and WhatsApp
# PT: Telefone e WhatsApp
# ---------------------------------------------------------------------------

def normalize_phone(raw):
    """EN: Return a phone as digits with country code 55, or None when invalid.
    PT: Devolve o telefone só com dígitos e o código 55, ou None se for inválido.

    '(11) 98765-4321'   -> '5511987654321'
    '+55 11 98765-4321' -> '5511987654321'
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    # EN: 10-11 digits = area code + number, add the country code
    # PT: 10-11 dígitos = DDD + número, adiciona o código do país
    if len(digits) in (10, 11):
        return "55" + digits
    if digits.startswith("55") and len(digits) in (12, 13):
        return digits
    return None


def format_phone(digits):
    """EN: '5511987654321' -> '(11) 98765-4321' for display.
    PT: '5511987654321' -> '(11) 98765-4321' para exibir.
    """
    if not digits or not digits.startswith("55"):
        return digits or ""
    local = digits[2:]
    area, number = local[:2], local[2:]
    return f"({area}) {number[:-4]}-{number[-4:]}"


def whatsapp_link(phone, message=""):
    """EN: Build a wa.me link with an optional pre-filled message.
    PT: Monta um link wa.me com uma mensagem pronta opcional.
    """
    link = f"https://wa.me/{phone}"
    return f"{link}?text={quote(message)}" if message else link


def support_link(message=""):
    """EN: WhatsApp link to SupplyFlow support, or None if SUPPORT_WHATSAPP is not set.
    PT: Link de WhatsApp do suporte da SupplyFlow, ou None se SUPPORT_WHATSAPP não existir.
    """
    phone = normalize_phone(os.environ.get("SUPPORT_WHATSAPP", ""))
    return whatsapp_link(phone, message) if phone else None


# ---------------------------------------------------------------------------
# EN: Security
# PT: Segurança
# ---------------------------------------------------------------------------

def csrf_token():
    """EN: Return this session's CSRF token, creating it on first use.
    PT: Devolve o token CSRF desta sessão, criando-o no primeiro uso.
    """
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(32)
    return session["_csrf"]


def csrf_is_valid():
    """EN: True when the submitted form carries this session's CSRF token.
        compare_digest takes the same time for any input, so it leaks nothing.
    PT: Verdadeiro quando o formulário enviado traz o token CSRF desta sessão.
        compare_digest demora o mesmo tempo para qualquer entrada, então não vaza nada.
    """
    expected = session.get("_csrf")
    received = request.form.get("_csrf", "")
    return expected is not None and secrets.compare_digest(expected, received)


def new_token():
    """EN: Create a random invite token. Returns (token, token_hash): the token goes in the
        link, only the hash goes in the database. If the database leaks, the links can't
        be rebuilt from it.
        SHA-256 is enough here (unlike passwords) because the token is long and random,
        so it can't be guessed; and a plain hash lets us look the invite up by it.
    PT: Cria um token de convite aleatório. Devolve (token, token_hash): o token vai no link,
        só o hash vai para o banco. Se o banco vazar, não dá para remontar os links.
        SHA-256 basta aqui (diferente de senha) porque o token é longo e aleatório, então não
        dá para adivinhar; e um hash simples permite procurar o convite por ele.
    """
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token):
    """EN: SHA-256 of a token, in hex. | PT: SHA-256 de um token, em hexadecimal."""
    return hashlib.sha256((token or "").encode()).hexdigest()


def safe_redirect_target(target, fallback="/"):
    """EN: Only allow redirects to paths on this site (blocks open redirects).
    PT: Só permite redirecionar para caminhos deste site (bloqueia "open redirect").
    """
    if not target:
        return fallback
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//"):
        return fallback
    return target
