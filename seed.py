"""
EN: Builds the demo data of SupplyFlow on an empty database, through the app's real routes
    (sign-up, invites, forms with CSRF tokens), so every rule and validation runs exactly as
    for a person using the site. Everything is fictional: people, companies, CNPJs, e-mails
    (the ".example" domain is reserved for examples) and numbers.
    Past orders (for the repurchase alerts and the reports) are created through the routes
    and then dated in the past directly in the database, the only way to simulate history.
    Dates are relative to today, so the demo never gets old.

    Usage, from project/:
        flask --app app init-db --reset
        python seed.py

    Accounts (password demo1234):
        dono@demo.com        owner of "Distribuidora Sabor do Campo" (Profissional plan)
        gerente@demo.com     manager            vendedor@demo.com    seller (Diego)
        vendedora@demo.com   seller (Fernanda)  comprador@demo.com   buyer of two distributors
        litoral@demo.com     owner of "Distribuidora Litoral" (Grátis plan)
        plataforma@demo.com  platform operator (/platform)

PT: Monta os dados de demonstração do SupplyFlow num banco vazio, pelas rotas reais do app
    (cadastro, convites, formulários com token CSRF), então toda regra e validação roda igual
    a uma pessoa usando o site. Tudo é fictício: pessoas, empresas, CNPJs, e-mails (o domínio
    ".example" é reservado para exemplos) e números.
    Os pedidos antigos (para os alertas de recompra e os relatórios) são criados pelas rotas
    e depois datados no passado direto no banco, o único jeito de simular histórico.
    As datas são relativas a hoje, então a demo nunca envelhece.

    Uso, dentro de project/:
        flask --app app init-db --reset
        python seed.py
"""

import logging
import re
import sys
from datetime import datetime, timedelta, timezone

import app as appmod
from database import get_db
from helpers import date_sp_in_days

PASSWORD = "demo1234"
app = appmod.app
db = get_db()
CSRF = re.compile(r'name="_csrf" type="hidden" value="([^"]+)"')


# ---------------------------------------------------------------------------
# EN: Helpers: talk to the app like a browser | PT: Funções de ajuda: falar com o app como um navegador
# ---------------------------------------------------------------------------

def token(client, page):
    """EN: The CSRF token of a page. | PT: O token CSRF de uma página."""
    found = CSRF.search(client.get(page).text)
    if not found:
        raise SystemExit(f"No form on {page}: did a step fail?")
    return found.group(1)


def send(client, url, page="/dashboard", files=False, **data):
    """EN: POST a form like the browser does; stops the seed if the app refuses it.
    PT: Envia um formulário como o navegador; para o seed se o app recusar.
    """
    data["_csrf"] = token(client, page)
    response = client.post(url, data=data, content_type="multipart/form-data" if files else None)
    if response.status_code >= 400:
        raise SystemExit(f"{url} answered {response.status_code}: the seed stopped so the demo stays consistent.")
    return response


def sign_up(email, name, kind="distributor", workspace="", invite=None, phone=""):
    client = app.test_client()
    page = "/register" + (f"?invite={invite}" if invite else "")
    data = dict(account_type=kind, name=name, email=email, phone=phone, workspace_name=workspace,
                password=PASSWORD, confirmation=PASSWORD)
    if invite:
        data["invite"] = invite
    send(client, "/register", page=page, **data)
    return client


def log_in(email):
    client = app.test_client()
    send(client, "/login", page="/login", email=email, password=PASSWORD)
    return client


def one(sql, *args):
    rows = db.execute(sql, *args)
    return rows[0] if rows else None


def utc_days_ago(days, hour=14):
    """EN: A moment `days` ago, as the database's UTC text. | PT: Um momento `days` atrás, no texto UTC do banco."""
    moment = datetime.now(timezone.utc).replace(hour=hour, minute=30, second=0, microsecond=0) - timedelta(days=days)
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def invite_link(owner, email, role):
    """EN: Staff invite; returns the token shown once on the team page.
    PT: Convite de equipe; devolve o token mostrado uma vez na página da equipe.
    """
    send(owner, "/team/invite", page="/team", email=email, role=role)
    return re.search(r'/invite/([^"]+)"', owner.get("/team").text).group(1)


# ---------------------------------------------------------------------------
# EN: Demo story | PT: A história da demo
# ---------------------------------------------------------------------------

