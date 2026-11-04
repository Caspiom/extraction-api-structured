"""Contrato de saida: o que a API devolve. O Pydantic e o PORTAO FINAL: nada sai como 'ok'
se nao passar aqui (CNPJ com digito verificador, data de calendario real, valor > 0)."""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def cnpj_valido(digitos: str) -> bool:
    if len(digitos) != 14 or len(set(digitos)) == 1:
        return False
    def dv(base: str, pesos: list[int]) -> str:
        r = sum(int(d) * p for d, p in zip(base, pesos)) % 11
        return "0" if r < 2 else str(11 - r)
    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = dv(digitos[:12], p1)
    d2 = dv(digitos[:12] + d1, [6] + p1)
    return digitos[12:] == d1 + d2


class NotaFiscal(BaseModel):
    numero: str = Field(pattern=r"^\d{1,9}$")
    emitente: str = Field(min_length=2, max_length=200)
    cnpj: str
    data_emissao: date
    valor_total: Decimal = Field(max_digits=14, decimal_places=2)

    @field_validator("cnpj")
    @classmethod
    def _cnpj(cls, v: str) -> str:
        d = "".join(c for c in v if c.isdigit())
        if not cnpj_valido(d):
            raise ValueError("CNPJ invalido (digito verificador nao confere)")
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"

    @field_validator("valor_total")
    @classmethod
    def _valor(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("valor_total deve ser maior que zero")
        return v


class FieldError(BaseModel):
    field: str
    reason: str


class ExtractRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class ExtractResponse(BaseModel):
    status: Literal["ok", "refused"]
    data: NotaFiscal | None = None
    errors: list[FieldError] = []
