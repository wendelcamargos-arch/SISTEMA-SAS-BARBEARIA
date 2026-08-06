# Segurança

## Autenticação e senhas

- Hash **bcrypt** (custo 12) — `app/auth.py:hash_senha`. Hashes legados
  `salt$sha256` são apenas verificados para migração; qualquer senha nova é bcrypt.
- Token HMAC-SHA256 assinado com `BARBEARIA_SECRET`, expiração de 12h.
  Em produção o segredo é obrigatório: a aplicação **recusa subir** sem ele.
- Recuperação de senha: token aleatório de uso único, hash SHA-256 em banco,
  validade 1h (`password_reset_tokens`). A resposta do endpoint é idêntica para
  e-mail existente/inexistente (anti-enumeração). O envio é feito por provider de
  e-mail (`app/email_service.py`): SMTP configurável por ambiente ou simulado em
  desenvolvimento; o link é white label por tenant e o token puro nunca vai a log
  (`token_dev` na resposta existe apenas fora de produção).

## Rate limit de login

5 falhas na janela de 15 min → bloqueio de 15 min por chave `email|IP` (HTTP 429).
Backend **Redis** (`REDIS_URL`, obrigatório em produção) — contadores e bloqueios
compartilhados entre réplicas, com expiração por TTL (`app/ratelimit.py`).
Fallback em memória existe apenas para desenvolvimento/teste sem Redis
(documentado; a aplicação recusa subir em produção sem Redis saudável).
Nenhuma credencial de Redis é registrada em log.

## RBAC

superadmin (plataforma) · gerente · recepcao. Toda rota exige dependência de
autorização; testes cobrem recepção tentando ações de gerente e acesso sem token.

## Webhook WhatsApp

Assinatura `X-Hub-Signature-256` validada com `META_APP_SECRET`
(comparação em tempo constante). Sem o segredo: produção responde 503;
desenvolvimento aceita (documentado). Idempotência por `whatsapp_events.evento_id`.

## Cabeçalhos e CORS

`X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`,
`Permissions-Policy` e HSTS (produção) em todas as respostas. CORS restrito a
`ALLOWED_ORIGINS`; em produção sem lista configurada, nenhuma origem cruzada.

## Segredos e demo

- Nenhum segredo hardcoded; tudo por variável de ambiente (`.env.example`).
- Seed de demonstração: bloqueado em produção e exige `DEMO_MODE=1` explícito
  (testado em `tests/test_auth.py`). As credenciais demo existem só nesse modo.

## Auditoria e logs

`audit_logs` registra login, fechamentos, estornos, sessões de caixa, campanha/
voucher, suspensão de tenant e onboarding. Regra fixa: o campo `detalhe` nunca
recebe CPF, senha, token ou telefone completo (`app/audit.py`).

## WhatsApp multi-tenant

Cada tenant tem `whatsapp_configs` própria; o access token NÃO é armazenado —
apenas `token_ref` (nome da variável de ambiente/secret manager). O webhook
roteia por `phone_number_id`, rejeita número desconhecido e escopa toda escrita
ao tenant identificado (testes em tests/test_whatsapp_multitenant.py).

## Pendências conscientes (pré-produção)

- Rotação de `BARBEARIA_SECRET` invalida sessões (aceito; TTL 12h).
- Credenciais SMTP e Meta são responsabilidade do operador do deploy.
