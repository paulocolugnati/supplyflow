# SupplyFlow — Arquitetura (v1)

> Documento vivo. Descreve **o que** o sistema faz e **por quê**, antes de qualquer tela.
> Nome "SupplyFlow" é provisório.

---

## Sumário

1. [Visão geral](#1-visão-geral)
2. [Glossário](#2-glossário)
3. [Tipos de conta e papéis](#3-tipos-de-conta-e-papéis)
4. [Mapa de relações](#4-mapa-de-relações)
5. [Tabelas](#5-tabelas)
6. [Regras de negócio](#6-regras-de-negócio)
7. [Planos e cotas](#7-planos-e-cotas)
8. [Matriz de permissões](#8-matriz-de-permissões)
9. [Segurança](#9-segurança)
10. [Decisões de design](#10-decisões-de-design)
11. [Escopo: v1 e v2](#11-escopo-v1-e-v2)
12. [Pendências](#12-pendências)

---

## 1. Visão geral

**Problema.** Distribuidoras pequenas (alimentos, bebidas, limpeza) vendem para lojas e
restaurantes por WhatsApp. Orçamentos se perdem, vendedores dão desconto demais sem
ninguém saber e clientes param de comprar sem que alguém perceba.

**Solução.** Um CRM B2B multi-tenant onde:

- a **distribuidora** organiza clientes, produtos, oportunidades e orçamentos;
- **descontos acima do limite do cargo** precisam de aprovação de alguém acima;
- o **cliente comprador** recebe o orçamento por link, entra no portal e aceita ou recusa;
- o sistema **avisa quando um cliente está atrasado para recomprar**;
- cada distribuidora usa um **plano** com limites (Grátis, Essencial, Profissional, Escala).

**Fluxo principal (o que aparece no vídeo):**

```
Vendedor cria orçamento com 15% de desconto
  -> passou do teto dele (5%) -> "Aguardando aprovação"
Gerente vê a fila -> aprova
Vendedor envia -> link vai pelo WhatsApp
Cliente entra no portal -> aceita
  -> oportunidade vai para "Fechado" -> dashboard atualiza
```

---

## 2. Glossário

| Termo | Significado |
|---|---|
| **Workspace** | Uma distribuidora dentro do sistema (o "tenant"). |
| **Equipe** | Usuários que trabalham na distribuidora (owner, admin, member). |
| **Cliente / Company** | Empresa que compra da distribuidora (restaurante, mercado). |
| **Contato** | Pessoa dentro de um cliente (o comprador, o dono do restaurante). |
| **Comprador** | Conta de usuário de um cliente, que acessa o **portal**. |
| **Oportunidade** | Uma negociação em andamento com um cliente. |
| **Orçamento / Quote** | Lista de produtos com preços e descontos, ligada a uma oportunidade. |
| **bps** | *Basis points*. 1 bps = 0,01%. 1000 bps = 10%. Usado para descontos e margens. |
| **Cents** | Dinheiro guardado em centavos inteiros. R$ 12,34 = `1234`. |

---

## 3. Tipos de conta e papéis

Existe **uma única tabela `users`**. O que a pessoa pode fazer depende dos **vínculos**:

```
                 users (uma conta por e-mail)
                /            |               \
   memberships          customer_users       is_platform_admin = 1
  (equipe de uma      (comprador de um       (você, dono da plataforma)
   distribuidora)      cliente de uma
                       distribuidora)
```

Uma mesma pessoa pode ter vários vínculos. O dono de um restaurante pode ser comprador de três
distribuidoras com o mesmo login.

### Papéis da equipe (por workspace)

| Papel | Quem é | Resumo |
|---|---|---|
| **owner** | Dono da distribuidora | Tudo. Configura limites, plano e equipe. **1 por workspace; 2 no plano Escala (sócios).** |
| **admin** | Gerente | Gerencia equipe (exceto owner), aprova descontos até o teto dele. |
| **member** | Vendedor | Trabalha clientes, oportunidades e orçamentos. Apaga só o que é dele. |

### Comprador

Só acessa o **portal**. Vê orçamentos **enviados** para os clientes aos quais está vinculado.
Nunca vê o CRM, custos, margens ou notas internas.

Pode criar conta de **dois jeitos**:

- **Direto**, pela página de cadastro ("Sou comprador"). A conta nasce sem vínculos; o portal
  mostra "Peça para sua distribuidora te convidar usando este e-mail".
- **Por convite** de uma distribuidora. A conta nasce já vinculada ao cliente e guarda
  **qual distribuidora trouxe o comprador** (`users.referred_by_workspace_id`). A distribuidora
  vê isso na lista de clientes ("Trazido por você"). Na v2 isso pode virar benefício por indicação.

Nos dois casos, o vínculo com um cliente só nasce de um **convite** da distribuidora. Um
comprador não consegue se vincular sozinho a um cliente (senão qualquer pessoa veria os
orçamentos de um restaurante só digitando o nome dele).

### Administrador da plataforma

Você. Vê a lista de workspaces, o uso e o plano de cada um, e pode trocar plano e preço
negociado. **Não** abre os dados de negócio das distribuidoras. A flag só é ligada pelo terminal
(`flask make-admin <email>`), nunca por uma tela.

---

## 4. Mapa de relações

```
plans 1──* workspaces
                │
  users *──memberships──* workspaces          (equipe)
                │
                ├──* invites                   (convites de equipe e de compradores)
                ├──* products
                ├──* pipelines 1──* stages
                ├──* companies 1──* contacts
                │        │
                │        └──* customer_users *── users   (compradores)
                │
                ├──* opportunities  (company, stage, contact?, owner)
                │        │
                │        └──* quotes 1──* quote_items *── products
                │               │
                │               └──* discount_requests
                │
                ├──* tasks        (ligada a company / contact / opportunity)
                └──* activities   (histórico; ligada a company / contact / opportunity / quote)
```

Legenda: `1──*` = um para muitos. `*──x──*` = muitos para muitos através da tabela `x`.

---

## 5. Tabelas

Convenções em todas as tabelas:

- `id INTEGER PRIMARY KEY`
- datas em **UTC**, texto ISO (`2026-09-30 14:00:00`); `created_at` com `DEFAULT CURRENT_TIMESTAMP`
- dinheiro em **centavos** (`*_cents INTEGER`), porcentagem em **bps** (`*_bps INTEGER`)
- toda tabela de negócio tem `workspace_id`

### 5.1 `plans` — catálogo de planos

| Coluna | Tipo | Notas |
|---|---|---|
| code | TEXT UNIQUE | `free`, `essencial`, `profissional`, `escala` |
| name | TEXT | Nome exibido |
| price_cents | INTEGER | Preço de tabela mensal |
| max_users | INTEGER NULL | Equipe total. `NULL` = ilimitado |
| max_owners | INTEGER | 1, ou 2 no Escala |
| max_admins | INTEGER NULL | |
| max_members | INTEGER NULL | |
| max_customers | INTEGER NULL | Clientes (companies) |
| max_products | INTEGER NULL | |
| max_quotes_month | INTEGER NULL | Orçamentos criados no mês |
| feat_discount_approval | INTEGER 0/1 | |
| feat_min_margin | INTEGER 0/1 | |
| feat_repurchase_alert | INTEGER 0/1 | |
| feat_csv_export | INTEGER 0/1 | |
| feat_multi_pipeline | INTEGER 0/1 | |
| feat_portal_full | INTEGER 0/1 | Portal completo ou básico (ver §7) |
| support_level | TEXT | `basico`, `padrao`, `prioritario`, `dedicado` |

Os planos são **dados**, não código: mudar um limite é um `UPDATE`, não um deploy.

### 5.2 `users`

| Coluna | Tipo | Notas |
|---|---|---|
| email | TEXT NOT NULL | Guardado em minúsculas. `UNIQUE` |
| name | TEXT NOT NULL | |
| hash | TEXT NOT NULL | `generate_password_hash` |
| phone | TEXT NULL | Só dígitos, normalizado |
| lang | TEXT | `pt` ou `en`. Padrão `pt` |
| is_platform_admin | INTEGER 0/1 | Padrão 0 |
| signup_source | TEXT | `direct` ou `invite` |
| referred_by_workspace_id | FK workspaces NULL | Distribuidora que convidou na criação da conta. Nunca muda depois |

### 5.3 `workspaces` — a distribuidora

| Coluna | Tipo | Notas |
|---|---|---|
| name | TEXT NOT NULL | |
| plan_id | INTEGER FK plans | Começa no Grátis |
| plan_started_at | TEXT | |
| custom_price_cents | INTEGER NULL | Preço negociado com o suporte |
| member_discount_limit_bps | INTEGER | Teto do vendedor. Padrão 500 (5%) |
| admin_discount_limit_bps | INTEGER | Teto do gerente. Padrão 1500 (15%) |
| min_margin_bps | INTEGER | Margem mínima. Padrão 1500 (15%) |
| next_quote_number | INTEGER | Próximo número de orçamento (#0001...). Padrão 1 |
| onboarding_done | INTEGER 0/1 | Owner já configurou os limites? |

`CHECK(0 <= member_discount_limit_bps AND member_discount_limit_bps <= admin_discount_limit_bps AND admin_discount_limit_bps <= 10000)`

### 5.4 `memberships` — equipe

| Coluna | Tipo | Notas |
|---|---|---|
| workspace_id | FK | |
| user_id | FK | |
| role | TEXT | `CHECK IN ('owner','admin','member')` |

- `UNIQUE(workspace_id, user_id)`
- Número de owners: **no mínimo 1** e **no máximo `plans.max_owners`**. Conferido no servidor
  (o limite depende do plano, então não dá para ser só um índice do banco).
- Com 2 owners: **um owner não remove nem rebaixa o outro**. Cada um só pode sair por conta
  própria, e só se não for o último. Protege um sócio do outro.

### 5.5 `invites` — convites de equipe e de compradores

| Coluna | Tipo | Notas |
|---|---|---|
| workspace_id | FK | |
| kind | TEXT | `staff` ou `customer` |
| email | TEXT | Para quem é o convite |
| role | TEXT NULL | Só para `staff` (`admin` / `member`) |
| company_id | FK NULL | Só para `customer` |
| token_hash | TEXT | **Hash** do token. O token puro só existe no link |
| created_by | FK users | |
| expires_at | TEXT | 7 dias |
| accepted_at | TEXT NULL | |

### 5.6 `companies` — clientes da distribuidora

| Coluna | Tipo | Notas |
|---|---|---|
| workspace_id | FK | |
| name | TEXT NOT NULL | |
| cnpj | TEXT NULL | Só dígitos |
| segment | TEXT NULL | Restaurante, mercado... (texto livre com sugestões) |
| phone | TEXT NULL | |
| city | TEXT NULL | |
| owner_id | FK users | Vendedor responsável |

`UNIQUE(id, workspace_id)` para permitir FKs compostas (ver §10).

### 5.7 `contacts`

`workspace_id, company_id, name, phone, email, position`

### 5.8 `customer_users` — vínculo comprador ↔ cliente

| Coluna | Tipo | Notas |
|---|---|---|
| workspace_id | FK | |
| company_id | FK | |
| user_id | FK | A conta do comprador |

`UNIQUE(company_id, user_id)`. Um comprador pode ter vínculos com clientes de **várias** distribuidoras.

### 5.9 `pipelines` e `stages`

**pipelines:** `workspace_id, name, position, is_default`

**stages:** `workspace_id, pipeline_id, name, position, kind`
- `kind CHECK IN ('open','won','lost')`
- Pipeline padrão criado no cadastro: **Novo**, **Contatado**, **Orçamento enviado** (`open`), **Fechado** (`won`), **Perdido** (`lost`).

### 5.10 `opportunities`

| Coluna | Tipo | Notas |
|---|---|---|
| workspace_id | FK | |
| pipeline_id, stage_id | FK | A etapa precisa ser do mesmo pipeline |
| company_id | FK NOT NULL | B2B: sempre tem cliente |
| contact_id | FK NULL | |
| owner_id | FK users | Vendedor responsável |
| title | TEXT NOT NULL | |
| value_cents | INTEGER ≥ 0 | Atualizado quando um orçamento é aceito |
| expected_close | TEXT NULL | |
| closed_at | TEXT NULL | Preenchido ao entrar em `won`/`lost` |
| lost_reason | TEXT NULL | |
| updated_at | TEXT | |

### 5.11 `products`

| Coluna | Tipo | Notas |
|---|---|---|
| workspace_id | FK | |
| sku | TEXT NOT NULL | `UNIQUE(workspace_id, sku)` |
| name | TEXT NOT NULL | |
| unit | TEXT | `un`, `cx`, `fd`, `kg`... |
| price_cents | INTEGER > 0 | Preço de tabela |
| cost_cents | INTEGER NULL | Opcional. Se digitado em %, o servidor converte para centavos |
| active | INTEGER 0/1 | Produto inativo não entra em orçamento novo |

### 5.12 `quotes` — orçamentos

| Coluna | Tipo | Notas |
|---|---|---|
| workspace_id | FK | |
| number | INTEGER | Sequencial por workspace (#0001, #0002...) |
| opportunity_id | FK | |
| company_id | FK | Repetido da oportunidade, para o portal filtrar rápido |
| created_by | FK users | |
| status | TEXT | Ver §6.4 |
| header_discount_bps | INTEGER | Desconto geral. Padrão 0 |
| valid_until | TEXT | Data de validade |
| list_total_cents | INTEGER | Total a preço de tabela (calculado) |
| final_total_cents | INTEGER | Total final (calculado) |
| effective_discount_bps | INTEGER | `1 - final/lista` (calculado) |
| margin_bps | INTEGER NULL | Calculada só com itens que têm custo |
| approved_by | FK NULL | |
| approved_at | TEXT NULL | |
| approved_discount_bps | INTEGER NULL | **O desconto exato que foi aprovado** |
| sent_at | TEXT NULL | |
| customer_user_id | FK NULL | Quem aceitou/recusou no portal |
| customer_decided_at | TEXT NULL | |
| decline_reason | TEXT NULL | |
| notes_internal | TEXT NULL | Nunca aparece no portal |
| notes_customer | TEXT NULL | Aparece no portal |
| updated_at | TEXT | |

`UNIQUE(workspace_id, number)`

### 5.13 `quote_items`

| Coluna | Tipo | Notas |
|---|---|---|
| workspace_id | FK | Necessário para as FKs compostas com `quotes` e `products` |
| quote_id | FK | |
| product_id | FK | |
| product_name | TEXT | **Cópia** do nome no momento do orçamento |
| unit | TEXT | Cópia |
| quantity | INTEGER > 0 | |
| list_price_cents | INTEGER | **Cópia** do preço de tabela no momento |
| cost_cents | INTEGER NULL | **Cópia** do custo no momento |
| discount_bps | INTEGER | Desconto do item. `0..10000` |
| line_total_cents | INTEGER | Calculado |

### 5.14 `discount_requests` — trilha da aprovação

| Coluna | Tipo | Notas |
|---|---|---|
| workspace_id, quote_id | FK | |
| requested_by | FK users | |
| requested_discount_bps | INTEGER | |
| requested_margin_bps | INTEGER NULL | |
| required_role | TEXT | `admin` ou `owner` |
| reason | TEXT | Justificativa do vendedor |
| status | TEXT | `pending`, `approved`, `rejected`, `cancelled` |
| decided_by | FK NULL | Nunca igual a `requested_by` |
| decided_at | TEXT NULL | |
| decision_note | TEXT NULL | |

### 5.15 `tasks`

`workspace_id, assignee_id, created_by, title, due_date, done_at, company_id?, contact_id?, opportunity_id?`

`CHECK` que pelo menos um dos três vínculos não é nulo.

### 5.16 `activities` — histórico (só inserção)

| Coluna | Tipo | Notas |
|---|---|---|
| workspace_id | FK | |
| user_id | FK | Quem fez (equipe ou comprador) |
| type | TEXT | Lista abaixo |
| body | TEXT | Texto livre ou descrição gerada |
| company_id, contact_id, opportunity_id, quote_id | FK NULL | Pelo menos um preenchido |

Tipos: `note`, `call`, `whatsapp`, `stage_change`, `task_done`, `quote_sent`,
`quote_accepted`, `quote_declined`, `discount_requested`, `discount_approved`, `discount_rejected`.

---

## 6. Regras de negócio

### 6.1 Isolamento entre distribuidoras (a regra nº 1)

1. O workspace ativo vem da **sessão**, nunca de formulário ou URL.
2. Toda consulta de negócio tem `AND workspace_id = ?`.
3. Todo id recebido de formulário (`company_id`, `product_id`, `stage_id`, `owner_id`...) é
   **conferido como pertencente ao mesmo workspace** antes de salvar.
4. Registro de outro workspace responde **404**, não 403. Assim não se confirma que ele existe.

### 6.2 Cadastro e onboarding

- **Distribuidora:** cria `user` + `workspace` (plano Grátis) + `membership` owner +
  pipeline padrão com etapas. Depois cai no **onboarding**: tetos de desconto e margem mínima
  (pode pular e usar os padrões). Botão "Falar com o suporte" visível.
- **Comprador direto:** cadastro em "Sou comprador". `signup_source = 'direct'`, sem vínculos.
- **Comprador por convite:** cria a conta pelo link. `signup_source = 'invite'`,
  `referred_by_workspace_id` = distribuidora do convite, e o vínculo com o cliente já é criado.
  Se a pessoa **já tem conta**, só faz login e o vínculo é criado; `referred_by` não muda
  (quem trouxe para a plataforma foi outra pessoa, ou ela veio sozinha).
- **Membro da equipe:** também por convite. A cota do plano é conferida **ao convidar e ao aceitar**.

### 6.3 Cálculo do orçamento

Ordem fixa, tudo em inteiros:

```
1. linha       = list_price_cents × quantity × (10000 − discount_bps) / 10000
2. subtotal    = soma das linhas
3. final       = subtotal × (10000 − header_discount_bps) / 10000
4. lista       = soma de (list_price_cents × quantity)
5. desconto efetivo = (lista − final) × 10000 / lista            -> bps
6. margem      = (final_com_custo − custo_total) × 10000 / final_com_custo
                 (somente sobre itens com custo; sem custo nenhum -> margem NULL)
```

Arredondamento: **meio para cima**, com aritmética inteira (`(x + 5000) // 10000`).
Não se usa `float` nem `round()` do Python, que arredonda "para o par".

### 6.4 Estados do orçamento

```
               editar                  enviar         cliente
   ┌──────── draft ─────► ready ───────► sent ───┬──► accepted
   │           │  ▲         ▲                    ├──► declined
   │  precisa  │  │rejeitado│aprovado            └──► expired (validade passou)
   │ aprovação ▼  │         │
   │      pending_approval ─┘
   │
   └─► cancelled  (de qualquer estado não final)
```

- Só se **edita** em `draft`. Editar um `ready` **volta para `draft` e derruba a aprovação**.
- Depois de `sent` **não se edita**: cancela e **duplica** (vira um orçamento novo).
- `expired` é verificado ao ler: `sent` com `valid_until < hoje` vira `expired`.
- Orçamento **nunca é apagado**, só cancelado. Mantém o histórico e a contagem da cota.
- Uma função central `transition(quote, novo_status, user)` recusa qualquer caminho fora do diagrama.

### 6.5 Aprovação de desconto

```
teto(papel) = member -> member_discount_limit_bps
              admin  -> admin_discount_limit_bps
              owner  -> sem limite

precisa_aprovação =
      desconto_efetivo > teto(papel de quem criou)
   OU (plano tem margem mínima E margem não é NULL E margem < min_margin_bps
       E quem criou não é owner)

quem_aprova = admin  se desconto_efetivo <= admin_discount_limit_bps
              owner  caso contrário
```

- **Ninguém aprova o próprio pedido.** `decided_by != requested_by`, conferido no servidor.
- Aprovar grava `approved_discount_bps`. Ao enviar, o servidor confere que o desconto atual é
  **igual ou menor** que o aprovado. Isso fecha o bypass "pede pouco, aumenta depois".
- Plano sem `feat_discount_approval` (Grátis): só existe o owner, que não tem teto, então a
  aprovação nunca é necessária.
- **Item sem custo cadastrado:** a margem não o considera. Se o orçamento tem desconto e algum
  item sem custo, o vendedor recebe **dois avisos** (um aviso na tela e uma confirmação ao
  concluir). Não vira aprovação sozinho: dentro do teto, conclui; acima do teto, a regra
  normal manda para quem aprova.
- A tela fala com quem está vendo: "seu teto" só para quem criou; para o gerente aparece
  "acima do teto de <nome>".

### 6.6 Portal do comprador

- Vê só orçamentos com status `sent`, `accepted`, `declined` ou `expired` de clientes aos quais
  está vinculado em `customer_users`.
- Vê produtos, quantidades, preço de tabela, desconto e total. **Nunca** vê custo, margem,
  `notes_internal`, pedidos de desconto ou outros clientes.
- Aceita/recusa apenas `sent` dentro da validade. A decisão grava `customer_user_id` e data, e
  não pode ser desfeita.
- **Aceitar:** a oportunidade vai para a etapa `won` do pipeline dela, `closed_at = agora`,
  `value_cents = final_total_cents`, e outros orçamentos `sent` da mesma oportunidade são cancelados.

### 6.7 Alerta de recompra

Para cada cliente, usando a data de aceite dos orçamentos (`customer_decided_at` com `accepted`):

```
se pedidos < 3                      -> sem alerta (pouco histórico)
intervalo_médio = (último − primeiro) / (pedidos − 1)
dias_sem_comprar = hoje − último
alerta se dias_sem_comprar > 1,5 × intervalo_médio
atraso = dias_sem_comprar − intervalo_médio
```

O alerta aparece no dashboard com o botão do WhatsApp e some sozinho com um novo pedido aceito.

### 6.8 Funil, tarefas e histórico

- Mudar de etapa: a nova etapa é do **mesmo pipeline**; entrar em `won`/`lost` preenche
  `closed_at`; voltar para `open` limpa; sempre gera activity `stage_change`.
- **Ganho manual** (venda fechada por telefone): entrar em `won` sem orçamento aceito exige
  valor maior que zero e marca `closed_manually = 1`. O painel mostra esse valor à parte
  ("fora do sistema"), e o aceite pelo portal sempre grava `closed_manually = 0`.
- Pipeline precisa ter pelo menos uma etapa `won` e uma `lost`. Etapa com oportunidades não
  pode ser apagada.
- Tarefa atrasada: `done_at IS NULL AND due_date < hoje`. "Hoje" é calculado no fuso
  `America/Sao_Paulo`.
- Activities não se editam. Só o autor ou um admin/owner pode apagar uma `note`. As geradas pelo
  sistema não se apagam.

### 6.9 Apagar registros

- **member** apaga só o que é dele (`owner_id` ou `created_by` = ele).
- Cliente com orçamentos não pode ser apagado (o histórico financeiro precisa continuar íntegro).
- Apagar oportunidade sem orçamentos: tarefas e activities dela vão junto.

### 6.10 Telefone e WhatsApp

Remove tudo que não é dígito. 10 ou 11 dígitos: prefixa `55`. Já com `55` e 12 ou 13 dígitos:
mantém. Qualquer outro caso: recusa. Botão abre `https://wa.me/<numero>?text=<mensagem>`.
Mensagens para clientes saem **sempre em português** (o cliente é uma empresa brasileira) e
cumprimentam o primeiro contato cadastrado; sem contato, usam o nome da empresa.

### 6.11 Suporte

`SUPPORT_WHATSAPP` em variável de ambiente. O botão "Falar com o suporte" aparece no cadastro, no
onboarding, na página de planos e em Configurações, com mensagem pronta contendo o nome do
workspace e o plano atual. É por ali que a distribuidora negocia preço do plano.

---

### 6.12 Relatório do painel e comissão

Período no calendário de São Paulo: este mês, mês passado ou últimos 90 dias.

- **Venda** = orçamento aceito pelo comprador no período (`customer_decided_at`) + ganho manual
  fechado no período (`closed_manually = 1`, valor da oportunidade).
- A venda é do **vendedor responsável pela oportunidade** (`opportunities.owner_id`).
- **Ticket médio** = vendido ÷ número de vendas. **Conversão** = orçamentos enviados no período
  que foram aceitos ÷ enviados no período. **Desconto médio** = (tabela − final) ÷ tabela dos
  orçamentos aceitos, ponderado pelo valor.
- **Comissão** = vendas do vendedor × `memberships.commission_bps`, definido pelo dono na tela
  de Equipe (o gerente só lê). Vendedor vê só os próprios números e a própria comissão.
- Tudo com inteiros (centavos e bps), arredondando como o `pricing.py`.

## 7. Planos e cotas

| | **Grátis** | **Essencial** | **Profissional** | **Escala** |
|---|---|---|---|---|
| Preço/mês | R$ 0 | R$ 99,90 | R$ 249,90 | R$ 449,90 |
| Equipe total | 1 | 4 | 8 | Ilimitada |
| Owners (máx.) | 1 | 1 | 1 | 2 (sócios) |
| Admins (máx.) | 0 | 1 | 2 | Ilimitados |
| Members (máx.) | 0 | 2 | 5 | Ilimitados |
| Clientes | 30 | 100 | 500 | Ilimitados |
| Produtos | 30 | 100 | Ilimitados | Ilimitados |
| Orçamentos/mês | 20 | 200 | 2.000 | Ilimitados |
| Portal do cliente | Básico | Completo | Completo | Completo |
| Aprovação de desconto | ✗ | ✓ | ✓ | ✓ |
| Margem mínima | ✗ | ✓ | ✓ | ✓ |
| Alerta de recompra | ✗ | ✗ | ✓ | ✓ |
| Exportar CSV | ✗ | ✗ | ✓ | ✓ |
| Vários pipelines | ✗ | ✗ | ✓ | ✓ |
| Suporte WhatsApp | Básico | Padrão | Prioritário | Gerente dedicado |

**Compradores nunca pagam e não contam como equipe.** Convidar compradores é o que traz gente
nova para a plataforma, por isso o portal existe em todos os planos.

### Como as cotas são aplicadas

- Conferidas **no servidor, antes de criar** (`check_quota(workspace_id, "products")`). Esconder
  botão é só conforto visual, não proteção.
- Orçamentos/mês: conta os criados no mês corrente (fuso de São Paulo), **incluindo cancelados**.
  Como orçamento não se apaga, não dá para "liberar cota" apagando.
- Equipe: conta membros + convites de equipe pendentes.
- **Portal básico (Grátis):** o comprador vê o orçamento e aceita/recusa. **Portal completo
  (pagos):** também informa o motivo da recusa e vê o histórico de pedidos e orçamentos antigos.
- **Downgrade:** nada é apagado. Exemplo: sair do Escala com 2 owners mantém os dois, mas
  bloqueia promover alguém a owner até ficar dentro do limite. O que passa do limite continua visível, só fica bloqueado criar
  novos. Features desligadas somem da interface e as rotas delas respondem com aviso de plano.
- Troca de plano na v1: **manual**, pelo painel da plataforma, depois de conversar no WhatsApp.

---

## 8. Matriz de permissões

| Ação | owner | admin | member | comprador | admin plataforma |
|---|:-:|:-:|:-:|:-:|:-:|
| Ver dados do workspace | ✓ | ✓ | ✓ | ✗ | ✗ |
| Ver oportunidades, orçamentos e valores | ✓ (todos) | ✓ (todos) | só os seus | ✗ | ✗ |
| Criar/editar clientes, contatos, oportunidades | ✓ | ✓ | ✓ | ✗ | ✗ |
| Apagar clientes, contatos, oportunidades | ✓ | ✓ | só os seus | ✗ | ✗ |
| Criar/editar produtos | ✓ | ✓ | ✗ | ✗ | ✗ |
| Criar orçamentos | ✓ | ✓ | ✓ | ✗ | ✗ |
| Aprovar desconto | ✓ (tudo) | ✓ (até o teto) | ✗ | ✗ | ✗ |
| Configurar pipelines e etapas | ✓ | ✓ | ✗ | ✗ | ✗ |
| Convidar compradores | ✓ | ✓ | ✓ | ✗ | ✗ |
| Convidar/remover equipe | ✓ | ✓ (members) | ✗ | ✗ | ✗ |
| Definir tetos e margem mínima | ✓ | ✗ | ✗ | ✗ | ✗ |
| Transferir posse / promover a owner | ✓ | ✗ | ✗ | ✗ | ✗ |
| Remover ou rebaixar outro owner | ✗ | ✗ | ✗ | ✗ | ✗ |
| Ver quais compradores vieram por convite seu | ✓ | ✓ | ✓ | ✗ | ✗ |
| Ver/aceitar orçamentos no portal | ✗ | ✗ | ✗ | ✓ (os seus) | ✗ |
| Trocar plano e preço de um workspace | ✗ | ✗ | ✗ | ✗ | ✓ |

Na implementação: decorator `@require_role("admin")` nas rotas e funções `can_*` para regras
por registro (ex.: `can_delete(user, record)`).

---

## 9. Segurança

| Risco | Defesa |
|---|---|
| SQL injection | Sempre `db.execute("... ?", valor)`. Nunca f-string com entrada do usuário. Nome de tabela dinâmico só a partir de uma lista fixa (whitelist). |
| Vazamento entre distribuidoras | §6.1 + FKs compostas (§10). |
| Comprador vendo dados internos | Templates do portal são separados e as consultas selecionam **só** colunas permitidas. |
| Bypass de aprovação | `approved_discount_bps` conferido no envio; editar derruba a aprovação. |
| Autoaprovação | `decided_by != requested_by` no servidor. |
| Validação só no front | Toda regra é repetida no servidor; o HTML é só conveniência. |
| Senha | `generate_password_hash` / `check_password_hash`. |
| Token de convite vazado no banco | Só o hash do token é salvo, como senha. Expira em 7 dias e é de uso único. |
| Formulário forjado entre sites (CSRF) | Toda ação que muda dados é `POST`. Token CSRF simples na sessão. |
| XSS | Jinja escapa por padrão. Proibido usar `|safe` com dado de usuário. |
| Admin da plataforma | Flag só pelo terminal. Painel não mostra dados de negócio. |

---

## 10. Decisões de design

1. **SQLite + biblioteca `cs50`.** Alinhado ao curso, sem servidor de banco para instalar. O
   modelo foi pensado para migrar para PostgreSQL sem mudanças grandes.
2. **Multi-tenant por coluna (`workspace_id`)** em vez de um banco por cliente. Mais simples de
   operar; o custo é a disciplina de filtrar sempre (§6.1).
3. **`workspace_id` repetido** em tabelas que poderiam deduzi-lo por JOIN. Todo filtro de
   segurança fica direto e indexado.
4. **FKs compostas** (`FOREIGN KEY (company_id, workspace_id) REFERENCES companies(id, workspace_id)`):
   o próprio banco impede um orçamento de apontar para o cliente de outra distribuidora.
5. **Centavos e bps inteiros.** `float` erra conta de dinheiro (`0.1 + 0.2 != 0.3`).
6. **Cópia de preço, custo e nome no item do orçamento.** Mudar o catálogo não reescreve
   orçamentos antigos.
7. **Aprovação amarrada a um valor**, não a um orçamento. É o que torna a aprovação confiável.
8. **Orçamento não se apaga**, só se cancela: auditoria e cota honestas.
9. **Etapas com `kind`** (`open`/`won`/`lost`): cada distribuidora nomeia as etapas como quiser
   e o dashboard continua funcionando.
10. **FKs explícitas em vez de polimórficas** (`company_id`, `opportunity_id`... em vez de
    `entity_type` + `entity_id`): integridade garantida pelo banco e JOINs simples.
11. **Planos como dados** (tabela `plans`): ajustar limite não exige mexer em código.
12. **Uma tabela `users` para todo mundo**, com papéis por vínculo: uma pessoa pode ser
    vendedora numa distribuidora e compradora em outra com o mesmo login.
13. **Tradução própria** (`translations.py` + `session["lang"]`) em vez de Flask-Babel: dois
    idiomas não justificam a dependência.
14. **Datas em UTC, exibição em `America/Sao_Paulo`.** Evita o bug de "tarefa de hoje" depois das 21h.

---

## 11. Escopo: v1 e v2

**v1 (projeto final do CS50) — escopo congelado:**

- Cadastro, login, logout, idioma PT/EN
- Workspaces, equipe por convite, papéis owner/admin/member
- Onboarding com tetos de desconto e margem mínima
- Clientes, contatos, busca e filtros
- Catálogo de produtos (custo em R$ ou %)
- Pipeline com etapas configuráveis, oportunidades, mudança de etapa
- Orçamentos com desconto por item e geral, estados, cancelar e duplicar
- Aprovação de desconto e margem mínima
- Portal do comprador multi-distribuidora com aceite/recusa
- Tarefas (hoje/atrasadas) e histórico de atividades
- Dashboard: valor em aberto, fechado no mês, orçamentos aguardando aprovação, alertas de recompra
- Planos com cotas, página de planos, painel da plataforma, botão de suporte
- Botão de WhatsApp com mensagem pronta
- Exportar CSV (para planos que têm)

**v2 (portfólio, depois do certificado):**

- Pagamento com Stripe (checkout + webhooks)
- API REST em JSON
- Workflows automáticos (ex.: criar tarefa X dias depois de enviar orçamento)
- Agentes de IA (resumo do cliente, sugestão de mensagem)
- Importar produtos e clientes por CSV
- Pedido de recompra direto pelo portal
- Benefício para distribuidoras que trazem compradores (usa `referred_by_workspace_id`) e o
  botão "indicar minha distribuidora" no portal
- Notificações (e-mail ou WhatsApp) de aprovação pendente e orçamento aceito
- Auditoria completa (quem mudou o quê e quando, em todas as telas)
- Exclusão de conta automatizada (LGPD)
- Preço anual e preço por usuário
- Deploy público com conta demo

---

## 12. Pendências

- [x] Portal básico do plano Grátis: vê e aceita/recusa; motivo e histórico só nos pagos.
- [x] Escopo da v1 congelado.
- [ ] Nome definitivo do produto.
- [ ] Preços finais dos planos.
