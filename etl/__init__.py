"""ETL da base tarifária: executa o processo de coleta e tratamento do IM (pasta processo_im).

O código do IM roda sem alterações. Este pacote só orquestra a execução (manual pela tela
/interno/etl ou pelo agendamento diário), grava o log no mesmo padrão do AtualizarDados.sh
e publica o tarifas.json na calculadora depois de validá-lo.
"""

from etl.agendamento import Agendador
from etl.config import ConfiguracaoEtl
from etl.executor import EtlEmExecucao, ExecutorEtl

__all__ = ["Agendador", "ConfiguracaoEtl", "EtlEmExecucao", "ExecutorEtl"]
