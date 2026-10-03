"""EN: Unit tests for pricing.py. Every expected number was calculated by hand.
    Run from project/:  python -m unittest discover tests
PT: Testes unitários do pricing.py. Todo número esperado foi calculado à mão.
    Rode dentro de project/:  python -m unittest discover tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pricing import apply_discount, calculate, line_total, ratio_bps, round_div  # noqa: E402


def item(price, quantity, discount=0, cost=None):
    return {"list_price_cents": price, "quantity": quantity, "discount_bps": discount, "cost_cents": cost}


class RoundingTests(unittest.TestCase):
    def test_half_rounds_away_from_zero(self):
        # EN: 2.5 -> 3 and -2.5 -> -3 (Python's round() would give 2 and -2)
        # PT: 2,5 -> 3 e -2,5 -> -3 (o round() do Python daria 2 e -2)
        self.assertEqual(round_div(5, 2), 3)
        self.assertEqual(round_div(-5, 2), -3)

    def test_below_and_above_half(self):
        self.assertEqual(round_div(1, 3), 0)    # EN/PT: 0,33 -> 0
        self.assertEqual(round_div(2, 3), 1)    # EN/PT: 0,67 -> 1
        self.assertEqual(round_div(10, 5), 2)   # EN/PT: exact | exato

    def test_denominator_must_be_positive(self):
        with self.assertRaises(ValueError):
            round_div(1, 0)


class DiscountTests(unittest.TestCase):
    def test_apply_discount(self):
        self.assertEqual(apply_discount(10000, 1250), 8750)   # EN/PT: R$ 100,00 - 12,5% = R$ 87,50
        self.assertEqual(apply_discount(999, 3333), 666)      # EN/PT: 9,99 x 0,6667 = 6,6603 -> 6,66
        self.assertEqual(apply_discount(5000, 0), 5000)
        self.assertEqual(apply_discount(5000, 10000), 0)

    def test_discount_out_of_range(self):
        with self.assertRaises(ValueError):
            apply_discount(100, -1)
        with self.assertRaises(ValueError):
            apply_discount(100, 10001)

    def test_line_rounds_once_per_line(self):
        # EN: 3 x R$ 0,33 with 50%: 99 x 0,5 = 49,5 -> 50 cents for the whole line
        #     (rounding each unit would give 3 x 17 = 51)
        # PT: 3 x R$ 0,33 com 50%: 99 x 0,5 = 49,5 -> 50 centavos na linha inteira
        #     (arredondar cada unidade daria 3 x 17 = 51)
        self.assertEqual(line_total(33, 3, 5000), 50)

    def test_quantity_must_be_positive(self):
        with self.assertRaises(ValueError):
            line_total(100, 0, 0)

    def test_ratio(self):
        self.assertEqual(ratio_bps(1, 8), 1250)
        self.assertEqual(ratio_bps(1, 3), 3333)


class QuoteTests(unittest.TestCase):
    def test_landing_page_example(self):
        # EN: The landing page's example: rice 10 x 100, oil 8 x 50, beans 5 x 80 = R$ 1.800,00
        #     list; cost R$ 1.376,00; 8% quote-wide discount.
        # PT: O exemplo da página inicial: arroz 10 x 100, óleo 8 x 50, feijão 5 x 80 =
        #     R$ 1.800,00 de tabela; custo R$ 1.376,00; 8% de desconto geral.
        items = [item(10000, 10, cost=7800), item(5000, 8, cost=3700), item(8000, 5, cost=6000)]
        result = calculate(items, 800)
        self.assertEqual(result["list_total_cents"], 180000)
        self.assertEqual(result["final_total_cents"], 165600)        # EN/PT: 1800 x 0,92
        self.assertEqual(result["effective_discount_bps"], 800)
        self.assertEqual(result["margin_bps"], 1691)                 # EN/PT: (1656 - 1376) / 1656 = 16,908%
        self.assertFalse(result["has_unpriced_cost"])

    def test_item_and_header_discounts_combine(self):
        # EN: Example from ARCHITECTURE.md 6.3: list R$ 1.200,00; rice 5% and oil 20% give
        #     R$ 1.110,00; then 5% quote-wide -> R$ 1.054,50; effective = 12,125% -> 1213 bps
        # PT: Exemplo do ARCHITECTURE.md 6.3: tabela R$ 1.200,00; arroz 5% e óleo 20% dão
        #     R$ 1.110,00; depois 5% geral -> R$ 1.054,50; efetivo = 12,125% -> 1213 bps
        items = [item(10000, 10, 500), item(5000, 4, 2000)]
        result = calculate(items, 500)
        self.assertEqual(result["lines"], [95000, 16000])
        self.assertEqual(result["final_total_cents"], 105450)
        self.assertEqual(result["effective_discount_bps"], 1213)
        self.assertIsNone(result["margin_bps"])
        self.assertTrue(result["has_unpriced_cost"])

    def test_margin_only_over_items_with_cost(self):
        # EN: Only the first item has a cost: margin = (100 - 60) / 100 = 40%,
        #     the second item (no cost) doesn't count.
        # PT: Só o primeiro item tem custo: margem = (100 - 60) / 100 = 40%,
        #     o segundo item (sem custo) não entra.
        result = calculate([item(10000, 1, cost=6000), item(5000, 2)])
        self.assertEqual(result["margin_bps"], 4000)
        self.assertTrue(result["has_unpriced_cost"])

    def test_negative_margin(self):
        # EN/PT: R$ 39,90 sold with cost R$ 41,00: (3990 - 4100) / 3990 = -2,757% -> -276 bps
        result = calculate([item(3990, 1, cost=4100)])
        self.assertEqual(result["margin_bps"], -276)

    def test_empty_quote(self):
        result = calculate([], 1000)
        self.assertEqual(result["final_total_cents"], 0)
        self.assertEqual(result["effective_discount_bps"], 0)
        self.assertIsNone(result["margin_bps"])

    def test_full_discount(self):
        result = calculate([item(10000, 2, cost=5000)], 10000)
        self.assertEqual(result["final_total_cents"], 0)
        self.assertEqual(result["effective_discount_bps"], 10000)
        self.assertIsNone(result["margin_bps"])   # EN/PT: nothing sold, no margin | nada vendido, sem margem

    def test_totals_add_up_to_the_cent(self):
        # EN: the stored lines always sum to the subtotal before the header discount
        # PT: as linhas guardadas sempre somam o subtotal antes do desconto geral
        items = [item(1999, 7, 333), item(2550, 3, 1250), item(99, 41, 0)]
        result = calculate(items, 0)
        self.assertEqual(sum(result["lines"]), result["final_total_cents"])


if __name__ == "__main__":
    unittest.main()
