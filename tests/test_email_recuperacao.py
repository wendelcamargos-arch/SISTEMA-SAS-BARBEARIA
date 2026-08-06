"""Recuperação de senha por e-mail: provider, link white label, uso único."""
from app.email_service import SimuladoEmailProvider, corpo_recuperacao
from tests.conftest import nova_barbearia


def test_email_enviado_com_link_white_label(client, admin, email_provider):
    b = nova_barbearia(client, admin)
    email = f"gerente@{b['slug']}.com"
    r = client.post("/api/auth/recuperar", json={"email": email})
    assert r.status_code == 200
    assert len(email_provider.enviados) == 1
    enviado = email_provider.enviados[0]
    assert enviado["para"] == email
    assert f"Barbearia {b['slug']}" in enviado["assunto"]        # white label por tenant
    assert "/app#redefinir=" in enviado["corpo"]

    # o token do e-mail funciona e é de uso único
    token = enviado["corpo"].split("/app#redefinir=")[1].split('"')[0]
    assert client.post("/api/auth/redefinir", json={
        "token": token, "nova_senha": "senha-nova-por-email"}).status_code == 200
    assert client.post("/api/auth/redefinir", json={
        "token": token, "nova_senha": "outra-tentativa-123"}).status_code == 422
    assert client.post("/api/auth/login", json={
        "email": email, "senha": "senha-nova-por-email"}).status_code == 200


def test_email_inexistente_nao_envia_mas_responde_igual(client, email_provider):
    r = client.post("/api/auth/recuperar", json={"email": "ninguem@nada.com"})
    assert r.status_code == 200
    assert email_provider.enviados == []
    assert "instruções" in r.json()["mensagem"]


def test_corpo_recuperacao_estrutura():
    assunto, corpo = corpo_recuperacao("Barbearia X", "João Silva", "http://x/link")
    assert assunto.startswith("Barbearia X")
    assert "João" in corpo and "http://x/link" in corpo
    assert "uma vez" in corpo                                     # aviso de uso único


def test_provider_simulado_nao_toca_rede():
    p = SimuladoEmailProvider()
    assert p.enviar("a@b.com", "t", "<p>x</p>") is True
    assert p.enviados[0]["para"] == "a@b.com"
