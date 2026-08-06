# Plano formal de migração

| Item | Definição |
|---|---|
| Origem | Consulta-Cnpj-Abertos · branch `claude/cadê-meu-time-jlbq7j` · commit `e8a63a4c…` · pasta `barbearia-saas/` |
| Destino | `wendelcamargos-arch/SISTEMA-SAS-BARBEARIA` · branch `claude/migracao-inicial-sistema-sas-barbearia` |
| Transporte | 63 arquivos versionados via `git archive` (conteúdo da pasta vira raiz) |
| Exclusões | `.env*` reais, bancos (`*.db*`, `*.sqlite*`), `.coverage`, caches (`__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`), venvs, logs, chaves (`*.pem/key/p12/pfx`), backups/dumps e o histórico `.git` da origem |
| Histórico | novo, iniciado no destino (sem carregar o histórico do repositório antigo) |
| Estratégia Git | branch de migração a partir da `main` do destino; um commit inicial do produto; push sem PR/merge/force |
| Rollback | destino intocado até o push; se necessário, deletar a branch de migração no destino restaura o estado anterior; origem nunca é alterada |
| Validação | compileall · ruff · mypy · alembic em banco vazio · pytest (+cov ≥85%, críticos ≥90%) · pip-audit · fumaça HTTP (health/landing/login/fluxo do balcão) — tudo executado fora da árvore da origem |
| Correções incluídas | Decimal/NUMERIC(14,2)+NUMERIC(7,4) · WhatsApp multi-tenant (whatsapp_configs + roteamento por phone_number_id + token_ref) · rate limit Redis · recuperação de senha por e-mail (provider) · rótulo DRE Gerencial + aviso · CI próprio |
| Migrations | Alembic `0001` já nasce com NUMERIC no destino (repositório novo → sem base legada para converter) |
| Serviços | PostgreSQL 16 (btree_gist) + Redis 7 (compose com health checks) |
| Variáveis | ver `.env.example` (núcleo, Meta, SMTP, Redis) |
| CI | `.github/workflows/ci.yml` com serviços de PostgreSQL e Redis, sem qualquer dependência da origem |
| Segurança | auditoria de segredos pré-commit; token WhatsApp apenas por referência de variável |
| Critérios de PASS | gate final da Execution Unit (32 itens) |
| Próximos passos | homologação real Meta + implantação da barbearia piloto nº 1 |
