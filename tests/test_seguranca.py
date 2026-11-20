import logging

import pytest
from conftest import CHAVE, OUTRA
from fastapi.testclient import TestClient

from src import seguranca
from src.app import app
from src.seguranca import SlidingWindow

OK_TXT = "NF-e nº 1\nEmitente: Mar Azul LTDA\nCNPJ: 11.222.333/0001-81\nData de emissão: 03/11/2026\nValor total: R$ 10,00"


def post(headers=None, json=None, c=None):
    c = c or TestClient(app)
    return c.post("/extract", json=json if json is not None else {"text": OK_TXT}, headers=headers or {})


# --- janela deslizante, com relogio falso ------------------------------------------------------------
class Relogio:
    t = 100.0

    def __call__(self):
        return self.t


def test_janela_deslizante_bloqueia_no_limite_e_libera_na_borda_exata():
    r = Relogio()
    w = SlidingWindow(3, 60.0, r)
    assert [w.allow("a")[0] for _ in range(3)] == [True, True, True]
    ok, espera = w.allow("a")
    assert not ok and espera == 60.0
    r.t += 59.999
    assert not w.allow("a")[0]
    r.t += 0.001  # exatamente window depois do 1o evento: o evento sai da janela
    assert w.allow("a")[0]


def test_retry_after_e_o_tempo_ate_o_evento_mais_antigo_sair():
    r = Relogio()
    w = SlidingWindow(2, 60.0, r)
    w.allow("a")
    r.t += 10
    w.allow("a")
    r.t += 5  # 1o evento tem 15s: faltam 45s (nao a janela inteira, nem o 2o evento)
    assert w.allow("a") == (False, 45.0)


def test_janela_e_deslizante_nao_fixa():
    r = Relogio()
    w = SlidingWindow(2, 10.0, r)
    w.allow("a")
    r.t += 6
    w.allow("a")
    r.t += 5  # o 1o saiu (11s), o 2o ainda conta (5s): so 1 vaga
    assert w.allow("a")[0] and not w.allow("a")[0]


def test_chaves_independentes_e_validacao_de_config():
    w = SlidingWindow(1, 60.0, Relogio())
    assert w.allow("a")[0] and w.allow("b")[0] and not w.allow("a")[0]
    for args in ((0, 60.0), (1, 0), (1, -1)):
        with pytest.raises(ValueError):
            SlidingWindow(*args)


def test_limitador_nao_cresce_sem_limite(monkeypatch):
    monkeypatch.setattr(seguranca, "MAX_TRACKED", 50)
    r = Relogio()
    w = SlidingWindow(1, 10.0, r)
    for i in range(50):
        w.allow(f"ip{i}")
    r.t += 11
    for i in range(50, 200):
        w.allow(f"ip{i}")
    assert len(w._hits) <= 150  # as expiradas foram podadas ao encher


# --- autenticacao ------------------------------------------------------------------------------------
def test_sem_chave_ou_chave_errada_da_401_generico():
    for h in ({}, {"x-api-key": "errada-errada-errada"}, {"x-api-key": ""}):
        r = post(h)
        assert r.status_code == 401 and r.json() == {"detail": "nao autorizado"}


def test_prefixo_ou_sufixo_da_chave_valida_nao_autentica():
    assert post({"x-api-key": CHAVE[:-1]}).status_code == 401
    assert post({"x-api-key": CHAVE + "x"}).status_code == 401
    assert post({"x-api-key": CHAVE.upper()}).status_code == 401


def test_chaves_validas_funcionam_e_a_segunda_tambem():
    assert post({"x-api-key": CHAVE}).status_code == 200 and post({"x-api-key": OUTRA}).status_code == 200


def test_auth_vem_antes_da_validacao_do_corpo():
    assert post({}, json={"text": ""}).status_code == 401  # corpo invalido (422) nao vaza antes do 401
    assert post({"x-api-key": CHAVE}, json={"text": ""}).status_code == 422


def test_sem_config_falha_fechada_503(monkeypatch):
    monkeypatch.delenv("EXTRACTION_API_KEYS")
    assert post({"x-api-key": CHAVE}).status_code == 503


def test_chave_curta_demais_e_ignorada_e_cai_em_503(monkeypatch):
    monkeypatch.setenv("EXTRACTION_API_KEYS", "curta")
    assert post({"x-api-key": "curta"}).status_code == 503


