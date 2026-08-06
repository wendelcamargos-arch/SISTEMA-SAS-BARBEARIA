"""Dinheiro em Decimal — única forma permitida de aritmética financeira.

Regras (FASE financeira da migração):
  - Banco: NUMERIC(14,2) para valores; NUMERIC(7,4) para percentuais.
  - Python: Decimal em toda conta de dinheiro; float é proibido em cálculo
    financeiro (teste de guarda em tests/test_decimal.py).
  - Arredondamento explícito: ROUND_HALF_UP em centavos (Decimal("0.01")).
"""
from decimal import ROUND_HALF_UP, Decimal

CENTAVO = Decimal("0.01")
QUATRO_CASAS = Decimal("0.0001")
ZERO = Decimal("0.00")


def D(valor) -> Decimal:
    """Converte com segurança para Decimal (floats passam por str para não
    herdar o erro binário: D(0.1) == Decimal('0.1'))."""
    if isinstance(valor, Decimal):
        return valor
    if valor is None:
        return Decimal("0")
    return Decimal(str(valor))


def dinheiro(valor) -> Decimal:
    """Valor monetário quantizado a centavos, ROUND_HALF_UP."""
    return D(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def percentual(valor) -> Decimal:
    """Percentual com 4 casas (NUMERIC(7,4))."""
    return D(valor).quantize(QUATRO_CASAS, rounding=ROUND_HALF_UP)


def aplicar_percentual(base, pct) -> Decimal:
    """base * pct% arredondado a centavos."""
    return dinheiro(D(base) * D(pct) / Decimal("100"))