def main():
    logging.disable(logging.CRITICAL)
    if one("SELECT COUNT(*) AS n FROM users")["n"]:
        raise SystemExit("The database is not empty. Run 'flask --app app init-db --reset' first, then 'python seed.py'.")

    print("Distributor, onboarding and team")
    owner = sign_up("dono@demo.com", "Carlos Almeida", workspace="Distribuidora Sabor do Campo", phone="(19) 99876-1234")
    ws = one("SELECT id FROM workspaces")["id"]
    # EN/PT: step 1 (company data) and step 2 (ceilings) of the real onboarding | passos 1 e 2 do onboarding real
    send(owner, "/onboarding", page="/onboarding", files=True, name="Distribuidora Sabor do Campo",
         cnpj="98.765.432/0001-98", email="contato@sabordocampo.example", phone="(19) 3232-4545", city="Campinas")
    send(owner, "/onboarding/limits", page="/onboarding/limits", action="save", member_limit="5", admin_limit="15", min_margin="15")
    # EN: the plan is changed by the platform operator, as in real life (manual, after a WhatsApp chat)
    # PT: o plano é trocado pelo operador da plataforma, como na vida real (manual, depois de uma conversa no WhatsApp)
    operator = sign_up("plataforma@demo.com", "Operador SupplyFlow", kind="buyer")
    # EN/PT: the only way to become an operator: the terminal command | o único jeito de virar operador: o comando no terminal
    app.test_cli_runner().invoke(args=["make-admin", "plataforma@demo.com"])
    send(operator, f"/platform/workspaces/{ws}", page="/platform", plan="profissional", custom_price="")

    manager = sign_up("gerente@demo.com", "Beatriz Souza", invite=invite_link(owner, "gerente@demo.com", "admin"))
    diego = sign_up("vendedor@demo.com", "Diego Lima", invite=invite_link(owner, "vendedor@demo.com", "member"))
    fernanda = sign_up("vendedora@demo.com", "Fernanda Rocha", invite=invite_link(owner, "vendedora@demo.com", "member"))
    invite_link(owner, "novo.vendedor@demo.com", "member")          # EN/PT: stays pending | fica pendente
    uid = {r["email"]: r["id"] for r in db.execute("SELECT id, email FROM users")}
    for email, value in (("gerente@demo.com", "1"), ("vendedor@demo.com", "3"), ("vendedora@demo.com", "2,5")):
        send(owner, f"/team/members/{uid[email]}/commission", page="/team", commission=value)

    print("Customers and contacts")
    # EN/PT: who each logged browser is (user id) | quem é cada navegador logado (id do usuário)
    owner_of = {id(owner): uid["dono@demo.com"], id(manager): uid["gerente@demo.com"],
                id(diego): uid["vendedor@demo.com"], id(fernanda): uid["vendedora@demo.com"]}
    customers = [
        ("Restaurante do Zé", "11.222.333/0001-81", "Restaurante", "(11) 98765-4321", "São Paulo", diego,
         [("José Almeida", "Dono", "(11) 98765-4321"), ("Marta Lima", "Compradora", "(11) 97654-3210")]),
        ("Mercadinho Bom Preço", "22.333.444/0001-81", "Mercado", "(19) 99123-4567", "Campinas", fernanda,
         [("Rita Gomes", "Compras", "(19) 99123-4567")]),
        ("Padaria Pão Quente", "", "Padaria", "(11) 94567-8901", "Santo André", diego,
         [("Antônio Ferreira", "Dono", "(11) 94567-8901")]),
        ("Lanchonete Esquina", "", "Lanchonete", "(11) 93456-7890", "São Paulo", diego,
         [("Kelly Santos", "Gerente", "(11) 93456-7890")]),
        ("Hotel Serra Azul", "33.444.555/0001-81", "Hotel", "(12) 98877-6655", "Campos do Jordão", owner,
         [("Paulo Rezende", "Suprimentos", "(12) 98877-6655")]),
    ]
    company = {}
    for name, cnpj, segment, phone, city, seller, contacts in customers:
        # EN: owner_id matters only for managers; a seller's new customer is always theirs
        # PT: owner_id só vale para gerentes; o cliente novo de um vendedor é sempre dele
        send(seller, "/customers/new", page="/customers/new", name=name, cnpj=cnpj, segment=segment, phone=phone, city=city,
             owner_id=str(owner_of[id(seller)]))
        company[name] = one("SELECT id FROM companies WHERE name = ?", name)["id"]
        for contact_name, role, contact_phone in contacts:
            send(seller, f"/customers/{company[name]}/contacts", page=f"/customers/{company[name]}",
                 name=contact_name, position=role, phone=contact_phone)

    print("Products")
    products = [
        ("ARZ-5", "Arroz tipo 1, 5 kg", "fd", "100,00", "61,23"),
        ("FEI-1", "Feijão carioca, 1 kg", "fd", "80,00", "52,00"),
        ("OLE-900", "Óleo de soja, 900 ml (cx 20)", "cx", "50,00", "34,50"),
        ("CAF-500", "Café torrado e moído, 500 g", "cx", "189,00", "128,00"),
        ("ACU-1", "Açúcar refinado, 1 kg", "fd", "45,90", "31,00"),
        ("DET-500", "Detergente neutro, 500 ml (cx 24)", "cx", "52,80", ""),
        ("REF-2L", "Refrigerante cola 2 L (fd 6)", "fd", "38,00", "39,20"),
        ("FAR-ESP", "Farinha especial (linha antiga)", "fd", "70,00", "45,00"),
    ]
    product = {}
    for sku, name, unit, price, cost in products:
        send(owner, "/products/new", page="/products/new", sku=sku, name=name, unit=unit, price=price, cost_mode="brl", cost=cost)
        product[sku] = one("SELECT id FROM products WHERE sku = ?", sku)["id"]
    send(owner, f"/products/{product['FAR-ESP']}/toggle", page="/products")       # EN/PT: inactive | inativo

    stage = {r["name"]: r["id"] for r in db.execute("SELECT id, name FROM stages WHERE workspace_id = ?", ws)}

    def opportunity(seller, customer, title, stage_name, value="", expected=None):
        send(seller, "/opportunities/new", page="/opportunities/new", title=title, company_id=str(company[customer]),
             stage_id=str(stage[stage_name]), value=value, expected_close=expected or "", owner_id=str(owner_of[id(seller)]))
        return one("SELECT id FROM opportunities WHERE title = ?", title)["id"]

    def quote(seller, opp, items, header="0", valid_days=10, notes=""):
        send(seller, f"/opportunities/{opp}/quotes", page=f"/opportunities/{opp}")
        qid = one("SELECT id FROM quotes WHERE opportunity_id = ? ORDER BY id DESC", opp)["id"]
        for sku, quantity, discount in items:
            send(seller, f"/quotes/{qid}/items", page=f"/quotes/{qid}", product_id=str(product[sku]), quantity=str(quantity), discount=discount)
        fields = {"header_discount": header, "valid_until": date_sp_in_days(valid_days), "notes_customer": notes, "notes_internal": ""}
        for row in db.execute("SELECT id, quantity, discount_bps FROM quote_items WHERE quote_id = ?", qid):
            fields[f"quantity_{row['id']}"] = str(row["quantity"])
            fields[f"discount_{row['id']}"] = str(row["discount_bps"] / 100).replace(".", ",")
        send(seller, f"/quotes/{qid}", page=f"/quotes/{qid}", **fields)
        return qid

    print("Pipeline, quotes and approvals")
    # EN: quote #0001: a draft above Diego's 5% ceiling, left for the demo video (he asks for approval live)
    # PT: orçamento #0001: rascunho acima do teto de 5% do Diego, deixado para o vídeo (ele pede a aprovação ao vivo)
    o1 = opportunity(diego, "Restaurante do Zé", "Pedido semanal de mercearia", "Orçamento enviado", "1.850,00", date_sp_in_days(9))
    quote(diego, o1, [("ARZ-5", 10, "0"), ("FEI-1", 5, "0"), ("OLE-900", 8, "2"), ("CAF-500", 2, "0")], header="9",
          notes="Entrega na terça pela manhã.")

    # EN: two quotes sent to Zé, waiting for his answer in the portal (one is urgent)
    # PT: dois orçamentos enviados ao Zé, esperando a resposta dele no portal (um é urgente)
    for title, items, header, days in (("Kit café da manhã", [("CAF-500", 3, "0"), ("ACU-1", 4, "0")], "0", 1),
                                       ("Reabastecimento quinzenal", [("ARZ-5", 6, "0"), ("OLE-900", 4, "0"), ("FEI-1", 3, "0")], "3", 7)):
        opp = opportunity(diego, "Restaurante do Zé", title, "Orçamento enviado")
        qid = quote(diego, opp, items, header=header, valid_days=days)
        send(diego, f"/quotes/{qid}/submit", page=f"/quotes/{qid}")
        send(diego, f"/quotes/{qid}/send", page=f"/quotes/{qid}")

    # EN: Fernanda: a deal in progress and three lost ones with reasons | PT: Fernanda: um negócio andando e três perdidos com motivo
    # EN: Fernanda's quote at 8% waits for the manager, so the approval queue is never empty
    # PT: o orçamento da Fernanda a 8% espera a gerente, para a fila de aprovação nunca ficar vazia
    o_fer = opportunity(fernanda, "Mercadinho Bom Preço", "Reposição de bebidas", "Contatado", "960,00", date_sp_in_days(14))
    q_fer = quote(fernanda, o_fer, [("OLE-900", 12, "0"), ("ACU-1", 10, "0")], header="8")
    send(fernanda, f"/quotes/{q_fer}/submit", page=f"/quotes/{q_fer}", reason="Pedido grande para o fim do mês; o concorrente cobrou menos.")
    for title, customer, value, reason in (("Cotação de mercearia", "Mercadinho Bom Preço", "1.200,00", "Preço do concorrente"),
                                           ("Linha de limpeza", "Lanchonete Esquina", "640,00", "Preço do concorrente"),
                                           ("Pedido de bebidas", "Padaria Pão Quente", "980,00", "Prazo de entrega")):
        opp = opportunity(fernanda, customer, title, "Novo", value)
        send(fernanda, f"/opportunities/{opp}/stage", page=f"/opportunities/{opp}", stage_id=str(stage["Perdido"]), lost_reason=reason)

    # EN: a sale closed by phone, marked as won by hand | PT: uma venda fechada por telefone, marcada como ganha à mão
    opportunity(manager, "Hotel Serra Azul", "Contrato mensal de café", "Fechado", "2.280,00")
    opportunity(owner, "Hotel Serra Azul", "Kit frigobar dos quartos", "Novo", "3.400,00", date_sp_in_days(20))

    print("Order history (dated in the past)")
    # EN: accepted orders in the past: Padaria and Hotel are late to reorder, Lanchonete is on rhythm
    # PT: pedidos aceitos no passado: Padaria e Hotel estão atrasados para recomprar, Lanchonete está no ritmo
    history = [("Padaria Pão Quente", diego, (61, 47, 33), [("ARZ-5", 4, "0"), ("ACU-1", 6, "0")]),
               ("Hotel Serra Azul", owner, (85, 65, 45), [("CAF-500", 6, "0"), ("ACU-1", 4, "0")]),
               ("Lanchonete Esquina", diego, (25, 18, 11, 4), [("REF-2L", 5, "0"), ("OLE-900", 2, "0")])]
    for customer, seller, days_list, items in history:
        for days in days_list:
            stamp = utc_days_ago(days)
            title = f"Pedido {customer} ({days} dias atrás)"
            opp = opportunity(seller, customer, title, "Orçamento enviado")
            qid = quote(seller, opp, items)
            send(seller, f"/quotes/{qid}/submit", page=f"/quotes/{qid}", reason="Pedido recorrente com preço de tabela.")
            if one("SELECT status FROM quotes WHERE id = ?", qid)["status"] == "pending_approval":
                rid = one("SELECT id FROM discount_requests WHERE quote_id = ?", qid)["id"]
                send(manager if seller is not manager else owner, f"/approvals/{rid}/approve", page="/approvals", note="Ok, cliente antigo.")
            send(seller, f"/quotes/{qid}/send", page=f"/quotes/{qid}")
            total = one("SELECT final_total_cents FROM quotes WHERE id = ?", qid)["final_total_cents"]
            db.execute("UPDATE quotes SET status = 'accepted', created_at = ?, sent_at = ?, customer_decided_at = ? WHERE id = ?",
                       stamp, stamp, stamp, qid)
            db.execute("UPDATE opportunities SET stage_id = ?, value_cents = ?, closed_at = ?, closed_manually = 0, created_at = ? WHERE id = ?",
                       stage["Fechado"], total, stamp, stamp, opp)

    print("Buyer portal (two distributors)")
    send(owner, f"/customers/{company['Restaurante do Zé']}/buyers/invite", page=f"/customers/{company['Restaurante do Zé']}", email="comprador@demo.com")
    link = re.search(r'/invite/([^"]+)"', owner.get(f"/customers/{company['Restaurante do Zé']}").text).group(1)
    buyer = sign_up("comprador@demo.com", "José Almeida", invite=link)

    litoral = sign_up("litoral@demo.com", "Marina Costa", workspace="Distribuidora Litoral")
    send(litoral, "/onboarding", page="/onboarding", files=True, name="Distribuidora Litoral",
         cnpj="12.345.678/0001-95", email="vendas@litoral.example", phone="(13) 3322-1100", city="Santos")
    send(litoral, "/onboarding/limits", page="/onboarding/limits", action="skip")
    send(litoral, "/customers/new", page="/customers/new", name="Restaurante do Zé (Praia)", phone="(13) 99876-5432", city="Guarujá")
    praia = one("SELECT id FROM companies WHERE name = 'Restaurante do Zé (Praia)'")["id"]
    send(litoral, f"/customers/{praia}/buyers/invite", page=f"/customers/{praia}", email="comprador@demo.com")
    praia_link = re.search(r'/invite/([^"]+)"', litoral.get(f"/customers/{praia}").text).group(1)
    send(buyer, f"/invite/{praia_link}/accept", page=f"/invite/{praia_link}")
    litoral_stage = one("SELECT id FROM stages WHERE workspace_id <> ? ORDER BY position LIMIT 1", ws)["id"]
    send(litoral, "/opportunities/new", page="/opportunities/new", title="Peixes e frutos do mar", company_id=str(praia),
         stage_id=str(litoral_stage), owner_id=str(one("SELECT id FROM users WHERE email = 'litoral@demo.com'")["id"]))
    send(litoral, "/products/new", page="/products/new", sku="CAM-1", name="Camarão limpo, 1 kg", unit="kg", price="89,90", cost_mode="brl", cost="62,00")
    praia_opp = one("SELECT id FROM opportunities WHERE title = 'Peixes e frutos do mar'")["id"]
    send(litoral, f"/opportunities/{praia_opp}/quotes", page=f"/opportunities/{praia_opp}")
    praia_quote = one("SELECT id FROM quotes WHERE opportunity_id = ?", praia_opp)["id"]
    send(litoral, f"/quotes/{praia_quote}/items", page=f"/quotes/{praia_quote}", product_id=str(one("SELECT id FROM products WHERE sku = 'CAM-1'")["id"]), quantity="12", discount="0")
    send(litoral, f"/quotes/{praia_quote}/submit", page=f"/quotes/{praia_quote}")
    send(litoral, f"/quotes/{praia_quote}/send", page=f"/quotes/{praia_quote}")

    print("Tasks and history notes")
    ze_id = company["Restaurante do Zé"]
    for client, data in ((diego, dict(title="Confirmar entrega do pedido semanal", opportunity_id=str(o1), due_date=date_sp_in_days(-1))),
                         (diego, dict(title="Ligar para oferecer o azeite novo", company_id=str(company["Lanchonete Esquina"]), due_date=date_sp_in_days(0))),
                         (diego, dict(title="Levar amostra de café", company_id=str(company["Padaria Pão Quente"]), due_date=date_sp_in_days(3))),
                         (diego, dict(title="Atualizar o CNPJ da padaria", company_id=str(company["Padaria Pão Quente"]))),
                         (fernanda, dict(title="Retornar sobre a reposição de bebidas", company_id=str(company["Mercadinho Bom Preço"]), due_date=date_sp_in_days(-2))),
                         (owner, dict(title="Revisar a tabela de preços com a gerente", company_id=str(company["Hotel Serra Azul"]),
                                      assignee_id=str(uid["gerente@demo.com"]), due_date=date_sp_in_days(2)))):
        send(client, "/tasks", page="/tasks", **data)
    send(diego, "/activities", page=f"/customers/{ze_id}", type="call", body="Falei com o José: quer fechar até sexta se o frete sair grátis.",
         company_id=str(ze_id), opportunity_id=str(o1))
    send(diego, "/activities", page=f"/customers/{ze_id}", type="whatsapp", body="Mandei fotos dos produtos novos; ele vai mostrar ao chef.", company_id=str(ze_id))
    send(owner, "/activities", page=f"/customers/{ze_id}", type="note", body="Cliente paga sempre em dia. Pode ganhar prazo de 28 dias.", company_id=str(ze_id))

    print("\nDone. Accounts (password demo1234):")
    for email, who in (("dono@demo.com", "owner"), ("gerente@demo.com", "manager"), ("vendedor@demo.com", "seller"),
                       ("vendedora@demo.com", "seller"), ("comprador@demo.com", "buyer, two distributors"),
                       ("litoral@demo.com", "owner of a second distributor"), ("plataforma@demo.com", "platform operator")):
        print(f"  {email:24} {who}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as stop:
        if stop.code not in (None, 0):
            print(stop.code, file=sys.stderr)
            sys.exit(1)
