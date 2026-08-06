"""Login com rate limit distribuído (Redis) e recuperação de senha por e-mail.

Anti-enumeração: login e recuperação respondem de forma idêntica para e-mail
existente ou não. O e-mail de recuperação leva um link white label do tenant;
o token puro nunca vai a log — em desenvolvimento (e somente nele) é retornado
na resposta como conveniência (`token_dev`).
"""
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..audit import auditar
from ..auth import (consumir_token_recuperacao, gerar_token, gerar_token_recuperacao,
                    hash_senha, verificar_senha)
from ..db import get_db, row
from ..email_service import corpo_recuperacao, obter_email_provider
from ..ratelimit import obter_limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    senha: str


class RecuperarIn(BaseModel):
    email: str


class RedefinirIn(BaseModel):
    token: str
    nova_senha: str


@router.post("/login")
def login(dados: LoginIn, request: Request):
    email = dados.email.lower().strip()
    ip = request.client.host if request.client else "?"
    limiter = obter_limiter()
    if limiter.bloqueado(email, ip):
        raise HTTPException(429, "Muitas tentativas — aguarde 15 minutos")
    with get_db() as db:
        u = row(db.execute("SELECT * FROM usuarios WHERE email=? AND ativo=1", (email,)))
        if not u or not verificar_senha(dados.senha, u["senha_hash"]):
            limiter.registrar_falha(email, ip)
            raise HTTPException(401, "E-mail ou senha inválidos")
        if u["tenant_id"]:
            t = row(db.execute("SELECT ativo FROM tenants WHERE id=?", (u["tenant_id"],)))
            if not t or not t["ativo"]:
                raise HTTPException(403, "Barbearia suspensa — contate a plataforma")
        limiter.limpar(email, ip)
        tenant = None
        if u["tenant_id"]:
            tenant = row(db.execute(
                "SELECT id, nome, slug, cor_primaria, logo_url FROM tenants WHERE id=?", (u["tenant_id"],)))
        auditar(db, u["tenant_id"], u["id"], "login")
    return {
        "token": gerar_token(u),
        "usuario": {"id": u["id"], "nome": u["nome"], "papel": u["papel"], "tenant_id": u["tenant_id"]},
        "tenant": tenant,
    }


@router.post("/recuperar")
def recuperar(dados: RecuperarIn):
    resposta = {"mensagem": "Se o e-mail existir, as instruções foram enviadas"}
    with get_db() as db:
        u = row(db.execute("SELECT * FROM usuarios WHERE email=? AND ativo=1",
                           (dados.email.lower().strip(),)))
        if not u:
            return resposta
        token = gerar_token_recuperacao(db, u["id"])
        barbearia = "Plataforma"
        if u["tenant_id"]:
            t = row(db.execute("SELECT nome FROM tenants WHERE id=?", (u["tenant_id"],)))
            barbearia = t["nome"] if t else barbearia
        base = os.environ.get("APP_BASE_URL", "http://localhost:8000")
        link = f"{base}/app#redefinir={token}"
        assunto, corpo = corpo_recuperacao(barbearia, u["nome"], link)
        enviado = obter_email_provider().enviar(u["email"], assunto, corpo)
        auditar(db, u["tenant_id"], u["id"],
                "recuperacao_solicitada" if enviado else "recuperacao_falha_envio")
        if os.environ.get("APP_ENV", "development") != "production":
            resposta["token_dev"] = token
    return resposta


@router.post("/redefinir")
def redefinir(dados: RedefinirIn):
    if len(dados.nova_senha) < 8:
        raise HTTPException(422, "A senha deve ter pelo menos 8 caracteres")
    with get_db() as db:
        usuario_id = consumir_token_recuperacao(db, dados.token)
        if not usuario_id:
            raise HTTPException(422, "Token inválido, expirado ou já utilizado")
        db.execute("UPDATE usuarios SET senha_hash=? WHERE id=?",
                   (hash_senha(dados.nova_senha), usuario_id))
        u = row(db.execute("SELECT tenant_id FROM usuarios WHERE id=?", (usuario_id,)))
        auditar(db, u["tenant_id"], usuario_id, "senha_redefinida")
    return {"mensagem": "Senha redefinida — faça login"}
