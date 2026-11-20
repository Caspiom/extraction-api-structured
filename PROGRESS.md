# PROGRESSO — extraction-api-structured

Último ponto onde parei (atualize ao fim de cada sessão de 1h):

- **Data:** 2026-11-20 (bloco de QUARTA 11/11, atrasado, feito pelo Hermes a pedido do Lucas)
- **Onde parei:** a API agora tem porta de entrada: chave de API em tempo constante (falha fechada com 503 sem config), limite por chave em janela deslizante com `Retry-After`, freio de força bruta por cliente que não gasta a cota da chave válida, 413 para corpo grande (middleware ASGI, funciona também em chunks) e `/health` aberto. 45 testes. Mutação: 20 mutantes, **1 sobreviveu na 1ª rodada** (`Retry-After` sem somar a janela, porque no teste a espera coincidia com a janela inteira) e virou teste com tempo avançado. Docker verificado: 401/200/429/413/503. Achado: checar tamanho em `Depends` não impede a leitura do corpo (FastAPI lê antes das dependências e engole exceções como 400), então virou middleware.
- **Limites:** limite em memória e por processo, sem TLS, IP do proxy atrás de proxy, JSON malformado dá 422 antes do 401, sem revisão externa.
- **Próximo passo:** (1) extrator com LLM atrás da mesma interface, comparado no mesmo eval, medindo *aceite errado* (começar por fixture; gasto pede ok); (2) entrada real: PDF/OCR e notas anonimizadas como teste; (3) limite compartilhado (Redis) se for ter mais de 1 réplica.
