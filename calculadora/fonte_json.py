"""Fonte em arquivo JSON: fixtures de teste e desenvolvimento sem Databricks."""

from __future__ import annotations

import json
from pathlib import Path

from calculadora.dados import TarifasInvalidas


class FonteJson:
    origem = "json"

    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)

    def carregar(self) -> dict:
        try:
            payload = json.loads(self.caminho.read_text(encoding="utf-8-sig"))
        except FileNotFoundError as exc:
            raise TarifasInvalidas(f"Arquivo de tarifas não encontrado: {self.caminho}") from exc
        except json.JSONDecodeError as exc:
            raise TarifasInvalidas(f"Arquivo de tarifas com JSON inválido: {exc}") from exc
        if not isinstance(payload, dict):
            raise TarifasInvalidas(f"Arquivo de tarifas sem o objeto principal: {self.caminho}")
        return {
            "generated_at": str(payload.get("generated_at", "")),
            "source": str(payload.get("source", "")) or str(self.caminho),
            "records": payload.get("records"),
            "parametros": payload.get("parametros"),
        }
