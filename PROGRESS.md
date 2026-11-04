# PROGRESSO — extraction-api-structured

Último ponto onde parei (atualize ao fim de cada sessão de 1h):

- **Data:** 2026-11-04 (bloco de QUARTA, feito pelo Hermes a pedido do Lucas)
- **Onde parei:** API funcionando de ponta a ponta. Schema Pydantic como portão final (CNPJ com dígito verificador, data real, valor > 0), extrator **por regras** (sem LLM) que recusa por campo em vez de chutar, FastAPI (`/extract`, `/health`), Dockerfile (build e execução verificados, `healthy`). 21 testes. Eval de 36 casos: dev 12/12; **test 23/24 na 1ª rodada** (a falha, t23, era um bug de lookbehind; corrigido depois, então o 24/24 é otimista). Validação por mutação: 10 mutantes, testes pegam 10, eval pega 8; um 11º revelou código morto e foi removido.
- **Honestidade:** extrator é de regras, não LLM. 36 casos escritos por mim em texto limpo; nada de PDF/OCR/nota real.
- **Próximo passo:** (1) extrator com LLM atrás da mesma interface, comparado no mesmo eval — medir *aceite errado*, não só acerto (gasta dinheiro: estimar custo e pedir ok antes; começar por provedor gratuito/fixture); (2) entrada real: PDF/OCR e um punhado de notas reais (anonimizadas) como conjunto de teste; (3) autenticação e limite de requisições antes de expor.
