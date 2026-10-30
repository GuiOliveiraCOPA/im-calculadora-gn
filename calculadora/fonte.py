"""Fontes da base tarifária.

Toda fonte devolve o mesmo payload, que o `dados.py` valida:
    {"generated_at": str, "source": str, "records": [...], "parametros": {nome: valor} | None}
"""

from __future__ import annotations

from typing import Protocol

from calculadora.config import Config


class FonteDados(Protocol):
    origem: str  # "databricks" ou "json": aparece no /saude

    def carregar(self) -> dict:
        """Lê a base inteira. Levanta exceção se não conseguir."""
        ...


def criar_fonte(config: Config) -> FonteDados:
    if config.fonte == "json":
        from calculadora.fonte_json import FonteJson

        return FonteJson(config.arquivo_json)
    from calculadora.fonte_databricks import FonteDatabricks

    return FonteDatabricks(config)
