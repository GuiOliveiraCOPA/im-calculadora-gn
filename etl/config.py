"""Caminhos do processo do IM e da área de trabalho do ETL."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROCESSO_IM_PADRAO = BASE_DIR / "processo_im"


@dataclass(frozen=True)
class ConfiguracaoEtl:
    processo_dir: Path  # cópia do processo do IM (1_Processo_Extracao_Dados, 2_Bases_Origem, 3_Manutencao)
    tarifas_json: Path  # base publicada, lida pela calculadora
    estado_dir: Path  # agendamento, histórico de execuções e saída temporária do ETL
    python: str = sys.executable  # interpretador com as bibliotecas do processo_im/.../requirements.txt
    senha: str = ""  # vazia: tela sem senha (apenas oculta)

    @classmethod
    def do_ambiente(cls, tarifas_json: Path) -> "ConfiguracaoEtl":
        tarifas_json = Path(tarifas_json)
        return cls(
            processo_dir=Path(os.environ.get("ETL_PROCESSO_DIR", PROCESSO_IM_PADRAO)),
            tarifas_json=tarifas_json,
            estado_dir=Path(os.environ.get("ETL_ESTADO_DIR", tarifas_json.parent / "etl")),
            python=os.environ.get("ETL_PYTHON", sys.executable),
            senha=os.environ.get("ETL_SENHA", ""),
        )

    # ------------------------------------------------ estrutura original do IM
    @property
    def comece_aqui(self) -> Path:
        return self.processo_dir / "1_Processo_Extracao_Dados" / "Comece_aqui"

    @property
    def codigo_central(self) -> Path:
        return self.comece_aqui / "Fonte_Dados" / "codigo_central.py"

    @property
    def log_dir(self) -> Path:
        return self.comece_aqui / "Execucoes_CMD"

    @property
    def planilha_final(self) -> Path:
        return self.comece_aqui / "Planilha_Final" / "Planilha_GN_Atualizada.xlsx"

    @property
    def manutencao_dir(self) -> Path:
        return self.processo_dir / "3_Manutencao"

    @property
    def tarifario_origem(self) -> Path:
        return self.processo_dir / "2_Bases_Origem" / "Tarifario_GN.xlsx"

    # ------------------------------------------------ área de trabalho do ETL
    @property
    def agendamento_json(self) -> Path:
        return self.estado_dir / "agendamento.json"

    @property
    def historico_json(self) -> Path:
        return self.estado_dir / "historico_execucoes.json"

    @property
    def saida_dir(self) -> Path:
        return self.estado_dir / "saida"
