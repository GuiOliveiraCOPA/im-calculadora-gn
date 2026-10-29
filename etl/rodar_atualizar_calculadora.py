"""Roda o 3_Manutencao/atualizar_calculadora.py do IM sem alterar o código dele.

O script original grava em caminhos fixos da estrutura antiga do projeto
(5_Calculadora_Final/tarifas.js e 6_Calculadora_Flask/data/tarifas.json). Aqui só
redirecionamos essas duas saídas para a pasta de trabalho do ETL. A publicação na
calculadora é feita depois pelo executor, e só se a base gerada passar na validação.

Uso: python rodar_atualizar_calculadora.py <pasta 3_Manutencao> <saída tarifas.json> <saída tarifas.js>
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    manutencao, saida_json, saida_js = (Path(arg) for arg in sys.argv[1:4])
    sys.path.insert(0, str(manutencao))
    import atualizar_calculadora as legado  # type: ignore

    legado.OUTPUT_TARIFFS_JSON = saida_json
    legado.OUTPUT_TARIFFS_JS = saida_js
    saida_js.parent.mkdir(parents=True, exist_ok=True)
    sys.argv = [str(manutencao / "atualizar_calculadora.py")]  # o original procura "--run-bat" no argv
    legado.main()


if __name__ == "__main__":
    main()
