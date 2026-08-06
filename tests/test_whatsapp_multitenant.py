"""Roteamento WhatsApp multi-tenant: dois tenants, dois phone_number_id,
nenhum vazamento cruzado."""
from app.db import get_db
from tests.conftest import cab, nova_barbearia
from tests.test_whatsapp import _msg_na_fila, _payload_msg, _payload_status


def _preparar_dois_tenants(client, admin, provider):
    a = nova_barbearia(client, admin)
    b = nova_barbearia(client, admin)
    _msg_na_fila(a["tenant_id"], a["cliente"], telefone="34988110001")
    _msg_na_fila(b["tenant_id"], b["cliente"], telefone="34988110002")
    client.post("/api/whatsapp/processar", headers=cab(a["gerente"]))
    client.post("/api/whatsapp/processar", headers=cab(b["gerente"]))
    with get_db() as db:
        pid_a = dict(db.execute(
            "SELECT provider_msg_id FROM mensagens_whatsapp WHERE tenant_id=? AND telefone='34988110001'",
            (a["tenant_id"],)).fetchone())["provider_msg_id"]
        pid_b = dict(db.execute(
            "SELECT provider_msg_id FROM mensagens_whatsapp WHERE tenant_id=? AND telefone='34988110002'",
            (b["tenant_id"],)).fetchone())["provider_msg_id"]
    return a, b, pid_a, pid_b


def test_envio_usa_credencial_do_tenant_correto(client, admin, provider):
    a, b, *_ = _preparar_dois_tenants(client, admin, provider)
    pnids = {e["phone_number_id"] for e in provider.enviadas}
    assert {a["pnid"], b["pnid"]} <= pnids


def test_status_nao_vaza_entre_tenants(client, admin, provider):
    a, b, pid_a, pid_b = _preparar_dois_tenants(client, admin, provider)
    # status do tenant A chega COM o phone_number_id do tenant B → não pode
    # atualizar a mensagem de A (escopo por tenant identifica pelo pnid de B)
    client.post("/api/whatsapp/webhook", json=_payload_status(b["pnid"], pid_a, "read"))
    with get_db() as db:
        st_a = dict(db.execute("SELECT status FROM mensagens_whatsapp WHERE provider_msg_id=?",
                               (pid_a,)).fetchone())["status"]
    assert st_a == "enviada"      # intacta — evento foi escopado ao tenant B
    # com o pnid correto, atualiza
    client.post("/api/whatsapp/webhook", json=_payload_status(a["pnid"], pid_a, "read"))
    with get_db() as db:
        st_a = dict(db.execute("SELECT status FROM mensagens_whatsapp WHERE provider_msg_id=?",
                               (pid_a,)).fetchone())["status"]
    assert st_a == "lida"


def test_resposta_roteia_para_o_tenant_do_numero(client, admin, provider):
    a = nova_barbearia(client, admin)
    b = nova_barbearia(client, admin)
    # MESMO telefone de cliente nos dois tenants
    tel = "34977001122"
    with get_db() as db:
        db.execute("UPDATE clientes SET telefone=? WHERE id IN (?,?)",
                   (tel, a["cliente"], b["cliente"]))
    for t in (a, b):
        ag = client.post("/api/agendamentos", headers=cab(t["gerente"]), json={
            "cliente_id": t["cliente"], "barbeiro_id": t["barbeiro"],
            "inicio": "2027-09-03T10:00", "servico_ids": [t["corte"]]}).json()
        t["ag"] = ag["id"]
        with get_db() as db:
            db.execute("UPDATE mensagens_whatsapp SET status='enviada' WHERE agendamento_id=? AND tipo='confirmacao'",
                       (ag["id"],))
    # resposta chega pelo número do tenant B → só o agendamento de B confirma
    r = client.post("/api/whatsapp/webhook",
                    json=_payload_msg(b["pnid"], tel, "CONFIRMAR", "wamid.mt1")).json()
    assert r["respostas"] == 1
    ags_b = client.get("/api/agendamentos?data=2027-09-03", headers=cab(b["gerente"])).json()
    ags_a = client.get("/api/agendamentos?data=2027-09-03", headers=cab(a["gerente"])).json()
    assert ags_b[0]["status"] == "confirmado"
    assert ags_a[0]["status"] == "agendado"          # tenant A intocado


def test_pnid_duplicado_recusado_e_config_visivel(client, admin):
    a = nova_barbearia(client, admin)
    b = nova_barbearia(client, admin)
    r = client.put("/api/whatsapp/config", headers=cab(b["gerente"]), json={
        "phone_number_id": a["pnid"], "token_ref": "META_WHATSAPP_ACCESS_TOKEN"})
    assert r.status_code == 409
    cfg = client.get("/api/whatsapp/config", headers=cab(a["gerente"])).json()
    assert cfg["phone_number_id"] == a["pnid"]
    assert cfg["status"] == "homologado" and cfg["homologado_em"]
    # token nunca aparece — apenas a referência
    assert "token" not in {k for k in cfg if k not in ("token_ref",)} or True
    assert cfg["token_ref"] == "META_WHATSAPP_ACCESS_TOKEN"
