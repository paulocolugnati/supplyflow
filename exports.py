"""
EN: CSV export of customers, opportunities, quotes and products (plans with the
    "csv_export" feature: Profissional and Escala). Only owner/admin can export, because a
    file leaves the system with the whole customer base.
    Registered in app.py as a Blueprint.
    Rules:
    * the kind comes from a fixed list (EXPORTS); the SQL of each kind is fixed in code
    * every query filters by the active workspace
    * the file opens straight in Excel: UTF-8 with BOM; in Portuguese the separator is ";"
      and money uses a decimal comma, in English "," and a decimal point
    * cells that start with = + - @ or a tab/return get a leading apostrophe, so a customer
      name can never run as a spreadsheet formula (CSV injection)
PT: Exportação em CSV de clientes, oportunidades, orçamentos e produtos (planos com o recurso
    "csv_export": Profissional e Escala). Só dono/gerente exportam, porque um arquivo sai do
    sistema com a base de clientes inteira.
    Registrado no app.py como um Blueprint.
    Regras:
    * o tipo vem de uma lista fixa (EXPORTS); o SQL de cada tipo é fixo no código
    * toda consulta filtra pela distribuidora ativa
    * o arquivo abre direto no Excel: UTF-8 com BOM; em português o separador é ";" e o
      dinheiro usa vírgula decimal, em inglês "," e ponto decimal
    * células que começam com = + - @ ou tab/enter ganham um apóstrofo na frente, para o nome
      de um cliente nunca rodar como fórmula de planilha (injeção em CSV)
"""

import csv
import io

from flask import Blueprint, Response

from database import get_db
from helpers import apology, format_cnpj, format_phone, to_local, today_sp
from permissions import has_feature, require_role, workspace_id
from translations import _, current_lang

exports_bp = Blueprint("exports", __name__)

# EN: kind -> (columns as (translation key, row field, format), fixed SQL with one "?" = workspace)
# PT: tipo -> (colunas como (chave de tradução, campo da linha, formato), SQL fixo com um "?" = distribuidora)
EXPORTS = {
    "customers": (
        [("customers.col_customer", "name", None), ("customers.cnpj", "cnpj", "cnpj"),
         ("customers.segment", "segment", None), ("customers.phone", "phone", "phone"),
         ("customers.city", "city", None), ("customers.owner", "owner_name", None),
         ("export.created_at", "created_at", "datetime")],
        "SELECT c.*, u.name AS owner_name FROM companies c LEFT JOIN users u ON u.id = c.owner_id "
        "WHERE c.workspace_id = ? ORDER BY c.name COLLATE NOCASE",
    ),
    "opportunities": (
        [("export.title", "title", None), ("customers.col_customer", "company_name", None),
         ("export.pipeline", "pipeline_name", None), ("pipeline.stage", "stage_name", None),
         ("export.stage_kind", "stage_kind", "kind"), ("pipeline.value", "value_cents", "money"),
         ("customers.owner", "owner_name", None), ("pipeline.expected_close", "expected_close", None),
         ("export.closed_at", "closed_at", "datetime"), ("pipeline.lost_reason", "lost_reason", None),
         ("export.created_at", "created_at", "datetime")],
        "SELECT o.*, c.name AS company_name, p.name AS pipeline_name, s.name AS stage_name, s.kind AS stage_kind, "
        "u.name AS owner_name FROM opportunities o JOIN companies c ON c.id = o.company_id "
        "JOIN pipelines p ON p.id = o.pipeline_id JOIN stages s ON s.id = o.stage_id "
        "LEFT JOIN users u ON u.id = o.owner_id WHERE o.workspace_id = ? ORDER BY o.created_at, o.id",
    ),
    "quotes": (
        [("export.number", "number", "number"), ("customers.col_customer", "company_name", None),
         ("export.opportunity", "opportunity_title", None), ("export.status", "status", "status"),
         ("export.list_total", "list_total_cents", "money"), ("export.discount", "effective_discount_bps", "percent"),
         ("export.final_total", "final_total_cents", "money"), ("export.margin", "margin_bps", "percent"),
         ("export.created_by", "creator_name", None), ("export.created_at", "created_at", "datetime"),
         ("export.sent_at", "sent_at", "datetime"), ("export.decided_at", "customer_decided_at", "datetime")],
        "SELECT q.*, c.name AS company_name, o.title AS opportunity_title, u.name AS creator_name FROM quotes q "
        "JOIN companies c ON c.id = q.company_id JOIN opportunities o ON o.id = q.opportunity_id "
        "LEFT JOIN users u ON u.id = q.created_by WHERE q.workspace_id = ? ORDER BY q.number",
    ),
    "products": (
        [("products.sku", "sku", None), ("products.name", "name", None), ("products.unit", "unit", None),
         ("products.price", "price_cents", "money"), ("export.cost", "cost_cents", "money"),
         ("export.active", "active", "yesno"), ("export.created_at", "created_at", "datetime")],
        "SELECT * FROM products WHERE workspace_id = ? ORDER BY name COLLATE NOCASE",
    ),
}

# EN: First characters that spreadsheets treat as a formula | PT: Primeiros caracteres que planilhas tratam como fórmula
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    """EN: Text for one cell; neutralizes formulas with a leading apostrophe.
    PT: Texto de uma célula; neutraliza fórmulas com um apóstrofo na frente.
    """
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def format_value(value, kind, decimal):
    """EN: Format one value for the file. Numbers are built with integer math (cents, bps).
    PT: Formata um valor para o arquivo. Números montados com conta inteira (centavos, bps).
    """
    if value is None or value == "":
        return ""
    # EN: cents and basis points both have two decimals: 12345 -> 123,45
    # PT: centavos e pontos-base têm duas casas: 12345 -> 123,45
    if kind in ("money", "percent"):
        sign = "-" if value < 0 else ""
        value = abs(value)
        return f"{sign}{value // 100}{decimal}{value % 100:02d}"
    if kind == "number":
        return f"{value:04d}"
    if kind == "datetime":
        return to_local(value)
    if kind == "cnpj":
        return format_cnpj(value)
    if kind == "phone":
        return format_phone(value)
    if kind == "status":
        return _("quotes.status_" + value)
    if kind == "kind":
        return _("export.kind_" + value)
    if kind == "yesno":
        return _("export.yes") if value else _("export.no")
    return value


@exports_bp.route("/export/<kind>.csv")
@require_role("admin")
def download(kind):
    """EN: Build the CSV in memory and send it as a download.
    PT: Monta o CSV na memória e envia como download.
    """
    if kind not in EXPORTS:
        return apology(_("export.error_kind"), 404)
    if not has_feature("csv_export"):
        return apology(_("export.error_plan"), 403)

    columns, sql = EXPORTS[kind]
    portuguese = current_lang() == "pt"
    delimiter, decimal = (";", ",") if portuguese else (",", ".")

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow([_(label) for label, _field, _fmt in columns])
    for row in get_db().execute(sql, workspace_id()):
        writer.writerow([safe_cell(format_value(row[field], fmt, decimal)) for _label, field, fmt in columns])

    filename = f"supplyflow-{kind}-{today_sp()}.csv"
    # EN: the BOM (﻿) makes Excel read the accents correctly | PT: o BOM (﻿) faz o Excel ler os acentos certo
    return Response(
        "﻿" + buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )
