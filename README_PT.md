# SupplyFlow

**Um CRM para distribuidoras de alimentos em que nenhum desconto sai sem a aprovação certa.**

O SupplyFlow é um CRM web, para várias empresas ao mesmo tempo, feito para distribuidoras que vendem arroz, café, óleo e outros produtos para restaurantes, padarias, mercados e hotéis. Cada cargo tem um limite de desconto: um orçamento acima do limite do vendedor fica bloqueado até um gerente aprovar *aquele desconto exato*. Depois, o cliente abre o orçamento no celular e aceita com um toque, e o dono acompanha vendas, comissões e clientes que pararam de comprar num painel.

> 🎓 Este foi o meu **projeto final do [CS50x 2026](https://cs50.harvard.edu/x/)**, o curso de Introdução à Ciência da Computação de Harvard.
> 🎥 **Vídeo de demonstração (1:51):** https://youtu.be/nsJty3MG6G8

(Read in English: [README.md](README.md).)

![Página inicial do SupplyFlow](docs/screenshots/01-pagina-inicial.png)

## O problema

No Brasil, a maior parte das vendas entre distribuidoras e clientes acontece pelo WhatsApp. O cliente pede um desconto maior, o vendedor aceita na hora, e o dono só descobre dias depois, quando a margem já foi embora. Os preços ficam em planilhas com nomes como `precos_v3_FINAL.xlsx`, ninguém percebe quando um bom cliente para de comprar aos poucos, e o comprador recebe orçamentos em PDFs e mensagens soltas.

## Como o SupplyFlow resolve

| | |
|---|---|
| **Limite de desconto por cargo** | O dono define até onde cada cargo pode ir (por exemplo, vendedor até 5% e gerente até 15%). Acima do limite, o orçamento **fica bloqueado** e o vendedor pede aprovação com um motivo. |
| **Aprovação presa a um valor** | O gerente vê os itens, a margem, o motivo e o histórico do cliente num cartão só, e aprova **aquele desconto exato**. Se o vendedor mudar o desconto depois, a aprovação cai. Uma margem mínima também pede aprovação, mesmo dentro do limite. |
| **Portal do comprador** | O cliente tem a própria conta, abre o orçamento no celular, confere cada item e **aceita ou recusa com um toque**. Ao aceitar, o negócio vira "ganho" sozinho. |
| **Painel do dono** | Funil em aberto, vendas do período, ticket médio, conversão, desconto médio, **ranking de vendedores com comissão**, clientes que mais compraram, motivos de perda e tarefas atrasadas. |
| **Alertas de recompra** | Um cliente com 3 ou mais pedidos que passa de 1,5 vez o intervalo normal de compra aparece como "atrasado para recomprar", para alguém ligar antes de perder o cliente. |

## Telas

| Orçamento acima do limite do vendedor | Aprovação do gerente |
|---|---|
| ![Orçamento acima do teto](docs/screenshots/05-orcamento-acima-do-teto.png) | ![Aprovação do gerente](docs/screenshots/06-aprovacao-do-gerente.png) |
| **Painel do dono** | **Funil de vendas** |
| ![Painel do dono](docs/screenshots/03-painel-do-dono.png) | ![Funil de vendas](docs/screenshots/04-funil-de-vendas.png) |
| **Orçamento em A4 / PDF** | **Portal do comprador no celular** |
| ![Orçamento em PDF](docs/screenshots/07-orcamento-em-pdf.png) | ![Portal do comprador](docs/screenshots/08-portal-do-comprador-celular.png) |

## Funcionalidades

- **Empresas e equipes.** A distribuidora se cadastra, preenche os dados da empresa (nome, CNPJ, contato, logo) e define os limites de desconto numa régua ao vivo. O dono convida gerentes e vendedores por link (uso único, vence em 7 dias). Várias distribuidoras usam o mesmo sistema sem nunca ver os dados umas das outras.
- **Clientes, produtos e funil.** Clientes e contatos com validação de CNPJ e busca; catálogo de produtos com custo em R$ ou em %, mostrando a margem; funil com etapas configuráveis, arrastar e soltar, tarefas e um histórico só de inserção (notas, ligações, WhatsApp, mudanças de etapa).
- **Orçamentos.** Desconto por item e geral, totais recalculados pelo servidor, numeração por distribuidora, uma máquina de estados (rascunho → aguardando aprovação / pronto → enviado → aceito, recusado, vencido ou cancelado), fila de aprovação, documento A4 para o cliente e rascunho guardado no navegador caso a internet caia.
- **Cargos.** Dono, gerente e vendedor. O vendedor vê só os próprios negócios e orçamentos; o gerente e o dono veem tudo. A lista de clientes é compartilhada, para dois vendedores não cadastrarem o mesmo restaurante.
- **Planos.** Quatro planos com cotas (usuários, clientes, produtos, orçamentos por mês), guardados como dados. Um painel separado do operador da plataforma troca o plano sem nunca mostrar dados de negócio.
- **E mais:** exportação em CSV (com proteção contra fórmulas de planilha), recuperação de senha por e-mail, interface em português e inglês, temas escuro e claro, páginas de termos e privacidade.

## Tecnologias

- **Servidor:** Python 3, Flask (blueprints), SQLite pela [biblioteca SQL do CS50](https://cs50.readthedocs.io/libraries/cs50/python/)
- **Interface:** templates Jinja, HTML, CSS e JavaScript puros (sem framework de front-end)
- **Testes:** `unittest`, que já vem com o Python

## Como rodar

Precisa do Python 3.10 ou mais novo.

```bash
git clone https://github.com/paulocolugnati/supplyflow.git
cd supplyflow
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m flask --app app init-db   # cria o project.db a partir do schema.sql
python seed.py                      # opcional: dados de demonstração fictícios
python -m flask --app app run
```

Abra http://127.0.0.1:5000.

**Contas de demonstração** (senha `demo1234`, criadas pelo `seed.py`):

| E-mail | Cargo |
|---|---|
| `dono@demo.com` | Dono |
| `gerente@demo.com` | Gerente |
| `vendedor@demo.com` | Vendedor |
| `comprador@demo.com` | Comprador (cliente de duas distribuidoras) |
| `plataforma@demo.com` | Operador da plataforma |

**Variáveis de ambiente opcionais:**
- `SUPPORT_WHATSAPP`: o número de suporte que aparece na página de planos.
- `MAIL_USERNAME` e `MAIL_PASSWORD`: uma senha de app do Gmail, para os e-mails de redefinição de senha. Sem elas, os links aparecem no terminal.

**Rodar os testes:**

```bash
python -m unittest discover tests
```

São 66 testes: 47 testes unitários das regras de negócio, 18 cenários que usam o sistema inteiro pelas rotas reais num banco temporário (642 conferências) e uma verificação de 47 regras do banco.

## Estrutura

```
app.py               criação do app, CSRF, cabeçalhos de segurança, login, páginas de erro, comandos
database.py          conexão com o SQLite (biblioteca SQL do CS50)
schema.sql           18 tabelas, restrições e o catálogo de planos
permissions.py       cargos, cotas dos planos e o filtro de cada consulta por empresa
helpers.py           formatação de dinheiro e datas, validação de CNPJ/telefone/e-mail, tokens
translations.py      todos os textos em português e inglês

customers.py  products.py  pipeline.py  quotes.py  portal.py  tasks.py  team.py
dashboard.py  plans.py  settings.py  password_reset.py  mailer.py  exports.py
documents.py  admin_panel.py      -> um blueprint do Flask por área

pricing.py  approval.py  repurchase.py  reports.py
                     -> regras de negócio puras (sem banco), testadas com contas feitas à mão

templates/           um template Jinja por tela + layout, telas de acesso, página inicial, partes reutilizáveis
static/              CSS/JS compartilhados, estilos do sistema e da página inicial, estilo do A4, fontes, marca
tests/               testes unitários + cenários de ponta a ponta
scripts/             verificador das regras do banco
docs/ARCHITECTURE.md tabelas, regras, permissões e planos em detalhe
seed.py              monta a demonstração pelas rotas reais
```

## Decisões de projeto

- **Um banco, várias empresas.** Toda tabela tem um `workspace_id` e toda consulta filtra por ele. Chaves estrangeiras compostas fazem o próprio banco recusar, por exemplo, um orçamento apontando para o cliente de outra empresa. Um registro de outra empresa responde 404, igual a um que não existe.
- **Dinheiro como inteiro.** Preços são guardados em centavos e porcentagens em pontos-base (500 = 5%), porque números com vírgula flutuante erram dinheiro (`0.1 + 0.2 != 0.3`). Os totais são sempre recalculados no servidor, nunca aceitos do navegador.
- **A aprovação fica presa a um valor, não ao orçamento.** Isso fecha o truque de pedir um desconto pequeno e aumentar depois da aprovação.
- **Regras de negócio em módulos puros.** Preços, aprovação, recompra e relatórios nunca tocam no banco, então dá para testá-los com números calculados à mão.
- **Planos são dados.** Os limites ficam na tabela `plans`, então mudar um limite é um `UPDATE`, não código novo.
- **Validar tudo no servidor.** As conferências do HTML são só conforto. Tokens de convite e de redefinição de senha são guardados só como hash SHA-256, todo formulário leva um token CSRF, os uploads são conferidos pelo conteúdo real, e uma Content Security Policy só deixa rodar scripts do próprio site.
- **Sem framework de front-end.** HTML, CSS e JavaScript puros deixam o sistema rápido no celular do vendedor. Toda ação é um formulário comum, então o JavaScript só dá conforto (totais ao vivo, arrastar e soltar, rascunho salvo) e o servidor sempre tem a última palavra.
- **Horário do Brasil.** As datas são guardadas em UTC e mostradas no horário de São Paulo; "hoje", "atrasada" e "este mês" seguem o calendário brasileiro.

## Sobre o projeto

Construí o SupplyFlow como projeto final do **CS50x 2026** (Introdução à Ciência da Computação da Universidade Harvard), em que o projeto final é um software livre, de criação própria. Escolhi um problema real que vi em pequenas distribuidoras brasileiras e fiz tudo de ponta a ponta: modelagem do banco, permissões, regras de negócio, interface e testes.

**Autor:** Paulo Henrique de Andrade Colugnati, São Paulo, Brasil, [GitHub](https://github.com/paulocolugnati).

## Créditos

- Animações de rolagem da página inicial: o motor "Sites Incríveis" (`static/fx/`), © 2026 Enzo Barbatto, Sparo Automações, usado com autorização do autor. Não fui eu que escrevi, e ele não está coberto pelos termos deste repositório.
- A fonte Archivo é usada sob a SIL Open Font License.
- Todas as pessoas, empresas e números da demonstração são fictícios.

## Licença

© 2026 Paulo Henrique de Andrade Colugnati. Todos os direitos reservados. O código é público para ser lido e avaliado; fale comigo antes de reutilizá-lo.
