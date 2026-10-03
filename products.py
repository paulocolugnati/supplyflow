"""EN: Product catalog of a distributor. Registered in app.py as a Blueprint.
PT: Catálogo de produtos de uma distribuidora. Registrado no app.py como um Blueprint.

EN: Rules (docs/ARCHITECTURE.md, sections 5.11, 7 and 8):
    * everyone on the staff sees the catalog; only admins and owners create, edit,
      activate/deactivate and delete products
    * SKU is unique per workspace (the database enforces it, we give a friendly message)
    * price is required and > 0; cost is optional and may be typed in R$ or as a % of the
      price: the server converts % to cents once and stores only cost_cents
    * a product already used in a quote can't be deleted (deactivate it instead); an
      inactive product stays in old quotes but can't enter new ones
    * the plan's product quota is checked before every insert
PT: Regras (docs/ARCHITECTURE.md, seções 5.11, 7 e 8):
    * toda a equipe vê o catálogo; só admins e owners criam, editam, ativam/desativam e
      apagam produtos
    * o SKU é único por distribuidora (o banco garante, nós damos uma mensagem amigável)
    * o preço é obrigatório e > 0; o custo é opcional e pode ser digitado em R$ ou em % do
      preço: o servidor converte % em centavos uma vez e guarda só cost_cents
    * produto já usado em orçamento não pode ser apagado (desative); produto inativo
      continua nos orçamentos antigos, mas não entra em orçamentos novos
    * a cota de produtos do plano é conferida antes de todo INSERT
"""

import re

from flask import Blueprint, flash, redirect, render_template, request

from database import get_db
from helpers import escape_like, money_input, parse_money, parse_percent, safe_redirect_target
from permissions import check_quota, get_scoped, has_role, require_role, workspace_id
from translations import _

products_bp = Blueprint("products", __name__)

# EN: Units a distributor sells in (shown translated) | PT: Unidades em que uma distribuidora vende (exibidas traduzidas)
UNITS = ["un", "cx", "fd", "pct", "kg", "g", "l", "ml", "dz"]
NAME_MAX = 120
SKU_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,29}$")


def margin_bps(price_cents, cost_cents):
    """EN: Margin over the selling price in basis points, or None without a cost.
        (price - cost) / price. It can be negative when the cost is above the price.
    PT: Margem sobre o preço de venda em basis points, ou None sem custo.
        (preço - custo) / preço. Pode ser negativa quando o custo passa do preço.
    """
    if cost_cents is None or not price_cents:
        return None
    return ((price_cents - cost_cents) * 10000) // price_cents


def read_product_form(existing=None):
    """EN: Read and validate the product form. Returns (form, values, errors).
    PT: Lê e valida o formulário de produto. Devolve (form, valores, erros).
    """
    form = {
        "sku": request.form.get("sku", "").strip().upper(),
        "name": request.form.get("name", "").strip(),
        "unit": request.form.get("unit", ""),
        "price": request.form.get("price", "").strip(),
        "cost_mode": request.form.get("cost_mode", "brl"),
        "cost": request.form.get("cost", "").strip(),
    }
    errors = []

    if not SKU_PATTERN.match(form["sku"]):
        errors.append("products.error_sku")
    else:
        taken = get_db().execute(
            "SELECT 1 FROM products WHERE workspace_id = ? AND sku = ? AND id != ?",
            workspace_id(), form["sku"], existing["id"] if existing else 0,
        )
        if taken:
            errors.append("products.error_sku_taken")
    if not 2 <= len(form["name"]) <= NAME_MAX:
        errors.append("products.error_name")
    if form["unit"] not in UNITS:
        errors.append("products.error_unit")

    price = parse_money(form["price"])
    if price is None or price <= 0:
        errors.append("products.error_price")

    # EN: Cost in R$ (default) or % of the price, converted to cents here, once
    # PT: Custo em R$ (padrão) ou em % do preço, convertido em centavos aqui, uma vez
    cost = None
    if form["cost"]:
        if form["cost_mode"] == "pct":
            bps = parse_percent(form["cost"])
            if bps is None:
                errors.append("products.error_cost_pct")
            elif price:
                cost = (price * bps + 5000) // 10000   # EN: half up | PT: meio para cima
        else:
            cost = parse_money(form["cost"])
            if cost is None:
                errors.append("products.error_cost")

    values = {"sku": form["sku"], "name": form["name"], "unit": form["unit"], "price_cents": price, "cost_cents": cost}
    return form, values, errors


def form_page(form, errors, product, status=200):
    return render_template("product_form.html", form=form, errors=errors, product=product, units=UNITS), status


