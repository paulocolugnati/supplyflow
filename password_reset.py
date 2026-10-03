"""
EN: "Forgot my password": the user types their e-mail and receives a link that lets them
    choose a new password. Registered in app.py as a Blueprint.
    Rules (same care as the invites):
    * the answer is always the same, whether the e-mail has an account or not, so the page
      can't be used to discover who uses SupplyFlow
    * only the SHA-256 hash of the token is stored; the link lasts 1 hour and works once
    * at most 3 links per account per hour (stops someone flooding a mailbox)
    * choosing a new password cancels every other open link of that account and logs out
      whoever was logged in on this browser
PT: "Esqueci minha senha": a pessoa digita o e-mail e recebe um link para escolher uma
    senha nova. Registrado no app.py como um Blueprint.
    Regras (o mesmo cuidado dos convites):
    * a resposta é sempre a mesma, tendo conta ou não, para a página não servir para
      descobrir quem usa o SupplyFlow
    * só o hash SHA-256 do token é guardado; o link dura 1 hora e funciona uma vez
    * no máximo 3 links por conta por hora (impede alguém de lotar uma caixa de e-mail)
    * escolher a senha nova cancela todos os outros links abertos da conta e desloga quem
      estava logado neste navegador
"""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

from database import get_db
from helpers import hash_token, is_valid_email, new_token, now_utc
from mailer import send_email
from translations import _, current_lang, translate

reset_bp = Blueprint("password_reset", __name__)

LINK_HOURS = 1
MAX_PER_HOUR = 3
PASSWORD_MIN = 8
PASSWORD_MAX = 128


def utc_in_hours(hours):
    """EN: UTC timestamp `hours` from now (negative = in the past), database format.
    PT: Horário UTC daqui a `hours` horas (negativo = no passado), formato do banco.
    """
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def valid_reset(token):
    """EN: The open, unexpired reset row for this raw token, or None.
    PT: A linha de redefinição aberta e dentro da validade para este token, ou None.
    """
    rows = get_db().execute(
        "SELECT r.*, u.email, u.lang FROM password_resets r JOIN users u ON u.id = r.user_id "
        "WHERE r.token_hash = ? AND r.used_at IS NULL AND r.expires_at > ?",
        hash_token(token), now_utc(),
    )
    return rows[0] if rows else None


@reset_bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    """EN: Ask for the e-mail and send the link (when the account exists and the hourly
        limit allows). Always the same answer.
    PT: Pede o e-mail e envia o link (quando a conta existe e o limite por hora permite).
        Sempre a mesma resposta.
    """
    if request.method == "GET":
        return render_template("forgot.html", email="", sent=False, error=None)

    email = request.form.get("email", "").strip().lower()
    if not is_valid_email(email):
        return render_template("forgot.html", email=email, sent=False, error="reset.error_email"), 400

    db = get_db()
    rows = db.execute("SELECT id, name, lang FROM users WHERE email = ?", email)
    if rows:
        user = rows[0]
        recent = db.execute("SELECT COUNT(*) AS n FROM password_resets WHERE user_id = ? AND created_at > ?",
                            user["id"], utc_in_hours(-1))[0]["n"]
        if recent < MAX_PER_HOUR:
            token, token_hash = new_token()
            db.execute("INSERT INTO password_resets (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
                       user["id"], token_hash, utc_in_hours(LINK_HOURS))
            # EN: the e-mail goes in the account's own language | PT: o e-mail vai no idioma da própria conta
            lang = user["lang"] or current_lang()
            link = url_for("password_reset.reset", token=token, _external=True)
            body = (translate("reset.email_body", lang)
                    .replace("{name}", user["name"].split()[0]).replace("{link}", link)
                    .replace("{hours}", str(LINK_HOURS)))
            send_email(email, translate("reset.email_subject", lang), body)

    return render_template("forgot.html", email=email, sent=True, error=None)


@reset_bp.route("/reset/<token>", methods=["GET", "POST"])
def reset(token):
    """EN: Choose the new password. Single use: the UPDATE only marks the link as used if
        nobody used it first, so two tabs can't both change the password.
    PT: Escolher a senha nova. Uso único: o UPDATE só marca o link como usado se ninguém
        usou antes, então duas abas não conseguem trocar a senha ao mesmo tempo.
    """
    row = valid_reset(token)
    if row is None:
        return render_template("reset.html", invalid=True, errors=[]), 404

    if request.method == "GET":
        return render_template("reset.html", invalid=False, errors=[], email=row["email"])

    password = request.form.get("password", "")
    errors = []
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        errors.append("register.error_password")
    elif password != request.form.get("confirmation", ""):
        errors.append("register.error_confirmation")
    if errors:
        return render_template("reset.html", invalid=False, errors=errors, email=row["email"]), 400

    db = get_db()
    db.execute("BEGIN TRANSACTION")
    try:
        used = db.execute("UPDATE password_resets SET used_at = ? WHERE id = ? AND used_at IS NULL", now_utc(), row["id"])
        if used != 1:
            db.execute("ROLLBACK")
            return render_template("reset.html", invalid=True, errors=[]), 404
        db.execute("UPDATE users SET hash = ? WHERE id = ?", generate_password_hash(password), row["user_id"])
        # EN: every other open link of this account stops working | PT: todos os outros links abertos da conta param de funcionar
        db.execute("UPDATE password_resets SET used_at = ? WHERE user_id = ? AND used_at IS NULL", now_utc(), row["user_id"])
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    lang = session.get("lang")
    session.clear()
    if lang:
        session["lang"] = lang
    flash(_("reset.done"), "success")
    return redirect("/login")
