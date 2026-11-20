import pytest

from src import seguranca

CHAVE = "chave-de-teste-0123456789"
OUTRA = "outra-chave-de-teste-9876543210"


@pytest.fixture(autouse=True)
def _config_padrao(monkeypatch):
    """Toda suite roda com auth ligada e limitadores zerados; cada teste sobrescreve o que precisar."""
    monkeypatch.setenv("EXTRACTION_API_KEYS", f"{CHAVE},{OUTRA}")
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1000")
    seguranca.estado.reset()
    yield
    seguranca.estado.reset()
