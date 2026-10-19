#!/usr/bin/env bash
# Atualização automática de tarifas GN — versão Linux (AlmaLinux / RHEL) do AtualizarDados.bat.
#
# Etapa 1: roda os extratores (Fonte_Dados/codigo_central.py) e gera
#          Planilha_Final/Planilha_GN_Atualizada.xlsx
# Etapa 2: atualiza a base da calculadora (3_Manutencao/atualizar_calculadora.py), que grava
#          6_Calculadora_Flask/data/tarifas.json e 5_Calculadora_Final/tarifas.js.
#          O servidor Flask recarrega a base sozinho, sem reiniciar.
#
# Uso:
#   ./AtualizarDados.sh                        # pergunta o responsável (se estiver num terminal)
#   NOME_RESPONSAVEL="Maria" ./AtualizarDados.sh
#   ./AtualizarDados.sh --only SP,RJ           # repassa opções ao codigo_central.py
#   ./AtualizarDados.sh --sem-calculadora      # só a etapa 1
#   ./AtualizarDados.sh --calculadora-mesmo-com-erro
#                                              # roda a etapa 2 mesmo se algum extrator falhar
#
# Opções do codigo_central.py: --only UF1,UF2 | --skip-run | --timeout SEGUNDOS | --output CAMINHO
set -uo pipefail

cd "$(dirname "$(readlink -f "$0")")"
COMECE_AQUI="$(pwd)"
PROJETO="$(cd ../.. && pwd)"
export PYTHONIOENCODING=utf-8
export LANG="${LANG:-C.UTF-8}"

FONTE_DADOS_DIR="Fonte_Dados"
CODIGO="$FONTE_DADOS_DIR/codigo_central.py"
REQ="$FONTE_DADOS_DIR/requirements.txt"
LOG_DIR="Execucoes_CMD"
RESULTADO_DIR="Planilha_Final"
UF_DIR="$FONTE_DADOS_DIR/PlanilhasUf"
VENV=".venv"
ATUALIZADOR_CALCULADORA="$PROJETO/3_Manutencao/atualizar_calculadora.py"

ATUALIZAR_CALCULADORA=1
CALCULADORA_MESMO_COM_ERRO=0
ARGS_CODIGO=()
for arg in "$@"; do
  case "$arg" in
    --sem-calculadora) ATUALIZAR_CALCULADORA=0 ;;
    --calculadora-mesmo-com-erro) CALCULADORA_MESMO_COM_ERRO=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) ARGS_CODIGO+=("$arg") ;;
  esac
done

# ---------------------------------------------------------------- responsável
NOME_RESPONSAVEL="${NOME_RESPONSAVEL:-}"
if [ -z "$NOME_RESPONSAVEL" ] && [ -t 0 ]; then
  echo
  echo "Para registrar quem fez a atualizacao, informe seu nome."
  echo "Se quiser usar o usuario do Linux ($(id -un)), apenas pressione ENTER."
  read -r -p "Nome do responsavel: " NOME_RESPONSAVEL || true
fi
NOME_RESPONSAVEL="${NOME_RESPONSAVEL:-$(id -un)}"
export NOME_RESPONSAVEL

if [ ! -f "$CODIGO" ]; then
  echo "ERRO: nao encontrei $CODIGO."
  echo "Confira se a pasta $FONTE_DADOS_DIR esta junto deste arquivo."
  exit 1
fi

mkdir -p "$LOG_DIR" "$RESULTADO_DIR" "$UF_DIR"

# Metadados lidos pelo codigo_central.py (aba Aviso e aba controle da planilha final).
export GN_EXEC_USER="$(id -un)"
export GN_EXEC_COMPUTER="$(hostname)"
export GN_EXEC_STARTED_AT="$(date '+%Y-%m-%d %H:%M:%S')"

DATA_HOJE="$(date '+%Y-%m-%d')"
USUARIO_LOG="$(printf '%s' "$NOME_RESPONSAVEL" | sed 's/[^A-Za-z0-9._-]/_/g')"
USUARIO_LOG="${USUARIO_LOG:-$GN_EXEC_USER}"
QTD_HOJE="$(find "$LOG_DIR" -maxdepth 1 -name "Execucao_*_${DATA_HOJE}_*.log" | wc -l)"
LOG_NAME="$(printf 'Execucao_%03d_%s_%s.log' "$((QTD_HOJE + 1))" "$DATA_HOJE" "$USUARIO_LOG")"
LOG="$LOG_DIR/$LOG_NAME"

registrar() { printf '%s\n' "$@" | tee -a "$LOG"; }

echo "========================================"
echo "Atualizacao automatica de tarifas GN"
echo "========================================"
echo
echo "Esta execucao pode levar alguns minutos."
echo "Ao final, a planilha central sera: $RESULTADO_DIR/Planilha_GN_Atualizada.xlsx"
echo "Log desta execucao: $COMECE_AQUI/$LOG"
echo

{
  echo "Execucao: $LOG_NAME"
  echo "Responsavel: $NOME_RESPONSAVEL"
  echo "Usuario Linux: $GN_EXEC_USER"
  echo "Computador: $GN_EXEC_COMPUTER"
  echo "Inicio: $GN_EXEC_STARTED_AT"
  echo "Pasta: $COMECE_AQUI"
  echo
  echo "===== PREPARACAO DO AMBIENTE ====="
} | tee "$LOG"

