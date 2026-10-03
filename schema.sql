-- ===========================================================================
-- SupplyFlow database schema (SQLite)
-- SupplyFlow: esquema do banco de dados (SQLite)
-- ===========================================================================
--
-- EN: Conventions (see docs/ARCHITECTURE.md, section 5):
--   * money is stored in integer cents             (R$ 12,34 -> 1234)
--   * percentages are stored in integer basis points (10% -> 1000)
--   * dates are UTC text, e.g. '2026-10-01 14:00:00'
--   * every business table has workspace_id (the tenant = one distributor)
--
-- PT: Convenções (veja docs/ARCHITECTURE.md, seção 5):
--   * dinheiro é guardado em centavos inteiros       (R$ 12,34 -> 1234)
--   * porcentagem é guardada em basis points inteiros (10% -> 1000)
--   * datas são texto em UTC, ex.: '2026-10-01 14:00:00'
--   * toda tabela de negócio tem workspace_id (o tenant = uma distribuidora)
--
-- EN: Composite foreign keys such as (company_id, workspace_id) make the database itself
--     refuse a row that points to a record from another workspace. For that to work,
--     the parent table declares UNIQUE (id, workspace_id).
-- PT: Chaves estrangeiras compostas como (company_id, workspace_id) fazem o próprio banco
--     recusar uma linha que aponte para um registro de outra distribuidora. Para isso
--     funcionar, a tabela "pai" declara UNIQUE (id, workspace_id).


-- ---------------------------------------------------------------------------
-- EN: Plans. They are data, not code: changing a limit is an UPDATE.
-- PT: Planos. São dados, não código: mudar um limite é um UPDATE.
-- ---------------------------------------------------------------------------

CREATE TABLE plans (
    id                     INTEGER PRIMARY KEY,
    code                   TEXT    NOT NULL UNIQUE,   -- EN: internal id ('free'...) | PT: identificador interno
    name                   TEXT    NOT NULL,          -- EN: name shown on screen | PT: nome exibido
    position               INTEGER NOT NULL,          -- EN: display order | PT: ordem de exibição
    price_cents            INTEGER NOT NULL CHECK (price_cents >= 0),

    -- EN: Limits. NULL means unlimited.
    -- PT: Limites. NULL significa ilimitado.
    max_users              INTEGER CHECK (max_users >= 1),
    max_owners             INTEGER NOT NULL DEFAULT 1 CHECK (max_owners >= 1),
    max_admins             INTEGER CHECK (max_admins >= 0),
    max_members            INTEGER CHECK (max_members >= 0),
    max_customers          INTEGER CHECK (max_customers >= 0),
    max_products           INTEGER CHECK (max_products >= 0),
    max_quotes_month       INTEGER CHECK (max_quotes_month >= 0),

    -- EN: Features (0 = off, 1 = on)
    -- PT: Recursos (0 = desligado, 1 = ligado)
    feat_discount_approval INTEGER NOT NULL DEFAULT 0 CHECK (feat_discount_approval IN (0, 1)),
    feat_min_margin        INTEGER NOT NULL DEFAULT 0 CHECK (feat_min_margin IN (0, 1)),
    feat_repurchase_alert  INTEGER NOT NULL DEFAULT 0 CHECK (feat_repurchase_alert IN (0, 1)),
    feat_csv_export        INTEGER NOT NULL DEFAULT 0 CHECK (feat_csv_export IN (0, 1)),
    feat_multi_pipeline    INTEGER NOT NULL DEFAULT 0 CHECK (feat_multi_pipeline IN (0, 1)),
    feat_portal_full       INTEGER NOT NULL DEFAULT 0 CHECK (feat_portal_full IN (0, 1)),

    support_level          TEXT    NOT NULL
                           CHECK (support_level IN ('basico', 'padrao', 'prioritario', 'dedicado'))
);


-- ---------------------------------------------------------------------------
-- EN: Accounts and tenants
-- PT: Contas e tenants (distribuidoras)
-- ---------------------------------------------------------------------------

