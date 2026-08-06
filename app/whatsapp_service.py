"""Mensageria WhatsApp — API oficial Meta Cloud, multi-tenant.

Cada tenant possui configuração própria em `whatsapp_configs` (phone_number_id,
business_account_id, display_phone_number, status, templates, homologado_em) e
uma REFERÊNCIA segura ao access token (`token_ref` = nome da variável de
ambiente/secret manager) — o token nunca é armazenado em texto puro no banco.

Fila em banco com estados:
  pendente → enviada → entregue → lida        (status via webhook)
  pendente → erro → retry (backoff 1/5/15min) → falha_final
Automação por WhatsApp Web/QR Code é proibida; wa.me existe só para disparo
manual da recepção.
"""
import json
import os
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Callable

from .db import row, rows
from .util import settings_tenant

RETRY_BACKOFF_MIN = [1, 5, 15]
MAX_TENTATIVAS = len(RETRY_BACKOFF_MIN) + 1

TEMPLATES: dict[str, Callable[..., str]] = {
    "confirmacao_agendamento": lambda c, b, hora, servicos:
        (f"Olá, {c.split()[0]}! 👋 Seu horário na {b} é às {hora} "
         f"({', '.join(servicos)}). Pode confirmar? Responda: CONFIRMAR · CANCELAR · VOU ATRASAR"),
    "lembrete_agendamento": lambda c, b, data, hora:
        f"Olá, {c.split()[0]}! Lembrando: sua agenda na {b} está marcada para {data} às {hora}. Até lá! ✂️",
    "aviso_final": lambda c, b, hora:
        f"{c.split()[0]}, seu horário na {b} é daqui a pouco, às {hora}. Estamos te esperando! 💈",
    "aniversario_cliente": lambda c, b, pct:
        (f"Feliz aniversário, {c.split()[0]}! 🎉 A {b} preparou um presente: "
         f"{pct:.0f}% de desconto. Apresente este voucher ao agendar. Válido conforme regulamento."),
}


def config_whatsapp(db, tenant_id: int) -> dict | None:
    return row(db.execute("SELECT * FROM whatsapp_configs WHERE tenant_id=?", (tenant_id,)))


def tenant_por_phone_number_id(db, phone_number_id: str) -> dict | None:
    return row(db.execute(
        "SELECT * FROM whatsapp_configs WHERE phone_number_id=? AND status != 'suspenso'",
        (phone_number_id,)))


class ProvedorMensageria(ABC):
    @abstractmethod
    def enviar(self, telefone: str, texto: str, config: dict | None = None) -> tuple[bool, str, str]:
        """Retorna (ok, provider_msg_id, detalhe). `config` é a linha de
        whatsapp_configs do tenant remetente."""


class SimuladoProvider(ProvedorMensageria):
    def __init__(self):
        import uuid
        self.enviadas: list[dict] = []
        self.falhar = False
        self._prefixo = uuid.uuid4().hex[:6]   # ids únicos entre instâncias

    def enviar(self, telefone: str, texto: str, config: dict | None = None) -> tuple[bool, str, str]:
        if self.falhar:
            return False, "", "falha simulada"
        self.enviadas.append({"telefone": telefone, "texto": texto,
                              "phone_number_id": (config or {}).get("phone_number_id", "")})
        return True, f"sim-{self._prefixo}-{len(self.enviadas)}", "simulado"