def test_auth_disabled_so_com_valor_exato_1(monkeypatch):
    monkeypatch.delenv("EXTRACTION_API_KEYS")
    for v, esperado in (("1", 200), ("true", 503), ("0", 503), ("", 503)):
        monkeypatch.setenv("AUTH_DISABLED", v)
        assert post().status_code == esperado, v


def test_health_continua_aberto_para_o_healthcheck_do_docker(monkeypatch):
    monkeypatch.delenv("EXTRACTION_API_KEYS")
    assert TestClient(app).get("/health").status_code == 200


def test_chave_nao_aparece_em_resposta_nem_em_log(caplog):
    caplog.set_level(logging.DEBUG)
    r = post({"x-api-key": CHAVE[:-1]})
    ok = post({"x-api-key": CHAVE})
    assert CHAVE not in r.text + ok.text + caplog.text and CHAVE[:-1] not in r.text + caplog.text


# --- limite de requisicoes ---------------------------------------------------------------------------
def test_429_com_retry_after_depois_do_limite(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "3")
    seguranca.estado.reset()
    h = {"x-api-key": CHAVE}
    assert [post(h).status_code for _ in range(3)] == [200, 200, 200]
    r = post(h)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1


def test_limite_e_por_chave(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    seguranca.estado.reset()
    assert post({"x-api-key": CHAVE}).status_code == 200
    assert post({"x-api-key": CHAVE}).status_code == 429
    assert post({"x-api-key": OUTRA}).status_code == 200


def test_tentativas_invalidas_nao_gastam_a_cota_da_chave_valida(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "2")
    monkeypatch.setenv("AUTH_FAIL_PER_MIN", "1000")
    seguranca.estado.reset()
    for _ in range(20):
        assert post({"x-api-key": "x" * 20}).status_code == 401
    assert post({"x-api-key": CHAVE}).status_code == 200  # cota intacta


def test_forca_bruta_e_freada_por_cliente(monkeypatch):
    monkeypatch.setenv("AUTH_FAIL_PER_MIN", "3")
    seguranca.estado.reset()
    codigos = [post({"x-api-key": "x" * 20}).status_code for _ in range(5)]
    assert codigos == [401, 401, 401, 429, 429]
    assert "retry-after" in post({"x-api-key": "x" * 20}).headers


def test_limite_so_vale_para_extract_e_respostas_429_nao_vazam_corpo(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
    seguranca.estado.reset()
    post({"x-api-key": CHAVE})
    r = post({"x-api-key": CHAVE})
    assert r.status_code == 429 and OK_TXT not in r.text
    assert TestClient(app).get("/health").status_code == 200


# --- tamanho do corpo --------------------------------------------------------------------------------
def test_corpo_gigante_da_413_mesmo_sem_chave():
    r = TestClient(app).post("/extract", content=b"x" * (seguranca.MAX_BODY_BYTES + 1),
                             headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_corpo_no_limite_de_caracteres_ainda_passa():
    r = post({"x-api-key": CHAVE}, json={"text": "ç" * 20000})  # 40.000 bytes: < MAX_BODY_BYTES
    assert r.status_code == 200


def test_limite_exato_passa_e_um_byte_a_mais_nao():
    c = TestClient(app, headers={"x-api-key": CHAVE, "content-type": "application/json"})
    vazio = b'{"text":""}'
    um = b'{"text":"' + b"a" * (seguranca.MAX_BODY_BYTES - len(vazio)) + b'"}'  # exatamente MAX_BODY_BYTES
    assert len(um) == seguranca.MAX_BODY_BYTES
    assert c.post("/extract", content=um).status_code != 413  # 422 (texto > 20000 chars), mas passou do limite de bytes
    assert c.post("/extract", content=um + b" ").status_code == 413


def test_corpo_chunked_sem_content_length_tambem_e_cortado():
    def gerador():
        for _ in range(12):
            yield b"x" * 10_000

    r = TestClient(app).post("/extract", content=gerador(), headers={"x-api-key": CHAVE, "content-type": "application/json"})
    assert r.status_code == 413


def test_o_corpo_grande_nao_chega_a_gastar_cota_nem_ao_handler(monkeypatch):
    chamadas = []
    monkeypatch.setattr("src.app.extrair", lambda t: chamadas.append(t))
    TestClient(app).post("/extract", content=b"x" * (seguranca.MAX_BODY_BYTES + 1),
                         headers={"x-api-key": CHAVE, "content-type": "application/json"})
    assert chamadas == [] and seguranca.estado.por_chave._hits == {}