-- EN: One table for everybody. What a person can do depends on links:
--     memberships (staff), customer_users (buyer) or is_platform_admin.
--     referred_by_workspace_id points to a table created below; SQLite only checks
--     foreign keys when data is written, so the order is fine.
-- PT: Uma tabela para todo mundo. O que a pessoa pode fazer depende dos vínculos:
--     memberships (equipe), customer_users (comprador) ou is_platform_admin.
--     referred_by_workspace_id aponta para uma tabela criada mais abaixo; o SQLite só
--     confere chaves estrangeiras quando um dado é gravado, então a ordem funciona.
CREATE TABLE users (
    id                       INTEGER PRIMARY KEY,
    email                    TEXT    NOT NULL CHECK (email = lower(email)),  -- EN: always lowercase | PT: sempre minúsculo
    name                     TEXT    NOT NULL,
    hash                     TEXT    NOT NULL,       -- EN: password hash, never the password | PT: hash da senha, nunca a senha
    phone                    TEXT,                   -- EN: digits only, with 55 | PT: só dígitos, com 55
    lang                     TEXT    NOT NULL DEFAULT 'pt' CHECK (lang IN ('pt', 'en')),
    is_platform_admin        INTEGER NOT NULL DEFAULT 0 CHECK (is_platform_admin IN (0, 1)),
    signup_source            TEXT    NOT NULL DEFAULT 'direct'
                             CHECK (signup_source IN ('direct', 'invite')),
    -- EN: distributor that invited this buyer when the account was created (never changes)
    -- PT: distribuidora que convidou este comprador na criação da conta (nunca muda)
    referred_by_workspace_id INTEGER REFERENCES workspaces (id) ON DELETE SET NULL,
    created_at               TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- EN: A distributor (the tenant)
-- PT: Uma distribuidora (o tenant)
CREATE TABLE workspaces (
    id                        INTEGER PRIMARY KEY,
    name                      TEXT    NOT NULL,
    plan_id                   INTEGER NOT NULL REFERENCES plans (id),
    plan_started_at           TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    custom_price_cents        INTEGER CHECK (custom_price_cents >= 0),  -- EN: price negotiated with support | PT: preço negociado com o suporte

    -- EN: Company data printed on quotes and shown in the portal. Name and CNPJ change only
    --     through support (platform panel); e-mail, WhatsApp, city and logo by the owner.
    -- PT: Dados da empresa impressos nos orçamentos e mostrados no portal. Nome e CNPJ só
    --     mudam pelo suporte (painel da plataforma); e-mail, WhatsApp, cidade e logo pelo dono.
    cnpj                      TEXT CHECK (cnpj IS NULL OR length(cnpj) = 14),  -- EN: 14 digits | PT: 14 dígitos
    email                     TEXT,     -- EN: public contact e-mail | PT: e-mail público de contato
    phone                     TEXT,     -- EN: WhatsApp, digits with 55 | PT: WhatsApp, dígitos com 55
    city                      TEXT,
    logo_path                 TEXT,     -- EN: /static/uploads/logos/<random>.png | PT: /static/uploads/logos/<aleatório>.png

    -- EN: Discount ceilings per role and minimum margin, set by the owner
    -- PT: Tetos de desconto por cargo e margem mínima, definidos pelo owner
    member_discount_limit_bps INTEGER NOT NULL DEFAULT 500,
    admin_discount_limit_bps  INTEGER NOT NULL DEFAULT 1500,
    min_margin_bps            INTEGER NOT NULL DEFAULT 1500
                              CHECK (min_margin_bps BETWEEN 0 AND 10000),

    -- EN: Next sequential quote number (#0001, #0002...) for this workspace
    -- PT: Próximo número sequencial de orçamento (#0001, #0002...) desta distribuidora
    next_quote_number         INTEGER NOT NULL DEFAULT 1 CHECK (next_quote_number >= 1),
    onboarding_done           INTEGER NOT NULL DEFAULT 0 CHECK (onboarding_done IN (0, 1)),
    created_at                TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- EN: A seller can never have more power than a manager
    -- PT: Um vendedor nunca pode ter mais poder que um gerente
    CHECK (0 <= member_discount_limit_bps
           AND member_discount_limit_bps <= admin_discount_limit_bps
           AND admin_discount_limit_bps <= 10000)
);

-- EN: Password reset links (sent by e-mail). Like invites, only the SHA-256 hash of the
--     token is stored; a link lasts 1 hour and works once.
-- PT: Links de redefinição de senha (enviados por e-mail). Como nos convites, só o hash
--     SHA-256 do token é guardado; um link dura 1 hora e funciona uma vez.
CREATE TABLE password_resets (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash  TEXT    NOT NULL UNIQUE,
    expires_at  TEXT    NOT NULL,
    used_at     TEXT,
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- EN: Staff of a workspace. The owner count (1, or 2 on Escala) is checked in Python,
--     because the limit depends on the plan.
-- PT: Equipe de uma distribuidora. A quantidade de owners (1, ou 2 no Escala) é conferida
--     no Python, porque o limite depende do plano.
CREATE TABLE memberships (
    id           INTEGER PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    role         TEXT    NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
    -- EN: commission on this person's sales, in basis points (500 = 5%), set by the owner
    -- PT: comissão sobre as vendas desta pessoa, em basis points (500 = 5%), definida pelo dono
    commission_bps INTEGER NOT NULL DEFAULT 0 CHECK (commission_bps BETWEEN 0 AND 10000),
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (workspace_id, user_id)  -- EN: one role per person per workspace | PT: um cargo por pessoa por distribuidora
);


-- ---------------------------------------------------------------------------
-- EN: Customers of a distributor
-- PT: Clientes de uma distribuidora
-- ---------------------------------------------------------------------------

CREATE TABLE companies (
    id           INTEGER PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    cnpj         TEXT,
    segment      TEXT,
    phone        TEXT,
    city         TEXT,
    owner_id     INTEGER REFERENCES users (id) ON DELETE SET NULL,  -- EN: responsible seller | PT: vendedor responsável
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, workspace_id)  -- EN: target of composite FKs | PT: alvo das FKs compostas
);

CREATE TABLE contacts (
    id           INTEGER PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    company_id   INTEGER NOT NULL,
    name         TEXT    NOT NULL,
    phone        TEXT,
    email        TEXT,
    position     TEXT,      -- EN: job title | PT: cargo na empresa
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, workspace_id),
    -- EN: the company must belong to the same workspace
    -- PT: a empresa precisa ser da mesma distribuidora
    FOREIGN KEY (company_id, workspace_id)
        REFERENCES companies (id, workspace_id) ON DELETE CASCADE
);

-- EN: Invitations for staff (kind = 'staff') and buyers (kind = 'customer').
--     Only the hash of the token is stored; the raw token lives only in the link.
-- PT: Convites para equipe (kind = 'staff') e compradores (kind = 'customer').
--     Só o hash do token é guardado; o token puro existe apenas no link.
CREATE TABLE invites (
    id           INTEGER PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    kind         TEXT    NOT NULL CHECK (kind IN ('staff', 'customer')),
    email        TEXT    NOT NULL CHECK (email = lower(email)),
    role         TEXT    CHECK (role IN ('admin', 'member')),
    company_id   INTEGER,
    token_hash   TEXT    NOT NULL UNIQUE,
    created_by   INTEGER NOT NULL REFERENCES users (id),
    expires_at   TEXT    NOT NULL,
    accepted_at  TEXT,
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- EN: Staff invites carry a role; buyer invites carry a company
    -- PT: Convite de equipe tem cargo; convite de comprador tem empresa
    CHECK ((kind = 'staff'    AND role IS NOT NULL AND company_id IS NULL)
        OR (kind = 'customer' AND role IS NULL     AND company_id IS NOT NULL)),
    FOREIGN KEY (company_id, workspace_id)
        REFERENCES companies (id, workspace_id) ON DELETE CASCADE
);

-- EN: Links a buyer account to a customer of a distributor.
--     One buyer can be linked to customers of many distributors.
-- PT: Liga uma conta de comprador a um cliente de uma distribuidora.
--     Um comprador pode estar ligado a clientes de várias distribuidoras.
CREATE TABLE customer_users (
    id           INTEGER PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    company_id   INTEGER NOT NULL,
    user_id      INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (company_id, user_id),
    FOREIGN KEY (company_id, workspace_id)
        REFERENCES companies (id, workspace_id) ON DELETE CASCADE
);


-- ---------------------------------------------------------------------------
-- EN: Sales pipeline
-- PT: Funil de vendas
-- ---------------------------------------------------------------------------

CREATE TABLE pipelines (
    id           INTEGER PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    position     INTEGER NOT NULL DEFAULT 0,
    is_default   INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, workspace_id)
);

-- EN: kind lets every distributor name stages freely while the dashboard still works
-- PT: kind deixa cada distribuidora nomear as etapas livremente e o dashboard continua funcionando
CREATE TABLE stages (
    id           INTEGER PRIMARY KEY,
    workspace_id INTEGER NOT NULL,
    pipeline_id  INTEGER NOT NULL,
    name         TEXT    NOT NULL,
    position     INTEGER NOT NULL DEFAULT 0,
    kind         TEXT    NOT NULL CHECK (kind IN ('open', 'won', 'lost')),
    UNIQUE (id, pipeline_id),  -- EN: lets opportunities check stage/pipeline | PT: permite conferir etapa/pipeline
    FOREIGN KEY (pipeline_id, workspace_id)
        REFERENCES pipelines (id, workspace_id) ON DELETE CASCADE
);

CREATE TABLE opportunities (
    id             INTEGER PRIMARY KEY,
    workspace_id   INTEGER NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    pipeline_id    INTEGER NOT NULL,
    stage_id       INTEGER NOT NULL,
    company_id     INTEGER NOT NULL,
    -- EN: Optional reference: plain FK with SET NULL. A composite FK with SET NULL would
    --     also null workspace_id (NOT NULL) and fail. Same-workspace check is in Python.
    -- PT: Referência opcional: FK simples com SET NULL. Uma FK composta com SET NULL também
    --     zeraria workspace_id (NOT NULL) e daria erro. A checagem de distribuidora fica no Python.
    contact_id     INTEGER REFERENCES contacts (id) ON DELETE SET NULL,
    owner_id       INTEGER REFERENCES users (id) ON DELETE SET NULL,
    title          TEXT    NOT NULL,
    value_cents    INTEGER NOT NULL DEFAULT 0 CHECK (value_cents >= 0),
    expected_close TEXT,
    closed_at      TEXT,    -- EN: set when entering a won/lost stage | PT: preenchido ao entrar em etapa won/lost
    -- EN: 1 = marked as won by hand (sale closed by phone, no accepted quote); reported apart
    -- PT: 1 = marcada como ganha à mão (venda fechada por telefone, sem orçamento aceito); contada à parte
    closed_manually INTEGER NOT NULL DEFAULT 0 CHECK (closed_manually IN (0, 1)),
    lost_reason    TEXT,
    created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, workspace_id),
    FOREIGN KEY (pipeline_id, workspace_id) REFERENCES pipelines (id, workspace_id),
    -- EN: The stage must belong to the same pipeline. A stage in use cannot be deleted.
    -- PT: A etapa precisa ser do mesmo pipeline. Etapa em uso não pode ser apagada.
    FOREIGN KEY (stage_id, pipeline_id)     REFERENCES stages (id, pipeline_id),
    FOREIGN KEY (company_id, workspace_id)
        REFERENCES companies (id, workspace_id) ON DELETE CASCADE
);


