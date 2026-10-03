"""
EN: Unit tests for the repurchase rule (repurchase.alert_for). Run from project/:
    python -m unittest discover tests
PT: Testes unitários da regra de recompra (repurchase.alert_for). Rode dentro de project/:
    python -m unittest discover tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from repurchase import alert_for


class AlertForTest(unittest.TestCase):

    def test_needs_three_orders(self):
        # EN: two orders long ago: still no alert (not enough history)
        # PT: dois pedidos há muito tempo: ainda sem alerta (histórico insuficiente)
        self.assertIsNone(alert_for(["2026-01-01", "2026-01-08"], "2026-09-01"))

    def test_every_order_on_the_same_day(self):
        # EN: no rhythm to compare with | PT: não há ritmo para comparar
        self.assertIsNone(alert_for(["2026-01-01"] * 3, "2026-09-01"))

    def test_on_rhythm_no_alert(self):
        # EN: weekly buyer, last order 7 days ago | PT: compra semanal, último pedido há 7 dias
        self.assertIsNone(alert_for(["2026-09-03", "2026-09-10", "2026-09-17"], "2026-09-24"))

    def test_exactly_one_and_a_half_is_not_late(self):
        # EN: average 10 days, 15 days without buying = exactly 1.5x -> no alert (rule is ">")
        # PT: média 10 dias, 15 dias sem comprar = exatamente 1,5x -> sem alerta (a regra é ">")
        self.assertIsNone(alert_for(["2026-09-01", "2026-09-11", "2026-09-21"], "2026-10-06"))

    def test_one_day_past_the_limit(self):
        alert = alert_for(["2026-09-01", "2026-09-11", "2026-09-21"], "2026-10-07")
        self.assertEqual(alert["orders"], 3)
        self.assertEqual(alert["average_days"], 10)
        self.assertEqual(alert["days_since"], 16)
        self.assertEqual(alert["late_days"], 6)
        self.assertEqual(alert["last"], "2026-09-21")

    def test_unsorted_dates_and_repeats(self):
        # EN: order of the list must not matter | PT: a ordem da lista não pode importar
        alert = alert_for(["2026-09-21", "2026-09-01", "2026-09-11", "2026-09-11"], "2026-10-30")
        self.assertEqual(alert["orders"], 4)
        self.assertEqual(alert["average_days"], 7)
        self.assertEqual(alert["days_since"], 39)

    def test_uneven_average_is_compared_without_rounding(self):
        # EN: span 7 over 2 gaps = 3.5 days; limit 5.25 -> 5 days is fine, 6 days is late
        # PT: intervalo 7 em 2 vãos = 3,5 dias; limite 5,25 -> 5 dias ok, 6 dias atrasado
        dates = ["2026-09-01", "2026-09-04", "2026-09-08"]
        self.assertIsNone(alert_for(dates, "2026-09-13"))
        alert = alert_for(dates, "2026-09-14")
        self.assertEqual(alert["average_days"], 4)
        self.assertEqual(alert["late_days"], 2)

    def test_new_order_clears_the_alert(self):
        dates = ["2026-07-01", "2026-07-15", "2026-07-29"]
        self.assertIsNotNone(alert_for(dates, "2026-09-01"))
        self.assertIsNone(alert_for(dates + ["2026-08-31"], "2026-09-01"))

    def test_rejects_invalid_dates(self):
        with self.assertRaises(ValueError):
            alert_for(["2026-13-01", "2026-01-01", "2026-02-01"], "2026-09-01")


if __name__ == "__main__":
    unittest.main()
