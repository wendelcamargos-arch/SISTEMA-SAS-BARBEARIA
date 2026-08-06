"""Rate limit de login — Redis por padrão, com fallback em memória.

Backend Redis (REDIS_URL): funciona com múltiplas réplicas — contadores e
bloqueios compartilhados, com expiração nativa (TTL). Chave normalizada por
e-mail (minúsculo) + IP.

Fallback em memória: apenas desenvolvimento/teste unitário sem Redis; em
produção a aplicação exige REDIS_URL (app/main.py). Documentado em
docs/SECURITY.md. Nenhuma credencial é registrada em log.
"""
import os
import time

MAX_TENTATIVAS = 5
JANELA_SEG = 60 * 15
BLOQUEIO_SEG = 60 * 15


class BackendMemoria:
    def __init__(self):
        self._tentativas: dict[str, list[float]] = {}
        self._bloqueios: dict[str, float] = {}

    def registrar_falha(self, chave: str, janela: int, maximo: int, bloqueio: int) -> None:
        agora = time.time()
        hist = [t for t in self._tentativas.get(chave, []) if agora - t < janela]
        hist.append(agora)
        self._tentativas[chave] = hist
        if len(hist) >= maximo:
            self._bloqueios[chave] = agora + bloqueio

    def bloqueado(self, chave: str) -> bool:
        ate = self._bloqueios.get(chave, 0)
        if ate and time.time() < ate:
            return True
        if ate:
            self._bloqueios.pop(chave, None)
            self._tentativas.pop(chave, None)
        return False

    def limpar(self, chave: str) -> None:
        self._tentativas.pop(chave, None)
        self._bloqueios.pop(chave, None)

    def saudavel(self) -> bool:
        return True


class BackendRedis:
    def __init__(self, url: str):
        import redis
        self._r = redis.Redis.from_url(url, decode_responses=True, socket_timeout=3)

    def registrar_falha(self, chave: str, janela: int, maximo: int, bloqueio: int) -> None:
        k = f"rl:tent:{chave}"
        atual = self._r.incr(k)
        if atual == 1:
            self._r.expire(k, janela)
        if atual >= maximo:
            self._r.set(f"rl:bloq:{chave}", "1", ex=bloqueio)

    def bloqueado(self, chave: str) -> bool:
        return bool(self._r.exists(f"rl:bloq:{chave}"))

    def limpar(self, chave: str) -> None:
        self._r.delete(f"rl:tent:{chave}", f"rl:bloq:{chave}")

    def saudavel(self) -> bool:
        try:
            return bool(self._r.ping())
        except Exception:
            return False


class RateLimiter:
    def __init__(self, backend=None, janela=JANELA_SEG, maximo=MAX_TENTATIVAS, bloqueio=BLOQUEIO_SEG):
        self.backend = backend or criar_backend()
        self.janela, self.maximo, self.bloqueio = janela, maximo, bloqueio

    @staticmethod
    def chave(email: str, ip: str) -> str:
        return f"{email.lower().strip()}|{ip or '?'}"

    def registrar_falha(self, email: str, ip: str) -> None:
        self.backend.registrar_falha(self.chave(email, ip), self.janela, self.maximo, self.bloqueio)

    def bloqueado(self, email: str, ip: str) -> bool:
        return self.backend.bloqueado(self.chave(email, ip))

    def limpar(self, email: str, ip: str) -> None:
        self.backend.limpar(self.chave(email, ip))


def criar_backend():
    url = os.environ.get("REDIS_URL", "")
    if url:
        backend = BackendRedis(url)
        if backend.saudavel():
            return backend
        if os.environ.get("APP_ENV", "development") == "production":
            raise RuntimeError("REDIS_URL configurada mas Redis inacessível")
    elif os.environ.get("APP_ENV", "development") == "production":
        raise RuntimeError("REDIS_URL é obrigatória em produção (rate limit distribuído)")
    return BackendMemoria()


_limiter: RateLimiter | None = None


def obter_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter


def definir_limiter(limiter: RateLimiter | None) -> None:
    """Injeção para testes."""
    global _limiter
    _limiter = limiter