@products_bp.route("/products")
@require_role("member")
def index():
    """EN: Catalog with search (name or SKU) and an active/inactive filter.
    PT: Catálogo com busca (nome ou SKU) e filtro de ativos/inativos.
    """
    q = request.args.get("q", "").strip()[:100]
    status = request.args.get("status", "active")

    conditions = ["workspace_id = ?"]
    params = [workspace_id()]
    if q:
        like = "%" + escape_like(q) + "%"
        conditions.append("(name LIKE ? ESCAPE '!' OR sku LIKE ? ESCAPE '!')")
        params += [like, like]
    if status == "active":
        conditions.append("active = 1")
    elif status == "inactive":
        conditions.append("active = 0")

    # EN: only the fixed condition strings are joined; values go through "?"
    # PT: só os pedaços fixos são juntados; os valores passam por "?"
    products = get_db().execute(
        "SELECT * FROM products WHERE " + " AND ".join(conditions) + " ORDER BY active DESC, name COLLATE NOCASE",
        *params,
    )
    for product in products:
        product["margin_bps"] = margin_bps(product["price_cents"], product["cost_cents"])

    counts = get_db().execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(active), 0) AS active FROM products WHERE workspace_id = ?",
        workspace_id(),
    )[0]
    return render_template(
        "products.html",
        products=products,
        counts=counts,
        filters={"q": q, "status": status},
        can_edit=has_role("admin"),
        can_add=check_quota("products"),
    )


@products_bp.route("/products/new", methods=["GET", "POST"])
@require_role("admin")
def create():
    """EN: Create a product (admins and owners; checks the plan quota first).
    PT: Cria um produto (admins e owners; confere a cota do plano antes).
    """
    if not check_quota("products"):
        flash(_("products.quota"), "warning")
        return redirect("/products")

    if request.method == "GET":
        return form_page({"unit": "cx", "cost_mode": "brl"}, [], None)

    form, values, errors = read_product_form()
    if errors:
        return form_page(form, errors, None, 400)

    try:
        get_db().execute(
            "INSERT INTO products (workspace_id, sku, name, unit, price_cents, cost_cents) VALUES (?, ?, ?, ?, ?, ?)",
            workspace_id(), values["sku"], values["name"], values["unit"], values["price_cents"], values["cost_cents"],
        )
    except ValueError:
        # EN: two people saving the same SKU at once; the UNIQUE index decides
        # PT: duas pessoas salvando o mesmo SKU ao mesmo tempo; o índice UNIQUE decide
        return form_page(form, ["products.error_sku_taken"], None, 400)

    flash(_("products.created"), "success")
    return redirect("/products")


@products_bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@require_role("admin")
def edit(product_id):
    """EN: Edit a product. Old quotes keep their copied price (quote_items), so a new
        price only affects new quotes.
    PT: Edita um produto. Orçamentos antigos guardam a cópia do preço (quote_items), então
        um preço novo só afeta orçamentos novos.
    """
    product = get_scoped("products", product_id)

    if request.method == "GET":
        form = {
            "sku": product["sku"], "name": product["name"], "unit": product["unit"],
            "price": money_input(product["price_cents"]), "cost_mode": "brl",
            "cost": money_input(product["cost_cents"]),
        }
        return form_page(form, [], product)

    form, values, errors = read_product_form(existing=product)
    if errors:
        return form_page(form, errors, product, 400)

    try:
        get_db().execute(
            "UPDATE products SET sku = ?, name = ?, unit = ?, price_cents = ?, cost_cents = ? "
            "WHERE id = ? AND workspace_id = ?",
            values["sku"], values["name"], values["unit"], values["price_cents"], values["cost_cents"],
            product_id, workspace_id(),
        )
    except ValueError:
        return form_page(form, ["products.error_sku_taken"], product, 400)

    flash(_("products.saved"), "success")
    return redirect("/products")


@products_bp.route("/products/<int:product_id>/toggle", methods=["POST"])
@require_role("admin")
def toggle(product_id):
    """EN: Activate or deactivate a product. Reactivating does not count against the quota:
        inactive products already count (the quota is about how many exist).
    PT: Ativa ou desativa um produto. Reativar não pesa na cota: produtos inativos já
        contam (a cota é sobre quantos existem).
    """
    product = get_scoped("products", product_id)
    new_state = 0 if product["active"] else 1
    get_db().execute("UPDATE products SET active = ? WHERE id = ? AND workspace_id = ?", new_state, product_id, workspace_id())
    flash(_("products.activated" if new_state else "products.deactivated"), "success")
    # EN: back to the same filtered list; only paths of this site are accepted
    # PT: volta para a mesma lista filtrada; só caminhos deste site são aceitos
    return redirect(safe_redirect_target(request.form.get("next"), "/products"))


@products_bp.route("/products/<int:product_id>/delete", methods=["POST"])
@require_role("admin")
def delete(product_id):
    """EN: Delete a product, unless a quote already uses it (then suggest deactivating).
    PT: Apaga um produto, a não ser que um orçamento já o use (aí sugere desativar).
    """
    get_scoped("products", product_id)
    try:
        get_db().execute("DELETE FROM products WHERE id = ? AND workspace_id = ?", product_id, workspace_id())
    except ValueError:
        flash(_("products.error_in_use"), "danger")
        return redirect("/products")
    flash(_("products.deleted"), "success")
    return redirect("/products")
