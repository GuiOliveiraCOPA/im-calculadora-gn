#!/usr/bin/env bash
# Calculadora GLP x GN (Python / Flask) — inicialização em Linux (AlmaLinux / RHEL).
#
# Uso:
#   ./Iniciar_Calculadora.sh                  # sobe em 0.0.0.0:5000
#   PORTA=8080 ./Iniciar_Calculadora.sh
#   HOST=127.0.0.1 ./Iniciar_Calculadora.sh   # só acesso local (ex.: atrás de nginx)
#   ./Iniciar_Calculadora.sh --testar         # roda os testes e sai
#
# Para rodar como serviço permanente, veja deploy/calculadora-gn.service.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"
export PYTHONIOENCODING=utf-8
export PORTA="${PORTA:-5000}"
export HOST="${HOST:-0.0.0.0}"

echo "========================================"
echo "Calculadora GLP x GN (Python / Flask)"
echo "========================================"

# Python 3.9+ (Flask 3.1). Prefere versões mais novas quando instaladas.
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

if [ ! -x ".venv/bin/python" ]; then
  if ! PYTHON_CMD="$(escolher_python)"; then
    echo "ERRO: Python 3.9 ou superior não encontrado. Instale com: sudo dnf install -y python3.11" >&2
    exit 1
  fi
  echo "Preparando o ambiente Python pela primeira vez ($PYTHON_CMD)..."
  "$PYTHON_CMD" -m venv .venv
  .venv/bin/python -m pip install -q --upgrade pip
fi

if [ "${1:-}" = "--testar" ]; then
  .venv/bin/python -m pip install -q -r requirements-dev.txt
  exec .venv/bin/python -m pytest
fi

.venv/bin/python -m pip install -q -r requirements.txt

if [ ! -f data/tarifas.json ]; then
  echo "ERRO: data/tarifas.json não encontrado. Rode antes o AtualizarDados.sh (1_Processo_Extracao_Dados/Comece_aqui)." >&2
  exit 1
fi

ENDERECO="$HOST"
if [ "$HOST" = "0.0.0.0" ]; then
  ENDERECO="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  ENDERECO="${ENDERECO:-127.0.0.1}"
fi
echo "Acesse: http://${ENDERECO}:${PORTA}/  (Ctrl+C para encerrar)"
exec .venv/bin/python app.py
