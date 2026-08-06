# Auditoria da origem (migração)

- **Origem:** `wendelcamargos-arch/Consulta-Cnpj-Abertos`, branch
  `claude/cadê-meu-time-jlbq7j`, commit `e8a63a4cc56767f0dcf1f8225f922d02b639abf9`,
  pasta `barbearia-saas/`.
- **Obtenção:** clone somente-leitura + `git checkout e8a63a4…` (working tree
  limpa, `git status --short` vazio). Exportação via `git archive` — transporta
  exclusivamente os **63 arquivos versionados**.

## Classificação dos arquivos da branch (main...HEAD na origem)

`git diff --name-status main...HEAD | grep -v "barbearia-saas/"` → vazio.
**63/63 arquivos classificados como BARBEARIA**; 0 CONSULTA_CNPJ, 0
COMPARTILHADO, 0 INDETERMINADO. Nenhum workflow, configuração de raiz ou
documento do produto de CNPJ foi tocado pela branch de origem.

## Artefatos NÃO transportados (existiam apenas no disco da origem, fora do Git)

`barbearia.db` (SQLite local) · `.coverage` · `__pycache__/` · `.pytest_cache/`
— excluídos por construção (git archive) e pelas exclusões da FASE 4.

## Busca de segredos na origem (pré-transporte)

`rg -i "password|secret|token|api[_-]?key|access[_-]?token|private[_-]?key"`:
todas as ocorrências são (a) nomes de variáveis de ambiente lidas em runtime,
(b) placeholders do `.env.example`, (c) senhas de demonstração do seed
(bloqueado em produção por `DEMO_MODE`) ou (d) fixtures de teste. **Nenhuma
credencial real encontrada.**

## Referências ao repositório antigo / caminho antigo

`rg -i "consulta-cnpj"` dentro do produto → 0 ocorrências operacionais.
`rg "barbearia-saas/"` em código/config → 0 ocorrências (o produto já era
autocontido; a promoção a raiz não exigiu ajuste de import, Docker, Alembic
ou testes).
