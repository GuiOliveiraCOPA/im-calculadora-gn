"""Executa o ETL pelo terminal, sem a tela (mesmo roteiro e mesmo log).

    python -m etl                      # todas as UFs
    python -m etl --only SP,RJ
    python -m etl --skip-run           # não acessa os sites; reaproveita as planilhas por UF
    python -m etl --calculadora-mesmo-com-erro
    docker exec calculadora-gn python -m etl
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from etl.config import BASE_DIR, ConfiguracaoEtl
from etl.executor import ExecutorEtl


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m etl", description="ETL da base tarifária da Calculadora GN.")
    parser.add_argument("--only", default="", help="UFs separadas por vírgula (padrão: todas)")
    parser.add_argument("--skip-run", action="store_true", help="não acessa os sites")
    parser.add_argument("--calculadora-mesmo-com-erro", action="store_true",
                        help="publica a base mesmo se algum extrator falhar")
    parser.add_argument("--responsavel", default=os.environ.get("NOME_RESPONSAVEL", ""))
    args = parser.parse_args()

    tarifas = Path(os.environ.get("TARIFAS_GN_JSON", BASE_DIR / "data" / "tarifas.json"))
    executor = ExecutorEtl(ConfiguracaoEtl.do_ambiente(tarifas))
    execucao = executor.executar(origem="terminal", responsavel=args.responsavel, ufs=args.only,
                                 skip_run=args.skip_run, mesmo_com_erro=args.calculadora_mesmo_com_erro)
    print(f"\nResultado: {execucao['status']} — {execucao['mensagem']}")
    print(f"Log: {executor.config.log_dir / execucao['log']}")
    return execucao["codigo_saida"] or 0


if __name__ == "__main__":
    sys.exit(main())
