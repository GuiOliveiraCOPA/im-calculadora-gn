"""Formatação pt-BR equivalente ao Intl.NumberFormat usado na versão JavaScript."""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

NBSP = " "


def _sinal_e_texto(valor: float, casas_min: int, casas_max: int) -> tuple[str, str]:
    if math.isnan(valor):
        return "", "NaN"
    negativo = valor < 0 or (valor == 0 and math.copysign(1, valor) < 0)
    if math.isinf(valor):
        return ("-" if negativo else ""), "∞"

    # O Intl arredonda a representação decimal mais curta do número (repr),
    # meia unidade para cima: 1.005 -> "1,01".
    arredondado = Decimal(repr(abs(float(valor)))).quantize(Decimal(1).scaleb(-casas_max), rounding=ROUND_HALF_UP)
    inteiro, _, fracao = f"{arredondado:f}".partition(".")
    fracao = fracao.rstrip("0").ljust(casas_min, "0")

    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    return ("-" if negativo else ""), ".".join(grupos) + ("," + fracao if fracao else "")


def numero(valor: float) -> str:
    """Como Intl.NumberFormat("pt-BR", {maximumFractionDigits: 2})."""
    sinal, texto = _sinal_e_texto(valor, 0, 2)
    return sinal + texto


def moeda(valor: float) -> str:
    """Como Intl.NumberFormat("pt-BR", {style: "currency", currency: "BRL"})."""
    sinal, texto = _sinal_e_texto(valor, 2, 2)
    return f"{sinal}R${NBSP}{texto}"


def faixa_maxima(valor: float) -> str:
    return "Acima" if valor > 999999999 else numero(valor)
