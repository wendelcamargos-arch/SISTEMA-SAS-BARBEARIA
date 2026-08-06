"""Ramos de validação e erro dos módulos críticos (auth, tenancy, financeiro,
whatsapp) — casos reais de rejeição que a operação encontra no dia a dia."""
import pytest

from app.auth import verificar_senha
from app.money import D
from app.whatsapp_service import link_wame
from tests.conftest import cab, nova_barbearia


def test_hash_legado_sha256_ainda_verifica():
    import hashlib
    legado = "abcd$" + hashlib.sha256(("abcd" + "senha123").encode()).hexdigest()
    assert verificar_senha("senha123", legado)
    assert not verificar_senha("errada", legado)
    assert not verificar_senha("x", "hash-sem-cifrao")
    assert not verificar_senha("x", "$2b$malformado")


def test_link_wame_normaliza_ddi():
    assert link_wame("34999000001", "oi").startswith("https://wa.me/5534999000001?")
    assert link_wame("5534999000001", "oi").startswith("https://wa.me/5534999000001?")


def test_validacoes_de_cadastro(client, barbearia):
    g = cab(barbearia["gerente"])
    assert client.post("/api/clientes", headers=g, json={
        "nome": "X", "telefone": "123"}).status_code == 422          # telefone curto
    assert client.post("/api/clientes", headers=g, json={
        "nome": "X", "telefone": "34999000009", "aniversario": "40/40"}).status_code == 422
    client.post("/api/clientes", headers=g, json={
        "nome": "A", "telefone": "34999000010", "cpf": "390.533.447-05"})
    assert client.post("/api/clientes", headers=g, json={
        "nome": "B", "telefone": "34999000011", "cpf": "39053344705"}).status_code == 409
    hist = client.get(f"/api/clientes/{barbearia['cliente']}/historico", headers=g).json()
    assert hist["cliente"]["id"] == barbearia["cliente"]


def test_validacoes_barbeiros_e_bloqueios(client, barbearia):
    g = cab(barbearia["gerente"])
    assert client.post("/api/barbeiros", headers=g, json={
        "nome": "X", "modelo": "franquia"}).status_code == 422
    assert client.put("/api/barbeiros/999999", headers=g, json={"nome": "X"}).status_code == 404
    r = client.put(f"/api/barbeiros/{barbearia['barbeiro']}", headers=g, json={
        "nome": "Renomeado", "percentual_comissao": 45})
    assert r.status_code == 200
    assert client.post(f"/api/barbeiros/{barbearia['barbeiro']}/bloqueios", headers=g, json={
        "inicio": "2027-06-15T10:00", "fim": "2027-06-15T09:00"}).status_code == 422
    bid = client.post(f"/api/barbeiros/{barbearia['barbeiro']}/bloqueios", headers=g, json={
        "inicio": "2027-12-01T10:00", "fim": "2027-12-01T12:00", "motivo": "curso"}).json()["id"]
    assert len(client.get(f"/api/barbeiros/{barbearia['barbeiro']}/bloqueios", headers=g).json()) == 1
    assert client.delete(f"/api/barbeiros/bloqueios/{bid}", headers=g).status_code == 200
    assert client.post(f"/api/barbeiros/{barbearia['barbeiro']}/cobrar-aluguel?competencia=2027-01",
                       headers=g).status_code == 422    # modelo comissão não cobra aluguel


def test_validacoes_caixa(client, admin):
    b = nova_barbearia(client, admin)
    g = cab(b["gerente"])
    assert client.post("/api/caixa", headers=g, json={
        "data": "2027-01-01", "tipo": "transferencia", "categoria": "outro",
        "descricao": "x", "valor": 1}).status_code == 422
    assert client.post("/api/caixa", headers=g, json={
        "data": "2027-01-01", "tipo": "saida", "categoria": "comissao_indevida",
        "descricao": "x", "valor": 1}).status_code == 422
    assert client.post("/api/caixa", headers=g, json={
        "data": "2027-01-01", "tipo": "saida", "categoria": "outro",
        "descricao": "x", "valor": 0}).status_code == 422
    assert client.post("/api/caixa/sessao/reforco", headers=g,
                       json={"valor": 10}).status_code == 409       # sem sessão aberta
    assert client.post("/api/caixa/sessao/fechar", headers=g,
                       json={"valor_contado": 0}).status_code == 409
    lanc = client.post("/api/caixa", headers=g, json={
        "data": "2027-01-01", "tipo": "saida", "categoria": "outro",
        "descricao": "avulso", "valor": 5}).json()["id"]
    assert client.delete(f"/api/caixa/{lanc}", headers=g).status_code == 200
    assert client.delete(f"/api/caixa/{lanc}", headers=g).status_code == 404


