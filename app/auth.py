"""Autenticação e autorização.

- Hash de senha: bcrypt (verificação de hash legado salt$sha256 apenas para
  migração de bases antigas; novo hash é sempre bcrypt).
- Token: HMAC-SHA256 assinado, com expiração. Em produção BARBEARIA_SECRET é
  obrigatório (a aplicação recusa subir sem ele).
- RBAC: superadmin | gerente | recepcao.
- Rate limit de login: Redis via app/ratelimit.py (fallback em memória apenas
  fora de produção — docs/SECURITY.md).
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

import bcrypt
from fastapi import Depends, Header, HTTPException

from .db import get_db, row

TOKEN_TTL = 60 * 60 * 12


def _secret() -> bytes:
    valor = os.environ.get("BARBEARIA_SECRET", "")
    if not valor:
        if os.environ.get("APP_ENV", "development") == "production":
            raise RuntimeError("BARBEARIA_SECRET é obrigatório em produção")
        valor = "segredo-apenas-desenvolvimento"
    return valor.encode()


def hash_senha(senha: str) -> str:
    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt(rounds=12)).decode()


def verificar_senha(senha: str, armazenada: str) -> bool:
    if armazenada.startswith("$2"):
        try:
            return bcrypt.checkpw(senha.encode(), armazenada.encode())
        except ValueError:
            return False
    try:
        salt, digest = armazenada.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(hashlib.sha256((salt + senha).encode()).hexdigest(), digest)


# ---------- token ----------

def gerar_token(usuario: dict) -> str:
    payload = {
        "uid": usuario["id"],
        "tenant_id": usuario["tenant_id"],
        "papel": usuario["papel"],
        "nome": usuario["nome"],
        "exp": int(time.time()) + TOKEN_TTL,
    }
    corpo = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    assinatura = hmac.new(_secret(), corpo.encode(), hashlib.sha256).hexdigest()
    return f"{corpo}.{assinatura}"


def decodificar_token(token: str) -> dict:
    try:
        corpo, assinatura = token.split(".", 1)
    except ValueError:
        raise HTTPException(401, "Token malformado")
    esperada = hmac.new(_secret(), corpo.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(assinatura, esperada):
        raise HTTPException(401, "Assinatura inválida")
    payload = json.loads(base64.urlsafe_b64decode(corpo))
    if payload["exp"] < time.time():
        raise HTTPException(401, "Sessão expirada, faça login novamente")
    return payload


# ---------- recuperação de senha ----------

def gerar_token_recuperacao(db, usuario_id: int) -> str:
    """Gera token aleatório; persiste apenas o hash. O token puro nunca é logado."""
    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO password_reset_tokens (usuario_id, token_hash, expira_em) VALUES (?,?,?)",
        (usuario_id, hashlib.sha256(token.encode()).hexdigest(),
         time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + 3600))))
    return token


def consumir_token_recuperacao(db, token: str) -> int | None:
    agora = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    t = row(db.execute(
        "SELECT * FROM password_reset_tokens WHERE token_hash=? AND usado=0 AND expira_em>?",
        (hashlib.sha256(token.encode()).hexdigest(), agora)))
    if not t:
        return None
    db.execute("UPDATE password_reset_tokens SET usado=1 WHERE id=?", (t["id"],))
    return t["usuario_id"]


# ---------- dependências de rota ----------

def usuario_atual(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Não autenticado")
    return decodificar_token(authorization.removeprefix("Bearer "))


def exigir_tenant(usuario: dict = Depends(usuario_atual)) -> dict:
    if usuario["tenant_id"] is None:
        raise HTTPException(403, "Superadmin deve informar o tenant (X-Tenant-Id)")
    return usuario


def exigir_gerente(usuario: dict = Depends(exigir_tenant)) -> dict:
    if usuario["papel"] not in ("gerente",):
        raise HTTPException(403, "Apenas o gerente pode executar esta ação")
    return usuario


def exigir_superadmin(usuario: dict = Depends(usuario_atual)) -> dict:
    if usuario["papel"] != "superadmin":
        raise HTTPException(403, "Apenas o administrador da plataforma")
    return usuario


def _tenant_ativo(db, tenant_id: int) -> bool:
    return bool(row(db.execute("SELECT id FROM tenants WHERE id=? AND ativo=1", (tenant_id,))))


def contexto_tenant(usuario: dict = Depends(usuario_atual),
                    x_tenant_id: int | None = Header(default=None)) -> dict:
    if usuario["tenant_id"] is not None:
        with get_db() as db:
            if not _tenant_ativo(db, usuario["tenant_id"]):
                raise HTTPException(403, "Barbearia suspensa — contate a plataforma")
        return usuario
    if x_tenant_id is None:
        raise HTTPException(403, "Superadmin deve informar X-Tenant-Id para operar uma barbearia")
    with get_db() as db:
        if not _tenant_ativo(db, x_tenant_id):
            raise HTTPException(404, "Barbearia não encontrada")
    return {**usuario, "tenant_id": x_tenant_id}