-- ---------------------------------------------------------------------------
-- EN: Catalog and quotes
-- PT: Catálogo e orçamentos
-- ---------------------------------------------------------------------------

CREATE TABLE products (
    id           INTEGER PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    sku          TEXT    NOT NULL,   -- EN: product code | PT: código do produto
    name         TEXT    NOT NULL,
    unit         TEXT    NOT NULL DEFAULT 'un',
    price_cents  INTEGER NOT NULL CHECK (price_cents > 0),
    cost_cents   INTEGER CHECK (cost_cents >= 0),   -- EN: optional | PT: opcional
    active       INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (workspace_id, sku),  -- EN: SKU unique per distributor | PT: SKU único por distribuidora
    UNIQUE (id, workspace_id)
);

-- EN: Quotes are never deleted, only cancelled (keeps history and the monthly quota honest).
--     Deleting an opportunity or company that has quotes is therefore blocked.
-- PT: Orçamentos nunca são apagados, só cancelados (mantém o histórico e a cota mensal honestos).
--     Por isso, apagar uma oportunidade ou cliente que tenha orçamentos é bloqueado.
CREATE TABLE quotes (
    id                     INTEGER PRIMARY KEY,
    workspace_id           INTEGER NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    number                 INTEGER NOT NULL,
    opportunity_id         INTEGER NOT NULL,
    company_id             INTEGER NOT NULL,   -- EN: copied from the opportunity, for the portal | PT: copiado da oportunidade, para o portal
    created_by             INTEGER NOT NULL REFERENCES users (id),
    status                 TEXT    NOT NULL DEFAULT 'draft'
                           CHECK (status IN ('draft', 'pending_approval', 'ready', 'sent',
                                             'accepted', 'declined', 'expired', 'cancelled')),
    header_discount_bps    INTEGER NOT NULL DEFAULT 0 CHECK (header_discount_bps BETWEEN 0 AND 10000),
    valid_until            TEXT    NOT NULL,

    -- EN: Calculated by pricing.py on every save
    -- PT: Calculados pelo pricing.py a cada salvamento
    list_total_cents       INTEGER NOT NULL DEFAULT 0 CHECK (list_total_cents >= 0),
    final_total_cents      INTEGER NOT NULL DEFAULT 0 CHECK (final_total_cents >= 0),
    effective_discount_bps INTEGER NOT NULL DEFAULT 0 CHECK (effective_discount_bps BETWEEN 0 AND 10000),
    margin_bps             INTEGER CHECK (margin_bps <= 10000),   -- EN: can be negative (below cost) | PT: pode ser negativa (abaixo do custo)

    -- EN: Approval is tied to an exact discount
    -- PT: A aprovação vale para um desconto exato
    approved_by            INTEGER REFERENCES users (id),
    approved_at            TEXT,
    approved_discount_bps  INTEGER CHECK (approved_discount_bps BETWEEN 0 AND 10000),

    sent_at                TEXT,
    customer_user_id       INTEGER REFERENCES users (id),   -- EN: buyer who accepted/declined | PT: comprador que aceitou/recusou
    customer_decided_at    TEXT,
    decline_reason         TEXT,
    notes_internal         TEXT,                            -- EN: never shown in the portal | PT: nunca aparece no portal
    notes_customer         TEXT,
    created_at             TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (workspace_id, number),
    UNIQUE (id, workspace_id),
    FOREIGN KEY (opportunity_id, workspace_id) REFERENCES opportunities (id, workspace_id),
    FOREIGN KEY (company_id, workspace_id)     REFERENCES companies (id, workspace_id)
);

