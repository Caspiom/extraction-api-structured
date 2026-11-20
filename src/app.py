"""API: POST /extract recebe texto e devolve JSON validado ou recusa com motivo por campo."""
from fastapi import Depends, FastAPI

from .extractor import extrair
from .seguranca import LimiteDeCorpo, exigir_acesso
from .schemas import ExtractRequest, ExtractResponse

app = FastAPI(title="extraction-api-structured", version="0.1.0")
app.add_middleware(LimiteDeCorpo)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/extract", response_model=ExtractResponse, dependencies=[Depends(exigir_acesso)])
def extract(req: ExtractRequest) -> ExtractResponse:
    # 200 mesmo quando recusa: a requisicao foi valida; "refused" e o RESULTADO da extracao.
    return extrair(req.text)
