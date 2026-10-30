"""Fonte Gold no Databricks, lida por SQL Warehouse.

Lê o contrato inteiro (cerca de 500 linhas) em `fct_gn_tarifa_vigente_calculadora` e os
parâmetros em `fct_gn_parametro_vigente_calculadora`, ambos do dbt (ADRs 0003 e 0018 do
tratamento). Converte Decimal para float e datas para texto ISO antes da validação.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from calculadora.config import Config
from calculadora.credenciais import parametros_autenticacao

# As 23 colunas do contrato, na ordem do modelo dbt.
COLUNAS_TARIFAS = (
    "grupo_tarifario_key", "uf", "concessionaria", "concessionaria_label", "segmento", "segmento_copa",
    "classe", "faixa_min", "faixa_max", "tarifa", "termo_fixo", "pis_cofins", "icms",
    "preco_concessionaria", "cascata", "dt_delib", "fonte", "ordem", "deliberacao", "vigencia_inicio",
    "atualizado_em", "status_atualizacao", "origem_valor",
)
COLUNAS_PARAMETROS = ("parametro", "valor", "vigencia_inicio")


def converter_valor(valor):
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (dt.date, dt.datetime)):
        return valor.isoformat()
    return valor


def _linhas_como_dict(cursor, colunas) -> list[dict]:
    return [dict(zip(colunas, map(converter_valor, linha))) for linha in cursor.fetchall()]


class FonteDatabricks:
    origem = "databricks"

    def __init__(self, config: Config, conectar=None):
        self.config = config
        self._conectar = conectar or self._conectar_sql_warehouse

    def sql_tarifas(self) -> str:
        return (f"SELECT {', '.join(COLUNAS_TARIFAS)} FROM {self.config.tabela_completa} "
                "ORDER BY uf, segmento_copa, concessionaria, segmento, classe")

    def sql_parametros(self) -> str:
        return f"SELECT {', '.join(COLUNAS_PARAMETROS)} FROM {self.config.tabela_parametros_completa} ORDER BY parametro"

    def carregar(self) -> dict:
        with self._conectar() as conexao, conexao.cursor() as cursor:
            cursor.execute(self.sql_tarifas())
            records = _linhas_como_dict(cursor, COLUNAS_TARIFAS)
            cursor.execute(self.sql_parametros())
            parametros = _linhas_como_dict(cursor, COLUNAS_PARAMETROS)

        # Data da base = a Execução válida mais recente entre as Tabelas.
        atualizacoes = [r["atualizado_em"] for r in records if r.get("atualizado_em")]
        return {
            "generated_at": max(atualizacoes, default=""),
            "source": self.config.tabela_completa,
            "records": records,
            "parametros": {p["parametro"]: p["valor"] for p in parametros},
        }

    def _conectar_sql_warehouse(self):
        from databricks import sql

        return sql.connect(
            server_hostname=self.config.databricks_host,
            http_path=self.config.databricks_http_path,
            # Tempo máximo de cada consulta no warehouse (o warehouse frio é tratado pela recarga em segundo plano).
            session_configuration={"STATEMENT_TIMEOUT": str(self.config.timeout_consulta_s)},
            user_agent_entry="calculadora-gn",
            **parametros_autenticacao(self.config),
        )
