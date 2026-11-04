"""Extrator por REGRAS (sem LLM). Fase 1: acha candidatos por campo. Fase 2: o Pydantic valida.
Regra de ouro: na duvida, RECUSA. Campo ausente, ambiguo (2 valores distintos) ou invalido
=> status "refused" com o motivo por campo. Nunca chuta um valor."""
import re
from datetime import datetime  # noqa: F401
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from .schemas import ExtractResponse, FieldError, NotaFiscal

CAMPOS = ("numero", "emitente", "cnpj", "data_emissao", "valor_total")
MESES = {m: i for i, m in enumerate(
    "janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro".split(), 1)}
MESES["marco"] = 3

CNPJ_RE = re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)")
NUMERO_RE = re.compile(
    r"\b(?:nota\s+fiscal(?:\s+eletr[ôo]nica|\s+de\s+servi[çc]o)?|nfs?-?e?|invoice)"
    r"\s*(?:n[ºo°]\.?|n[úu]mero)?\s*:?\s*(\d+)\b", re.I)
EMIT_LABEL_RE = re.compile(r"^\s*(?:emitente|prestador|fornecedor|raz[ãa]o\s+social)\s*:?\s*(.+?)\s*$", re.I)
DEST_RE = re.compile(r"destinat|tomador|cliente|comprador", re.I)
PROSA_EMIT_RE = re.compile(r"emitida\s+por\s+(.+?)\s*\(", re.I)
DATA_LINHA_RE = re.compile(r"emiss[ãa]o|emitid[ao]", re.I)
VALOR_RE = re.compile(
    r"(?<![\wà-ú])(?:valor\s+total|total(?:\s+a\s+pagar)?)(?:\s+de)?[\s.:]*"
    r"(?P<cur>R\$|US\$|USD|EUR|€)?\s*(?P<neg>-)?\s*"
    r"(?P<num>\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}|\d+\.\d{2})", re.I)


def _unico(valores: list[str], erros: dict, campo: str):
    """Devolve o unico valor distinto; registra erro se nenhum ou se mais de um."""
    distintos = list(dict.fromkeys(valores))
    if not distintos:
        erros[campo] = "nao encontrado"
    elif len(distintos) > 1:
        erros[campo] = f"ambiguo: {len(distintos)} valores distintos ({', '.join(distintos)})"
    else:
        return distintos[0]
    return None


def _datas(linha: str) -> list[str]:
    linha = CNPJ_RE.sub(" ", linha)
    out = []
    for a, m, d in re.findall(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", linha):
        out.append(f"{a}-{m}-{d}")
    for d, m, a in re.findall(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})(?!\d)", linha):
        out.append(f"{a}-{int(m):02d}-{int(d):02d}")
    for d, mes, a in re.findall(r"(?<!\d)(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})", linha, re.I):
        if mes.lower() in MESES:
            out.append(f"{a}-{MESES[mes.lower()]:02d}-{int(d):02d}")
    return out


def extrair(texto: str) -> ExtractResponse:
    erros: dict[str, str] = {}
    linhas = texto.splitlines()

    numero = _unico([str(int(n)) for n in NUMERO_RE.findall(texto)], erros, "numero")

    # CNPJ do EMITENTE: atribui cada CNPJ ao rotulo de parte mais proximo (emitente x destinatario)
    parte, cnpjs, nomes = None, [], []
    for i, ln in enumerate(linhas):
        m = EMIT_LABEL_RE.match(ln)
        if m:
            parte = "emit"; nomes.append(m.group(1))
        elif DEST_RE.search(ln):
            parte = "dest"
        for c in CNPJ_RE.findall(ln):
            papel = "dest" if DEST_RE.search(ln) else (parte or "emit")
            if papel == "emit":
                cnpjs.append("".join(ch for ch in c if ch.isdigit()))
                if not nomes and i > 0 and not re.search(r"\d|nf|nota", linhas[i - 1], re.I):
                    nomes.append(linhas[i - 1].strip())   # layout sem rotulo: nome na linha acima do CNPJ
    cnpj = _unico(cnpjs, erros, "cnpj")

    if not nomes:
        nomes = [m.strip() for m in PROSA_EMIT_RE.findall(texto)]
    emitente = _unico(nomes, erros, "emitente")

    datas = [d for ln in linhas if DATA_LINHA_RE.search(ln) for d in _datas(ln)]  # so linhas com rotulo de emissao
    data = _unico(datas, erros, "data_emissao")

    valores, moeda_ruim = [], set()
    for m in VALOR_RE.finditer(texto):
        cur = (m["cur"] or "R$").upper()
        if cur != "R$":
            moeda_ruim.add(cur); continue
        n = m["num"].replace(".", "").replace(",", ".") if "," in m["num"] else m["num"]
        valores.append(("-" if m["neg"] else "") + str(Decimal(n)))
    valor = _unico(valores, erros, "valor_total")
    if moeda_ruim and "valor_total" in erros and not valores:
        erros["valor_total"] = f"moeda nao suportada ({', '.join(sorted(moeda_ruim))}); so BRL"

    candidatos = {"numero": numero, "emitente": emitente, "cnpj": cnpj, "data_emissao": data, "valor_total": valor}
    try:
        nota = NotaFiscal(**{k: v for k, v in candidatos.items() if v is not None})
    except ValidationError as e:                      # portao final: Pydantic
        for err in e.errors():
            campo = str(err["loc"][0])
            if campo not in erros:
                erros[campo] = err["msg"].removeprefix("Value error, ")
        nota = None
    if erros:
        return ExtractResponse(status="refused", errors=[FieldError(field=c, reason=erros[c])
                                                         for c in CAMPOS if c in erros])
    return ExtractResponse(status="ok", data=nota)