-- EN: Name, unit, price and cost are copies taken when the item is added:
--     changing the catalog later never rewrites old quotes.
-- PT: Nome, unidade, preço e custo são cópias feitas quando o item é adicionado:
--     mudar o catálogo depois nunca reescreve orçamentos antigos.
CREATE TABLE quote_items (
    id                INTEGER PRIMARY KEY,
    workspace_id      INTEGER NOT NULL,
    quote_id          INTEGER NOT NULL,
    product_id        INTEGER NOT NULL,
    product_name      TEXT    NOT NULL,
    unit              TEXT    NOT NULL,
    quantity          INTEGER NOT NULL CHECK (quantity > 0),
    list_price_cents  INTEGER NOT NULL CHECK (list_price_cents >= 0),
    cost_cents        INTEGER CHECK (cost_cents >= 0),
    discount_bps      INTEGER NOT NULL DEFAULT 0 CHECK (discount_bps BETWEEN 0 AND 10000),
    line_total_cents  INTEGER NOT NULL DEFAULT 0 CHECK (line_total_cents >= 0),
    FOREIGN KEY (quote_id, workspace_id)
        REFERENCES quotes (id, workspace_id) ON DELETE CASCADE,
    -- EN: A product used in a quote cannot be deleted (deactivate it instead)
    -- PT: Produto usado em orçamento não pode ser apagado (desative em vez disso)
    FOREIGN KEY (product_id, workspace_id) REFERENCES products (id, workspace_id)
);

