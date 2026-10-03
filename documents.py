"""
EN: The quote as a document for the customer (the "PDF"). One A4 page built in HTML: the
    browser's "Save as PDF" turns it into a file, so nothing extra is installed.
    Used by the staff (/quotes/<id>/document) and by the buyer (/portal/quotes/<id>/document);
    each route checks its own access first and then calls quote_document().
    Rules:
    * only customer-safe data: never cost, margin, internal notes or the approval trail
    * always in Portuguese: it is a commercial document for a Brazilian business
    * a quote that is not final yet (draft, waiting for approval, ready) carries a clear
      "not final" banner; declined, expired and cancelled ones say so too
PT: O orçamento como documento para o cliente (o "PDF"). Uma página A4 feita em HTML: o
    "Salvar como PDF" do navegador vira o arquivo, então nada extra é instalado.
    Usado pela equipe (/quotes/<id>/document) e pelo comprador (/portal/quotes/<id>/document);
    cada rota confere o próprio acesso antes e depois chama quote_document().
    Regras:
    * só dados que o cliente pode ver: nunca custo, margem, notas internas ou a trilha da aprovação
    * sempre em português: é um documento comercial para uma empresa brasileira
    * um orçamento que ainda não é final (rascunho, aguardando aprovação, pronto) leva um aviso
      claro de "não é final"; recusado, expirado e cancelado também avisam
"""

import re

from flask import render_template

from database import get_db
from translations import customer_text

# EN: Statuses in which the numbers can still change | PT: Status em que os números ainda podem mudar
NOT_FINAL = ("draft", "pending_approval", "ready")
# EN: Statuses that end without a sale | PT: Status que terminam sem venda
CLOSED_WITHOUT_SALE = ("declined", "expired", "cancelled")


def quote_document(quote, back_url):
    """EN: Render the document of one quote. `quote` is a full quotes row the caller already
        checked access to. Every query is limited to the quote's own workspace.
    PT: Monta o documento de um orçamento. `quote` é uma linha completa de quotes cujo acesso
        quem chamou já conferiu. Toda consulta fica limitada à distribuidora do orçamento.
    """
    db = get_db()
    ws = quote["workspace_id"]
    workspace = db.execute("SELECT * FROM workspaces WHERE id = ?", ws)[0]
    customer = db.execute("SELECT name, cnpj, city, phone FROM companies WHERE id = ? AND workspace_id = ?",
                          quote["company_id"], ws)[0]
    contact = db.execute(
        "SELECT k.name FROM opportunities o JOIN contacts k ON k.id = o.contact_id "
        "WHERE o.id = ? AND o.workspace_id = ?", quote["opportunity_id"], ws)
    seller = db.execute("SELECT name, email FROM users WHERE id = ?", quote["created_by"])
    # EN: only the columns a customer may see | PT: só as colunas que o cliente pode ver
    items = db.execute(
        "SELECT product_name, unit, quantity, list_price_cents, discount_bps, line_total_cents "
        "FROM quote_items WHERE quote_id = ? AND workspace_id = ? ORDER BY id",
        quote["id"], ws,
    )

    number = f"{quote['number']:04d}"
    # EN: the page title becomes the PDF file name: "Orcamento-0001-Restaurante-do-Ze"
    # PT: o título da página vira o nome do arquivo PDF: "Orcamento-0001-Restaurante-do-Ze"
    file_name = "Orcamento-" + number + "-" + re.sub(r"[^\w]+", "-", customer["name"]).strip("-")

    if quote["status"] in NOT_FINAL:
        banner = "doc.banner_not_final"
    elif quote["status"] in CLOSED_WITHOUT_SALE:
        banner = "doc.banner_" + quote["status"]
    else:
        banner = None

    return render_template(
        "quote_document.html",
        d=customer_text,
        quote=quote,
        number=number,
        file_name=file_name,
        workspace=workspace,
        customer=customer,
        contact=contact[0]["name"] if contact else None,
        seller=seller[0] if seller else None,
        items=items,
        discount_cents=quote["list_total_cents"] - quote["final_total_cents"],
        banner=banner,
        back_url=back_url,
    )
