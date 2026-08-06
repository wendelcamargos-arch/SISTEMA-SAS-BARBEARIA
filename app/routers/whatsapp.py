"""WhatsApp: fila, processamento, configuração por tenant e webhook multi-tenant.

Roteamento do webhook (docs/WHATSAPP_WEBHOOK_FLOW.md):
  1. valida assinatura (X-Hub-Signature-256 + META_APP_SECRET);
  2. extrai value.metadata.phone_number_id;
  3. localiza o tenant em whatsapp_configs;
  4. número desconhecido → evento rejeitado (contado, não processado);
  5. idempotência por evento (whatsapp_events.evento_id UNIQUE);
  6. todo processamento é escopado ao tenant identificado — sem acesso cruzado.
"""
import hashlib
import hmac
import json
import os
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ..audit import auditar
from ..auth import contexto_tenant, exigir_gerente
from ..db import get_db, row, rows
from ..util import agora_tenant
from ..whatsapp_service import (config_whatsapp, link_wame, processar_fila,
                                tenant_por_phone_number_id)

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


# ---------- configuração por tenant ----------

class ConfigIn(BaseModel):
    phone_number_id: str
    business_account_id: str = ""
    display_phone_number: str = ""
    token_ref: str = ""          # NOME da variável de ambiente com o token — nunca o token
    status: str = "pendente"     # pendente | homologado | suspenso
    templates: list[str] = []


@router.get("/config")
def obter_config(usuario: dict = Depends(exigir_gerente)):
    with get_db() as db:
        cfg = config_whatsapp(db, usuario["tenant_id"])
    return cfg or {"configurado": False}