-- EN: Audit trail of discount approvals
-- PT: Trilha de auditoria das aprovações de desconto
CREATE TABLE discount_requests (
    id                     INTEGER PRIMARY KEY,
    workspace_id           INTEGER NOT NULL,
    quote_id               INTEGER NOT NULL,
    requested_by           INTEGER NOT NULL REFERENCES users (id),
    requested_discount_bps INTEGER NOT NULL CHECK (requested_discount_bps BETWEEN 0 AND 10000),
    requested_margin_bps   INTEGER CHECK (requested_margin_bps <= 10000),
    required_role          TEXT    NOT NULL CHECK (required_role IN ('admin', 'owner')),
    reason                 TEXT    NOT NULL,
    status                 TEXT    NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    decided_by             INTEGER REFERENCES users (id),
    decided_at             TEXT,
    decision_note          TEXT,
    created_at             TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- EN: Nobody approves their own request (also checked in Python)
    -- PT: Ninguém aprova o próprio pedido (também conferido no Python)
    CHECK (decided_by IS NULL OR decided_by <> requested_by),
    FOREIGN KEY (quote_id, workspace_id)
        REFERENCES quotes (id, workspace_id) ON DELETE CASCADE
);


-- ---------------------------------------------------------------------------
-- EN: Tasks and activity history
-- PT: Tarefas e histórico de atividades
-- ---------------------------------------------------------------------------

