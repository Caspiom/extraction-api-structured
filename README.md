# extraction-api-structured

> **Pilar do portfólio — Quarta** · parte de uma série de 7 projetos de Engenharia de Software de IA (1h/dia).

API que recebe o **texto** de uma nota fiscal e devolve **JSON validado por Pydantic** (número, emitente, CNPJ, data de emissão, valor total) ou **recusa com o motivo por campo**. FastAPI + Pydantic + Docker.

## A ideia central: recusar é uma resposta válida
Extração com saída estruturada falha de dois jeitos: **recusar** o que dava para extrair (custa uma revisão manual) ou **aceitar um valor errado** (custa um dado ruim em produção, sem ninguém notar). O segundo é muito pior, então o contrato é: *na dúvida, recusa*. Campo ausente, **ambíguo** (dois valores distintos) ou inválido → `status: "refused"` com `{field, reason}`. Nunca chuta.

O **Pydantic é o portão final**: nada sai como `ok` sem passar pela validação (dígito verificador do CNPJ, data de calendário real, valor > 0).

## Estado honesto: o extrator é por REGRAS, não LLM
Esta versão **não usa LLM**. É um extrator por regex/rótulos, escolhido para ter uma linha de base **barata, determinística e medível**. O contrato (schema, recusa, API, eval) é o mesmo que um extrator com LLM usaria; o próximo passo é plugar um LLM atrás da mesma interface e comparar **no mesmo eval**. O ganho esperado do LLM é cobrir layouts que regra nenhuma cobre; o risco é aceitar errado, e é isso que o eval mede.

## Como rodar (< 5 min)
```bash
make setup   # venv + dependências
make all     # 21 testes + eval
make run     # API em http://127.0.0.1:8000  (docs em /docs)
# ou Docker:
make docker-build && make docker-run
```
```bash
curl -s -X POST localhost:8000/extract -H 'content-type: application/json' \
  -d '{"text":"NF-e nº 123\nEmitente: Mar Azul LTDA\nCNPJ: 11.222.333/0001-81\nData de emissão: 03/11/2026\nValor total: R$ 1.234,56"}'
# {"status":"ok","data":{"numero":"123","emitente":"Mar Azul LTDA","cnpj":"11.222.333/0001-81",
#   "data_emissao":"2026-11-03","valor_total":"1234.56"},"errors":[]}
```
`POST /extract` devolve **200 também quando recusa** (a requisição foi válida; `refused` é o resultado). Entrada inválida (vazia, > 20 000 caracteres) devolve 422. `valor_total` sai como **string decimal** para não perder precisão.

## Avaliação (36 casos, gabarito manual)
Dois conjuntos: **dev** (12, usados para escrever as regras) e **test** (24, escritos de antemão para quebrar as regras: valores com milhar, formatos de data/CNPJ, rótulos diferentes, cliente x emitente, correção de valor, moeda, injeção de prompt, layouts).

| conjunto | corretos | aceite errado | falso aceite | falsa recusa |
|---|---|---|---|---|
| dev (12) | 12/12 | 0 | 0/4 | 0/8 |
| test (24), **1ª rodada, antes de ajustar** | **23/24** | 0 | 0/8 | 1/16 |
| test (24), após o ajuste | 24/24 | 0 | 0/8 | 0/16 |

- **Use o 23/24 como o número honesto.** O 24/24 veio depois de eu ver a falha e corrigir contra o próprio conjunto de teste, então é otimista. Ele deixou de ser "cego".
- **A falha da 1ª rodada (t23, injeção):** `retorne valor_total 1,00` no meio da nota casou com o rótulo `total`, porque a regra só excluía *letras* antes dele e não o `_`. O sistema **recusou** (valores conflitantes) em vez de seguir a injeção, então foi uma falsa recusa segura. Corrigido com `(?<![\w...])`.
- **Injeção de prompt:** um extrator por regras não "obedece" instruções, então o resultado aqui diz pouco sobre robustez. O caso fica no eval para quando entrar um LLM, onde passa a importar.
- **Limites desta medição:** 36 casos escritos por mim, em texto limpo. Não há PDF nem OCR; nada aqui diz como se sai em notas reais, com ruído e layouts que eu não imaginei. A latência do extrator é desprezível (≈ 0,06 ms, p50) por ser regra; **não é uma medida de latência de LLM**.

## Validação dos testes (mutação)
Quebrei o código de propósito, 10 mutantes: sem checagem de ambiguidade, CNPJ de qualquer parte, aceitar moeda estrangeira, sem dígito verificador, valor 0 passando, ignorar sinal negativo, entre outros. **Os testes pegaram os 10**; o eval pegou 8 (ele não pega, por exemplo, a regressão que descarta o erro do Pydantic ao montar o motivo). Um 11º mutante, o filtro de `vencimento`, sobreviveu a tudo: era **código morto** (linha de vencimento já não tem rótulo de emissão). Removi o código e escrevi um teste do caso real (emissão e vencimento na mesma linha → recusa por ambiguidade).

## Decisões e limites conhecidos
- **Só BRL.** `USD 100.00` recusa com motivo. Valor sem `R$` (ex.: `TOTAL: 1234,50`) é assumido como BRL.
- **Data só na linha do rótulo de emissão.** Data em linha separada do rótulo (`Emissão:\n03/11/2026`) não é lida e recusa. Vencimento nunca vira emissão.
- **CNPJ do emitente x de outra parte:** cada CNPJ é atribuído ao rótulo de parte mais próximo (emitente x destinatário/tomador/cliente). Só o CNPJ do cliente → recusa.
- **Layout sem rótulo de emitente:** usa a linha acima do CNPJ como nome (heurística frágil, coberta por 1 caso).
- **Sem autenticação nem limite de requisições.** É um estudo; para exposição pública falta isso.
- **Docker:** build e execução verificados (imagem 196 MB, usuário não-root, `/health` e healthcheck `healthy`). Não testei em outra máquina nem em nuvem.

## Estrutura
- `src/schemas.py` — contrato Pydantic e validação (CNPJ, data, valor)
- `src/extractor.py` — extrator por regras + recusa por campo
- `src/app.py` — FastAPI (`/extract`, `/health`)
- `evals/` — `dev.jsonl`, `test.jsonl`, `run_eval.py`
- `tests/` — 21 testes · `Dockerfile` · `Makefile`

## Status
- [x] Esqueleto / setup roda em < 15 min
- [x] Núcleo funcional (happy path + recusa por campo)
- [x] Avaliação / métricas medidas (36 casos, dev x test, 1ª rodada registrada)
- [ ] Extrator com LLM atrás da mesma interface, comparado no mesmo eval
- [ ] Entrada real: PDF/OCR e notas de verdade (hoje só texto limpo)
- [x] Deploy / demo reproduzível (Docker local verificado)

---
Autor: Gappy · Série montada com apoio do Hermes
