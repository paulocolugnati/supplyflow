"""EN: Discount approval and quote states: the rules that make SupplyFlow exist.
    Pure functions (no database, no Flask), so they are easy to test and to explain.
PT: Aprovação de desconto e estados do orçamento: as regras que fazem o SupplyFlow existir.
    Funções puras (sem banco, sem Flask), então são fáceis de testar e de explicar.

EN: The rules (docs/ARCHITECTURE.md, sections 6.4 and 6.5):
    1. Each role has a ceiling: member -> member_discount_limit_bps,
       admin -> admin_discount_limit_bps, owner -> no ceiling.
    2. A quote needs approval when its effective discount is above the creator's ceiling,
       OR (plan has minimum margin) its margin is below the workspace minimum and the
       creator is not the owner.
    3. Who approves: an admin when the discount fits the admin ceiling, otherwise the owner.
    4. Nobody approves their own request.
    5. The approval is for an EXACT discount: the quote can only be sent while its discount
       is not above the approved one. Editing sends it back to draft and drops the approval,
       so "ask for 10%, get it approved, then raise to 25%" is impossible.
PT: As regras (docs/ARCHITECTURE.md, seções 6.4 e 6.5):
    1. Cada cargo tem um teto: member -> member_discount_limit_bps,
       admin -> admin_discount_limit_bps, owner -> sem teto.
    2. Um orçamento precisa de aprovação quando o desconto efetivo passa do teto de quem
       criou, OU (plano com margem mínima) a margem fica abaixo da mínima da distribuidora e
       quem criou não é o owner.
    3. Quem aprova: um admin quando o desconto cabe no teto do admin, senão o owner.
    4. Ninguém aprova o próprio pedido.
    5. A aprovação vale para um desconto EXATO: o orçamento só pode ser enviado enquanto o
       desconto não passar do aprovado. Editar devolve para rascunho e derruba a aprovação,
       então "pedir 10%, ser aprovado e depois subir para 25%" é impossível.
"""

ROLE_RANK = {"member": 1, "admin": 2, "owner": 3}


# ---------------------------------------------------------------------------
# EN: Quote state machine
# PT: Máquina de estados do orçamento
# ---------------------------------------------------------------------------

# EN: Allowed moves. Anything not listed is refused by transition().
# PT: Movimentos permitidos. Qualquer coisa fora da lista é recusada pelo transition().
TRANSITIONS = {
    "draft": {"pending_approval", "ready", "cancelled"},
    "pending_approval": {"ready", "draft", "cancelled"},      # EN: approved / rejected or reopened | PT: aprovado / recusado ou reaberto
    "ready": {"sent", "draft", "cancelled"},                 # EN: draft = reopened to edit | PT: draft = reaberto para editar
    "sent": {"accepted", "declined", "expired", "cancelled"},
    "accepted": set(),
    "declined": set(),
    "expired": set(),
    "cancelled": set(),
}
FINAL_STATES = {state for state, moves in TRANSITIONS.items() if not moves}


class TransitionError(ValueError):
    """EN: A move that the state machine doesn't allow. | PT: Um movimento que a máquina de estados não permite."""


def transition(current, new):
    """EN: Validate a status change and return the new status, or raise TransitionError.
        Every route that changes a quote's status goes through here.
    PT: Valida uma mudança de status e devolve o status novo, ou levanta TransitionError.
        Toda rota que muda o status de um orçamento passa por aqui.
    """
    if new not in TRANSITIONS.get(current, set()):
        raise TransitionError(f"{current} -> {new} is not allowed")
    return new


# ---------------------------------------------------------------------------
# EN: Ceilings and approval
# PT: Tetos e aprovação
# ---------------------------------------------------------------------------

def ceiling(role, workspace):
    """EN: The discount a role may give alone, in bps, or None for "no ceiling" (owner).
    PT: O desconto que um cargo pode dar sozinho, em bps, ou None para "sem teto" (owner).
    """
    if role == "owner":
        return None
    if role == "admin":
        return workspace["admin_discount_limit_bps"]
    return workspace["member_discount_limit_bps"]


def approval_reasons(effective_bps, margin_bps, creator_role, workspace, min_margin_enabled):
    """EN: Why this quote needs approval: a list with "discount" and/or "margin"
        (empty list = it doesn't need approval).
    PT: Por que este orçamento precisa de aprovação: uma lista com "discount" e/ou "margin"
        (lista vazia = não precisa de aprovação).
    """
    reasons = []
    limit = ceiling(creator_role, workspace)
    if limit is not None and effective_bps > limit:
        reasons.append("discount")
    if (min_margin_enabled and creator_role != "owner" and margin_bps is not None
            and margin_bps < workspace["min_margin_bps"]):
        reasons.append("margin")
    return reasons


def required_role(effective_bps, workspace):
    """EN: Lowest role allowed to approve: admin if the discount fits the admin ceiling.
    PT: Menor cargo que pode aprovar: admin se o desconto cabe no teto do admin.
    """
    return "admin" if effective_bps <= workspace["admin_discount_limit_bps"] else "owner"


def can_decide(decider_id, decider_role, request):
    """EN: May this person approve or reject this request? Never the requester themselves,
        and only someone at or above the required role.
    PT: Esta pessoa pode aprovar ou recusar este pedido? Nunca o próprio solicitante, e só
        alguém no cargo exigido ou acima.
    """
    if decider_id == request["requested_by"]:
        return False
    return ROLE_RANK.get(decider_role, 0) >= ROLE_RANK[request["required_role"]]


def can_send(quote, reasons):
    """EN: The send check: a quote that needs approval may only go out if it was approved
        for at least its current discount (rule 5).
    PT: A conferência do envio: um orçamento que precisa de aprovação só sai se foi aprovado
        para pelo menos o desconto atual (regra 5).
    """
    if not reasons:
        return True
    approved = quote["approved_discount_bps"]
    return approved is not None and quote["effective_discount_bps"] <= approved
