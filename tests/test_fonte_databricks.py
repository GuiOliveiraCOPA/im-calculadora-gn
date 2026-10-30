"""Contrato da Gold (seção 6.2 do plano): leitura com conexão falsa e, com variáveis, real."""

import datetime as dt
import os
from decimal import Decimal

import pytest

from calculadora.config import carregar_config
from calculadora.credenciais import parametros_autenticacao
from calculadora.dados import montar_base
from calculadora.fonte_databricks import COLUNAS_PARAMETROS, COLUNAS_TARIFAS, FonteDatabricks

ENV = {
    "GN_AMBIENTE": "prd", "DATABRICKS_HOST": "https://adb-1.azuredatabricks.net/",
    "DATABRICKS_HTTP_PATH": "/sql/1.0/warehouses/abc", "DATABRICKS_CLIENT_ID": "id", "DATABRICKS_CLIENT_SECRET": "s",
}

LINHA_GOLD = (
    "SP|COMGAS|INDUSTRIAL", "SP", "COMGÁS", "SP (Comgás)", "Industrial", "INDUSTRIAL", 1,
    Decimal("0E-8"), Decimal("50000.00000000"), Decimal("2.12345678"), Decimal("-3.50000000"),
    Decimal("0.092500"), Decimal("0.180000"), "sem impostos", True, dt.date(2026, 10, 1),
    "https://exemplo", 1, None, dt.date(2026, 10, 1), dt.date(2026, 10, 29), "atualizada", "execucao_atual",
)
PARAMETROS_GOLD = [
    ("ALIQUOTA_MONOFASICA_GLP", Decimal("1.6377"), dt.date(2026, 1, 1)),
    ("FATOR_GLP_PARA_GN", Decimal("1.210526"), dt.date(2000, 1, 1)),
    ("FATOR_GN_PARA_GLP", Decimal("0.826087"), dt.date(2000, 1, 1)),
]


class CursorFalso:
    def __init__(self, conexao):
        self.conexao = conexao
        self._resultado = []

    def execute(self, sql):
        self.conexao.consultas.append(sql)
        self._resultado = [LINHA_GOLD] if "tarifa_vigente" in sql else PARAMETROS_GOLD

    def fetchall(self):
        return self._resultado

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class ConexaoFalsa:
    def __init__(self):
        self.consultas = []

    def cursor(self):
        return CursorFalso(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_le_o_contrato_e_converte_tipos():
    conexao = ConexaoFalsa()
    fonte = FonteDatabricks(carregar_config(ENV), conectar=lambda: conexao)
    payload = fonte.carregar()

    assert len(COLUNAS_TARIFAS) == 23
    assert conexao.consultas[0].startswith(f"SELECT {', '.join(COLUNAS_TARIFAS)} FROM marketing_prd.marketing_gold."
                                           "fct_gn_tarifa_vigente_calculadora")
    assert conexao.consultas[1] == (f"SELECT {', '.join(COLUNAS_PARAMETROS)} FROM marketing_prd.marketing_gold."
                                    "fct_gn_parametro_vigente_calculadora ORDER BY parametro")
    r = payload["records"][0]
    assert r["tarifa"] == 2.12345678 and isinstance(r["faixa_min"], float)
    assert (r["vigencia_inicio"], r["atualizado_em"], r["deliberacao"]) == ("2026-10-01", "2026-10-29", None)
    assert payload["parametros"] == {"ALIQUOTA_MONOFASICA_GLP": 1.6377, "FATOR_GLP_PARA_GN": 1.210526,
                                     "FATOR_GN_PARA_GLP": 0.826087}
    assert payload["generated_at"] == "2026-10-29"
    # A saída da fonte passa na mesma validação do dados.py.
    base = montar_base(payload, "databricks", "2026-10-30T09:00:00+00:00")
    assert base.parametros["FATOR_GN_PARA_GLP"] == 0.826087
    assert base.parametros["ALIQUOTA_MONOFASICA_GLP"] == 1.6377


def test_autenticacao_por_tipo():
    assert parametros_autenticacao(carregar_config({**ENV, "GN_AUTH_TIPO": "pat", "DATABRICKS_TOKEN": "t"})) == {
        "access_token": "t"}
    m2m = parametros_autenticacao(carregar_config(ENV))  # padrão de prd: service principal
    assert set(m2m) == {"credentials_provider"} and callable(m2m["credentials_provider"])
    u2m = parametros_autenticacao(carregar_config({**ENV, "GN_AUTH_TIPO": "oauth_u2m"}))
    assert set(u2m) == {"credentials_provider"}


@pytest.mark.databricks
@pytest.mark.skipif(not os.environ.get("DATABRICKS_HOST"), reason="sem DATABRICKS_HOST: integração real desligada")
def test_integracao_real_com_a_gold():
    """pytest -m databricks com as variáveis do .env: SELECT real na Gold do ambiente."""
    config = carregar_config()
    payload = FonteDatabricks(config).carregar()
    assert set(payload["records"][0]) == set(COLUNAS_TARIFAS)
    montar_base(payload, "databricks", "2026-10-30T09:00:00+00:00")
