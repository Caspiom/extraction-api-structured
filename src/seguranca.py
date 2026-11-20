"""Autenticacao por chave de API + limite de requisicoes, ANTES de expor a API.

Decisoes (e o que cada uma NAO cobre, ver README):
- Falha FECHADA: sem `EXTRACTION_API_KEYS` configurada o /extract responde 503, nunca aberto "por esquecimento".
  Para desenvolvimento local o opt-out e explicito: `AUTH_DISABLED=1`.
- Chaves comparadas com `hmac.compare_digest` (tempo constante) e com no minimo 16 caracteres.
- Limite por CHAVE (nao por IP: `X-Forwarded-For` e forjavel), janela deslizante. Tentativas com chave invalida
  tem limitador PROPRIO por cliente, para que um atacante nao esgote a cota de uma chave valida nem force
  tentativas ilimitadas.
- Estado em memoria, por processo: com varios workers/replicas o limite efetivo e N x o configurado.
"""
from __future__ import annotations

import hmac
import os
import threading
import time
from collections import deque
from typing import Callable

from fastapi import HTTPException, Request

MIN_KEY_LEN = 16
MAX_BODY_BYTES = 100_000  # 20.000 chars x ate 4 bytes (UTF-8) + folga do JSON
MAX_TRACKED = 10_000  # teto de chaves de limitador (anti-crescimento por IPs aleatorios)


class SlidingWindow:
    """No maximo `limit` eventos por `window` segundos, por chave. `allow` devolve (ok, retry_after_s)."""

    def __init__(self, limit: int, window: float, clock: Callable[[], float] = time.monotonic):
        if limit < 1 or window <= 0:
            raise ValueError("limit >= 1 e window > 0")
        self.limit, self.window, self.clock = limit, window, clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, float]:
        now = self.clock()
        with self._lock:
            if len(self._hits) >= MAX_TRACKED and key not in self._hits:
                self._prune(now)
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False, round(q[0] + self.window - now, 3)
            q.append(now)
            return True, 0.0

    def _prune(self, now: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - self.window]:
            del self._hits[k]


def _env_int(nome: str, padrao: int) -> int:
    try:
        v = int(os.getenv(nome, ""))
        return v if v >= 1 else padrao
    except ValueError:
        return padrao


class Estado:
    """Limitadores do processo. `reset()` recria (testes e mudanca de config)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.reset()

    def reset(self) -> None:
        self.por_chave = SlidingWindow(_env_int("RATE_LIMIT_PER_MIN", 30), 60.0, self.clock)
        self.falhas = SlidingWindow(_env_int("AUTH_FAIL_PER_MIN", 10), 60.0, self.clock)


estado = Estado()


def chaves_configuradas() -> list[str]:
    bruto = os.getenv("EXTRACTION_API_KEYS", "")
    return [k for k in (p.strip() for p in bruto.split(",")) if len(k) >= MIN_KEY_LEN]


def _chave_valida(recebida: str, validas: list[str]) -> str | None:
    """Devolve a chave valida igual a recebida. Percorre TODAS (sem curto-circuito) e usa tempo constante."""
    achada = None
    for k in validas:
        if hmac.compare_digest(recebida.encode(), k.encode()):
            achada = k
    return achada


def exigir_acesso(request: Request) -> None:
    """Dependencia do FastAPI: 503 (sem config) -> 401 -> 429. Roda antes da VALIDACAO do corpo (nao antes da leitura:
    o FastAPI le o corpo antes das dependencias; quem limita o tamanho e `LimiteDeCorpo`)."""
    if os.getenv("AUTH_DISABLED") == "1":
        return
    validas = chaves_configuradas()
    if not validas:
        raise HTTPException(503, "autenticacao nao configurada no servidor")
    cliente = request.client.host if request.client else "?"
    recebida = request.headers.get("x-api-key", "")
    chave = _chave_valida(recebida, validas) if recebida else None
    if chave is None:
        ok, espera = estado.falhas.allow(cliente)
        if not ok:
            raise HTTPException(429, "muitas tentativas invalidas", headers={"Retry-After": str(int(espera) + 1)})
        raise HTTPException(401, "nao autorizado")
    ok, espera = estado.por_chave.allow(chave)
    if not ok:
        raise HTTPException(429, "limite de requisicoes excedido", headers={"Retry-After": str(int(espera) + 1)})


class LimiteDeCorpo:
    """Middleware ASGI: 413 se `Content-Length` > limite, e tambem para corpo sem Content-Length (chunked), contando
    os bytes conforme chegam. Fica ANTES do roteamento porque o FastAPI le o corpo inteiro antes de rodar
    dependencias: checar tamanho em `Depends` nao evita a leitura. Ao estourar no meio do fluxo, envia o 413 e
    entrega `http.disconnect` ao app (o FastAPI engole excecoes da leitura do corpo e viraria 400); tudo que o app
    tentar enviar depois e descartado."""

    def __init__(self, app, limite: int | None = None):
        self.app = app
        self.limite = limite

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limite = self.limite if self.limite is not None else MAX_BODY_BYTES
        cl = dict(scope["headers"]).get(b"content-length", b"")
        if cl.isdigit() and int(cl) > limite:
            return await self._413(send)
        total = 0
        estado = {"iniciou": False, "cortado": False}

        async def receive_contando():
            nonlocal total
            if estado["cortado"]:
                return {"type": "http.disconnect"}
            msg = await receive()
            if msg["type"] == "http.request":
                total += len(msg.get("body", b""))
                if total > limite and not estado["iniciou"]:
                    estado["cortado"] = True
                    await self._413(send)
                    return {"type": "http.disconnect"}
            return msg

        async def send_marcando(msg):
            if estado["cortado"]:
                return
            if msg["type"] == "http.response.start":
                estado["iniciou"] = True
            await send(msg)

        await self.app(scope, receive_contando, send_marcando)

    @staticmethod
    async def _413(send):
        corpo = b'{"detail":"corpo grande demais"}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(corpo)).encode())]})
        await send({"type": "http.response.body", "body": corpo})