class MetaCloudProvider(ProvedorMensageria):
    """WhatsApp Business Cloud API oficial. O token vem da variável de ambiente
    apontada por config['token_ref'] (fallback: META_WHATSAPP_ACCESS_TOKEN)."""

    def _credenciais(self, config: dict | None) -> tuple[str, str]:
        token_ref = (config or {}).get("token_ref") or "META_WHATSAPP_ACCESS_TOKEN"
        token = os.environ.get(token_ref, "")
        phone_id = (config or {}).get("phone_number_id") or os.environ.get("META_WHATSAPP_PHONE_NUMBER_ID", "")
        return token, phone_id

    def enviar(self, telefone: str, texto: str, config: dict | None = None) -> tuple[bool, str, str]:
        token, phone_id = self._credenciais(config)
        if not token or not phone_id:
            return False, "", "credenciais ausentes para o tenant"
        numero = telefone if telefone.startswith("55") else f"55{telefone}"
        corpo = json.dumps({"messaging_product": "whatsapp", "to": numero,
                            "type": "text", "text": {"body": texto}}).encode()
        req = urllib.request.Request(
            f"https://graph.facebook.com/v21.0/{phone_id}/messages", data=corpo,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                dados = json.loads(resp.read())
                msg_id = (dados.get("messages") or [{}])[0].get("id", "")
                return True, msg_id, "ok"
        except Exception as exc:
            return False, "", str(exc)[:200]


_provider: ProvedorMensageria | None = None


def obter_provider() -> ProvedorMensageria:
    global _provider
    if _provider is None:
        if os.environ.get("META_WHATSAPP_ACCESS_TOKEN"):
            _provider = MetaCloudProvider()
        else:
            _provider = SimuladoProvider()
    return _provider


def definir_provider(p: ProvedorMensageria | None) -> None:
    global _provider
    _provider = p


def link_wame(telefone: str, texto: str) -> str:
    numero = telefone if telefone.startswith("55") else f"55{telefone}"
    return f"https://wa.me/{numero}?text={urllib.parse.quote(texto)}"


def _enfileirar(db, tenant_id: int, cliente: dict, ag_id: int | None, tipo: str,
                template: str, texto: str, quando: datetime) -> None:
    db.execute(
        """INSERT INTO mensagens_whatsapp
           (tenant_id, cliente_id, agendamento_id, telefone, tipo, template, texto, agendada_para)
           VALUES (?,?,?,?,?,?,?,?)""",
        (tenant_id, cliente["id"], ag_id, cliente["telefone"], tipo, template, texto,
         quando.strftime("%Y-%m-%dT%H:%M")))


def agendar_mensagens_do_agendamento(db, tenant_id: int, ag_id: int, cliente: dict,
                                     barbeiro: dict, inicio: datetime,
                                     servicos: list[str], agora: datetime) -> None:
    barbearia = row(db.execute("SELECT nome FROM tenants WHERE id=?", (tenant_id,)))["nome"]
    cfg = settings_tenant(db, tenant_id)
    hora = inicio.strftime("%H:%M")
    data_fmt = inicio.strftime("%d/%m")
    momentos = [
        ("confirmacao", "confirmacao_agendamento", cfg["confirmacao_min"],
         TEMPLATES["confirmacao_agendamento"](cliente["nome"], barbearia, hora, servicos)),
        ("lembrete", "lembrete_agendamento", cfg["lembrete_min"],
         TEMPLATES["lembrete_agendamento"](cliente["nome"], barbearia, data_fmt, hora)),
        ("aviso_final", "aviso_final", cfg["aviso_min"],
         TEMPLATES["aviso_final"](cliente["nome"], barbearia, hora)),
    ]
    for tipo, template, minutos, texto in momentos:
        quando = inicio - timedelta(minutes=minutos)
        if quando > agora:
            _enfileirar(db, tenant_id, cliente, ag_id, tipo, template, texto, quando)


def cancelar_mensagens_do_agendamento(db, ag_id: int) -> None:
    db.execute(
        "UPDATE mensagens_whatsapp SET status='cancelada' WHERE agendamento_id=? AND status='pendente'",
        (ag_id,))


def processar_fila(db, tenant_id: int, agora: datetime) -> dict:
    marca = agora.strftime("%Y-%m-%dT%H:%M")
    provider = obter_provider()
    config = config_whatsapp(db, tenant_id)
    enviadas = erros = finais = 0
    pendentes = rows(db.execute(
        """SELECT * FROM mensagens_whatsapp
           WHERE tenant_id=? AND (
             (status='pendente' AND agendada_para<=?) OR
             (status='erro' AND proximo_retry IS NOT NULL AND proximo_retry<=?))""",
        (tenant_id, marca, marca)))
    for m in pendentes:
        ok, provider_id, _detalhe = provider.enviar(m["telefone"], m["texto"], config)
        tentativas = m["tentativas"] + 1
        if ok:
            db.execute(
                "UPDATE mensagens_whatsapp SET status='enviada', provider_msg_id=?, tentativas=?, enviada_em=?, proximo_retry=NULL WHERE id=?",
                (provider_id, tentativas, marca, m["id"]))
            enviadas += 1
        elif tentativas >= MAX_TENTATIVAS:
            db.execute(
                "UPDATE mensagens_whatsapp SET status='falha_final', tentativas=?, proximo_retry=NULL WHERE id=?",
                (tentativas, m["id"]))
            finais += 1
        else:
            retry = agora + timedelta(minutes=RETRY_BACKOFF_MIN[tentativas - 1])
            db.execute(
                "UPDATE mensagens_whatsapp SET status='erro', tentativas=?, proximo_retry=? WHERE id=?",
                (tentativas, retry.strftime("%Y-%m-%dT%H:%M"), m["id"]))
            erros += 1
    return {"enviadas": enviadas, "erros": erros, "falhas_finais": finais}
