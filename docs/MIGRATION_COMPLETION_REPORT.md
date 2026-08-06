# Relatório de conclusão da migração

**Data:** 2026-08-06

| Item | Valor |
|---|---|
| Origem | `wendelcamargos-arch/Consulta-Cnpj-Abertos` · branch `claude/cadê-meu-time-jlbq7j` · commit `e8a63a4cc56767f0dcf1f8225f922d02b639abf9` · pasta `barbearia-saas/` |
| Destino | `wendelcamargos-arch/SISTEMA-SAS-BARBEARIA` · branch `claude/migracao-inicial-sistema-sas-barbearia` |
| Transportados | 63 arquivos versionados (via `git archive` — conteúdo da pasta promovido à raiz) |
| Excluídos | histórico `.git` da origem, `barbearia.db`, `.coverage`, `__pycache__/`, `.pytest_cache/` e demais artefatos não versionados; nenhum `.env` real existia |
| Segredos | varredura executada — nenhuma credencial real transportada; token WhatsApp só por referência (`token_ref`); senhas demo restritas a `DEMO_MODE` |

## Correções aplicadas no destino (além do transporte)

1. **Financeiro:** NUMERIC(14,2) para valores, NUMERIC(7,4) para percentuais,
   NUMERIC(12,3) para quantidades; Python 100% `Decimal` com ROUND_HALF_UP
   (`app/money.py`); teste de guarda contra `float`/`round()` monetário.
2. **WhatsApp multi-tenant:** `whatsapp_configs` por tenant; webhook roteado por
   `phone_number_id` com rejeição de número desconhecido, idempotência por
   tenant e escopo de escrita; token nunca em texto puro.
3. **Rate limit Redis:** backend distribuído com TTL, obrigatório em produção;
   fallback em memória documentado para desenvolvimento.
4. **Recuperação de senha por e-mail:** provider simulado + SMTP configurável,
   link white label por tenant, token de uso único (hash em banco).
5. **DRE Gerencial:** nomenclatura pública + aviso legal no endpoint, painel,
   página comercial e termos de uso.
6. **CI próprio:** `.github/workflows/ci.yml` com serviços PostgreSQL e Redis.
7. Validador de aniversário passou a rejeitar dia/mês fora de faixa.

## Validações executadas (fora da árvore da origem)

- `python -m compileall app` ✔ · `ruff check .` ✔ · `mypy app` ✔ (0 erros)
- `alembic upgrade head` em banco **vazio** → 29 tabelas; tipos NUMERIC
  confirmados no catálogo (`payments.valor` = numeric(14,2);
  `commissions.percentual` = numeric(7,4))
- Suíte oficial (PostgreSQL + Redis): **100 passed · cobertura 93%**
  (auth 94/100%, tenants 93%, agendamentos 93%, caixa 98%, relatórios 100%,
  whatsapp 93/100%, money 100%)
- Suíte SQLite (unitária): 96 passed, 4 skipped (testes exclusivos de Redis/PG)
- `pip-audit`: sem vulnerabilidades conhecidas
- Fumaça HTTP: `/health/ready` (postgres + redis ok) · landing `/` 200 · login ·
  `GET /api/relatorios/dre` retornando "DRE Gerencial" com aviso
- `docker compose config` válido. **Limitação:** o daemon Docker não roda no
  ambiente de migração (sandbox) — `compose build/up` não executados aqui; o
  job `docker` do CI cobre o build na primeira execução no GitHub.

## Rollback

Origem intocada (fonte da verdade preservada). Para reverter o destino, basta
excluir a branch `claude/migracao-inicial-sistema-sas-barbearia` — a `main` do
destino permanece no commit inicial `fdbbcdb`.

## Pendência registrada

A remoção futura da pasta `barbearia-saas/` da origem depende de autorização
expressa do owner (não executada nesta migração).