@router.put("/config")
def salvar_config(dados: ConfigIn, usuario: dict = Depends(exigir_gerente)):
    if dados.status not in ("pendente", "homologado", "suspenso"):
        raise HTTPException(422, "Status inválido")
    if dados.token_ref and not dados.token_ref.replace("_", "").isalnum():
        raise HTTPException(422, "token_ref deve ser o NOME de uma variável de ambiente")
    with get_db() as db:
        outro = row(db.execute(
            "SELECT tenant_id FROM whatsapp_configs WHERE phone_number_id=? AND tenant_id != ?",
            (dados.phone_number_id, usuario["tenant_id"])))
        if outro:
            raise HTTPException(409, "phone_number_id já vinculado a outra barbearia")
        homologado_em = agora_tenant(db, usuario["tenant_id"]).strftime("%Y-%m-%dT%H:%M") \
            if dados.status == "homologado" else None
        if config_whatsapp(db, usuario["tenant_id"]):
            db.execute(
                """UPDATE whatsapp_configs SET phone_number_id=?, business_account_id=?,
                   display_phone_number=?, token_ref=?, status=?, templates=?,
                   homologado_em=COALESCE(?, homologado_em) WHERE tenant_id=?""",
                (dados.phone_number_id, dados.business_account_id, dados.display_phone_number,
                 dados.token_ref, dados.status, json.dumps(dados.templates),
                 homologado_em, usuario["tenant_id"]))
        else:
            db.execute(
                """INSERT INTO whatsapp_configs (tenant_id, phone_number_id, business_account_id,
                   display_phone_number, token_ref, status, templates, homologado_em)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (usuario["tenant_id"], dados.phone_number_id, dados.business_account_id,
                 dados.display_phone_number, dados.token_ref, dados.status,
                 json.dumps(dados.templates), homologado_em))
        auditar(db, usuario["tenant_id"], usuario["uid"], "whatsapp_config_salva",
                detalhe=f"phone_number_id={dados.phone_number_id} status={dados.status}")
    return {"mensagem": "Configuração WhatsApp salva"}


# ---------- fila ----------

@router.get("/fila")
def fila(status: str = "", pendencia: int = 0, usuario: dict = Depends(contexto_tenant)):
    condicoes, params = ["m.tenant_id=?"], [usuario["tenant_id"]]
    if status:
        condicoes.append("m.status=?")
        params.append(status)
    if pendencia:
        condicoes.append("m.pendente_recepcao=1")
    with get_db() as db:
        lista = rows(db.execute(
            f"""SELECT m.*, c.nome cliente FROM mensagens_whatsapp m
                LEFT JOIN clientes c ON c.id=m.cliente_id
                WHERE {' AND '.join(condicoes)} ORDER BY m.agendada_para DESC LIMIT 200""", params))
    for m in lista:
        m["link_wame"] = link_wame(m["telefone"], m["texto"])
    return lista


@router.post("/processar")
def processar(usuario: dict = Depends(contexto_tenant)):
    with get_db() as db:
        return processar_fila(db, usuario["tenant_id"], agora_tenant(db, usuario["tenant_id"]))


# ---------- respostas ----------

RESPOSTAS = {"CONFIRMAR": "confirmar", "CANCELAR": "cancelar",
             "VOU ATRASAR": "atrasar", "ATRASAR": "atrasar"}


def _normalizar(texto: str) -> str:
    s = unicodedata.normalize("NFD", texto.strip().upper())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def interpretar_resposta(texto: str) -> str | None:
    return RESPOSTAS.get(_normalizar(texto))


def aplicar_resposta(db, mensagem: dict, resposta: str | None, texto_bruto: str) -> dict:
    if resposta is None:
        db.execute(
            "UPDATE mensagens_whatsapp SET pendente_recepcao=1, resposta=? WHERE id=?",
            (f"ambigua: {texto_bruto[:80]}", mensagem["id"]))
        return {"resultado": "ambigua", "encaminhado_recepcao": True}
    db.execute("UPDATE mensagens_whatsapp SET resposta=?, pendente_recepcao=0 WHERE id=?",
               (resposta, mensagem["id"]))
    if mensagem["agendamento_id"]:
        novo = {"confirmar": "confirmado", "cancelar": "cancelado", "atrasar": "atrasado"}[resposta]
        db.execute(
            """UPDATE agendamentos SET status=? WHERE id=? AND tenant_id=?
               AND status IN ('agendado','confirmado')""",
            (novo, mensagem["agendamento_id"], mensagem["tenant_id"]))
        auditar(db, mensagem["tenant_id"], None, f"whatsapp_resposta_{resposta}",
                "agendamento", mensagem["agendamento_id"])
    return {"resultado": resposta}


class RespostaIn(BaseModel):
    resposta: str


@router.post("/{msg_id}/resposta")
def registrar_resposta_manual(msg_id: int, dados: RespostaIn, usuario: dict = Depends(contexto_tenant)):
    if dados.resposta not in ("confirmar", "cancelar", "atrasar"):
        raise HTTPException(422, "Resposta deve ser confirmar, cancelar ou atrasar")
    with get_db() as db:
        m = row(db.execute("SELECT * FROM mensagens_whatsapp WHERE id=? AND tenant_id=?",
                           (msg_id, usuario["tenant_id"])))
        if not m:
            raise HTTPException(404, "Mensagem não encontrada")
        return aplicar_resposta(db, m, dados.resposta, dados.resposta)


# ---------- webhook oficial Meta (multi-tenant) ----------

@router.get("/webhook", response_class=PlainTextResponse)
def webhook_verificacao(hub_mode: str = Query(default="", alias="hub.mode"),
                        hub_verify_token: str = Query(default="", alias="hub.verify_token"),
                        hub_challenge: str = Query(default="", alias="hub.challenge")):
    esperado = os.environ.get("META_WHATSAPP_VERIFY_TOKEN", "")
    if not esperado:
        raise HTTPException(503, "META_WHATSAPP_VERIFY_TOKEN não configurado")
    if hub_mode == "subscribe" and hmac.compare_digest(hub_verify_token, esperado):
        return hub_challenge
    raise HTTPException(403, "Token de verificação inválido")


def _validar_assinatura(corpo: bytes, cabecalho: str) -> None:
    segredo = os.environ.get("META_APP_SECRET", "")
    if not segredo:
        if os.environ.get("APP_ENV", "development") == "production":
            raise HTTPException(503, "META_APP_SECRET não configurado")
        return
    esperada = "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(cabecalho or "", esperada):
        raise HTTPException(403, "Assinatura do webhook inválida")


def _evento_ja_processado(db, evento_id: str, tenant_id: int | None, tipo: str, payload: str) -> bool:
    if row(db.execute("SELECT id FROM whatsapp_events WHERE evento_id=?", (evento_id,))):
        return True
    db.execute(
        "INSERT INTO whatsapp_events (evento_id, tenant_id, tipo, payload, processado) VALUES (?,?,?,?,1)",
        (evento_id, tenant_id, tipo, payload[:2000]))
    return False


STATUS_MAP = {"sent": "enviada", "delivered": "entregue", "read": "lida", "failed": "erro"}


@router.post("/webhook")
async def webhook_eventos(request: Request):
    corpo = await request.body()
    _validar_assinatura(corpo, request.headers.get("X-Hub-Signature-256", ""))
    try:
        payload = json.loads(corpo)
    except json.JSONDecodeError:
        raise HTTPException(422, "Payload inválido")

    resultados = {"status_atualizados": 0, "respostas": 0, "duplicados": 0,
                  "ignorados": 0, "rejeitados_numero_desconhecido": 0}
    with get_db() as db:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                valor = change.get("value", {})
                phone_number_id = (valor.get("metadata") or {}).get("phone_number_id", "")
                cfg = tenant_por_phone_number_id(db, phone_number_id) if phone_number_id else None
                if not cfg:
                    resultados["rejeitados_numero_desconhecido"] += 1
                    auditar(db, None, None, "webhook_numero_desconhecido",
                            detalhe=f"phone_number_id={phone_number_id[:32]}")
                    continue
                tenant_id = cfg["tenant_id"]

                for st in valor.get("statuses", []):
                    ev_id = f"status:{tenant_id}:{st.get('id')}:{st.get('status')}"
                    if _evento_ja_processado(db, ev_id, tenant_id, "status", json.dumps(st)):
                        resultados["duplicados"] += 1
                        continue
                    novo = STATUS_MAP.get(st.get("status", ""))
                    if not novo:
                        resultados["ignorados"] += 1
                        continue
                    db.execute(
                        """UPDATE mensagens_whatsapp SET status=? WHERE provider_msg_id=?
                           AND tenant_id=? AND status NOT IN ('lida','falha_final','cancelada')""",
                        (novo, st.get("id", ""), tenant_id))
                    resultados["status_atualizados"] += 1

                for msg in valor.get("messages", []):
                    ev_id = f"msg:{tenant_id}:{msg.get('id')}"
                    if _evento_ja_processado(db, ev_id, tenant_id, "mensagem", json.dumps(msg)):
                        resultados["duplicados"] += 1
                        continue
                    texto = (msg.get("text") or {}).get("body", "") or \
                            (msg.get("button") or {}).get("text", "")
                    telefone = (msg.get("from") or "").removeprefix("55")
                    pendente = row(db.execute(
                        """SELECT * FROM mensagens_whatsapp
                           WHERE tenant_id=? AND telefone=? AND tipo='confirmacao'
                             AND status IN ('enviada','entregue','lida') AND resposta=''
                           ORDER BY agendada_para DESC LIMIT 1""", (tenant_id, telefone)))
                    if pendente:
                        aplicar_resposta(db, pendente, interpretar_resposta(texto), texto)
                        resultados["respostas"] += 1
                    else:
                        resultados["ignorados"] += 1
    return resultados