CREATE TABLE tasks (
    id             INTEGER PRIMARY KEY,
    workspace_id   INTEGER NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    assignee_id    INTEGER REFERENCES users (id) ON DELETE SET NULL,
    created_by     INTEGER NOT NULL REFERENCES users (id),
    title          TEXT    NOT NULL,
    due_date       TEXT,                 -- EN: 'YYYY-MM-DD' in Sao Paulo time | PT: 'AAAA-MM-DD' no horário de São Paulo
    done_at        TEXT,
    company_id     INTEGER,
    contact_id     INTEGER,
    opportunity_id INTEGER,
    created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- EN: a task must be linked to at least one record
    -- PT: a tarefa precisa estar ligada a pelo menos um registro
    CHECK (company_id IS NOT NULL OR contact_id IS NOT NULL OR opportunity_id IS NOT NULL),
    FOREIGN KEY (company_id, workspace_id)
        REFERENCES companies (id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (contact_id, workspace_id)
        REFERENCES contacts (id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (opportunity_id, workspace_id)
        REFERENCES opportunities (id, workspace_id) ON DELETE CASCADE
);

-- EN: Insert-only history. Never edited.
-- PT: Histórico só de inserção. Nunca é editado.
CREATE TABLE activities (
    id             INTEGER PRIMARY KEY,
    workspace_id   INTEGER NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    user_id        INTEGER REFERENCES users (id) ON DELETE SET NULL,   -- EN: staff or buyer | PT: equipe ou comprador
    type           TEXT    NOT NULL
                   CHECK (type IN ('note', 'call', 'whatsapp', 'stage_change', 'task_done',
                                   'quote_sent', 'quote_accepted', 'quote_declined',
                                   'discount_requested', 'discount_approved', 'discount_rejected')),
    body           TEXT    NOT NULL,
    company_id     INTEGER,
    contact_id     INTEGER,
    opportunity_id INTEGER,
    quote_id       INTEGER,
    created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (company_id IS NOT NULL OR contact_id IS NOT NULL
           OR opportunity_id IS NOT NULL OR quote_id IS NOT NULL),
    FOREIGN KEY (company_id, workspace_id)
        REFERENCES companies (id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (contact_id, workspace_id)
        REFERENCES contacts (id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (opportunity_id, workspace_id)
        REFERENCES opportunities (id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (quote_id, workspace_id)
        REFERENCES quotes (id, workspace_id)
);


-- ---------------------------------------------------------------------------
-- EN: Indexes on columns used in WHERE / JOIN. The UNIQUE constraints above
--     already create their own indexes.
-- PT: Índices nas colunas usadas em WHERE / JOIN. As restrições UNIQUE acima
--     já criam os próprios índices.
-- ---------------------------------------------------------------------------

CREATE UNIQUE INDEX users_email ON users (email);

CREATE INDEX memberships_user          ON memberships (user_id);
-- EN: one distributor per CNPJ (empty CNPJs don't collide) | PT: uma distribuidora por CNPJ (CNPJs vazios não colidem)
CREATE UNIQUE INDEX workspaces_cnpj      ON workspaces (cnpj) WHERE cnpj IS NOT NULL;
CREATE INDEX password_resets_user        ON password_resets (user_id, created_at);
CREATE INDEX invites_workspace         ON invites (workspace_id, kind);
CREATE INDEX companies_ws_name         ON companies (workspace_id, name);
CREATE INDEX companies_ws_owner        ON companies (workspace_id, owner_id);
CREATE INDEX contacts_ws_company       ON contacts (workspace_id, company_id);
CREATE INDEX customer_users_user       ON customer_users (user_id);
CREATE INDEX stages_pipeline           ON stages (pipeline_id, position);
CREATE INDEX opportunities_ws_stage    ON opportunities (workspace_id, stage_id);
CREATE INDEX opportunities_ws_owner    ON opportunities (workspace_id, owner_id);
CREATE INDEX opportunities_ws_company  ON opportunities (workspace_id, company_id);
CREATE INDEX products_ws_active        ON products (workspace_id, active);
CREATE INDEX quotes_ws_status          ON quotes (workspace_id, status);
CREATE INDEX quotes_ws_created         ON quotes (workspace_id, created_at);
CREATE INDEX quotes_company_status     ON quotes (company_id, status);
CREATE INDEX quotes_opportunity        ON quotes (opportunity_id);
CREATE INDEX quote_items_quote         ON quote_items (quote_id);
CREATE INDEX discount_requests_ws      ON discount_requests (workspace_id, status);
CREATE INDEX tasks_ws_due              ON tasks (workspace_id, done_at, due_date);
CREATE INDEX tasks_ws_assignee         ON tasks (workspace_id, assignee_id);
CREATE INDEX activities_ws_opportunity ON activities (workspace_id, opportunity_id);
CREATE INDEX activities_ws_company     ON activities (workspace_id, company_id);
CREATE INDEX activities_quote          ON activities (quote_id);


-- ---------------------------------------------------------------------------
-- EN: Seed data: plans (docs/ARCHITECTURE.md, section 7). NULL = unlimited.
-- PT: Dados iniciais: planos (docs/ARCHITECTURE.md, seção 7). NULL = ilimitado.
-- ---------------------------------------------------------------------------

INSERT INTO plans (code, name, position, price_cents,
                   max_users, max_owners, max_admins, max_members,
                   max_customers, max_products, max_quotes_month,
                   feat_discount_approval, feat_min_margin, feat_repurchase_alert,
                   feat_csv_export, feat_multi_pipeline, feat_portal_full, support_level)
VALUES
    ('free',         'Grátis',       1,     0,    1, 1,    0,    0,   30,   30,   20, 0, 0, 0, 0, 0, 0, 'basico'),
    ('essencial',    'Essencial',    2,  9990,    4, 1,    1,    2,  100,  100,  200, 1, 1, 0, 0, 0, 1, 'padrao'),
    ('profissional', 'Profissional', 3, 24990,    8, 1,    2,    5,  500, NULL, 2000, 1, 1, 1, 1, 1, 1, 'prioritario'),
    ('escala',       'Escala',       4, 44990, NULL, 2, NULL, NULL, NULL, NULL, NULL, 1, 1, 1, 1, 1, 1, 'dedicado');
