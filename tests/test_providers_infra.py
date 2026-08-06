"""Providers de infraestrutura: Meta Cloud (HTTP simulado), SMTP (simulado),
seleção de provider e utilitários de fuso."""
import io
import json

import pytest

from app import email_service, whatsapp_service
from app.util import dia_fechado, timezone_tenant
from app.whatsapp_service import MetaCloudProvider, SimuladoProvider, obter_provider


class _RespostaFake(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_meta_provider_resolve_credenciais_por_token_ref(monkeypatch):
    monkeypatch.setenv("TOKEN_TENANT_X", "token-do-tenant")
    p = MetaCloudProvider()
    token, phone = p._credenciais({"token_ref": "TOKEN_TENANT_X", "phone_number_id": "pn-1"})
    assert token == "token-do-tenant" and phone == "pn-1"
    # sem credencial → falha explícita sem tocar a rede
    monkeypatch.delenv("META_WHATSAPP_ACCESS_TOKEN", raising=False)
    ok, _, detalhe = p.enviar("34999", "oi", {"token_ref": "VAR_INEXISTENTE", "phone_number_id": ""})
    assert not ok and "credenciais" in detalhe


def test_meta_provider_sucesso_e_erro_http(monkeypatch):
    monkeypatch.setenv("TOKEN_OK", "t")
    p = MetaCloudProvider()
    chamadas = {}

    def urlopen_ok(req, timeout):
        chamadas["url"] = req.full_url
        chamadas["auth"] = req.headers.get("Authorization")
        corpo = json.loads(req.data)
        chamadas["para"] = corpo["to"]
        return _RespostaFake(json.dumps({"messages": [{"id": "wamid.META1"}]}).encode())

    monkeypatch.setattr(whatsapp_service.urllib.request, "urlopen", urlopen_ok)
    ok, msg_id, _ = p.enviar("34999000001", "olá",
                             {"token_ref": "TOKEN_OK", "phone_number_id": "pn-77"})
    assert ok and msg_id == "wamid.META1"
    assert "pn-77/messages" in chamadas["url"]
    assert chamadas["auth"] == "Bearer t"
    assert chamadas["para"] == "5534999000001"          # DDI normalizado

    def urlopen_erro(req, timeout):
        raise OSError("rede fora")
    monkeypatch.setattr(whatsapp_service.urllib.request, "urlopen", urlopen_erro)
    ok, _, detalhe = p.enviar("34999000001", "olá",
                              {"token_ref": "TOKEN_OK", "phone_number_id": "pn-77"})
    assert not ok and "rede fora" in detalhe


def test_selecao_de_provider_por_ambiente(monkeypatch):
    whatsapp_service.definir_provider(None)
    monkeypatch.delenv("META_WHATSAPP_ACCESS_TOKEN", raising=False)
    assert isinstance(obter_provider(), SimuladoProvider)
    whatsapp_service.definir_provider(None)
    monkeypatch.setenv("META_WHATSAPP_ACCESS_TOKEN", "x")
    assert isinstance(obter_provider(), MetaCloudProvider)
    whatsapp_service.definir_provider(None)


class _SMTPFake:
    instancias = []

    def __init__(self, host, porta, timeout):
        self.host, self.porta = host, porta
        self.acoes = []
        _SMTPFake.instancias.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        self.acoes.append("starttls")

    def login(self, usuario, senha):
        self.acoes.append(("login", usuario))

    def sendmail(self, de, para, corpo):
        self.acoes.append(("sendmail", de, para))


def test_smtp_provider_envia_e_falha(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.exemplo.com")
    monkeypatch.setenv("SMTP_USER", "envio@exemplo.com")
    monkeypatch.setenv("SMTP_PASSWORD", "nao-logar")
    monkeypatch.setattr(email_service.smtplib, "SMTP", _SMTPFake)
    p = email_service.SMTPProvider()
    assert p.enviar("dest@x.com", "assunto", "<p>oi</p>") is True
    fake = _SMTPFake.instancias[-1]
    assert "starttls" in fake.acoes
    assert ("login", "envio@exemplo.com") in fake.acoes

    def smtp_quebrado(*a, **k):
        raise ConnectionError("smtp fora")
    monkeypatch.setattr(email_service.smtplib, "SMTP", smtp_quebrado)
    assert p.enviar("dest@x.com", "assunto", "<p>oi</p>") is False  # sem vazar exceção


def test_obter_email_provider_por_ambiente(monkeypatch):
    email_service.definir_email_provider(None)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert isinstance(email_service.obter_email_provider(), email_service.SimuladoEmailProvider)
    email_service.definir_email_provider(None)


def test_util_timezone_fallback_e_dia_fechado():
    class FakeDB:
        def execute(self, *a):
            class Cur:
                def fetchone(self):
                    return {"timezone": "Fuso/Inexistente"}
            return Cur()
    assert str(timezone_tenant(FakeDB(), 1)) == "America/Sao_Paulo"
    import datetime as dt
    cfg = {"dias_fechados": [6, "2027-12-25"]}
    assert dia_fechado(cfg, dt.date(2027, 12, 25))
    assert dia_fechado(cfg, dt.date(2027, 6, 20))        # domingo
    assert not dia_fechado(cfg, dt.date(2027, 6, 15))


def test_relatorios_barbeiros_e_auditoria(client, admin):
    from tests.conftest import cab, nova_barbearia
    b = nova_barbearia(client, admin)
    ag = client.post("/api/agendamentos", headers=cab(b["gerente"]), json={
        "cliente_id": b["cliente"], "barbeiro_id": b["barbeiro"],
        "inicio": "2027-06-15T10:00", "servico_ids": [b["corte"]]}).json()
    client.patch(f"/api/agendamentos/{ag['id']}/status?status=atendido", headers=cab(b["gerente"]))
    client.post(f"/api/agendamentos/{ag['id']}/fechar", headers=cab(b["gerente"]),
                json={"pagamentos": [{"forma": "pix"}]})
    desempenho = client.get("/api/relatorios/barbeiros?competencia=2027-06",
                            headers=cab(b["gerente"])).json()
    assert desempenho[0]["faturamento"] == 50.0
    assert desempenho[0]["comissoes"] >= 0
    kpis = client.get("/api/relatorios/indicadores?competencia=2027-06",
                      headers=cab(b["gerente"])).json()
    assert kpis["ticket_medio"] == 50.0
    trilha = client.get("/api/relatorios/auditoria?limite=10", headers=cab(b["gerente"])).json()
    assert any(a["acao"] == "fechamento" for a in trilha)


def test_campanha_aniversario_configuracao_e_bordas(client, admin):
    from tests.conftest import cab, nova_barbearia
    b = nova_barbearia(client, admin)
    g = cab(b["gerente"])
    assert client.put("/api/aniversario/campanha", headers=g,
                      json={"percentual": 150}).status_code == 422
    assert client.put("/api/aniversario/campanha", headers=g,
                      json={"percentual": 15, "validade_dias": 10}).status_code == 200
    cfg = client.get("/api/aniversario/campanha", headers=g).json()
    assert cfg["validade_dias"] == 10
    client.put("/api/aniversario/campanha", headers=g, json={"ativo": False, "percentual": 15})
    assert client.post("/api/aniversario/gerar?mes=5", headers=g).status_code == 422
    assert client.post("/api/aniversario/gerar?mes=13", headers=g).status_code == 422
    assert client.post("/api/aniversario/vouchers/999999/cancelar", headers=g).status_code == 404


@pytest.mark.parametrize("freq,payload", [
    ("semanal", {}), ("mensal", {"dia_mes": 40}), ("anual", {}), ("diaria", {"dia_semana": 1})])
def test_recorrencia_validacoes(client, barbearia, freq, payload):
    from tests.conftest import cab
    corpo = {"cliente_id": barbearia["cliente"], "barbeiro_id": barbearia["barbeiro"],
             "servico_id": barbearia["corte"], "frequencia": freq, "hora": "10:00", **payload}
    assert client.post("/api/recorrencias", headers=cab(barbearia["gerente"]),
                       json=corpo).status_code == 422
