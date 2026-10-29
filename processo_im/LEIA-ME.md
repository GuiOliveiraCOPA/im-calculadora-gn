# Processo de coleta e tratamento do IM (versão 1, migrada sem alterações)

Esta pasta é a **cópia fiel** do processo que o time de Inteligência de Mercado (IM) usava para
atualizar a base tarifária da calculadora. Ela foi trazida para dentro do produto
(`6_Calculadora_Flask`, hoje a raiz deste repositório) em 19/10/2026 **sem nenhuma alteração ou melhoria no código**. A estrutura
de pastas é a mesma da raiz do projeto, porque os scripts dependem dos caminhos relativos entre elas.

| Pasta | Origem | Papel |
|---|---|---|
| `1_Processo_Extracao_Dados/` | `1_Processo_Extracao_Dados/` | 17 extratores (`Fonte_Dados/tabela_*.py`) e a consolidação (`codigo_central.py`) que gera `Comece_aqui/Planilha_Final/Planilha_GN_Atualizada.xlsx` |
| `2_Bases_Origem/` | `2_Bases_Origem/` | Base manual `Tarifario_GN.xlsx` (estrutura, faixas, impostos, cascata) |
| `3_Manutencao/` | `3_Manutencao/` | `atualizar_calculadora.py`: cruza a planilha final com o `Tarifario_GN.xlsx` e gera o `tarifas.json` |
| `4_Mapa_GN/` | `4_Mapa_GN/` | Mapa de GN, servido pela calculadora em `/mapa/` |

## Como é executado agora

Quem executa é o ETL da calculadora (`etl/`, na raiz do repositório), no mesmo roteiro do
`AtualizarDados.sh`:

1. `Fonte_Dados/codigo_central.py` (extração + consolidação);
2. `3_Manutencao/atualizar_calculadora.py` (base da calculadora), só se a etapa 1 terminar sem erro;
3. validação do `tarifas.json` gerado e publicação em `data/tarifas.json`.

O único ajuste está **fora** desta pasta: o `etl/rodar_atualizar_calculadora.py` redireciona as
duas saídas do `atualizar_calculadora.py` (que apontavam para `5_Calculadora_Final/tarifas.js` e
`6_Calculadora_Flask/data/tarifas.json` na estrutura antiga) para a área de trabalho do ETL, onde
a base é validada antes de ir para a calculadora.

- **No Docker:** roda sozinho todo dia às 00:00. Execução manual, log e agendamento na tela
  `/interno/etl`.
- **No terminal:** `python -m etl` (na raiz do repositório) ou
  `docker exec calculadora-gn python -m etl`.

Os scripts `Comece_aqui/AtualizarDados.bat` e `AtualizarDados.sh` foram mantidos como referência do
processo original. Os logs continuam em `Comece_aqui/Execucoes_CMD/`, no mesmo padrão de nome.

## Manutenção

Correções nos extratores (por exemplo, quando um site muda de formato) são feitas aqui, nos
arquivos desta pasta. As pastas originais na raiz do projeto deixam de ser a fonte usada pela
calculadora.

Os backups manuais que existiam aqui (`*_backup_antes_*`, `Backups_Manutencao/`) foram removidos em
29/10/2026, porque o histórico do git passou a cumprir esse papel. Para ver uma versão anterior de
um extrator: `git log -p -- processo_im/1_Processo_Extracao_Dados/Comece_aqui/Fonte_Dados/<arquivo>.py`.

Os documentos originais do IM (`1_Processo_Extracao_Dados/Comece_aqui/README.md`, `3_Manutencao/README_mapa.md`)
foram mantidos como estavam e descrevem a estrutura antiga do projeto (pastas `5_Calculadora_Final`,
`6_Calculadora_Flask` lado a lado) e a execução pelo `.bat`/`.sh`. O fluxo atual é o descrito acima.