def test_validacoes_tenants_e_settings(client, admin, barbearia):
    g = cab(barbearia["gerente"])
    assert client.patch("/api/tenants/meu/settings", headers=g,
                        json={"politica_recorrencia": "adivinhar"}).status_code == 422
    assert client.patch("/api/tenants/meu", headers=g, json={}).json()["mensagem"] == "Nada para atualizar"
    assert client.post("/api/tenants/meu/usuarios", headers=g, json={
        "nome": "X", "email": "curta@x.com", "senha": "123", "papel": "recepcao"}).status_code == 422
    assert client.post("/api/tenants/meu/usuarios", headers=g, json={
        "nome": "X", "email": "dono@x.com", "senha": "12345678", "papel": "dono"}).status_code == 422
    lista = client.get("/api/tenants", headers=cab(admin)).json()
    assert any(t["slug"] == barbearia["slug"] for t in lista)
    assert client.post("/api/tenants", headers=cab(admin), json={
        "nome": "Dup", "slug": barbearia["slug"],
        "gerente_nome": "X", "gerente_email": "novo@dup.com",
        "gerente_senha": "12345678"}).status_code == 409


def test_validacoes_whatsapp_config_e_resposta(client, barbearia):
    g = cab(barbearia["gerente"])
    assert client.put("/api/whatsapp/config", headers=g, json={
        "phone_number_id": "p1", "status": "ligado"}).status_code == 422
    assert client.put("/api/whatsapp/config", headers=g, json={
        "phone_number_id": "p1", "token_ref": "não é var!"}).status_code == 422
    assert client.post("/api/whatsapp/999999/resposta", headers=g,
                       json={"resposta": "confirmar"}).status_code == 404
    assert client.post("/api/whatsapp/1/resposta", headers=g,
                       json={"resposta": "talvez"}).status_code == 422
    corpo_invalido = client.post("/api/whatsapp/webhook", content=b"nao-e-json")
    assert corpo_invalido.status_code == 422


def test_validacoes_financeiro(client, admin):
    b = nova_barbearia(client, admin)
    g = cab(b["gerente"])
    ag = client.post("/api/agendamentos", headers=g, json={
        "cliente_id": b["cliente"], "barbeiro_id": b["barbeiro"],
        "inicio": "2027-06-15T10:00", "servico_ids": [b["corte"]]}).json()
    client.patch(f"/api/agendamentos/{ag['id']}/status?status=atendido", headers=g)
    assert client.post(f"/api/agendamentos/{ag['id']}/fechar", headers=g,
                       json={"pagamentos": []}).status_code == 422
    assert client.post(f"/api/agendamentos/{ag['id']}/fechar", headers=g,
                       json={"pagamentos": [{"forma": "cheque"}]}).status_code == 422
    assert client.post(f"/api/agendamentos/{ag['id']}/fechar", headers=g,
                       json={"pagamentos": [{"forma": "pix", "valor": -1}]}).status_code == 422
    assert client.post(f"/api/agendamentos/{ag['id']}/estorno?payment_id=999",
                       headers=g).status_code == 404
    assert client.post(f"/api/agendamentos/{ag['id']}/fechar", headers=g,
                       json={"pagamentos": [{"forma": "pix"}],
                             "voucher_codigo": "NIVER-INEXISTENTE"}).status_code == 404
    # reagendamento inválido e status inexistente
    assert client.put(f"/api/agendamentos/{ag['id']}", headers=g,
                      json={"inicio": "data-quebrada"}).status_code == 422
    assert client.patch(f"/api/agendamentos/{ag['id']}/status?status=pago",
                        headers=g).status_code == 422
    assert client.patch("/api/agendamentos/999999/status?status=cancelado",
                        headers=g).status_code == 404


def test_health_checks(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    ready = client.get("/health/ready").json()
    assert ready["status"] == "ok" and "rate_limit" in ready


def test_paginas_publicas(client):
    for caminho, trecho in [("/", "DRE Gerencial"), ("/privacidade", "LGPD"),
                            ("/termos", "gerencial"), ("/app", "SISTEMA")]:
        r = client.get(caminho)
        assert r.status_code == 200
        assert trecho.lower() in r.text.lower(), f"{caminho} sem '{trecho}'"


def test_dinheiro_helper_rejeita_none_e_decimal_passa():
    assert D(None) == 0
    assert D(D("1.5")) == D("1.5")
    with pytest.raises(Exception):
        D("não-numérico")
