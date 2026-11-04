"""Eval: mede o extrator contra gabarito manual. Uso: python -m evals.run_eval [dev|test|all] [--verbose]
Metricas que importam (em ordem de gravidade):
  aceite errado   = disse "ok" com algum campo ERRADO (erro silencioso, o pior)
  falso aceite    = devia recusar e disse "ok"
  falsa recusa    = devia extrair e recusou
"""
import json
import sys
import time
from pathlib import Path

from src.extractor import extrair

D = Path(__file__).parent


def carregar(nome):
    return [json.loads(l) for l in (D / f"{nome}.jsonl").read_text().splitlines() if l.strip()]


def avaliar(caso):
    r = extrair(caso["text"])
    if caso["expect"] == "ok":
        if r.status != "ok":
            return "falsa_recusa", [f"{e.field}: {e.reason}" for e in r.errors]
        got = r.data.model_dump(mode="json")
        erradas = [f"{k}: esperado {v!r}, veio {got[k]!r}" for k, v in caso["gold"].items() if got[k] != v]
        return ("ok", []) if not erradas else ("aceite_errado", erradas)
    if r.status == "ok":
        return "falso_aceite", [f"aceitou {r.data.model_dump(mode='json')}"]
    campos = {e.field for e in r.errors}
    falta = set(caso["refuse_fields"]) - campos
    return ("ok", []) if not falta else ("recusa_sem_o_campo_certo", [f"devia apontar {sorted(falta)}, apontou {sorted(campos)}"])


def rodar(nome, verbose):
    casos, cont, falhas, t = carregar(nome), {}, [], []
    for c in casos:
        t0 = time.perf_counter(); res, det = avaliar(c); t.append((time.perf_counter() - t0) * 1000)
        cont[res] = cont.get(res, 0) + 1
        if res != "ok": falhas.append((c["id"], c["cat"], res, det))
    n, ok = len(casos), cont.get("ok", 0)
    esp_ok = sum(c["expect"] == "ok" for c in casos); esp_rec = n - esp_ok
    print(f"\n== {nome}: {ok}/{n} corretos ==")
    print(f"  aceite errado (erro silencioso): {cont.get('aceite_errado', 0)}")
    print(f"  falso aceite (devia recusar):    {cont.get('falso_aceite', 0)}/{esp_rec}")
    print(f"  falsa recusa (devia extrair):    {cont.get('falsa_recusa', 0)}/{esp_ok}")
    print(f"  recusa sem o campo certo:        {cont.get('recusa_sem_o_campo_certo', 0)}")
    t.sort(); print(f"  latencia do extrator: p50 {t[len(t)//2]:.3f} ms, max {t[-1]:.3f} ms")
    for id_, cat, res, det in falhas:
        print(f"  FALHA {id_} [{cat}] {res}: {'; '.join(det)}")
    return ok, n, cont


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    alvo = args[0] if args else "all"
    tot = [0, 0]
    for nome in (["dev", "test"] if alvo == "all" else [alvo]):
        ok, n, _ = rodar(nome, "--verbose" in sys.argv); tot[0] += ok; tot[1] += n
    sys.exit(0 if tot[0] == tot[1] else 1)
