"""EN: Quote pricing: the single place where a quote's numbers are calculated.
    Pure functions (no database, no Flask), so they are easy to test and to explain.
PT: Cálculo do orçamento: o único lugar onde os números de um orçamento são calculados.
    Funções puras (sem banco, sem Flask), então são fáceis de testar e de explicar.

EN: Units (docs/ARCHITECTURE.md, section 6.3):
    * money is integer cents          R$ 12,34 -> 1234
    * percentages are basis points    12,5%    -> 1250   (10000 = 100%)
    No float anywhere: 0.1 + 0.2 is not 0.3 in floating point, and a quote must add up
    to the cent every time.
PT: Unidades (docs/ARCHITECTURE.md, seção 6.3):
    * dinheiro em centavos inteiros       R$ 12,34 -> 1234
    * porcentagem em basis points         12,5%    -> 1250   (10000 = 100%)
    Nada de float: 0.1 + 0.2 não dá 0.3 em ponto flutuante, e um orçamento precisa fechar
    no centavo, sempre.

EN: Order of the calculation (fixed, so the same quote always gives the same total):
    1. line     = list price x quantity, minus the item discount
    2. subtotal = sum of the lines
    3. final    = subtotal minus the quote-wide (header) discount
    4. list     = sum of list price x quantity (what it would cost with no discount)
    5. effective discount = (list - final) / list          -> what approval looks at
    6. margin   = (final - cost) / final, only over items that have a cost
PT: Ordem do cálculo (fixa, para o mesmo orçamento sempre dar o mesmo total):
    1. linha    = preço de tabela x quantidade, menos o desconto do item
    2. subtotal = soma das linhas
    3. final    = subtotal menos o desconto geral do orçamento
    4. tabela   = soma de preço de tabela x quantidade (quanto custaria sem desconto)
    5. desconto efetivo = (tabela - final) / tabela          -> é o que a aprovação olha
    6. margem   = (final - custo) / final, só sobre os itens que têm custo
"""

BPS_FULL = 10000   # EN: 100% in basis points | PT: 100% em basis points


def round_div(numerator, denominator):
    """EN: Integer division rounded half away from zero (the way people round money):
        round_div(5, 2) = 3, round_div(-5, 2) = -3. Python's round() rounds half to even
        (round(2.5) == 2), which would surprise a customer, so we don't use it.
    PT: Divisão inteira arredondando o meio para longe do zero (como as pessoas arredondam
        dinheiro): round_div(5, 2) = 3, round_div(-5, 2) = -3. O round() do Python arredonda
        o meio para o par (round(2.5) == 2), o que surpreenderia um cliente, então não usamos.
    """
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    sign = -1 if numerator < 0 else 1
    return sign * ((abs(numerator) * 2 + denominator) // (denominator * 2))


def apply_discount(cents, discount_bps):
    """EN: Value after a discount: 10000 cents with 1250 bps (12,5%) -> 8750.
    PT: Valor depois de um desconto: 10000 centavos com 1250 bps (12,5%) -> 8750.
    """
    if not 0 <= discount_bps <= BPS_FULL:
        raise ValueError("discount must be between 0 and 10000 bps")
    return round_div(cents * (BPS_FULL - discount_bps), BPS_FULL)


def line_total(list_price_cents, quantity, discount_bps):
    """EN: Step 1: one item line. The discount is applied to the whole line (price x
        quantity), not to the unit price, so rounding happens once per line.
    PT: Passo 1: uma linha de item. O desconto é aplicado na linha inteira (preço x
        quantidade), não no preço unitário, então o arredondamento acontece uma vez por linha.
    """
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    return apply_discount(list_price_cents * quantity, discount_bps)


def ratio_bps(part, whole):
    """EN: part / whole as basis points, rounded: ratio_bps(1, 8) = 1250 (12,5%).
    PT: parte / todo em basis points, arredondado: ratio_bps(1, 8) = 1250 (12,5%).
    """
    return round_div(part * BPS_FULL, whole)


def calculate(items, header_discount_bps=0):
    """EN: Calculate a whole quote.
        items: list of dicts with list_price_cents, quantity, discount_bps and an optional
        cost_cents (None when the product has no cost registered).
        Returns the line totals plus every total stored in the quotes table.
    PT: Calcula um orçamento inteiro.
        items: lista de dicts com list_price_cents, quantity, discount_bps e um cost_cents
        opcional (None quando o produto não tem custo cadastrado).
        Devolve o total de cada linha e todos os totais guardados na tabela quotes.
    """
    lines = [line_total(i["list_price_cents"], i["quantity"], i["discount_bps"]) for i in items]

    # EN: steps 2-4 | PT: passos 2-4
    subtotal = sum(lines)
    final = apply_discount(subtotal, header_discount_bps)
    list_total = sum(i["list_price_cents"] * i["quantity"] for i in items)

    # EN: step 5: an empty or free quote has no discount
    # PT: passo 5: orçamento vazio ou gratuito não tem desconto
    effective = ratio_bps(list_total - final, list_total) if list_total else 0

    # EN: Step 6: margin only where the cost is known. The header discount also applies to
    #     those lines, so it is applied to their subtotal the same way as in step 3.
    # PT: Passo 6: margem só onde o custo é conhecido. O desconto geral também vale para
    #     essas linhas, então é aplicado no subtotal delas do mesmo jeito do passo 3.
    costed = [(line, item) for line, item in zip(lines, items) if item.get("cost_cents") is not None]
    margin = None
    if costed:
        costed_final = apply_discount(sum(line for line, _ in costed), header_discount_bps)
        costed_cost = sum(item["cost_cents"] * item["quantity"] for _, item in costed)
        if costed_final > 0:
            # EN: can be negative (selling below cost), never above 100%
            # PT: pode ser negativa (vendendo abaixo do custo), nunca acima de 100%
            margin = ratio_bps(costed_final - costed_cost, costed_final)

    return {
        "lines": lines,
        "list_total_cents": list_total,
        "final_total_cents": final,
        "effective_discount_bps": effective,
        "margin_bps": margin,
        "has_unpriced_cost": len(costed) < len(items),
    }