STATUS=0
finalizar() {
  {
    echo
    echo "===== FIM DA EXECUCAO ====="
    echo "Termino: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "Status: $STATUS"
  } | tee -a "$LOG"
  echo
  if [ "$STATUS" = "0" ]; then
    echo "========================================"
    echo "Concluido com sucesso."
    echo "Planilha: $COMECE_AQUI/$RESULTADO_DIR/Planilha_GN_Atualizada.xlsx"
    echo "========================================"
  else
    echo "========================================"
    echo "Ocorreu um erro na atualizacao."
    echo "Envie o arquivo de log abaixo para suporte:"
    echo "$COMECE_AQUI/$LOG"
    echo "========================================"
  fi
  exit "$STATUS"
}

# ---------------------------------------------------------------- ambiente Python
# O AmbientePython (Python portátil) é só para Windows; no Linux usamos um .venv próprio.
escolher_python() {
  for candidato in "${PYTHON:-}" python3.12 python3.11 python3.10 python3; do
    [ -n "$candidato" ] || continue
    if command -v "$candidato" >/dev/null 2>&1 &&
       "$candidato" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      echo "$candidato"
      return 0
    fi
  done
  return 1
}

if [ ! -x "$VENV/bin/python" ]; then
  if ! PYTHON_BASE="$(escolher_python)"; then
    registrar "ERRO: Python 3.9 ou superior nao encontrado. Instale com: sudo dnf install -y python3.11"
    STATUS=1; finalizar
  fi
  registrar "Criando ambiente Python em $VENV com $PYTHON_BASE ..."
  if ! "$PYTHON_BASE" -m venv "$VENV" >>"$LOG" 2>&1; then
    registrar "ERRO: nao consegui criar o ambiente Python (.venv)."
    STATUS=1; finalizar
  fi
fi
PYTHON_CMD="$VENV/bin/python"

if "$PYTHON_CMD" -c "import openpyxl, pandas, requests, bs4, pdfplumber, fitz, selenium" >>"$LOG" 2>&1; then
  registrar "Dependencias carregadas com sucesso."
else
  registrar "Bibliotecas ausentes. Instalando dependencias, aguarde..."
  "$PYTHON_CMD" -m pip install -q --upgrade pip >>"$LOG" 2>&1
  if ! "$PYTHON_CMD" -m pip install -r "$REQ" >>"$LOG" 2>&1; then
    registrar "ERRO: nao consegui instalar as dependencias. Veja o log."
    STATUS=1; finalizar
  fi
  registrar "Dependencias instaladas."
fi

# Cegás, Copergás e MSGás usam navegador headless (Selenium). Sem Chrome/Chromium esses
# três extratores falham e o restante segue normalmente.
NAVEGADOR=""
for nome in google-chrome google-chrome-stable chromium chromium-browser; do
  if command -v "$nome" >/dev/null 2>&1; then NAVEGADOR="$(command -v "$nome")"; break; fi
done
if [ -n "$NAVEGADOR" ]; then
  registrar "Navegador para Selenium: $NAVEGADOR"
  export GN_CHROME_BINARY="${GN_CHROME_BINARY:-$NAVEGADOR}"
else
  registrar "AVISO: Chrome/Chromium nao encontrado. Os extratores CE (Cegas), PE (Copergas) e MS (MSGas) podem falhar." \
            "       Instale com: sudo dnf install -y epel-release && sudo dnf install -y chromium"
fi

# ---------------------------------------------------------------- etapa 1: extração
{
  echo
  echo "===== SAIDA DO CODIGO ====="
} | tee -a "$LOG"

"$PYTHON_CMD" "$CODIGO" "${ARGS_CODIGO[@]}" 2>&1 | tee -a "$LOG"
STATUS="${PIPESTATUS[0]}"

# ---------------------------------------------------------------- etapa 2: calculadora
if [ "$ATUALIZAR_CALCULADORA" = "1" ]; then
  if [ "$STATUS" != "0" ] && [ "$CALCULADORA_MESMO_COM_ERRO" != "1" ]; then
    registrar "" "Base da calculadora NAO foi atualizada porque houve erro na extracao." \
              "Confira o log; para atualizar assim mesmo, rode novamente com --calculadora-mesmo-com-erro"
  elif [ ! -f "$ATUALIZADOR_CALCULADORA" ]; then
    registrar "" "AVISO: $ATUALIZADOR_CALCULADORA nao encontrado; base da calculadora nao atualizada."
  else
    { echo; echo "===== ATUALIZACAO DA CALCULADORA ====="; } | tee -a "$LOG"
    "$PYTHON_CMD" "$ATUALIZADOR_CALCULADORA" 2>&1 | tee -a "$LOG"
    STATUS_CALC="${PIPESTATUS[0]}"
    if [ "$STATUS_CALC" != "0" ]; then
      registrar "ERRO: falha ao atualizar a base da calculadora."
      STATUS="$STATUS_CALC"
    fi
  fi
fi

finalizar
