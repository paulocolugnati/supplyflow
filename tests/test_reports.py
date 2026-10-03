"""
EN: Unit tests for the dashboard report math (reports.py), no database. Run from project/:
    python -m unittest discover tests
PT: Testes unitários das contas do relatório do painel (reports.py), sem banco. Rode dentro
    de project/: python -m unittest discover tests
"""

import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import SAO_PAULO
from reports import by_customer, by_seller, period_range, summarize


def sale(owner, company, total, list_total=None, manual=False, at="2026-10-01 12:00:00"):
    return {"owner_id": owner, "company_id": company, "total": total, "list": list_total, "manual": 1 if manual else 0, "at": at}


class PeriodTest(unittest.TestCase):
    NOW = datetime(2026, 10, 15, 14, 30, tzinfo=SAO_PAULO)

    def test_this_month_starts_at_midnight_in_sao_paulo(self):
        # EN: 1 Oct 00:00 in Sao Paulo = 03:00 UTC | PT: 1º/out 00:00 em São Paulo = 03:00 UTC
        self.assertEqual(period_range("month", self.NOW), ("2026-10-01 03:00:00", None))

    def test_last_month_is_closed(self):
        self.assertEqual(period_range("last_month", self.NOW), ("2026-09-01 03:00:00", "2026-10-01 03:00:00"))

    def test_last_month_in_january_goes_to_december(self):
        now = datetime(2027, 1, 10, 9, 0, tzinfo=SAO_PAULO)
        self.assertEqual(period_range("last_month", now), ("2026-12-01 03:00:00", "2027-01-01 03:00:00"))

    def test_ninety_days(self):
        self.assertEqual(period_range("90d", self.NOW), ("2026-07-17 03:00:00", None))

    def test_unknown_code_falls_back_to_month(self):
        self.assertEqual(period_range("'; DROP TABLE quotes; --", self.NOW), period_range("month", self.NOW))


class SummaryTest(unittest.TestCase):

    def test_empty_period(self):
        totals = summarize([], 0, 0)
        self.assertEqual((totals["sold"], totals["orders"], totals["ticket"]), (0, 0, 0))
        self.assertIsNone(totals["avg_discount_bps"])
        self.assertIsNone(totals["conversion_bps"])

    def test_totals_ticket_discount_and_conversion(self):
        rows = [sale(1, 10, 9000, 10000), sale(1, 11, 30000, 30000), sale(2, 10, 5000, manual=True)]
        totals = summarize(rows, sent=4, sent_accepted=1)
        self.assertEqual(totals["sold"], 44000)
        self.assertEqual(totals["orders"], 3)
        self.assertEqual(totals["manual"], 5000)
        self.assertEqual(totals["ticket"], 14667)            # EN/PT: 44000 / 3 = 14666,67 -> 14667
        self.assertEqual(totals["avg_discount_bps"], 250)    # EN/PT: 1000 off 40000 = 2,5% (manual win ignored)
        self.assertEqual(totals["conversion_bps"], 2500)     # EN/PT: 1 of 4 = 25%


class RankingTest(unittest.TestCase):
    PEOPLE = {1: {"name": "Diego", "commission_bps": 300}, 2: {"name": "Fernanda", "commission_bps": 250}}

    def test_ranking_order_commission_and_share(self):
        rows = [sale(1, 10, 10000, 10000), sale(2, 10, 30000, 32000), sale(2, 11, 3333, manual=True)]
        ranking = by_seller(rows, self.PEOPLE)
        self.assertEqual([g["name"] for g in ranking], ["Fernanda", "Diego"])
        fernanda, diego = ranking
        self.assertEqual(fernanda["sold"], 33333)
        self.assertEqual(fernanda["commission"], 833)        # EN/PT: 2,5% of 333,33 = 8,33
        self.assertEqual(fernanda["avg_discount_bps"], 625)  # EN/PT: 2000 off 32000 = 6,25%
        self.assertEqual(fernanda["manual"], 3333)
        self.assertEqual(diego["commission"], 300)
        self.assertEqual((fernanda["share"], diego["share"]), (1.0, 0.3))

    def test_sale_without_seller_and_unknown_person(self):
        ranking = by_seller([sale(None, 10, 500), sale(99, 10, 700)], self.PEOPLE)
        self.assertEqual({g["user_id"] for g in ranking}, {None, 99})
        self.assertTrue(all(g["commission"] == 0 for g in ranking))

    def test_top_customers(self):
        rows = [sale(1, 10, 100, at="2026-10-02 10:00:00"), sale(1, 10, 200, at="2026-10-05 10:00:00"), sale(2, 11, 250)]
        top = by_customer(rows, {10: "Restaurante", 11: "Padaria"})
        self.assertEqual([(c["name"], c["total"], c["orders"]) for c in top], [("Restaurante", 300, 2), ("Padaria", 250, 1)])
        self.assertEqual(top[0]["last"], "2026-10-05 10:00:00")


if __name__ == "__main__":
    unittest.main()
