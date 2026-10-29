"""Filtros em cascata (UF → Segmento → Concessionária → Segmento tarifário)."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

# Ordem de pontuação usada pelo navegador (ICU) em localeCompare("pt-BR"):
# pontuação < dígitos < letras, com esta sequência entre os sinais mais comuns.
_ORDEM_PONTUACAO = " _-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"


def _peso_primario(caractere: str) -> tuple[int, int]:
    if caractere in _ORDEM_PONTUACAO:
        return (0, _ORDEM_PONTUACAO.index(caractere))
    if caractere.isdigit():
        return (1, ord(caractere))
    return (2, ord(caractere))


def chave_ordenacao_pt_br(texto: str):
    """Aproxima String.localeCompare(..., "pt-BR"): base da letra, depois acento, depois caixa."""
    decomposto = [unicodedata.normalize("NFD", c) for c in texto]
    base = [d[0].casefold() for d in decomposto]
    primario = tuple(_peso_primario(c) for c in base)
    secundario = tuple(d[1:] for d in decomposto)  # sem acento vem antes
    terciario = tuple(c.isupper() for c in texto)  # minúscula vem antes
    return (primario, secundario, terciario)


def unicos_ordenados(valores) -> list[str]:
    return sorted({v for v in valores if v}, key=chave_ordenacao_pt_br)


@dataclass(frozen=True)
class Filtro:
    opcoes: list[str]
    selecionado: str


@dataclass(frozen=True)
class Filtros:
    uf: Filtro
    segmento_copa: Filtro
    concessionaria: Filtro
    segmento: Filtro

    def selecao(self) -> dict[str, str]:
        return {
            "uf": self.uf.selecionado,
            "segmento_copa": self.segmento_copa.selecionado,
            "concessionaria": self.concessionaria.selecionado,
            "segmento": self.segmento.selecionado,
        }

    def como_dict(self) -> dict:
        return {
            nome: {"opcoes": filtro.opcoes, "selecionado": filtro.selecionado}
            for nome, filtro in vars(self).items()
        }


def _escolher(opcoes: list[str], anterior: str | None) -> Filtro:
    # Mantém a escolha anterior quando ela continua válida; senão, a primeira opção.
    if anterior in opcoes:
        return Filtro(opcoes, anterior)
    return Filtro(opcoes, opcoes[0] if opcoes else "")


def resolver_filtros(records, uf=None, segmento_copa=None, concessionaria=None, segmento=None) -> Filtros:
    f_uf = _escolher(unicos_ordenados(r["uf"] for r in records), uf)

    por_uf = [r for r in records if r["uf"] == f_uf.selecionado]
    f_seg_copa = _escolher(unicos_ordenados(r["segmento_copa"] for r in por_uf), segmento_copa)

    por_segmento = [r for r in por_uf if r["segmento_copa"] == f_seg_copa.selecionado]
    f_conc = _escolher(unicos_ordenados(r["concessionaria"] for r in por_segmento), concessionaria)

    por_conc = [r for r in por_segmento if r["concessionaria"] == f_conc.selecionado]
    f_segmento = _escolher(unicos_ordenados(r["segmento"] for r in por_conc), segmento)

    return Filtros(f_uf, f_seg_copa, f_conc, f_segmento)
