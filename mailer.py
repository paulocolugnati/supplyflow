"""
EN: Sending e-mail with Python's own smtplib (nothing to install). Configured by environment
    variables, so no password ever lives in the code:
        MAIL_USERNAME   the Gmail address that sends (e.g. supplyflow.app@gmail.com)
        MAIL_PASSWORD   a Gmail "app password" (16 letters), not the account password
        MAIL_FROM       optional display sender, defaults to MAIL_USERNAME
        MAIL_SERVER     optional, defaults to smtp.gmail.com
        MAIL_PORT       optional, defaults to 465 (SSL)
    Without MAIL_USERNAME/MAIL_PASSWORD (development, or the CS50 graders running it), the
    message is printed in the terminal instead, so the flow can still be tested.
PT: Envio de e-mail com o smtplib do próprio Python (nada para instalar). Configurado por
    variáveis de ambiente, então nenhuma senha fica no código:
        MAIL_USERNAME   o endereço Gmail que envia (ex.: supplyflow.app@gmail.com)
        MAIL_PASSWORD   uma "senha de app" do Gmail (16 letras), não a senha da conta
        MAIL_FROM       remetente exibido, opcional; padrão = MAIL_USERNAME
        MAIL_SERVER     opcional; padrão smtp.gmail.com
        MAIL_PORT       opcional; padrão 465 (SSL)
    Sem MAIL_USERNAME/MAIL_PASSWORD (desenvolvimento, ou a banca do CS50 rodando), a mensagem
    é mostrada no terminal, para o fluxo continuar testável.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app


def mail_configured():
    """EN: True when real sending is set up. | PT: Verdadeiro quando o envio real está configurado."""
    return bool(os.environ.get("MAIL_USERNAME") and os.environ.get("MAIL_PASSWORD"))


def send_email(to, subject, body):
    """EN: Send a plain-text e-mail. Returns True when it was handed to the server (or printed
        in development). Network or login errors are logged and return False: the caller
        shows the same message either way, so nobody learns which e-mails exist.
    PT: Envia um e-mail de texto. Devolve True quando foi entregue ao servidor (ou mostrado
        no terminal em desenvolvimento). Erros de rede ou de login vão para o log e devolvem
        False: quem chama mostra a mesma mensagem nos dois casos, então ninguém descobre
        quais e-mails existem.
    """
    if not mail_configured():
        current_app.logger.warning("E-mail not configured (MAIL_USERNAME/MAIL_PASSWORD). Message to %s:\n%s\n%s",
                                   to, subject, body)
        return True

    message = EmailMessage()
    message["From"] = os.environ.get("MAIL_FROM") or os.environ["MAIL_USERNAME"]
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        server = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
        port = int(os.environ.get("MAIL_PORT", "465"))
        with smtplib.SMTP_SSL(server, port, context=ssl.create_default_context(), timeout=15) as smtp:
            smtp.login(os.environ["MAIL_USERNAME"], os.environ["MAIL_PASSWORD"])
            smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException) as error:
        current_app.logger.error("E-mail to %s failed: %s", to, error)
        return False
