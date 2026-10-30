"""Regras de cálculo GLP x GN.

Porta fiel de 5_Calculadora_Final/app.js: mesma ordem de operações em ponto
flutuante, para que os resultados sejam idênticos aos da versão no navegador
(verificado por tests/test_paridade_js.py). Única regra diferente de propósito:
o termo fixo na cascata (B-03, ADR 0005 do tratamento).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

# Valores de referência, usados quando a base não traz os parâmetros (fixture antiga).
# Com a Gold, vêm da fct_gn_parametro_vigente_calculadora (ADR 0018 do tratamento).
FATOR_GN_PARA_GLP = 0.826087
FATOR_GLP_PARA_GN = 1.210526
ALIQUOTA_MONOFASICA_GLP = 1.6377

MSG_SEM_TARIFA = "Não há tarifa para a combinação selecionada ou o volume é inválido."
MSG_FORA_DAS_FAIXAS = "Volume fora das faixas disponíveis para a combinação selecionada."


# ---------------------------------------------------------------- impostos

def _normalizar_texto(valor) -> str:
    texto = unicodedata.normalize("NFD", str(valor or ""))
    return "".join(c for c in texto if not "̀" <= c <= "ͯ").lower()


def aliquotas_aplicaveis(row) -> tuple[float, float]:
    return (row.get("pis_cofins") or 0, row.get("icms") or 0)


def aliquotas_da_publicacao(row) -> tuple[float, float]:
    """Impostos já embutidos no preço publicado pela concessionária."""
    rotulo = _normalizar_texto(row.get("preco_concessionaria"))
    pis_cofins, icms = aliquotas_aplicaveis(row)
    tem_pis_cofins = "pis" in rotulo or "cofins" in rotulo
    tem_icms = "icms" in rotulo and "sem icms" not in rotulo
    return (pis_cofins if tem_pis_cofins else 0, icms if tem_icms else 0)


def tarifa_liquida_unitaria(row) -> float:
    pis_cofins, icms = aliquotas_da_publicacao(row)
    return (row.get("tarifa") or 0) * (1 - pis_cofins - icms)


def termo_fixo_liquido(row) -> float:
    pis_cofins, icms = aliquotas_da_publicacao(row)
    return (row.get("termo_fixo") or 0) * (1 - pis_cofins - icms)


def _gross_up(valor: float, aliquota: float) -> float:
    return valor / (1 - aliquota) if aliquota > 0 else valor


def impostos_sobre_liquido(valor: float, row) -> tuple[float, float]:
    """(PIS/Cofins, ICMS) em R$ sobre um valor líquido — ICMS por dentro sobre o valor com PIS/Cofins."""
    pis_cofins, icms = aliquotas_aplicaveis(row)
    com_pis_cofins = _gross_up(valor, pis_cofins)
    com_todos = _gross_up(com_pis_cofins, icms)
    return (com_pis_cofins - valor, com_todos - com_pis_cofins)


# ---------------------------------------------------------------- resultado

@dataclass(frozen=True)
class FaixaCalculada:
    faixa_min: float
    faixa_max: float
    consumo: float
    tarifa_liquida_unitaria: float
    termo_fixo: float
    fatura_liquida: float
    pis_cofins: float
    icms: float
    fatura_bruta: float
    tarifa_bruta_unitaria: float


@dataclass(frozen=True)
class ResultadoCalculo:
    cascata: bool
    entrada_glp: bool
    volume_glp: float
    volume_gn: float
    aliquota_pis_cofins: float
    aliquota_icms: float
    faixas: tuple[FaixaCalculada, ...]
    termo_fixo: float
    fatura_liquida: float
    total_pis_cofins: float
    total_icms: float
    fatura_bruta_gn: float
    total_consumo_faixas: float
    aliquota_monofasica_glp: float = ALIQUOTA_MONOFASICA_GLP

    @property
    def tarifa_liquida_unitaria_glp(self) -> float:
        return self.fatura_liquida / self.volume_glp

    @property
    def tarifa_bruta_unitaria_glp(self) -> float:
        return self.tarifa_liquida_unitaria_glp + self.aliquota_monofasica_glp

    @property
    def fatura_bruta_glp(self) -> float:
        return self.tarifa_bruta_unitaria_glp * self.volume_glp

    @property
    def tarifa_liquida_unitaria_gn(self) -> float:
        return self.fatura_liquida / self.volume_gn

    @property
    def tarifa_bruta_unitaria_gn(self) -> float:
        return self.fatura_bruta_gn / self.volume_gn

    @property
    def gn_bruto_por_kg_glp(self) -> float:
        """Custo do GN com impostos por kg de GLP equivalente (empresas sem crédito)."""
        return self.fatura_bruta_gn / self.volume_glp

    @property
    def tarifa_liquida_media(self) -> float:
        return self.fatura_liquida / self.total_consumo_faixas

    @property
    def tarifa_bruta_media(self) -> float:
        return self.fatura_bruta_gn / self.total_consumo_faixas


@dataclass(frozen=True)
class SemResultado:
    mensagem: str


# ---------------------------------------------------------------- cálculo

def linhas_tarifarias(records, uf, segmento_copa, concessionaria, segmento) -> list[dict]:
    linhas = [
        r for r in records
        if r["uf"] == uf
        and r["segmento_copa"] == segmento_copa
        and r["concessionaria"] == concessionaria
        and r["segmento"] == segmento
    ]
    return sorted(linhas, key=lambda r: (r["faixa_min"], r["ordem"]))


def _escolher_modalidade(linhas) -> tuple[list[dict], bool]:
    cascata = [r for r in linhas if r.get("cascata")]
    if cascata:
        return cascata, True
    return [r for r in linhas if not r.get("cascata")], False


def _faixa(row, consumo: float, subtotal: float, termo_fixo: float, tarifa_liq: float) -> FaixaCalculada:
    fatura_liquida = subtotal + (termo_fixo or 0)
    pis_cofins, icms = impostos_sobre_liquido(fatura_liquida, row)
    fatura_bruta = fatura_liquida + pis_cofins + icms
    return FaixaCalculada(
        faixa_min=row["faixa_min"],
        faixa_max=row["faixa_max"],
        consumo=consumo,
        tarifa_liquida_unitaria=tarifa_liq,
        termo_fixo=termo_fixo,
        fatura_liquida=fatura_liquida,
        pis_cofins=pis_cofins,
        icms=icms,
        fatura_bruta=fatura_bruta,
        tarifa_bruta_unitaria=fatura_bruta / consumo if consumo > 0 else 0,
    )


def _calcular_sem_cascata(linhas, volume_gn):
    selecionada = next((r for r in linhas if r["faixa_min"] <= volume_gn <= r["faixa_max"]), None)
    if selecionada is None:
        return None
    tarifa_liq = tarifa_liquida_unitaria(selecionada)
    subtotal = volume_gn * tarifa_liq
    termo_fixo = termo_fixo_liquido(selecionada)
    return selecionada, [_faixa(selecionada, volume_gn, subtotal, termo_fixo, tarifa_liq)], termo_fixo


def _calcular_com_cascata(linhas, volume_gn):
    faixas = []
    restante = volume_gn
    ultima = None
    for row in linhas:
        if restante <= 0:
            break
        largura = max(0, float(row["faixa_max"]) - float(row["faixa_min"]))
        consumo = min(restante, largura)
        if consumo > 0:
            tarifa_liq = tarifa_liquida_unitaria(row)
            faixas.append(_faixa(row, consumo, consumo * tarifa_liq, 0, tarifa_liq))
            restante -= consumo
            ultima = row
    if not faixas:
        return None
    # B-03 (resposta da IM, ADR 0005): soma o termo fixo da última Classe atingida, na faixa dela.
    termo_fixo = termo_fixo_liquido(ultima)
    if termo_fixo:
        f = faixas[-1]
        faixas[-1] = _faixa(ultima, f.consumo, f.consumo * f.tarifa_liquida_unitaria, termo_fixo, f.tarifa_liquida_unitaria)
    return ultima, faixas, termo_fixo


def fatores_conversao(parametros=None) -> tuple[float, float]:
    """(GN→GLP, GLP→GN): da Gold quando a base traz os parâmetros, senão as constantes."""
    parametros = parametros or {}
    return (parametros.get("FATOR_GN_PARA_GLP", FATOR_GN_PARA_GLP),
            parametros.get("FATOR_GLP_PARA_GN", FATOR_GLP_PARA_GN))


def calcular(records, uf, segmento_copa, concessionaria, segmento, tipo_entrada, volume,
             parametros=None) -> ResultadoCalculo | SemResultado:
    linhas, cascata = _escolher_modalidade(linhas_tarifarias(records, uf, segmento_copa, concessionaria, segmento))
    if not linhas or not volume or volume <= 0:
        return SemResultado(MSG_SEM_TARIFA)

    fator_gn_para_glp, fator_glp_para_gn = fatores_conversao(parametros)
    entrada_glp = tipo_entrada == "glp"
    volume_glp = volume if entrada_glp else volume * fator_gn_para_glp
    volume_gn = volume * fator_glp_para_gn if entrada_glp else volume

    calculado = _calcular_com_cascata(linhas, volume_gn) if cascata else _calcular_sem_cascata(linhas, volume_gn)
    if calculado is None:
        return SemResultado(MSG_FORA_DAS_FAIXAS)
    linha_referencia, faixas, termo_fixo = calculado

    # Somatórios na mesma ordem do app.js (reduce da esquerda para a direita).
    fatura_liquida = total_pis_cofins = total_icms = fatura_bruta = consumo_total = 0
    for f in faixas:
        fatura_liquida += f.fatura_liquida
        total_pis_cofins += f.pis_cofins
        total_icms += f.icms
        fatura_bruta += f.fatura_bruta
    for f in faixas:
        consumo_total += f.consumo

    pis_cofins, icms = aliquotas_aplicaveis(linha_referencia)
    return ResultadoCalculo(
        cascata=cascata,
        entrada_glp=entrada_glp,
        volume_glp=volume_glp,
        volume_gn=volume_gn,
        aliquota_pis_cofins=pis_cofins,
        aliquota_icms=icms,
        faixas=tuple(faixas),
        termo_fixo=termo_fixo,
        fatura_liquida=fatura_liquida,
        total_pis_cofins=total_pis_cofins,
        total_icms=total_icms,
        fatura_bruta_gn=fatura_bruta,
        total_consumo_faixas=consumo_total,
        aliquota_monofasica_glp=(parametros or {}).get("ALIQUOTA_MONOFASICA_GLP", ALIQUOTA_MONOFASICA_GLP),
    )
