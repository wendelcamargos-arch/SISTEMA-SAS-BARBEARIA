"""Rate limit distribuído: bloqueio, expiração e compartilhamento entre réplicas.

Roda contra Redis real quando REDIS_URL estiver definido; caso contrário os
testes de Redis são pulados (o fallback em memória é coberto em test_auth.py).
"""
import os
import time

import pytest

from app.ratelimit import BackendMemoria, BackendRedis, RateLimiter

REDIS_URL = os.environ.get("REDIS_URL", "")
precisa_redis = pytest.mark.skipif(not REDIS_URL, reason="REDIS_URL não definido")


def test_memoria_bloqueia_e_limpa():
    rl = RateLimiter(BackendMemoria(), janela=60, maximo=3, bloqueio=60)
    for _ in range(3):
        rl.registrar_falha("a@b.com", "1.1.1.1")
    assert rl.bloqueado("a@b.com", "1.1.1.1")
    assert not rl.bloqueado("a@b.com", "2.2.2.2")     # chave inclui o IP
    assert not rl.bloqueado("A@B.COM ", "2.2.2.2")
    rl.limpar("a@b.com", "1.1.1.1")
    assert not rl.bloqueado("a@b.com", "1.1.1.1")


def test_memoria_expira_bloqueio():
    rl = RateLimiter(BackendMemoria(), janela=60, maximo=2, bloqueio=1)
    rl.registrar_falha("x@y.com", "ip")
    rl.registrar_falha("x@y.com", "ip")
    assert rl.bloqueado("x@y.com", "ip")
    time.sleep(1.2)
    assert not rl.bloqueado("x@y.com", "ip")


@precisa_redis
def test_redis_bloqueia_e_expira():
    backend = BackendRedis(REDIS_URL)
    assert backend.saudavel()
    rl = RateLimiter(backend, janela=60, maximo=3, bloqueio=1)
    rl.limpar("r@t.com", "ip")
    for _ in range(3):
        rl.registrar_falha("r@t.com", "ip")
    assert rl.bloqueado("r@t.com", "ip")
    time.sleep(1.2)                                    # TTL do Redis expira o bloqueio
    assert not rl.bloqueado("r@t.com", "ip")


@precisa_redis
def test_redis_compartilha_entre_instancias():
    """Duas instâncias de limiter (réplicas simuladas) veem o mesmo estado."""
    replica_1 = RateLimiter(BackendRedis(REDIS_URL), janela=60, maximo=2, bloqueio=30)
    replica_2 = RateLimiter(BackendRedis(REDIS_URL), janela=60, maximo=2, bloqueio=30)
    replica_1.limpar("multi@r.com", "ip")
    replica_1.registrar_falha("multi@r.com", "ip")
    replica_2.registrar_falha("multi@r.com", "ip")     # 2ª falha em OUTRA réplica
    assert replica_1.bloqueado("multi@r.com", "ip")
    assert replica_2.bloqueado("multi@r.com", "ip")
    replica_2.limpar("multi@r.com", "ip")
    assert not replica_1.bloqueado("multi@r.com", "ip")


@precisa_redis
def test_login_bloqueado_via_redis(client, barbearia):
    from app.ratelimit import definir_limiter
    backend = BackendRedis(REDIS_URL)
    definir_limiter(RateLimiter(backend))
    email = f"gerente@{barbearia['slug']}.com"
    backend.limpar(RateLimiter.chave(email, "testclient"))
    for _ in range(5):
        assert client.post("/api/auth/login",
                           json={"email": email, "senha": "errada"}).status_code == 401
    assert client.post("/api/auth/login",
                       json={"email": email, "senha": "senha-gerente-123"}).status_code == 429
    backend.limpar(RateLimiter.chave(email, "testclient"))
