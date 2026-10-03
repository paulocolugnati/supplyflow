"""EN: Unit tests for approval.py: ceilings, who approves, self-approval and the
    "approve 10%, raise to 25%" bypass. Run from project/:  python -m unittest discover tests
PT: Testes unitários do approval.py: tetos, quem aprova, autoaprovação e o bypass
    "aprova 10%, sobe para 25%". Rode dentro de project/:  python -m unittest discover tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from approval import (FINAL_STATES, TransitionError, approval_reasons, can_decide, can_send,  # noqa: E402
                      ceiling, required_role, transition)

# EN: seller 5%, manager 15%, minimum margin 15% (the product's defaults)
# PT: vendedor 5%, gerente 15%, margem mínima 15% (os padrões do produto)
WS = {"member_discount_limit_bps": 500, "admin_discount_limit_bps": 1500, "min_margin_bps": 1500}


class StateMachineTests(unittest.TestCase):
    def test_happy_paths(self):
        self.assertEqual(transition("draft", "ready"), "ready")
        self.assertEqual(transition("draft", "pending_approval"), "pending_approval")
        self.assertEqual(transition("pending_approval", "ready"), "ready")
        self.assertEqual(transition("ready", "sent"), "sent")
        self.assertEqual(transition("sent", "accepted"), "accepted")

    def test_shortcuts_are_refused(self):
        # EN: a draft can't jump to sent or accepted; a pending quote can't be sent
        # PT: um rascunho não pula para enviado ou aceito; um pendente não pode ser enviado
        for current, new in [("draft", "sent"), ("draft", "accepted"), ("pending_approval", "sent"), ("sent", "draft")]:
            with self.assertRaises(TransitionError):
                transition(current, new)

    def test_final_states_are_final(self):
        self.assertEqual(FINAL_STATES, {"accepted", "declined", "expired", "cancelled"})
        for state in FINAL_STATES:
            with self.assertRaises(TransitionError):
                transition(state, "draft")

    def test_unknown_state(self):
        with self.assertRaises(TransitionError):
            transition("hacked", "ready")


class CeilingTests(unittest.TestCase):
    def test_ceilings(self):
        self.assertEqual(ceiling("member", WS), 500)
        self.assertEqual(ceiling("admin", WS), 1500)
        self.assertIsNone(ceiling("owner", WS))

    def test_within_and_above(self):
        self.assertEqual(approval_reasons(500, 2000, "member", WS, True), [])           # EN/PT: exactly on the ceiling | exatamente no teto
        self.assertEqual(approval_reasons(501, 2000, "member", WS, True), ["discount"])
        self.assertEqual(approval_reasons(1200, 2000, "admin", WS, True), [])
        self.assertEqual(approval_reasons(9000, 2000, "owner", WS, True), [])           # EN/PT: owner has no ceiling | owner não tem teto

    def test_margin_trigger(self):
        self.assertEqual(approval_reasons(300, 1200, "member", WS, True), ["margin"])
        self.assertEqual(approval_reasons(800, 1200, "member", WS, True), ["discount", "margin"])
        self.assertEqual(approval_reasons(300, 1200, "member", WS, False), [])          # EN/PT: plan without the feature | plano sem o recurso
        self.assertEqual(approval_reasons(300, None, "member", WS, True), [])           # EN/PT: no cost known | custo desconhecido
        self.assertEqual(approval_reasons(300, -500, "owner", WS, True), [])            # EN/PT: owner decides alone | owner decide sozinho

    def test_who_approves(self):
        self.assertEqual(required_role(800, WS), "admin")
        self.assertEqual(required_role(1500, WS), "admin")
        self.assertEqual(required_role(1501, WS), "owner")


class DecisionTests(unittest.TestCase):
    def test_nobody_approves_their_own_request(self):
        request = {"requested_by": 7, "required_role": "admin"}
        self.assertFalse(can_decide(7, "owner", request))
        self.assertTrue(can_decide(8, "admin", request))

    def test_role_must_reach_the_required_one(self):
        request = {"requested_by": 7, "required_role": "owner"}
        self.assertFalse(can_decide(8, "admin", request))
        self.assertFalse(can_decide(8, "member", request))
        self.assertTrue(can_decide(9, "owner", request))


class SendTests(unittest.TestCase):
    def test_no_approval_needed(self):
        self.assertTrue(can_send({"approved_discount_bps": None, "effective_discount_bps": 300}, []))

    def test_needed_but_never_approved(self):
        self.assertFalse(can_send({"approved_discount_bps": None, "effective_discount_bps": 800}, ["discount"]))

    def test_the_bypass_is_closed(self):
        # EN: approved for 10%, then the discount became 25%: can't be sent
        # PT: aprovado para 10%, depois o desconto virou 25%: não pode ser enviado
        self.assertFalse(can_send({"approved_discount_bps": 1000, "effective_discount_bps": 2500}, ["discount"]))
        self.assertTrue(can_send({"approved_discount_bps": 1000, "effective_discount_bps": 1000}, ["discount"]))


if __name__ == "__main__":
    unittest.main()
