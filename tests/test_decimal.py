"""Precisão financeira: Decimal em todo cálculo monetário (FASE financeira).

Cobre os nove cenários exigidos: soma exata, comissão, desconto, pagamento
dividido, rateio, custo médio, estorno, fechamento de caixa e DRE Gerencial —
mais o teste de guarda contra float no caminho monetário.
"""
from decimal import Decimal

from app.money import D, aplicar_percentual, dinheiro, percentual
from tests.conftest import cab, nova_barbearia


def test_soma_exata_sem_erro_binario():
    assert Decimal("0.10") + Decimal("0.20") == Decimal("0.30")
    assert D(0.10) + D(0.20) == Decimal("0.30")          # D(float) passa por str
    assert dinheiro("0.105") == Decimal("0.11")           # ROUND_HALF_UP explícito
    assert dinheiro("0.104") == Decimal("0.10")
    assert percentual("33.33333") == Decimal("33.3333")


def test_comissao_percentual_meio_centavo():
    # 33.33% de R$ 10,01 = 3.336333 → 3.34 (HALF_UP)
    assert aplicar_percentual("10.01", "33.33") == Decimal("3.34")
    assert aplicar_percentual("50.00", "50") == Decimal("25.00")


def _atendido(client, b, hora="10:00"):
    ag = client.post("/api/agendamentos", headers=cab(b["gerente"]), json={
        "cliente_id": b["cliente"], "barbeiro_id": b["barbeiro"],
        "inicio": f"2027-06-15T{hora}", "servico_ids": [b["corte"]]}).json()
    client.patch(f"/api/agendamentos/{ag['id']}/status?status=atendido", headers=cab(b["gerente"]))
    return ag


def test_desconto_e_fechamento_com_centavos(client, admin):
    b = nova_barbearia(client, admin)
    # serviço com preço quebrado: 49.99
    servico = client.post("/api/servicos", headers=cab(b["gerente"]),
                          json={"nome": "Degradê", "preco": "49.99", "duracao_min": 30}).json()["id"]
    ag = client.post("/api/agendamentos", headers=cab(b["gerente"]), json={
        "cliente_id": b["cliente"], "barbeiro_id": b["barbeiro"],
        "inicio": "2027-06-15T09:00", "servico_ids": [servico]}).json()
    client.patch(f"/api/agendamentos/{ag['id']}/status?status=atendido", headers=cab(b["gerente"]))
    r = client.post(f"/api/agendamentos/{ag['id']}/fechar", headers=cab(b["gerente"]),
                    json={"pagamentos": [{"forma": "pix"}], "desconto": "0.10"}).json()
    assert r["recebido"] == 49.89                    # 49.99 - 0.10 exato
    assert r["comissao_barbeiro"] == 24.95           # 50% de 49.89 = 24.945 → HALF_UP


def test_pagamento_dividido_rateio_sem_sobra(client, admin):
    b = nova_barbearia(client, admin)
    ag = _atendido(client, b)
    r = client.post(f"/api/agendamentos/{ag['id']}/fechar", headers=cab(b["gerente"]),
                    json={"pagamentos": [{"forma": "dinheiro", "valor": "16.67"},
                                          {"forma": "debito", "valor": "16.67"},
                                          {"forma": "pix"}]}).json()   # pix = restante exato
    assert r["status"] == "pago"
    pagamentos = client.get(f"/api/agendamentos/{ag['id']}/pagamentos",
                            headers=cab(b["gerente"])).json()
    assert sorted(p["valor"] for p in pagamentos) == [16.66, 16.67, 16.67]
    assert round(sum(p["valor"] for p in pagamentos), 2) == 50.0


def test_custo_medio_quatro_casas(client, admin):
    b = nova_barbearia(client, admin)
    pid = client.post("/api/estoque", headers=cab(b["gerente"]), json={
        "nome": "Cera", "custo": "10.00", "preco_venda": "30.00"}).json()["id"]
    g = cab(b["gerente"])
    client.post(f"/api/estoque/{pid}/movimento", headers=g,
                json={"tipo": "compra", "quantidade": 3, "valor_unitario": "10.00"})
    r = client.post(f"/api/estoque/{pid}/movimento", headers=g,
                    json={"tipo": "compra", "quantidade": 3, "valor_unitario": "10.01"}).json()
    # (3*10 + 3*10.01)/6 = 10.005 → NUMERIC(_,4) mantém a precisão
    assert r["custo_medio"] == 10.005


def test_estorno_e_caixa_exatos(client, admin):
    b = nova_barbearia(client, admin)
    ag = _atendido(client, b)
    client.post(f"/api/agendamentos/{ag['id']}/fechar", headers=cab(b["gerente"]),
                json={"pagamentos": [{"forma": "pix", "valor": "0.30"}]})
    pg = client.get(f"/api/agendamentos/{ag['id']}/pagamentos", headers=cab(b["gerente"])).json()[0]
    r = client.post(f"/api/agendamentos/{ag['id']}/estorno?payment_id={pg['id']}",
                    headers=cab(b["gerente"])).json()
    assert r["valor"] == 0.3
    caixa = client.get("/api/caixa", headers=cab(b["gerente"])).json()
    estornos = [lanc for lanc in caixa["lancamentos"] if lanc["categoria"] == "estorno"]
    assert estornos[0]["valor"] == 0.3


def test_fechamento_de_caixa_com_divergencia_de_um_centavo(client, admin):
    b = nova_barbearia(client, admin)
    client.post("/api/caixa/sessao/abrir", headers=cab(b["gerente"]),
                json={"valor_inicial": "10.10"})
    client.post("/api/caixa/sessao/reforco", headers=cab(b["gerente"]), json={"valor": "0.20"})
    r = client.post("/api/caixa/sessao/fechar", headers=cab(b["gerente"]),
                    json={"valor_contado": "10.29"}).json()
    assert r["valor_esperado_dinheiro"] == 10.3      # 10.10 + 0.20 exato
    assert r["divergencia"] == -0.01


def test_dre_gerencial_sem_residuo_float(client, admin):
    b = nova_barbearia(client, admin)
    hoje = client.get("/api/caixa", headers=cab(b["gerente"])).json()["periodo"]["fim"]
    for valor in ("0.10", "0.20", "0.30"):
        client.post("/api/caixa", headers=cab(b["gerente"]), json={
            "data": hoje, "tipo": "entrada", "categoria": "outro",
            "descricao": f"ajuste {valor}", "valor": valor})
    dre = client.get("/api/relatorios/dre", headers=cab(b["gerente"])).json()
    assert dre["tipo"] == "DRE Gerencial"
    assert "não substitui escrituração contábil" in dre["aviso"]
    assert dre["detalhe_receita"]["outras"] == 0.6   # 0.10+0.20+0.30 exato
    assert dre["lucro_liquido"] == 0.6


def test_guarda_sem_float_em_calculo_monetario():
    """Varredura: nenhum round(<expressão monetária>, 2) restante nos routers
    financeiros — todo arredondamento passa por app.money."""
    import re
    from pathlib import Path
    financeiros = ["app/routers/agendamentos.py", "app/routers/caixa.py",
                   "app/routers/estoque.py", "app/routers/relatorios.py",
                   "app/routers/aniversario.py", "app/money.py"]
    for arquivo in financeiros:
        conteudo = Path(arquivo).read_text()
        assert not re.search(r"round\([^)]*,\s*[24]\)", conteudo), \
            f"round() monetário proibido em {arquivo}"
        assert " float(" not in conteudo, f"float() proibido em {arquivo}"
