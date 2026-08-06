# 💈 SISTEMA SAS BARBEARIA — White Label SaaS para Barbearias

**Objetivo:** sistema operacional de recorrência e redução de faltas para
barbearias — agenda recorrente, confirmações pelo WhatsApp oficial (Meta Cloud
API), gestão de cadeiras e visão financeira (caixa por sessão, estoque com
custo médio e **DRE Gerencial**). Multi-tenant white label com painel
administrativo da plataforma.

> **Origem da extração:** este repositório foi extraído do commit
> `e8a63a4cc56767f0dcf1f8225f922d02b639abf9` da branch
> `claude/cadê-meu-time-jlbq7j` do repositório Consulta-Cnpj-Abertos,
> exclusivamente para separar os produtos. Detalhes em
> `docs/MIGRATION_COMPLETION_REPORT.md`.

## Arquitetura

Monolito modular FastAPI (um router por domínio) + PostgreSQL 16 + Redis +
SPA vanilla JS. Todo dado de negócio é isolado por `tenant_id`
(`docs/MULTI_TENANCY.md`); valores monetários usam **NUMERIC(14,2)** no banco e
**Decimal** no Python, com arredondamento explícito ROUND_HALF_UP
(`app/money.py`). Visão completa: `docs/ARCHITECTURE.md`.

## Requisitos

Python 3.11+ · PostgreSQL 16 (extensão `btree_gist`) · Redis 7 (rate limit
distribuído; obrigatório em produção) · Docker/Compose opcional.

## Instalação local

```bash
pip install -r requirements.txt
cp .env.example .env                      # preencha as variáveis
export DATABASE_URL=postgresql://barbearia:senha@localhost:5432/barbearia_dev
export REDIS_URL=redis://localhost:6379/0
python -m alembic upgrade head            # migrations
DEMO_MODE=1 python -m app.seed            # seed de demonstração (PROIBIDO em produção)
uvicorn app.main:app --reload             # site em /, painel em /app
```

## Variáveis de ambiente

Ver `.env.example` — núcleo (`APP_ENV`, `DATABASE_URL`, `BARBEARIA_SECRET`,
`REDIS_URL`, `ALLOWED_ORIGINS`, `APP_BASE_URL`), WhatsApp Meta (`META_*`) e
SMTP (`SMTP_*`, sem host o provider de e-mail é simulado). Em produção a
aplicação **recusa subir** sem PostgreSQL, `BARBEARIA_SECRET` e Redis.

## Testes

```bash
pytest -q                                                   # SQLite (unitário)
DATABASE_URL=postgresql://barbearia:senha@localhost:5432/barbearia_test \
REDIS_URL=redis://localhost:6379/0 pytest -q --cov=app      # suíte oficial
ruff check . && mypy app && pip-audit -r requirements.txt
```

## Docker

```bash
cp .env.example .env
docker compose up -d --build     # app + PostgreSQL + Redis, com health checks
```

## WhatsApp (Meta Cloud API, multi-tenant)

Cada barbearia tem configuração própria (`whatsapp_configs`): `phone_number_id`,
conta business, status de homologação e **referência** segura do token
(`token_ref` = nome da variável de ambiente — o token nunca vai ao banco). O
webhook roteia cada evento ao tenant pelo `phone_number_id`, valida assinatura
e aplica idempotência. Setup: `docs/WHATSAPP_META_SETUP.md`. Automação por
WhatsApp Web/QR Code não é usada.

## Multi-tenancy e segurança

Escopo central por token assinado + revalidação de recurso por tenant, tenants
suspensos barrados a cada requisição, bcrypt, rate limit distribuído em Redis,
recuperação de senha por e-mail com token de uso único, auditoria sem dados
sensíveis. `docs/MULTI_TENANCY.md` · `docs/SECURITY.md` · `docs/LGPD.md`.

## DRE Gerencial

Relatório por regime de caixa com plano de categorias (descontos, estornos,
impostos, comissões, CMV, fixas/variáveis). **Este relatório é gerencial e não
substitui escrituração contábil, demonstrações contábeis oficiais ou obrigações
fiscais** — aviso presente no endpoint, na interface e nos termos de uso.

## Estado atual e limitações

MVP tecnicamente apto a piloto controlado — **não é produção pronta**.
Limitações conhecidas: integração real com a Meta ainda não homologada com
número/templates de produção; envio SMTP depende de credenciais do operador;
UI não expõe todas as APIs (bloqueios/cadeiras via API). Runbook do piloto:
`docs/PILOT_RUNBOOK.md`. Licença: pendente de definição (`LICENSE_PENDING.md`).

## Documentação

`docs/` — arquitetura, banco, multi-tenancy, segurança, LGPD, WhatsApp (setup,
templates, webhook), deploy, backup, runbook do piloto, pesquisa de mercado e
relatórios de migração.
